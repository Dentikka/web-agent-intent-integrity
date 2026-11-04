"""Offline analysis of native-cart drift runs; decision boundaries are explicit."""
from __future__ import annotations
import argparse
import collections
import csv
import json
import hashlib
from pathlib import Path
import sqlite3

from bounded_api import write


def analyze(stage: Path) -> dict:
    write(stage/'analysis-sources.json',dict(analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        actor_sources='Retained separately in immutable manifest.json and source/'))
    manifest=json.loads((stage/'manifest.json').read_text(encoding='utf8'))
    rows=[]
    for file in sorted(stage.glob('*/result.json')):
        result=json.loads(file.read_text(encoding='utf8'))
        backend=json.loads((file.parent/'backend.json').read_text(encoding='utf8'))
        trace=json.loads((file.parent/'trace.json').read_text(encoding='utf8'))
        events=backend['events'];target=backend['target']
        def equal(state):
            items=state['saved']['items']
            return len(items)==1 and all(state['form'][k]==items[0][k] for k in ('product_id','quantity'))
        def requested(state):return all(state['form'][k]==target[k] for k in target)
        assert equal(dict(form={'product_id':backend['initial']['cart']['items'][0]['product_id'],
            'quantity':backend['initial']['cart']['items'][0]['quantity']},saved=backend['initial']['cart']))
        for i,e in enumerate(events):
            if i:assert e['before']==events[i-1]['after'],file.parent.name
        orders=backend['final']['orders']
        cap=backend.get('cap',10000)
        wrong=any(o['items']!=[target] or o['currency']!='USD' or o['total_minor']>cap or o['paid'] for o in orders)
        success=len(orders)==1 and not wrong
        assert wrong==result['scores']['wrong_commit'] and success==result['scores']['task_success']
        commits=[e for e in events if len(e['after']['orders'])>len(e['before']['orders'])]
        first=commits[0]['seq'] if commits else len(events)
        turns={};previous=0
        for t in trace:
            count=t.get('backend_events',previous)
            for seq in range(previous,count):turns[seq]=t['turn']
            previous=count
        commit_turn=turns.get(first,float('inf'))
        reads=[e for e in events[:first] if e['action']=='site_cart']
        available=[e for e in reads if turns[e['seq']]<commit_turn]
        last_edit=max((e['seq'] for e in events[:first] if e['action'] in ('edit','site_replace_cart','save')),default=-1)
        fresh_available=[e for e in available if e['seq']>last_edit]
        drifts=[e for e in events if equal(e['before']) and not equal(e['after'])]
        onset=drifts[0]['seq'] if drifts else None
        resync=[e for e in events if onset is not None and e['seq']>onset and not equal(e['before']) and equal(e['after'])]
        edits=[e for e in events if e['action'] in ('edit','site_replace_cart')]
        row=dict(episode=file.parent.name,**result['spec'],error=result['error'],truncated=result['truncated'],
            terminal_kind=('error' if result['error'] else 'structured' if result['report'] else
                'unstructured' if any(t.get('unstructured_final') for t in trace) else 'turn_cap'),
            success=success,wrong_commit=wrong,duplicate=len(orders)>1,orders=len(orders),
            drift=bool(drifts),first_drift_channel=drifts[0]['channel'] if drifts else None,
            resynchronized=bool(resync),resync_correct=any(requested(e['after']) for e in resync),
            resync_wrong=any(not requested(e['after']) for e in resync),
            drift_at_commit=bool(commits) and not equal(commits[0]['before']),
            commit_channel=commits[0]['channel'] if commits else None,
            first_edit=edits[0]['channel'] if edits else None,
            native_check_chosen=bool(reads),native_check_available=bool(available),
            post_edit_native_check_available=bool(fresh_available),
            action_count=len(trace),seconds=result['seconds'],
            structured_false_completion=bool(result['report']) and result['report']['status']=='completed' and not success)
        row['assigned_start_obeyed']=(row['first_edit']=='ui' if row['mode']=='hybrid_ui_start' else
            row['first_edit']=='tool' if row['mode']=='hybrid_tool_start' else None)
        rows.append(row)
    groups=collections.defaultdict(list)
    for r in rows:groups[(r['sync'],r['mode'],r['policy'])].append(r)
    cells=[]
    for key,rs in sorted(groups.items()):
        valid=[r for r in rs if not r['error']]
        cells.append(dict(zip(('sync','mode','policy'),key),n=len(rs),errors=len(rs)-len(valid),
            valid=len(valid),success=sum(r['success'] for r in valid),wrong=sum(r['wrong_commit'] for r in valid),
            drift=sum(r['drift'] for r in valid),resync_correct=sum(r['resync_correct'] for r in valid),
            resync_wrong=sum(r['resync_wrong'] for r in valid),checks_available=sum(r['native_check_available'] for r in valid),
            no_final=sum(r['truncated'] for r in valid),
            mean_actions=sum(r['action_count'] for r in valid)/len(valid) if valid else None))
    db=sqlite3.connect((stage.parent/'usage.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    charges=db.execute('SELECT episode,COALESCE(actual,reserve),status FROM calls').fetchall();db.close()
    episode_ids={r['episode'] for r in rows}
    spent=sum(v for ep,v,status in charges if ep in episode_ids)
    result=dict(planned=len(manifest['design']),observed=len(rows),valid=sum(not r['error'] for r in rows),
        stage_upper_cost=spent,global_upper_cost=sum(v for ep,v,status in charges),
        unresolved=sum(status=='pending' for ep,v,status in charges),
        uncertain_calls=sum(status=='uncertain' for ep,v,status in charges),
        uncertain_reserve=sum(v for ep,v,status in charges if status=='uncertain'),cells=cells,rows=rows)
    write(stage/'metrics.json',result)
    if rows:
        with (stage/'episodes.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    text=['# Endogenous interface drift: offline results','',
        'Real WooCommerce cart and unpaid orders; controlled form/WebMCP adapters. One model. Exploratory; no field-prevalence claim.','',
        f'Observed {len(rows)}/{len(manifest["design"])}; stage upper tariff ${spent:.6f}; global upper tariff ${result["global_upper_cost"]:.6f}.','',
        '| State | Mode | Policy | Valid | Success | Wrong commit | Drift created | Correct resync | Wrong resync | Prior-turn native check | No structured finish |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in cells:text.append('| '+' | '.join(str(c[k]) for k in ('sync','mode','policy','valid','success','wrong','drift','resync_correct','resync_wrong','checks_available','no_final'))+' |')
    (stage/'REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',type=Path)
    analyze(p.parse_args().stage)
