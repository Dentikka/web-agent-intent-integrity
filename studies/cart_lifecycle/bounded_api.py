"""Bounded Chat Completions client. No provider keys in saved payloads."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import threading
import urllib.error
import urllib.parse
import urllib.request

def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

def write(path: Path, value: object) -> None:
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(encode(value),encoding='utf8')
    for attempt in range(10):
        try:
            temporary.replace(path);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.1*(attempt+1))

class StopRun(Exception):
    pass

class Ledger:
    def __init__(self, root: Path, cfg: dict):
        self.db = sqlite3.connect(root / 'usage.sqlite',check_same_thread=False,timeout=30)
        self.lock = threading.RLock()
        self.db.execute('CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, episode TEXT, reserve REAL, actual REAL, status TEXT, usage TEXT)')
        self.cap = float(cfg.get('budget_usd', 18))
        self.deadline = cfg['started_epoch'] + float(cfg.get('hours', 7.5)) * 3600
        if self.db.execute("SELECT 1 FROM calls WHERE status='pending'").fetchone():
            self.db.close()
            raise StopRun('Unresolved API call: retain its reserve and reconcile before resume. Do not retry blindly.')

    def reserve(self, episode: str, amount: float) -> int:
        if not math.isfinite(amount) or amount<0:raise ValueError('Invalid request reservation')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                spent = self.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls').fetchone()[0]
                if spent + amount > self.cap:raise StopRun('Budget gate reached')
                if time.time() + 100 > self.deadline:raise StopRun('Wall-clock gate reached')
                cur = self.db.execute("INSERT INTO calls(episode,reserve,status) VALUES(?,?,'pending')", (episode, amount))
                self.db.commit()
                return cur.lastrowid
            except BaseException:
                self.db.rollback();raise

    def settle(self, call: int, usage: dict, model: dict) -> None:
        inp, out = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if type(inp) is not int or type(out) is not int or min(inp, out) < 0:
            raise StopRun('Missing token usage; API call reserve retained. Reconcile provider billing.')
        calculated = (inp * model['input_per_million'] + out * model['output_per_million']) / 1e6
        try:
            reported = float(usage.get('cost') or 0)
        except (ValueError, TypeError):
            raise StopRun('Invalid provider cost; reservation retained') from None
        if not math.isfinite(calculated) or not math.isfinite(reported) or reported < 0:
            raise StopRun('Nonfinite or negative provider cost; reservation retained')
        actual = max(calculated, reported)
        with self.lock:
            self.db.execute("UPDATE calls SET actual=?,status='done',usage=? WHERE id=?", (actual, encode(usage), call))
            self.db.commit()
            if actual > self.db.execute('SELECT reserve FROM calls WHERE id=?', (call,)).fetchone()[0]:
                raise StopRun('Provider billing exceeded reservation; review rates before continuing')

def api(model: dict, messages: list, schemas: list, ledger: Ledger, episode: str, folder: Path, step: int) -> dict:
    for field in ('input_per_million', 'output_per_million'):
        value=model.get(field)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('Explicit finite positive token prices required')
    url = model['base_url'].rstrip('/') + '/chat/completions'
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use a clean HTTPS API base URL')
    if parsed.hostname == 'openrouter.ai' or (parsed.hostname or '').endswith('.openrouter.ai'):
        raise ValueError('OpenRouter is prohibited in this project')
    extra = model.get('extra_body', {})
    if set(extra) & {'model', 'messages', 'tools', 'stream', 'max_tokens', 'max_completion_tokens'}:
        raise ValueError('extra_body cannot override actor tools, model or token limits')
    limit = int(model.get('max_output_tokens', 768))
    field = model.get('token_limit_field', 'max_tokens')
    if field not in ('max_tokens', 'max_completion_tokens') or not 64 <= limit <= 4096:
        raise ValueError('Invalid output token cap')
    body = dict(model=model['id'], messages=messages, tools=schemas, stream=False, **extra)
    body[field] = limit
    blob = encode(body).encode('utf-8')
    # For supported byte-tokenizers: UTF-8 bytes upper-bound text token count;
    # a margin covers message/tool framing. No cache discount is assumed.
    reserve = ((len(blob) + 4096) * model['input_per_million'] + limit * model['output_per_million']) / 1e6 * 1.1
    if not model.get('byte_token_bound_verified', False):
        raise ValueError('Verify provider tokenizer and billed reasoning cap before enabling byte_token_bound_verified')
    key = os.environ.get(model.get('key_env', 'MODEL_API_KEY'))
    if not key and model.get('key_file'):
        key = Path(model['key_file']).expanduser().read_text(encoding='utf-8').strip()
    if not key:
        raise ValueError('API key missing; specify key_env or local key_file')
    call = ledger.reserve(episode, reserve)
    write(folder / f'request-{step:02d}.json', body)  # No headers or keys.
    req = urllib.request.Request(url, data=blob, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not log provider error bodies, which may echo auth data. Fail closed.
        raise StopRun(f'API HTTP {exc.code}; reservation retained; no automatic retry') from None
    except (OSError, ValueError) as exc:
        raise StopRun(f'API transport/JSON failure ({type(exc).__name__}); reservation retained') from None
    write(folder / f'response-{step:02d}.json', result)
    ledger.settle(call, result.get('usage', {}), model)
    return result

def launch(playwright, cfg: dict):
    options = {'headless': True, 'args': cfg.get('browser_args', [])}
    if cfg.get('browser_channel'):
        options['channel'] = cfg['browser_channel']
    if cfg.get('browser_executable'):
        options['executable_path'] = cfg['browser_executable']
    return playwright.chromium.launch(**options)
