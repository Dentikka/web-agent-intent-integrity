"""Offline meaningful-price evaluation: valid refusal differs from task failure."""
from __future__ import annotations
import argparse
import collections
import json
from pathlib import Path

from bounded_api import write
from drift_analyze import analyze


def run(stage: Path) -> dict:
    base=analyze(stage)
    annotation_file=stage/'text-annotations.json'
    annotations=json.loads(annotation_file.read_text(encoding='utf8'))['rows'] if annotation_file.exists() else {}
    groups=collections.defaultdict(list);template={}
    for row in base['rows']:
        original=json.loads((stage/row['episode']/'result.json').read_text(encoding='utf8'))
        row['report_status']=(original.get('report') or {}).get('status')
        label=annotations.get(row['episode'],{}).get('label')
        if label not in (None,'correct_budget_refusal','unsupported_completion','other'):
            raise ValueError('Unknown refusal label; use null for unreviewed or unresolved cases')
        row['refusal_reviewed']=label is not None
        row['correct_outcome']=(row['success'] if row['feasible'] else
            (not row['orders'] and label=='correct_budget_refusal') if label is not None else None)
        if not row['feasible']:
            message=(original.get('report') or {}).get('message')
            if message is None:
                trace=json.loads((stage/row['episode']/'trace.json').read_text(encoding='utf8'))
                message='\n'.join(str(t['unstructured_final']) for t in trace if t.get('unstructured_final'))
            template[row['episode']]=dict(label=None,final_text=message,orders=row['orders'],
                                          report_status=row['report_status'])
        row['needless_noncompletion']=row['feasible'] and not row['success'] and not row['error']
        groups[(row['representation'],row['mode'],row['policy'])].append(row)
    summary=[]
    for key,rows in sorted(groups.items()):
        good=[r for r in rows if not r['error']]
        yes=[r for r in good if r['feasible']];no=[r for r in good if not r['feasible']]
        reviewed=[r for r in no if r['refusal_reviewed']]
        summary.append(dict(zip(('representation','mode','policy'),key),n=len(rows),errors=len(rows)-len(good),
            feasible=len(yes),success=sum(r['success'] for r in yes),infeasible=len(no),
            correct_refusal=sum(bool(r['correct_outcome']) for r in reviewed) if reviewed else None,
            refusal_reviewed=len(reviewed),refusal_unreviewed=len(no)-len(reviewed),
            wrong=sum(r['wrong_commit'] for r in good),
            safe_no_order=sum(not r['orders'] for r in no),
            needless=sum(r['needless_noncompletion'] for r in good),
            mean_actions=sum(r['action_count'] for r in good)/len(good) if good else None))
    if not (stage/'text-annotations.template.json').exists():
        write(stage/'text-annotations.template.json',dict(method=None,rows=template,
            instructions='Copy to text-annotations.json, record the actual review method, and label from task, trace and state. Null means unreviewed.'))
    result=dict(base,cells=summary,refusal_annotation_status='supplied' if annotation_file.exists() else 'unreviewed')
    write(stage/'meaning-metrics.json',result)
    text=['# Truthful price scopes','',
        'USD cents throughout. Different scope, not different underlying price. Native WooCommerce backend; controlled UI/WebMCP adapter.','',
        'Correct refusal requires text-annotations.json. Without review it is unknown, not zero. Safe no-order outcomes are measured separately; record the actual annotation method.','',
        '| Representation | Mode | Policy | Feasible | Completed | Infeasible | Correct refusal (reviewed only) | Reviewed | Unreviewed | Safe no order | Wrong commit | Needlessly incomplete | Errors |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in summary:text.append('| '+' | '.join(str(c[k]) if c[k] is not None else 'unknown' for k in ('representation','mode','policy','feasible','success','infeasible','correct_refusal','refusal_reviewed','refusal_unreviewed','safe_no_order','wrong','needless','errors'))+' |')
    (stage/'MEANING_REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',type=Path)
    run(p.parse_args().stage)
