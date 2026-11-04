"""RQ1-RQ4 descriptive comparisons and explicit cost/latency scaling scenarios.

Pricing replay is not a measurement of another model's tokens, reasoning or speed.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import statistics

from intent_cases import IntentApp,SINGLES
from intent_audit import audit


def analyze(root: Path) -> dict:
    summary=json.loads((root/'summary.json').read_text(encoding='utf8'))
    cfg=json.loads((root/'config.json').read_text(encoding='utf8'))
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
    for name,digest in manifest['sources'].items():
        if hashlib.sha256((root/'source'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen source snapshot mismatch: '+name)
    rows=[]
    with closing(sqlite3.connect(root/'usage.sqlite')) as db:
        calls=[dict(zip(('episode','reserve','actual','status','usage'),r)) for r in db.execute('SELECT episode,reserve,actual,status,usage FROM calls')]
    for p in sorted(root.glob('*/result.json')):
        row=json.loads(p.read_text(encoding='utf8'));row['episode']=p.parent.name
        if row['spec']['section']=='intent':
            spec=row['spec'];app=IntentApp(spec['scenario'],spec['mismatch'],spec['seed'],spec['high_cost'])
            backend=json.loads((p.parent/'backend.json').read_text(encoding='utf8'))
            app.domain.records=backend['final'];app.events=backend['events']
            proposals=[e['observation']['prepared'] for e in app.events if 'prepared' in e['observation']]
            app.proposal=proposals[-1] if proposals else None
            row['scores']=app.score(row['report']);row['cascade_audit']=audit(app,row['report'])
        these=[c for c in calls if c['episode']==p.parent.name]
        row['calls']=len(these)
        row['cost']=sum(c['actual'] if c['actual'] is not None else c['reserve'] for c in these)
        rows.append(row)
    expected={(m['id'],json.dumps(c,sort_keys=True)) for m in manifest['models'] for c in manifest['matrix']}
    actual=[(r['model'],json.dumps(r['spec'],sort_keys=True)) for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)-expected:raise ValueError('Unexpected or duplicate episode')
    coverage_complete=set(actual)==expected
    if summary['complete'] and not coverage_complete:raise ValueError('Summary claims completion but design coverage is incomplete')
    seed_count=len(cfg.get('seeds',[0]))
    section_sizes={s:sum(c['section']==s for c in manifest['matrix']) for s in ('rq1','intent')}
    full_program=(not cfg.get('calibration',False) and section_sizes=={'rq1':54*seed_count,'intent':84*seed_count})
    metrics=('unauthorized_commit','wrong_object_or_terms','duplicate_commit','uncancelled_action','false_success','task_success','receipt_mismatch','read_after_write')
    groups=defaultdict(list)
    for r in rows:
        s=r['spec']
        if s['section']=='rq1':key=(r['model'],'rq1',s['app'],s['condition'],s['mode'])
        else:key=(r['model'],'intent',s['scenario'],s['mismatch'],s['mode'],s['policy'],s['high_cost'])
        groups[key].append(r)
    table=[]
    for key,items in sorted(groups.items(),key=lambda kv:str(kv[0])):
        table.append(dict(key=list(key),n=len(items),reported=sum(not r['truncated'] and not r['error'] for r in items),
            outcomes={m:sum(bool(r['scores'].get(m,False)) for r in items) for m in metrics},
            calls=sum(r['calls'] for r in items),cost=sum(r['cost'] for r in items),seconds=sum(r['seconds'] for r in items)))
    def signature(r,**changes):
        s=dict(r['spec'],**changes)
        return (r['model'],json.dumps(s,sort_keys=True))
    lookup={signature(r):r for r in rows}
    contrasts=[]
    for r in rows:
        s=r['spec']
        if s['section']!='intent':continue
        partner=None;kind=None
        if s['mismatch']:
            partner=lookup.get(signature(r,mismatch=False));kind='mismatch-minus-aligned'
        if partner is not None:
            contrasts.append(dict(kind=kind,spec=s,model=r['model'],
                deltas={m:int(bool(r['scores'].get(m)))-int(bool(partner['scores'].get(m))) for m in metrics},
                calls_delta=r['calls']-partner['calls'],cost_delta=r['cost']-partner['cost']))
        if s['policy']!='baseline':
            partner=lookup.get(signature(r,policy='baseline'))
            if partner:
                contrasts.append(dict(kind=s['policy']+'-minus-baseline',spec=s,model=r['model'],
                    deltas={m:int(bool(r['scores'].get(m)))-int(bool(partner['scores'].get(m))) for m in metrics},
                    calls_delta=r['calls']-partner['calls'],cost_delta=r['cost']-partner['cost']))
    usage=[json.loads(c['usage']) for c in calls if c['usage']]
    inp=sum(u['prompt_tokens'] for u in usage);out=sum(u['completion_tokens'] for u in usage)
    # For multiple measured models, project their mean workload to two target models.
    measured_models=len({r['model'] for r in rows}) or 1
    ip,op=inp/measured_models,out/measured_models
    pricing=[]
    for name,i_mult,o_mult in (('token_replay',1,1),('tokenizer_and_reasoning_stress',1.5,2),('larger_reasoning_stress',1.5,4)):
        opus=(ip*i_mult*4+op*o_mult*20)/1e6
        sol=(ip*i_mult*2+op*o_mult*10)/1e6
        pricing.append(dict(scenario=name,input_multiplier=i_mult,output_multiplier=o_mult,
            opus_5_5_usd=opus,sol_profile_usd=sol,combined_usd=opus+sol,within_main_18_usd=opus+sol<=18,
            within_main_19_usd=opus+sol<=19,within_total_20_usd=opus+sol<=20,
            prices_per_million=dict(opus_5_5=[4,20],sol_profile=[2,10])))
    request_count=len(calls)/measured_models
    workers=int(cfg.get('workers',4))
    # Include 50% scheduling/native/UI overhead. No claim of observed Opus latency.
    latency=[dict(seconds_per_model_call=seconds,projected_hours_two_models=request_count*2*seconds/workers*1.5/3600,
                  within_7_5_hours=request_count*2*seconds/workers*1.5<=7.5*3600)
             for seconds in (5,10,20,30,45,60)]
    break_even=7.5*3600*workers/(request_count*2*1.5) if request_count else None
    result=dict(complete=summary['complete'] and coverage_complete,coverage_complete=coverage_complete,full_program=full_program,
        scaling_covers_full_program=full_program and coverage_complete and summary['complete'],episodes=len(rows),planned=len(expected),
        cost_upper_tariff_usd=summary['cost_upper_tariff_usd'],api_calls=len(calls),input_tokens=inp,output_tokens=out,
        errors=summary['errors'],pending_api_calls=summary['pending_calls'],
        table=table,paired_contrasts=contrasts,
        rq3_audits=[dict(episode=r['episode'],spec=r['spec'],audit=r['cascade_audit']) for r in rows if 'cascade_audit' in r],
        pricing_scenarios=pricing,latency_scenarios=latency,latency_break_even_seconds_two_models=break_even,
        uncertainty='One sample/cell, three synthetic apps sharing a framework; no valid cross-site confidence interval or significance claim.',
        pricing_sources=['https://platform.claude.com/docs/en/about-claude/pricing','https://developers.openai.com/api/docs/pricing'],
        scaling_limit='Opus 5.5 always has adaptive thinking. Replay/stress scenarios are conditional forecasts; actual provider compatibility, token usage and latency need calibration before paid scale-out.')
    result['evaluator_sources']={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('intent_cases.py','intent_audit.py','program_analyze.py')}
    if (root/'validation-notes.json').exists():result['validation_notes']=json.loads((root/'validation-notes.json').read_text(encoding='utf8'))
    (root/'program-metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# \u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0430 RQ1–RQ4: \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0438 \u043c\u0430\u0441\u0448\u0442\u0430\u0431\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435','',
        f"\u042d\u043f\u0438\u0437\u043e\u0434\u044b: {len(rows)}/{summary['planned']}; complete={summary['complete']}. API-\u0432\u044b\u0437\u043e\u0432\u044b: {len(calls)}. \u0420\u0430\u0441\u0445\u043e\u0434 \u043f\u043e \u0432\u0435\u0440\u0445\u043d\u0435\u043c\u0443 \u0442\u0430\u0440\u0438\u0444\u0443: ${summary['cost_upper_tariff_usd']:.6f}.",'',
        f'\u0422\u043e\u043a\u0435\u043d\u044b \u0432\u0445\u043e\u0434\u0430/\u0432\u044b\u0445\u043e\u0434\u0430: {inp} / {out}. \u0412\u0441\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044b \u0438\u0441\u0442\u043e\u0440\u0438\u0438 \u0438 \u0441\u0445\u0435\u043c\u044b \u0438\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442\u043e\u0432 \u0432\u043a\u043b\u044e\u0447\u0435\u043d\u044b.','',
        '## \u041f\u0435\u0440\u0435\u0441\u0447\u0451\u0442 \u043d\u0430 \u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0435 \u0442\u0430\u0440\u0438\u0444\u044b','',
        '[Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview): $4/$20 \u0437\u0430 \u043c\u043b\u043d input/output, \u0431\u0435\u0437 \u043a\u044d\u0448-\u0441\u043a\u0438\u0434\u043a\u0438. Sol-\u043f\u0440\u043e\u0444\u0438\u043b\u044c: $2/$10. \u0420\u0438\u0437\u043e\u043d\u0438\u043d\u0433 Opus \u043d\u0435\u043b\u044c\u0437\u044f \u043e\u0442\u043a\u043b\u044e\u0447\u0438\u0442\u044c; \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b DeepSeek \u0431\u0435\u0437 \u0440\u0438\u0437\u043e\u043d\u0438\u043d\u0433\u0430 \u043d\u0435 \u0434\u0430\u044e\u0442 \u0435\u0433\u043e \u0444\u0430\u043a\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0440\u0430\u0441\u0445\u043e\u0434.','',
        '| \u0421\u0446\u0435\u043d\u0430\u0440\u0438\u0439 \u043d\u0430\u0433\u0440\u0443\u0437\u043a\u0438 | Opus 5.5 | Sol-\u043f\u0440\u043e\u0444\u0438\u043b\u044c | \u0412\u043c\u0435\u0441\u0442\u0435 | \u0412 $19 main |','|---|---:|---:|---:|---|']
    if result.get('validation_notes'):
        lines[2:2]=['**\u041e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u0435 \u0432\u0435\u0440\u0441\u0438\u0438:** '+result['validation_notes']['limitation'],'']
    for p in pricing:lines.append(f"| {p['scenario']} | ${p['opus_5_5_usd']:.2f} | ${p['sol_profile_usd']:.2f} | ${p['combined_usd']:.2f} | {p['within_main_19_usd']} |")
    lines+=['',f'\u041f\u0435\u0440\u0435\u0441\u0447\u0451\u0442 \u043f\u043e\u043a\u0440\u044b\u0432\u0430\u0435\u0442 \u043f\u043e\u043b\u043d\u0443\u044e \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0443: {full_program and coverage_complete and summary["complete"]}. \u0414\u043b\u044f \u044d\u0442\u043e\u0433\u043e \u043d\u0443\u0436\u043d\u044b \u0432\u0441\u0435 54 RQ1 \u0438 84 intent-\u044f\u0447\u0435\u0439\u043a\u0438 \u043d\u0430 seed. complete=true \u0443 \u043a\u0430\u043b\u0438\u0431\u0440\u043e\u0432\u043a\u0438 \u0438\u0437 \u0442\u0440\u0451\u0445 \u044f\u0447\u0435\u0435\u043a \u043d\u0435 \u044f\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u043f\u0440\u043e\u0433\u043d\u043e\u0437\u043e\u043c 138 \u044d\u043f\u0438\u0437\u043e\u0434\u043e\u0432. \u041f\u0440\u0438 \u043d\u0435\u043f\u043e\u043b\u043d\u043e\u0439 \u0438\u043b\u0438 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0439 \u043f\u043e\u0434\u0441\u0435\u0440\u0438\u0438 \u043f\u043e\u043a\u0430\u0437\u0430\u043d \u043b\u0438\u0448\u044c \u0442\u0430\u0440\u0438\u0444\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0441\u0447\u0451\u0442 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u043d\u043e\u0433\u043e \u043e\u0431\u044a\u0451\u043c\u0430.','',
        '## \u0412\u0440\u0435\u043c\u044f','',
        f'\u041f\u0440\u0438 {workers} \u0432\u043e\u0440\u043a\u0435\u0440\u0430\u0445 \u0438 50% \u0437\u0430\u043f\u0430\u0441\u0435 \u043d\u0430\u043a\u043b\u0430\u0434\u043d\u044b\u0445 \u0440\u0430\u0441\u0445\u043e\u0434\u043e\u0432 \u0441\u0440\u0435\u0434\u043d\u044f\u044f \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u043c\u043e\u0434\u0435\u043b\u044c\u043d\u043e\u0433\u043e \u0432\u044b\u0437\u043e\u0432\u0430 \u0434\u043b\u044f \u0434\u0432\u0443\u0445 \u043c\u043e\u0434\u0435\u043b\u0435\u0439 \u0434\u043e\u043b\u0436\u043d\u0430 \u0431\u044b\u0442\u044c \u043d\u0435 \u0432\u044b\u0448\u0435 {break_even:.1f} \u0441\u0435\u043a\u0443\u043d\u0434, \u0447\u0442\u043e\u0431\u044b \u0443\u043b\u043e\u0436\u0438\u0442\u044c\u0441\u044f \u0432 7.5 \u0447\u0430\u0441\u0430.' if break_even else '\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e API-\u0432\u044b\u0437\u043e\u0432\u043e\u0432 \u0434\u043b\u044f \u0440\u0430\u0441\u0447\u0451\u0442\u0430.',
        '\u042d\u0442\u043e \u0434\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u0430\u044f latency, \u043d\u0435 \u0438\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u0435 \u0441\u043a\u043e\u0440\u043e\u0441\u0442\u0438 Opus. \u0421\u0446\u0435\u043d\u0430\u0440\u0438\u0438 5–60 \u0441\u0435\u043a\u0443\u043d\u0434 \u043d\u0430 \u0432\u044b\u0437\u043e\u0432 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u044b \u0432 JSON. Runtime \u0438\u043c\u0435\u0435\u0442 \u043e\u0431\u0449\u0438\u0439 deadline, \u043d\u043e \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043f\u043e \u043d\u0435\u043c\u0443 \u043d\u0435 \u0434\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u0435 \u0432\u0441\u0435\u0439 \u043c\u0430\u0442\u0440\u0438\u0446\u044b.','',
        '## \u0418\u043d\u0442\u0435\u0440\u043f\u0440\u0435\u0442\u0430\u0446\u0438\u044f','',
        'RQ2: \u043f\u0430\u0440\u043d\u044b\u0435 mismatch–aligned \u0440\u0430\u0437\u043d\u043e\u0441\u0442\u0438 \u043f\u0440\u0438 \u043e\u0434\u043d\u043e\u043c \u0437\u0430\u0434\u0430\u043d\u0438\u0438, \u0440\u0435\u0436\u0438\u043c\u0435, \u043f\u043e\u043b\u0438\u0442\u0438\u043a\u0435 \u0438 \u0446\u0435\u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438. RQ3: \u043d\u0430\u0431\u043b\u044e\u0434\u0430\u0435\u043c\u044b\u0435 \u0441\u0438\u0433\u043d\u0430\u043b\u044b, commit, readback, \u043f\u043e\u0432\u0442\u043e\u0440 \u0438 \u043e\u0442\u0447\u0451\u0442; \u0432\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u0438\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u044b \u043d\u0435 \u0432\u044b\u0432\u043e\u0434\u044f\u0442\u0441\u044f \u0438\u0437 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0438\u044f \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0439. RQ4: \u043f\u0430\u0440\u043d\u044b\u0435 \u0440\u0430\u0437\u043d\u043e\u0441\u0442\u0438 \u043f\u043e\u043b\u043d\u043e\u0439 \u0438 \u043a\u043e\u043c\u043f\u043e\u043d\u0435\u043d\u0442\u043d\u044b\u0445 \u043f\u043e\u043b\u0438\u0442\u0438\u043a \u043e\u0442\u043d\u043e\u0441\u0438\u0442\u0435\u043b\u044c\u043d\u043e baseline \u0441 \u0443\u0447\u0451\u0442\u043e\u043c \u0437\u0430\u0442\u0440\u0430\u0442 \u0438 \u043d\u0435\u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u044b\u0445 \u0437\u0430\u0434\u0430\u0447.','',
        '\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 counts, \u0437\u043d\u0430\u043c\u0435\u043d\u0430\u0442\u0435\u043b\u0438, \u043a\u043e\u043d\u0442\u0440\u0430\u0441\u0442\u044b, \u0430\u0431\u043b\u044f\u0446\u0438\u0438, \u0441\u043e\u0447\u0435\u0442\u0430\u043d\u0438\u044f \u0444\u0430\u043a\u0442\u043e\u0440\u043e\u0432 \u0438 RQ3-\u0430\u0443\u0434\u0438\u0442\u044b \u043d\u0430\u0445\u043e\u0434\u044f\u0442\u0441\u044f \u0432 program-metrics.json. \u0421\u044b\u0440\u043e\u0439 RQ1-\u0444\u043b\u0430\u0433 false_success \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u043e\u0439 \u0442\u043e\u0447\u043d\u043e\u0439 \u043a\u0432\u0438\u0442\u0430\u043d\u0446\u0438\u0438; \u0432 RQ2–RQ4 false_success \u043e\u0437\u043d\u0430\u0447\u0430\u0435\u0442 \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0438\u0435 \u043d\u0443\u0436\u043d\u043e\u0433\u043e backend-\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430, \u0430 receipt_mismatch \u0445\u0440\u0430\u043d\u0438\u0442\u0441\u044f \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e.','',
        '\u0422\u0440\u0438 \u0434\u043e\u043c\u0435\u043d\u043d\u044b\u0445 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f \u0438\u043c\u0435\u044e\u0442 \u043e\u0431\u0449\u0438\u0439 UI/\u0442\u0440\u0430\u043d\u0441\u043f\u043e\u0440\u0442. \u041e\u0434\u0438\u043d seed \u0438 \u043e\u0434\u0438\u043d \u0441\u044d\u043c\u043f\u043b \u043d\u0430 \u044f\u0447\u0435\u0439\u043a\u0443 \u043d\u0435 \u0434\u0430\u044e\u0442 \u0441\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043d\u0430\u0434\u0451\u0436\u043d\u043e\u0439 \u043e\u0446\u0435\u043d\u043a\u0438 \u043f\u0435\u0440\u0435\u043d\u043e\u0441\u0430 \u043d\u0430 \u043d\u0435\u0437\u0430\u0432\u0438\u0441\u0438\u043c\u044b\u0435 \u0441\u0430\u0439\u0442\u044b. \u0420\u0435\u0430\u043b\u0438\u0441\u0442\u0438\u0447\u043d\u043e\u0441\u0442\u044c \u0432\u043c\u0435\u0448\u0430\u0442\u0435\u043b\u044c\u0441\u0442\u0432 \u0434\u043e\u043b\u0436\u043d\u0430 \u0431\u044b\u0442\u044c \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0432\u043d\u0435\u0448\u043d\u0438\u043c \u0430\u0443\u0434\u0438\u0442\u043e\u043c \u0438\u043b\u0438 \u044d\u043a\u0441\u043f\u0435\u0440\u0442\u043d\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u043e\u0439 \u043f\u0435\u0440\u0435\u0434 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u044e\u0449\u0435\u0439 \u0441\u0435\u0440\u0438\u0435\u0439.']
    lines+=['','## \u041e\u0441\u043d\u043e\u0432\u043d\u044b\u0435 \u0438\u0441\u0445\u043e\u0434\u044b RQ2/RQ4','',
        '| \u0420\u0435\u0436\u0438\u043c / \u043f\u043e\u043b\u0438\u0442\u0438\u043a\u0430 | n | \u041e\u043f\u0430\u0441\u043d\u044b\u0439 commit | \u041b\u043e\u0436\u043d\u043e\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u0435 | Backend-\u0443\u0441\u043f\u0435\u0445 | \u041d\u0435\u0442 \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u043e\u0442\u0447\u0451\u0442\u0430 | \u0421\u0440\u0435\u0434\u043d\u0435\u0435 API-\u0432\u044b\u0437\u043e\u0432\u043e\u0432 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    core=[r for r in rows if r['spec']['section']=='intent' and r['spec']['scenario'] in SINGLES and not r['spec']['high_cost']]
    for mode,policy in (('ui','baseline'),('tool','baseline'),('hybrid','baseline'),('hybrid','full')):
        items=[r for r in core if r['spec']['mode']==mode and r['spec']['policy']==policy]
        if not items:continue
        danger=sum(any(r['scores'][m] for m in ('unauthorized_commit','wrong_object_or_terms','duplicate_commit')) for r in items)
        lines.append(f"| {mode} / {policy} | {len(items)} | {danger} | {sum(r['scores']['false_success'] for r in items)} | {sum(r['scores']['task_success'] for r in items)} | {sum(r['truncated'] for r in items)} | {statistics.mean(r['calls'] for r in items):.2f} |")
    lines+=['','\u041d\u0430\u0447\u0430\u043b\u044c\u043d\u0430\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430, \u043e\u0442\u043c\u0435\u043d\u0443 \u043a\u043e\u0442\u043e\u0440\u043e\u0439 backend \u0432\u0441\u0435\u0433\u0434\u0430 \u043e\u0442\u043a\u043b\u043e\u043d\u044f\u0435\u0442, \u043d\u0435 \u0441\u0447\u0438\u0442\u0430\u0435\u0442\u0441\u044f \u043e\u043f\u0430\u0441\u043d\u044b\u043c \u043d\u043e\u0432\u044b\u043c commit. \u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 uncancelled \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e; \u043e\u043d\u043e \u0441\u0430\u043c\u043e \u043f\u043e \u0441\u0435\u0431\u0435 \u043d\u0435 \u0434\u043e\u043a\u0430\u0437\u044b\u0432\u0430\u0435\u0442 \u043e\u0448\u0438\u0431\u043a\u0443 \u0430\u0433\u0435\u043d\u0442\u0430. \u0426\u0435\u043d\u0430 \u0432\u044b\u0448\u0435 \u043b\u0438\u043c\u0438\u0442\u0430 \u0438 \u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u044b\u0439 \u043e\u0442\u043a\u0430\u0437 \u0442\u0430\u043a\u0436\u0435 \u043d\u0435 \u0440\u0430\u0432\u043d\u044b \u0443\u0441\u043f\u0435\u0448\u043d\u043e\u0439 \u0442\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0438.','',
        '\u041e\u0448\u0438\u0431\u043a\u0438 \u0437\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f object/id \u0432 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u043e\u0439 \u043a\u0432\u0438\u0442\u0430\u043d\u0446\u0438\u0438 \u0438 truthfulness \u0442\u0435\u043a\u0441\u0442\u0430 \u0442\u0440\u0435\u0431\u0443\u044e\u0442 \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e\u0433\u043e \u0432\u043d\u0438\u043c\u0430\u043d\u0438\u044f. \u041e\u0446\u0435\u043d\u043a\u0430 proposal \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0435\u0442 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f \u043e\u0431\u044a\u0435\u043a\u0442\u0430/\u0446\u0435\u043d\u044b, \u0430 \u043d\u0435 \u0442\u043e\u043b\u044c\u043a\u043e \u0444\u0430\u043a\u0442 \u043f\u043e\u044f\u0432\u043b\u0435\u043d\u0438\u044f \u043b\u044e\u0431\u043e\u0433\u043e \u043f\u0440\u0435\u0434\u043b\u043e\u0436\u0435\u043d\u0438\u044f. \u0412 evaluator_sources \u0437\u0430\u043f\u0438\u0441\u0430\u043d\u044b \u0432\u0435\u0440\u0441\u0438\u0438 \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u043e\u0433\u043e scorer \u0438 \u0430\u0443\u0434\u0438\u0442\u0430; \u0438\u0441\u0445\u043e\u0434\u043d\u044b\u0435 result.json \u0438 frozen sources \u043d\u0435 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0438\u0441\u0430\u043d\u044b.']
    (root/'PROGRAM_REPORT_RU.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('run',type=Path);r=analyze(p.parse_args().run)
    print(json.dumps({k:v for k,v in r.items() if k not in ('table','paired_contrasts','rq3_audits')},ensure_ascii=False))
