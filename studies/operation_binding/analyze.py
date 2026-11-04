"""Offline native-state audit and safety/utility/cost summaries; no model calls."""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics

from binding_app import CART  # activates the existing runtime helpers, without starting an app
from bounded_api import write
from design import score, order_witnesses


def audit_episode(folder: Path) -> dict:
    path = folder / 'state.sqlite'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Native SQLite integrity failure')
        context = json.loads(db.execute("SELECT option_value FROM wp_options WHERE option_name='_binding_context_json'").fetchone()[0])
        records = []
        for (oid,) in db.execute("SELECT DISTINCT post_id FROM wp_postmeta WHERE meta_key='_drift_episode' AND meta_value=?", (folder.name,)):
            meta = dict(db.execute('SELECT meta_key,meta_value FROM wp_postmeta WHERE post_id=?', (oid,)))
            items = []
            for (iid,) in db.execute("SELECT order_item_id FROM wp_woocommerce_order_items WHERE order_id=? AND order_item_type='line_item'", (oid,)):
                values = dict(db.execute('SELECT meta_key,meta_value FROM wp_woocommerce_order_itemmeta WHERE order_item_id=?', (iid,)))
                items.append(dict(product_id=int(values['_product_id']), quantity=int(Decimal(values['_qty']))))
            status = db.execute('SELECT post_status FROM wp_posts WHERE ID=?', (oid,)).fetchone()[0]
            records.append(dict(order_id=oid, operation_id=meta.get('_binding_operation', ''),
                                role=meta.get('_binding_role', ''), subject=int(meta['_customer_user']),
                                items=items, currency=meta['_order_currency'],
                                total_minor=int(Decimal(meta['_order_total']) * 100),
                                paid=status in ('wc-processing', 'wc-completed')))
    finally:
        db.close()
    backend = json.loads((folder / 'backend.json').read_text(encoding='utf-8'))['final']
    expected = sorted(backend['orders'], key=lambda o: o['order_id'])
    if (sorted(records, key=lambda o: o['order_id']) != expected or context['current'] != backend['current']
            or context['approval'] != backend['approval']):
        raise ValueError('Native SQLite disagrees with recorded backend')
    result_file = folder / 'result.json'
    if result_file.exists():
        r = json.loads(result_file.read_text(encoding='utf-8'))
        trace = json.loads((folder / 'trace.json').read_text(encoding='utf-8'))
        finish = next((t for t in trace if t.get('tool') == 'finish' and t.get('observation', {}).get('finished')), None)
        prior: set[int] = set()
        if finish:
            request = json.loads((folder / f"request-{finish['turn']:02d}.json").read_text(encoding='utf-8'))
            seen = {m.get('tool_call_id') for m in request['messages'] if m['role'] == 'tool'}
            for t in trace:
                if t.get('call_id') in seen:
                    prior.update(order_witnesses(t.get('observation'), context['current']))
        approved = context['approval']['decision'] == 'approved' and all(
            context['approval'][k] == context['current'][k] for k in
            ('operation_id', 'subject', 'product_id', 'quantity', 'currency', 'total_minor'))
        independent = score(context['current'], records, approved, r['report'], prior, r['spec']['series'])
        if any(r['scores'].get(k) != v for k, v in independent.items()):
            raise ValueError('Selecting-context/native scorer disagrees with recorded outcomes')
    if hashlib.sha256(path.read_bytes()).hexdigest() != before:
        raise ValueError('Read-only native audit changed database')
    return dict(passed=True, database_sha256=before, orders=len(records),
                current_operation=context['current']['operation_id'])


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    z = 1.95996398454
    center = (k / n + z*z / (2*n)) / (1 + z*z / n)
    half = z * ((k/n * (1-k/n) / n + z*z / (4*n*n)) ** .5) / (1+z*z/n)
    return [max(0, center-half), min(1, center+half)]


