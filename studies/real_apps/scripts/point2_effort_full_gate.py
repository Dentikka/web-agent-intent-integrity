import hashlib,json,os,random,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from point2_review_controls.surfaces import activate as setup,initialize_catalog
from point2_effort_full_gate.runtime import Surface,activate
from point2_review_controls.run import run_worker,scores
ART=ROOT/'artifacts/point2_effort_full_gate';ACTIVE=[0,1,2,3,4,5,7,12]
def matrix():
    parent=json.loads((ROOT/'artifacts/point2_review_controls/plan.json').read_text())
    cells=[dict(c,block='effort_full_gate',study='review_effort_full_gate',cohort='post_delivery_fee_audit') for c in parent['cells'] if c['block']=='effort_budget']
    random.Random(2026102410).shuffle(cells);assert len(cells)==192;return cells

def grouped(args,log):
    return subprocess.Popen(['sudo','-n','setpriv','--reuid',str(os.getuid()),'--regid',str(os.stat('/var/run/docker.sock').st_gid),'--init-groups','--reset-env',
        str(ROOT/'.tools/colleague-venv/bin/python'),'-u',str(Path(__file__).resolve()),*args],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)

def target(i):return json.loads((ROOT/'artifacts/point2_review_controls/plan.json').read_text())['workers'][str(i)]
def validate(i):
    from playwright.sync_api import sync_playwright
    t=target(i);setup(t);out=ART/'validation'/str(i);out.mkdir(parents=True,exist_ok=True);(out/'catalog.json').write_text(initialize_catalog());cells=matrix()
    with sync_playwright() as p:
        b=p.chromium.connect_over_cdp('http://127.0.0.1:9235')
        for j,steps in enumerate([7,1]):
            c=next(c for c in cells if c['task_id']==100+ACTIVE.index(i) and c['ui_steps']==steps and c['condition']=='tool_stale_under')
            f=out/str(j);f.mkdir(exist_ok=True);s=Surface(b,c,t,f)
            if steps==7:
                assert '€' not in s.read()['text']
                for k in range(6):s.act('ui_click',{'selector':'#review-open-summary'})
            assert s.visible_total()==c['actual_total'] and c['shipping'] in s.read()['text']
            if i==0 and steps==1:
                s.page.get_by_test_id('submit-order-button').click()
                for z in range(60):
                    if s.observe():break
                    s.page.wait_for_timeout(250)
                assert scores(c,s.observe(),None,[])['valid_commit']
                (f/'gold_write.json').write_text(json.dumps(s.observe(),indent=2))
            (f/'passed.json').write_text(json.dumps(dict(passed=True,spec=c),indent=2));s.close();print('passed',i,j,flush=True)
        b.close()
def main():
    assert not (ART/'plan.json').exists();jobs=[]
    for i in ACTIVE:
        with (ART/f'validation-{i}.log').open('a') as log:jobs.append(grouped(['validate',str(i)],log))
    codes=[p.wait() for p in jobs];assert not any(codes),codes
    cells=matrix();workers={str(i):dict(target(i),cells=[],budget_usd=1) for i in ACTIVE}
    for j,c in enumerate(cells):workers[str(ACTIVE[j%8])]['cells'].append(c)
    paths=[Path(__file__).resolve(),ROOT/'research/point2_effort_full_gate/PROTOCOL_RU.md',ROOT/'configs/point2_v2.json']
    for d in ['point2_effort_full_gate','point2_review_controls','point2_v3','point2_routes_live','medusa_v1','realapp_v1']:
        paths += [p for p in (ROOT/'src'/d).glob('*') if p.suffix in ['.py','.js']]
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        f=ART/'frozen_inputs'/p.relative_to(ROOT);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(p.read_bytes())
    (ART/'plan.json').write_text(json.dumps(dict(cells=cells,workers=workers,source_hashes=hashes,planned=192,reason='current delivery fee remained visible in prior partial gate'),indent=2))
    jobs=[]
    for i in ACTIVE:
        with (ART/f'worker-{i}.log').open('w') as log:jobs.append(grouped(['worker',str(i)],log))
    codes=[p.wait() for p in jobs];(ART/'exit_codes.json').write_text(json.dumps(codes));assert not any(codes),codes
    assert len(list(ART.glob('worker-*/*/result.json')))==192
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=192,paid_replays=0)))
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='validate':validate(int(sys.argv[2]))
    elif len(sys.argv)>1:
        i=sys.argv[2];t=json.loads((ART/'plan.json').read_text())['workers'][i];setup(t);activate();run_worker(json.loads((ROOT/'configs/point2_v2.json').read_text()),t,t['cells'],ART/f'worker-{i}')
    else:main()
