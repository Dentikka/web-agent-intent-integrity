"""Fixed reviewer-control experiment, with model-free validation first."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from point2_review_controls.design import matrix
from point2_review_controls.surfaces import Surface,activate,initialize_catalog,native
from point2_review_controls.run import run_worker,scores
ART=ROOT/'artifacts/point2_review_controls';PYTHON=ROOT/'.tools/colleague-venv/bin/python'
ACTIVE=[0,1,2,3,4,5,7,12,16,17,18,19]

def targets():
    ts=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers']
    return {i:dict(ts[i],cells=[],budget_usd=4 if ts[i]['app']=='ea' else 3) for i in ACTIVE}

def grouped(args,log):
    return subprocess.Popen(['sudo','-n','setpriv','--reuid',str(os.getuid()),'--regid',str(os.stat('/var/run/docker.sock').st_gid),
        '--init-groups','--reset-env',str(PYTHON),'-u',str(Path(__file__).resolve()),*args],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)

def validate(index):
    from playwright.sync_api import sync_playwright
    target=targets()[index];activate(target);cfg=json.loads((ROOT/'configs/point2_v2.json').read_text());allc=matrix([m['id'] for m in cfg['models']])
    out=ART/'validation'/str(index);out.mkdir(parents=True,exist_ok=True)
    if target['app']=='medusa':(out/'catalog.json').write_text(initialize_catalog())
    app=target['app'];i=(ACTIVE.index(index))%6;arm=['fresh_ui','fresh_tool','full'][ACTIVE.index(index)%3]
    selected=[next(c for c in allc if c['block']=='active_source' and c['app']==app and c['task_id']==i and c['condition']==cond and c['evidence_arm']==arm) for cond in ['ui_stale_over','tool_stale_under']]
    if app=='medusa':
        task_id=100+[0,1,2,3,4,5,6,7][ACTIVE.index(index)]
        selected+=[next(c for c in allc if c['block']=='effort_budget' and c['task_id']==task_id and c['ui_steps']==cost and c['budget']=='double') for cost in [1,7]]
    else:
        selected+=[next(c for c in allc if c['block']=='duration' and c['task_id']==i and c['feasible']==f and c['evidence_arm']==arm) for f in [False,True]]
    with sync_playwright() as p:
        b=p.chromium.connect_over_cdp('http://127.0.0.1:'+('9235' if app=='medusa' else '9234'))
        for j,c in enumerate(selected):
            folder=out/str(j);folder.mkdir(exist_ok=True);s=Surface(b,c,target,folder)
            if c['policy']=='evidence':
                events=s.assisted_evidence();assert len(events)==4 and not s.observe()
                shown=[e for e in events if e['observation']!={'verification_preparation_completed':True}]
                assert len(shown)==(2 if arm=='full' else 1)
            if c['block']=='effort_budget' and c['ui_steps']==7:
                assert s.visible_total() is None
                for k in range(6):s.act('ui_click',{'selector':'#review-open-summary'})
                assert s.visible_total()==c['actual_total']
                assert s.page.evaluate("sessionStorage.getItem('review_gate_remaining')")=='0'
                s.act('ui_reload',{});assert s.visible_total()==c['actual_total']
            # Independent positive/negative duration-write golds on one own EA.
            if index==16 and c['block']=='duration':
                avail=native(s.page,'check_availability',dict(service_id=s.service_id,provider_id=2,date=c['day'],days=1))
                d=next(d for d in avail['days'] if d.get('open_slots'))
                result=native(s.page,'book_appointment',dict(service_id=s.service_id,provider_id=2,date=d['date'],time=d['open_slots'][0],
                    first_name='Alex',last_name='Research',email='ea.point2.v2@example.com',phone_number='+15550199',address='10 Test Street',city='London',zip_code='SW1A 1AA',notes=''))
                backend=s.observe();sc=scores(c,backend,None,[])
                assert len(backend)==1 and sc['dangerous_commit']==(not c['feasible']),(result,backend,sc)
                (folder/'gold_write.json').write_text(json.dumps(dict(backend=backend,scores=sc),indent=2))
            (folder/'passed.json').write_text(json.dumps(dict(spec=c,passed=True),indent=2));s.close();print('validated',index,j,flush=True)
        b.close()

def main(reuse_validation=False):
    ART.mkdir(exist_ok=True)
    assert not (ART/'plan.json').exists(),'Never replay paid study'
    if not reuse_validation:
        jobs=[]
        for i in ACTIVE:
            with (ART/f'validation-{i}.log').open('a') as log:jobs.append(grouped(['validate',str(i)],log))
        codes=[p.wait() for p in jobs];(ART/'validation_exit_codes.json').write_text(json.dumps(codes));assert not any(codes),codes
    assert len(list((ART/'validation').glob('*/*/passed.json')))==48
    cfg=json.loads((ROOT/'configs/point2_v2.json').read_text());cells=matrix([m['id'] for m in cfg['models']]);ts=targets()
    counts=dict(ea=0,medusa=0);slots={a:[i for i,t in ts.items() if t['app']==a] for a in counts}
    for c in cells:
        app=c['app'];i=slots[app][counts[app]%len(slots[app])];counts[app]+=1;ts[i]['cells'].append(c)
    paths=[Path(__file__).resolve(),ROOT/'configs/point2_v2.json',ROOT/'research/point2_review_controls/PROTOCOL_RU.md',ROOT/'vendor/colleague-intent-integrity/webmcp-intent-integrity-main/api_client.py']
    for d in ['point2_review_controls','point2_v3','point2_routes_live','medusa_v1','realapp_v1']:
        paths+=[p for p in (ROOT/'src'/d).glob('*') if p.suffix in ['.py','.js']]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        dest=ART/'frozen_inputs'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    (ART/'plan.json').write_text(json.dumps(dict(cells=cells,workers={str(i):t for i,t in ts.items()},planned=1152,source_hashes=hashes,started_epoch=time.time(),budget_usd=40),indent=2))
    jobs=[]
    for i in ACTIVE:
        with (ART/f'worker-{i}.log').open('w') as log:jobs.append(grouped(['worker',str(i)],log))
    codes=[p.wait() for p in jobs];(ART/'exit_codes.json').write_text(json.dumps(codes))
    assert not any(codes),'Preserve and audit paid episodes; do not replay'
    assert len(list(ART.glob('worker-*/*/result.json')))==1152
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=1152,paid_replays=0)))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='validate':validate(int(sys.argv[2]))
    elif len(sys.argv)>1 and sys.argv[1]=='worker':
        i=sys.argv[2];t=json.loads((ART/'plan.json').read_text())['workers'][i];activate(t)
        run_worker(json.loads((ROOT/'configs/point2_v2.json').read_text()),t,t['cells'],ART/f'worker-{i}')
    elif len(sys.argv)>1 and sys.argv[1]=='repair-ea-and-run':
        jobs=[]
        for i in [16,17,18,19]:
            with (ART/f'validation-{i}.log').open('a') as log:jobs.append(grouped(['validate',str(i)],log))
        codes=[p.wait() for p in jobs];(ART/'ea_validation_exit_codes.json').write_text(json.dumps(codes));assert not any(codes),codes
        main(True)
    else:main()
