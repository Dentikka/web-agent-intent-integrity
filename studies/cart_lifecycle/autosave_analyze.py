"""Offline quiescent-state evaluation for the own-autosave cart task."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sqlite3

from bounded_api import write


def analyze(stage: Path) -> dict:
    manifest=json.loads((stage/'manifest.json').read_text(encoding='utf8'))
    rows=[]
    for path in sorted(stage.glob('*/result.json')):
        r=json.loads(path.read_text(encoding='utf8'))
        b=json.loads((path.parent/'backend.json').read_text(encoding='utf8'))
        trace=json.loads((path.parent/'trace.json').read_text(encoding='utf8'))
        target=b['target'];cart=b['final']['saved']
        def matches(c):return len(c['items'])==1 and all(c['items'][0][k]==target[k] for k in target)
        correct=matches(cart)
        assert correct==r['scores']['final_cart_matches']
        assert not b['final']['pending_saves']
        for i,e in enumerate(b['events']):
            if i:assert e['before']==b['events'][i-1]['after'],path.parent.name
            if e['channel']=='background':
                origin=e['args']['scheduled_from_seq']
                assert origin<e['seq'] and b['events'][origin]['action']=='edit'
        observations=[t['observation']['saved_cart'] for t in trace if isinstance(t.get('observation'),dict) and 'saved_cart' in t['observation']]
        report=r.get('report') or {}
        row=dict(episode=path.parent.name,**r['spec'],error=r['error'],success=r['scores']['task_success'],
            final_cart_matches=correct,lost_update=r['scores']['lost_update_observed'],
            pending_at_report=r['scores']['pending_at_finish'],
            structured_false_completion=report.get('status')=='completed' and not correct,
            last_native_cart_observation_correct=matches(observations[-1]) if observations else None,
            preview_done=r['scores']['preview_done'],native_final_attempted=r['scores']['native_final_attempted'],
            actions=len(trace),seconds=r['seconds'],report_status=report.get('status'),
            waited=any(t.get('tool')=='site_wait_for_save' or (t.get('tool')=='ui_click' and json.loads(t['args']).get('id')=='save') for t in trace if t.get('args')))
        rows.append(row)
    groups=collections.defaultdict(list)
    for row in rows:groups[(row['timing'],row['policy'])].append(row)
    cells=[]
    for key,rs in sorted(groups.items()):
        good=[r for r in rs if not r['error']]
        cells.append(dict(zip(('timing','policy'),key),n=len(rs),valid=len(good),errors=len(rs)-len(good),
            success=sum(r['success'] for r in good),lost_update=sum(r['lost_update'] for r in good),
            wrong_final=sum(not r['final_cart_matches'] for r in good),
            pending_at_report=sum(r['pending_at_report'] for r in good),
            false_completion=sum(r['structured_false_completion'] for r in good),
            waited=sum(r['waited'] for r in good)))
    db=sqlite3.connect((stage.parent/'usage.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    charges=db.execute('SELECT episode,COALESCE(actual,reserve),status FROM calls').fetchall();db.close()
    ids={r['episode'] for r in rows}
    result=dict(planned=len(manifest['design']),observed=len(rows),valid=sum(not r['error'] for r in rows),
        stage_upper_cost=sum(v for ep,v,s in charges if ep in ids),global_upper_cost=sum(v for ep,v,s in charges),
        pending=sum(s=='pending' for ep,v,s in charges),cells=cells,rows=rows)
    write(stage/'metrics.json',result)
    write(stage/'analysis-sources.json',dict(analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    text=['# Own queued autosaves','',
        'Controlled asynchronous adapter; native WooCommerce saved cart. Outcome is read after own pending jobs finish. No orders requested.','',
        '| Materialization | Policy | Valid | Success | Lost update observed | Wrong final cart | Pending at report | Structured false completion | Used wait | Errors |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in cells:text.append('| '+' | '.join(str(c[k]) for k in ('timing','policy','valid','success','lost_update','wrong_final','pending_at_report','false_completion','waited','errors'))+' |')
    (stage/'AUTOSAVE_REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',type=Path)
    analyze(p.parse_args().stage)
