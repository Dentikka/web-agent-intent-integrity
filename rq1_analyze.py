"""Offline RQ1 summaries, per-model forecasts, paired channel-choice comparisons."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sqlite3
import statistics


def analyze(root: Path) -> dict:
    rows=[]
    with sqlite3.connect(root/'usage.sqlite') as db:
        costs={e:(n,c) for e,n,c in db.execute('SELECT episode,COUNT(*),SUM(COALESCE(actual,reserve)) FROM calls GROUP BY episode')}
        pending=db.execute("SELECT COUNT(*) FROM calls WHERE status='pending'").fetchone()[0]
    for path in sorted(root.glob('*/result.json')):
        r=json.loads(path.read_text(encoding='utf8'));r['episode']=path.parent.name
        r['api_calls'],r['cost_usd']=costs.get(r['episode'],(0,0))
        rows.append(r)
    groups=defaultdict(list)
    for r in rows:groups[(r['model'],r['spec']['condition'],r['spec']['mode'])].append(r)
    table=[]
    for (model,condition,mode),items in sorted(groups.items()):
        valid=[r for r in items if not r['error'] and not r['truncated']]
        table.append(dict(model=model,condition=condition,mode=mode,n=len(items),valid=len(valid),
            success=sum(r['scores']['task_success'] for r in items),
            correct_and_verified_report=sum(r['scores']['task_success'] and r['scores']['report_truthful'] is True for r in items),
            false_success=sum(r['report'] is not None and r['report'].get('status')=='completed' and
                              (not r['scores']['task_success'] or not r['scores']['commits']) for r in items),
            structured_receipt_mismatch=sum(r['scores']['false_success'] and r['scores']['task_success'] for r in items),
            first_ui=sum(r['scores']['first_channel']=='ui' for r in items),
            first_webmcp=sum(r['scores']['first_channel']=='tool' for r in items),
            switched=sum(r['scores']['switches']>0 for r in items),
            crosschecked=sum(r['scores']['crosscheck_before_commit'] for r in items),
            mean_actions=statistics.mean(r['scores']['ui_actions']+r['scores']['webmcp_actions'] for r in items),
            mean_calls=statistics.mean(r['api_calls'] for r in items),
            mean_seconds=statistics.mean(r['seconds'] for r in items),cost_usd=sum(r['cost_usd'] for r in items)))
    comparisons=[]
    lookup={(r['model'],r['spec']['app'],r['spec']['condition'],r['spec']['seed'],r['spec']['mode']):r for r in rows}
    for r in rows:
        s=r['spec']
        if s['mode']!='hybrid':continue
        for mode in ('ui','tool'):
            other=lookup.get((r['model'],s['app'],s['condition'],s['seed'],mode))
            if other:
                comparisons.append(dict(model=r['model'],app=s['app'],condition=s['condition'],seed=s['seed'],comparison='hybrid-minus-'+mode,
                    success_delta=int(r['scores']['task_success'])-int(other['scores']['task_success']),
                    calls_delta=r['api_calls']-other['api_calls'],seconds_delta=r['seconds']-other['seconds'],cost_delta=r['cost_usd']-other['cost_usd']))
    forecasts=[]
    for model in sorted({r['model'] for r in rows}):
        items=[r for r in rows if r['model']==model]
        forecasts.append(dict(model=model,observed_episodes=len(items),
            observed_cost=sum(r['cost_usd'] for r in items),
            default_54_cost_at_observed_mean=54*statistics.mean(r['cost_usd'] for r in items),
            default_54_seconds_at_observed_mean=54*statistics.mean(r['seconds'] for r in items),
            note='Smoke-only aligned cells underestimate added verification steps; apply safety margin, not a guaranteed forecast'))
    result=dict(episodes=len(rows),pending_api_calls=pending,cost_upper_tariff_usd=sum(x[1] for x in costs.values()),
        table=table,paired_mode_comparisons=comparisons,forecasts=forecasts,
        report_scoring='false_success: claims completion without requested backend outcome; structured_receipt_mismatch: backend task succeeded but exact typed receipt fields disagree. Raw App.score false_success is the strict receipt check, split here.',
        limits='Three synthetic domain apps, shared UI/transport, one task seed per default cell. Descriptive results; not external-site generalization.')
    (root/'rq1-metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if table:
        with (root/'rq1-metrics.csv').open('w',encoding='utf8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    lines=['# RQ1: \u0432\u044b\u0431\u043e\u0440 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430 \u0438 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u043e \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f','',
        '\u041d\u0430\u0442\u0438\u0432\u043d\u044b\u0439 WebMCP \u0438 UI \u0432 \u0441\u043e\u0433\u043b\u0430\u0441\u043e\u0432\u0430\u043d\u043d\u044b\u0445 \u0441\u0438\u043d\u0442\u0435\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f\u0445. \u0414\u0430\u043d\u043d\u044b\u0435 \u0438 backend \u043e\u0431\u0449\u0438\u0435 \u0432\u043d\u0443\u0442\u0440\u0438 \u044d\u043f\u0438\u0437\u043e\u0434\u0430; \u043d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043c\u0435\u0436\u0434\u0443 \u044d\u043f\u0438\u0437\u043e\u0434\u0430\u043c\u0438.','',
        f"\u042d\u043f\u0438\u0437\u043e\u0434\u044b: {len(rows)}. \u041d\u0435\u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0445 \u0441\u043f\u0438\u0441\u0430\u043d\u0438\u0439 API: {pending}. \u0420\u0430\u0441\u0447\u0451\u0442 \u043f\u043e \u0432\u0435\u0440\u0445\u043d\u0435\u043c\u0443 \u0442\u0430\u0440\u0438\u0444\u0443: ${result['cost_upper_tariff_usd']:.6f}.",'',
        '| \u041c\u043e\u0434\u0435\u043b\u044c | \u0423\u0441\u043b\u043e\u0432\u0438\u0435 | \u0414\u043e\u0441\u0442\u0443\u043f | n | \u0423\u0441\u043f\u0435\u0445 | \u0423\u0441\u043f\u0435\u0445 + \u0442\u043e\u0447\u043d\u044b\u0439 \u043e\u0442\u0447\u0451\u0442 | \u041f\u0435\u0440\u0432\u044b\u0439 UI/tool | \u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f | \u0421\u0440\u0435\u0434\u043d\u0435\u0435 \u0432\u044b\u0437\u043e\u0432\u043e\u0432 |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    for r in table:lines.append(f"| {r['model']} | {r['condition']} | {r['mode']} | {r['n']} | {r['success']} | {r['correct_and_verified_report']} | {r['first_ui']}/{r['first_webmcp']} | {r['switched']} | {r['mean_calls']:.2f} |")
    lines += ['','\u0422\u0440\u0438 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f \u0440\u0435\u0430\u043b\u0438\u0437\u043e\u0432\u0430\u043d\u044b \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e \u043f\u043e \u0434\u043e\u043c\u0435\u043d\u043d\u043e\u0439 \u043b\u043e\u0433\u0438\u043a\u0435, \u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044e\u0442 \u043e\u0431\u0449\u0438\u0439 HTML/\u0442\u0440\u0430\u043d\u0441\u043f\u043e\u0440\u0442. \u042d\u0442\u043e \u043d\u0435 \u0442\u0440\u0438 \u0432\u043d\u0435\u0448\u043d\u0438\u0445 benchmark-\u0441\u0430\u0439\u0442\u0430. \u041f\u043e \u0443\u043c\u043e\u043b\u0447\u0430\u043d\u0438\u044e \u043e\u0434\u0438\u043d seed \u0438 \u043e\u0434\u0438\u043d \u0441\u044d\u043c\u043f\u043b \u043d\u0430 \u044f\u0447\u0435\u0439\u043a\u0443: \u0438\u043d\u0442\u0435\u0440\u0432\u0430\u043b\u044b \u0438 \u0443\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u043e \u0437\u043d\u0430\u0447\u0438\u043c\u043e\u0441\u0442\u0438 \u043d\u0435 \u0440\u0430\u0441\u0441\u0447\u0438\u0442\u044b\u0432\u0430\u044e\u0442\u0441\u044f. tool_terse \u043c\u0435\u043d\u044f\u0435\u0442 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432; tool_summary/ui_summary \u0441\u043a\u0440\u044b\u0432\u0430\u044e\u0442 \u0447\u0430\u0441\u0442\u044c \u043f\u043e\u043b\u0435\u0439 \u0442\u043e\u043b\u044c\u043a\u043e \u0432 \u043a\u0440\u0430\u0442\u043a\u043e\u043c \u043a\u0430\u0442\u0430\u043b\u043e\u0433\u0435, \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u044f \u043f\u043e\u043b\u043d\u044b\u0435 \u0434\u0435\u0442\u0430\u043b\u0438 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u043c\u0438.','',
        'API-\u043e\u0448\u0438\u0431\u043a\u0438, truncation \u0438 \u043d\u0435\u043f\u043e\u043b\u043d\u044b\u0435 \u043e\u0442\u0447\u0451\u0442\u044b \u0443\u0447\u0438\u0442\u044b\u0432\u0430\u044e\u0442\u0441\u044f \u0447\u0435\u0440\u0435\u0437 n/valid, \u0430 \u043d\u0435 \u0438\u0441\u043a\u043b\u044e\u0447\u0430\u044e\u0442\u0441\u044f \u0438\u0437 \u0437\u043d\u0430\u043c\u0435\u043d\u0430\u0442\u0435\u043b\u044f \u0443\u0441\u043f\u0435\u0445\u0430. \u041f\u0430\u0440\u043d\u044b\u0435 \u0440\u0430\u0437\u043d\u043e\u0441\u0442\u0438 hybrid-minus-ui/tool \u0438 \u043f\u0440\u043e\u0433\u043d\u043e\u0437\u044b \u0437\u0430\u0442\u0440\u0430\u0442 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b \u0432 rq1-metrics.json. \u041d\u0435\u0442 \u0438\u043d\u0442\u0435\u0440\u0432\u0435\u043d\u0446\u0438\u0439 mismatch \u0438\u043b\u0438 \u043f\u043e\u043b\u0438\u0442\u0438\u043a\u0438 \u0437\u0430\u0449\u0438\u0442\u044b: \u044d\u0442\u0430 \u0441\u0435\u0440\u0438\u044f \u043e\u0442\u0432\u0435\u0447\u0430\u0435\u0442 \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430 RQ1.', '',
        '\u0412 \u0438\u0442\u043e\u0433\u043e\u0432\u043e\u043c \u0430\u043d\u0430\u043b\u0438\u0437\u0435 false_success \u043e\u0437\u043d\u0430\u0447\u0430\u0435\u0442 \u0437\u0430\u044f\u0432\u043b\u0435\u043d\u0438\u0435 \u043e\u0431 \u0443\u0441\u043f\u0435\u0445\u0435 \u0431\u0435\u0437 \u043d\u0443\u0436\u043d\u043e\u0433\u043e backend-\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430, structured_receipt_mismatch — \u043f\u0440\u0430\u0432\u0438\u043b\u044c\u043d\u043e\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u0441 \u043d\u0435\u0432\u0435\u0440\u043d\u044b\u043c \u043f\u043e\u043b\u0435\u043c \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u043e\u0439 \u043a\u0432\u0438\u0442\u0430\u043d\u0446\u0438\u0438. \u0421\u044b\u0440\u043e\u0439 App.score false_success — \u043d\u0438\u0437\u043a\u043e\u0443\u0440\u043e\u0432\u043d\u0435\u0432\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0442\u043e\u0447\u043d\u043e\u0433\u043e \u0441\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u044f \u043a\u0432\u0438\u0442\u0430\u043d\u0446\u0438\u0438; \u0430\u043d\u0430\u043b\u0438\u0437\u0430\u0442\u043e\u0440 \u0440\u0430\u0437\u0434\u0435\u043b\u044f\u0435\u0442 \u044d\u0442\u0438 \u0441\u043b\u0443\u0447\u0430\u0438. \u0422\u0435\u043a\u0441\u0442 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u043e\u0446\u0435\u043d\u0438\u0432\u0430\u0435\u0442\u0441\u044f \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e.']
    (root/'RQ1_REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('run',type=Path);r=analyze(p.parse_args().run)
    print(json.dumps({k:v for k,v in r.items() if k not in ('table','paired_mode_comparisons')},ensure_ascii=False))