def analyze(root: Path) -> dict:
    models = []
    endpoints = ('valid_execution', 'unauthorized_commit', 'incompatible_commit', 'duplicate_commit',
                 'grounded_completed', 'unsupported_completed', 'correct_authorization_decision',
                 'feasible_noncompletion', 'route_obeyed')
    for model_root in sorted(root.glob('model-*')):
        cfg = json.loads((model_root / 'config.json').read_text(encoding='utf-8'))
        ledger_uri = (model_root / 'usage.sqlite').resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(ledger_uri, uri=True)) as ledger:
            calls = ledger.execute('SELECT episode,reserve,actual,status,usage FROM calls').fetchall()
        resources: dict = defaultdict(lambda: dict(input_tokens=0, output_tokens=0, cost_upper_usd=0.,
                                                  model_calls=0, unresolved_calls=0))
        for episode, reserve, actual, status, usage in calls:
            row = resources[episode]
            row['model_calls'] += 1
            row['cost_upper_usd'] += actual if actual is not None else reserve
            row['unresolved_calls'] += status != 'done'
            u = json.loads(usage) if usage else {}
            row['input_tokens'] += u.get('prompt_tokens', 0)
            row['output_tokens'] += u.get('completion_tokens', 0)
        stages = {}
        audits = []
        for stage in ('smoke', 'receipt', 'consent', 'validation'):
            mf = model_root / stage / 'manifest.json'
            if not mf.exists():
                continue
            manifest = json.loads(mf.read_text(encoding='utf-8'))
            groups: dict = defaultdict(list)
            rows = []
            expected = {json.dumps(s, sort_keys=True) for s in manifest['design']}
            observed_specs: set[str] = set()
            for file in sorted((model_root / stage).glob('*/result.json')):
                r = json.loads(file.read_text(encoding='utf-8'))
                signature = json.dumps(r['spec'], sort_keys=True)
                if signature not in expected or signature in observed_specs or r['model'] != cfg['model']['id']:
                    raise ValueError('Unexpected, duplicate or mislabeled result')
                observed_specs.add(signature)
                r['source'] = str(file.relative_to(root))
                r['resources'] = resources[file.parent.name]
                if (file.parent / 'backend.json').exists():
                    audits.append(dict(source=r['source'], **audit_episode(file.parent)))
                rows.append(r)
                s = r['spec']
                groups[(s['series'], s['evidence'], s['route'], s['policy'])].append(r)
            cells = []
            for key, assigned in sorted(groups.items()):
                complete = [r for r in assigned if not r.get('error')]
                cell = dict(zip(('series', 'evidence', 'route', 'policy'), key))
                cell.update(assigned=len(assigned), complete=len(complete), errors=len(assigned)-len(complete),
                            no_structured_report=sum(r['report'] is None for r in complete))
                cell['backend_known'] = sum(bool(r['scores']) for r in assigned)
                cell['backend_unknown'] = len(assigned) - cell['backend_known']
                for endpoint in endpoints:
                    known = [r for r in assigned if endpoint in r['scores'] and r['scores'][endpoint] is not None]
                    cell[endpoint] = sum(bool(r['scores'][endpoint]) for r in known)
                    cell[endpoint + '_known_n'] = len(known)
                    cell[endpoint + '_wilson95'] = wilson(cell[endpoint], len(known))
                cell['known_effects_in_errors'] = {e: sum(bool(r['scores'].get(e)) for r in assigned if r['error']) for e in endpoints}
                for field in ('input_tokens', 'output_tokens', 'cost_upper_usd', 'model_calls'):
                    cell[field] = sum(r['resources'][field] for r in assigned)
                cell['mean_actions'] = statistics.mean(r['scores'].get('actions', 0) for r in complete) if complete else None
                cell['median_seconds'] = statistics.median(r['seconds'] for r in complete) if complete else None
                cells.append(cell)
            stages[stage] = dict(planned=len(manifest['design']), observed=len(rows),
                                 coverage_complete=observed_specs == expected,
                                 errors=sum(bool(r['error']) for r in rows), cells=cells)
            write(model_root / stage / 'ANALYSIS.json', dict(cells=cells, rows=rows))
        models.append(dict(model=cfg['model']['id'], stages=stages, database_audits=audits,
                           model_cost_upper_usd=sum(r[2] if r[2] is not None else r[1] for r in calls)))
    if not models:
        raise ValueError('No model outputs found')
    result = dict(models=models, total_cost_upper_usd=sum(m['model_cost_upper_usd'] for m in models),
                  units='One fresh agent trajectory per assignment; tool/API calls are separate resources.',
                  inference='Cell rates describe these fixtures; repeats are not independent sites. Errors are retained.',
                  latency='Episode wall-clock includes local runtime/tools and provider calls; not pure API latency.',
                  technical_stages='smoke and validation are excluded from research counts', model_api_calls=0)
    write(root / 'BINDING_RESULTS.json', result)
    return result
