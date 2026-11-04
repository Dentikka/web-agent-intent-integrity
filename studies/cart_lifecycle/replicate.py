"""Reproduce the completed cart studies with a configurable list of API models."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

from bounded_api import StopRun, write
import drift_runner
import meaning_series
import handoff_series
import autosave_series

STAGES = ('smoke', 'main', 'meaning', 'handoff', 'autosave')
COUNTS = {'smoke': 6, 'main': 120, 'meaning': 48, 'handoff': 96, 'autosave': 24}


def reject_embedded_credentials(value: object) -> None:
    if isinstance(value, dict):
        if {str(k).lower() for k in value} & {'key', 'api_key', 'authorization', 'token', 'password'}:
            raise ValueError('Use key_env/key_file references; embedded credentials are not allowed')
        for nested in value.values():
            reject_embedded_credentials(nested)
    elif isinstance(value, list):
        for nested in value:
            reject_embedded_credentials(nested)


def design(stage: str) -> list[dict]:
    if stage in ('smoke', 'main'):
        return drift_runner.matrix(stage)
    return {'meaning': meaning_series, 'handoff': handoff_series,
            'autosave': autosave_series}[stage].matrix()


def validate(cfg: dict, paid: bool = False) -> None:
    reject_embedded_credentials(cfg)
    models = cfg.get('models')
    if not isinstance(models, list) or not models:
        raise ValueError('Provide a nonempty models list')
    ids = [m.get('id') for m in models]
    if any(not isinstance(x, str) or not x.strip() for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Use nonempty unique model IDs')
    for key, maximum in [('budget_usd', 20), ('hours', 8)]:
        value = cfg.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise ValueError(f'Explicit {key} must be positive and at most {maximum}')
    if not 1 <= cfg.get('workers', 3) <= 8 or not 1 <= cfg.get('max_turns', 14) <= 20:
        raise ValueError('Use 1..8 workers and 1..20 turns')
    budgets = allocations(cfg)
    if (any(not isinstance(b, (int, float)) or not math.isfinite(b) or b <= 0 for b in budgets)
            or sum(budgets) > cfg['budget_usd']):
        raise ValueError('Positive per-model budgets must sum to no more than the total budget')
    for model in models:
        if {k.lower() for k in model} & {'key', 'api_key', 'authorization', 'token', 'password'}:
            raise ValueError('Store only key_env/key_file references, never key values')
        parsed = urlsplit(model.get('base_url', ''))
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError('Use a clean HTTPS Chat Completions base_url')
        if parsed.hostname == 'openrouter.ai' or parsed.hostname.endswith('.openrouter.ai'):
            raise ValueError('OpenRouter is prohibited')
        if paid:
            for key in ('input_per_million', 'output_per_million'):
                price = model.get(key)
                if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
                    raise ValueError('Set explicit positive billed prices before running')
            if model.get('byte_token_bound_verified') is not True:
                raise ValueError('Verify provider tokenizer and billed reasoning cap before running')
            if not model.get('key_env') and not model.get('key_file'):
                raise ValueError('Specify key_env or key_file')
            limit = model.get('max_output_tokens', 768)
            if not isinstance(limit, int) or not 64 <= limit <= 4096:
                raise ValueError('Output cap must be 64..4096')
            if model.get('token_limit_field', 'max_tokens') not in ('max_tokens', 'max_completion_tokens'):
                raise ValueError('Unsupported token limit field')
            if set(model.get('extra_body', {})) & {'model', 'messages', 'tools', 'stream', 'max_tokens', 'max_completion_tokens'}:
                raise ValueError('extra_body cannot override model, messages, tools, streaming or output caps')


def allocations(cfg: dict) -> list[float]:
    models = cfg['models']
    if any('budget_usd' in m for m in models):
        if not all('budget_usd' in m for m in models):
            raise ValueError('Specify individual budgets for every model or for none')
        return [m['budget_usd'] for m in models]
    return [cfg['budget_usd'] / len(models)] * len(models)


def plan(cfg: dict, stages: list[str]) -> dict:
    validate(cfg)
    if not stages or any(s not in STAGES for s in stages) or len(stages) != len(set(stages)):
        raise ValueError('Select each valid stage at most once')
    per_model = {s: len(design(s)) for s in stages}
    assert all(per_model[s] == COUNTS[s] for s in stages)
    return {'models': [m['id'] for m in cfg['models']], 'episodes_per_model': per_model,
            'research_per_model': sum(n for s, n in per_model.items() if s != 'smoke'),
            'total_model_episodes': sum(per_model.values()) * len(cfg['models']),
            'budget_total_usd': cfg['budget_usd'],
            'budget_per_model_usd': dict(zip([m['id'] for m in cfg['models']], allocations(cfg))),
            'hours_total': cfg['hours'], 'model_api_calls': 0}


def configure_runtime(cfg: dict, config_dir: Path) -> dict:
    cfg = dict(cfg)
    for key, env in [('runtime_wp_site', 'DRIFT_WP_SITE'), ('base_database', 'DRIFT_BASE_DB'),
                     ('php_binary', 'DRIFT_PHP_BINARY')]:
        if cfg.get(key):
            path = Path(cfg[key]).expanduser()
            if not path.is_absolute():
                path = config_dir / path
            cfg[key] = str(path.resolve())
            os.environ[env] = cfg[key]
    workspace = Path(cfg.get('workspace', '.')).expanduser()
    cfg['workspace'] = str((config_dir / workspace).resolve() if not workspace.is_absolute() else workspace.resolve())
    if 'browser_channel' in cfg:
        os.environ['DRIFT_BROWSER_CHANNEL'] = cfg['browser_channel'] or ''
    if cfg.get('browser_executable'):
        path = Path(cfg['browser_executable']).expanduser()
        cfg['browser_executable'] = str((config_dir / path).resolve() if not path.is_absolute() else path.resolve())
        os.environ['DRIFT_BROWSER_EXECUTABLE'] = cfg['browser_executable']
    for model in cfg['models']:
        if model.get('key_file'):
            path = Path(model['key_file']).expanduser()
            model['key_file'] = str((config_dir / path).resolve() if not path.is_absolute() else path.resolve())
    return cfg


@contextmanager
def exclusive_run(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'replication.lock').open('a+b') as lock:
        lock.seek(0, 2)
        if not lock.tell():
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def run(cfg: dict, root: Path, stages: list[str]) -> None:
    plan(cfg, stages)
    validate(cfg, paid=True)
    if 'onedrive' in str(root.resolve()).lower():
        raise ValueError('Store paid runs outside OneDrive/cloud-synced directories')
    with exclusive_run(root):
        controller = root / 'replication.json'
        if controller.exists():
            saved = json.loads(controller.read_text(encoding='utf-8'))
            if saved['config'] != cfg:
                raise ValueError('Frozen replication config changed; select a fresh output root')
        else:
            saved = {'config': cfg, 'started_epoch': time.time()}
            write(controller, saved)
        deadline = saved['started_epoch'] + cfg['hours'] * 3600
        budgets = allocations(cfg)
        for stage in stages:
            for index, model in enumerate(cfg['models']):
                model_root = root / ('model-' + str(index + 1) + '-' + hashlib.sha256(model['id'].encode()).hexdigest()[:8]) / 'paid'
                if time.time() + 100 >= deadline:
                    raise StopRun('Global replication deadline reached')
                model_cfg = {k: v for k, v in cfg.items() if k != 'models'}
                model_cfg.update(model=model, budget_usd=budgets[index], budget_ceiling_usd=cfg['budget_usd'],
                                 hours=max(0, (deadline - time.time()) / 3600))
                frozen = model_root / 'config.json'
                if frozen.exists():
                    existing = json.loads(frozen.read_text(encoding='utf-8'))
                    model_cfg['hours'] = existing['hours']
                if stage in ('smoke', 'main'):
                    drift_runner.run(model_cfg, model_root, stage)
                elif stage == 'meaning':
                    drift_runner.run(model_cfg, model_root, stage, design(stage), meaning_series.MeaningApp,
                                     meaning_series.POLICY, ('meaning_series.py', 'meaning_controls.py', 'meaning_analyze.py'))
                elif stage == 'handoff':
                    drift_runner.run(model_cfg, model_root, stage, design(stage), handoff_series.HandoffApp,
                                     drift_runner.SYNC_POLICY, ('handoff_series.py', 'handoff_controls.py'))
                else:
                    drift_runner.run(model_cfg, model_root, stage, design(stage), autosave_series.AutosaveApp,
                                     autosave_series.POLICY, ('autosave_series.py', 'autosave_controls.py', 'autosave_analyze.py'),
                                     autosave_series.AutosaveSurface)
                summary = json.loads((model_root / stage / 'summary.json').read_text(encoding='utf-8'))
                if not summary['complete']:
                    raise StopRun('Incomplete stage retained; inspect errors and billing before continuing')



def selftest(cfg: dict, root: Path) -> None:
    # Explicitly no API client invocation, and no key is read.
    for module in ('drift_controls', 'meaning_controls', 'handoff_controls', 'resync_controls', 'autosave_controls'):
        subprocess.run([sys.executable, str(Path(__file__).with_name(module + '.py')),
                        '--workspace', cfg['workspace'], '--out', str(root / module.replace('_', '-'))], check=True)


def analyze(root: Path) -> dict:
    import drift_analyze
    import meaning_analyze
    import autosave_analyze
    from verify_drift_databases import verify
    models = []
    for paid in sorted(root.glob('model-*/paid')):
        cfg = json.loads((paid / 'config.json').read_text(encoding='utf-8'))
        results = {}
        for stage in STAGES:
            if not (paid / stage / 'manifest.json').exists():
                continue
            analyzer = (meaning_analyze.run if stage == 'meaning' else
                        autosave_analyze.analyze if stage == 'autosave' else drift_analyze.analyze)
            results[stage] = {k: v for k, v in analyzer(paid / stage).items() if k != 'rows'}
        audit = verify(paid)
        complete = all(s in results and results[s]['observed'] == COUNTS[s]
                       and results[s]['valid'] == COUNTS[s] for s in STAGES)
        models.append({'model': cfg['model']['id'], 'complete': complete, 'stages': results,
                       'refusal_review_complete': ('meaning' in results and results['meaning']['observed']==COUNTS['meaning']
                           and all(c['refusal_unreviewed']==0 for c in results['meaning']['cells'])),
                       'database_audit': {'checked': audit['checked'], 'mismatches': audit['mismatches']}})
    if not models:
        raise ValueError('No model-*/paid runs found')
    payload = {'models': models, 'interpretation': 'Model results remain separate; no substituted historical numbers.'}
    write(root / 'REPLICATION_RESULTS.json', payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('plan', 'selftest', 'run', 'analyze'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--stages', nargs='+', choices=STAGES, default=list(STAGES))
    args = parser.parse_args()
    if args.command == 'analyze':
        if not args.out:
            parser.error('--out is required')
        print(json.dumps(analyze(args.out.resolve()), indent=2))
        return
    if not args.config:
        parser.error('--config is required')
    cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
    if args.command == 'plan':
        print(json.dumps(plan(cfg, args.stages), indent=2))
        return
    if not args.out:
        parser.error('--out is required')
    cfg = configure_runtime(cfg, args.config.resolve().parent)
    if args.command == 'selftest':
        selftest(cfg, args.out.resolve())
    else:
        run(cfg, args.out.resolve(), args.stages)


if __name__ == '__main__':
    main()
