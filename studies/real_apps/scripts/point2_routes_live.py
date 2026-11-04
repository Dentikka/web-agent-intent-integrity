"""Execute the fixed 216-route matrix using warm stores and isolated sessions."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from point2_routes_replication import matrix
from point2_routes_live.runtime import activate,initialize_catalog,Surface
from point2_v3.surfaces import relocate
from point2_v3.run import run_worker
ART=ROOT/'artifacts/point2_routes_replication'
ACTIVE=[0,1,2,3,4,5,7,12]
PYTHON=ROOT/'.tools/colleague-venv/bin/python'

def grouped(args,log):
    command=['sudo','-n','setpriv','--reuid',str(os.getuid()),'--regid',str(os.stat('/var/run/docker.sock').st_gid),'--init-groups','--reset-env',
        str(PYTHON),'-u',str(Path(__file__).resolve()),*args]
    return subprocess.Popen(command,cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log,start_new_session=True)

def validate(index):
    from playwright.sync_api import sync_playwright
    target=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers'][index]
    relocate(target);activate();folder=ART/'warm_validation'/str(index);folder.mkdir(parents=True,exist_ok=True)
    (folder/'catalog.json').write_text(initialize_catalog())
    config=json.loads((ROOT/'configs/point2_v2.json').read_text())
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:9235')
        for i in range(12):
            if ACTIVE[i%len(ACTIVE)]!=index:continue
            c=next(c for c in matrix([config['models'][0]['id']]) if c['task_id']==100+i and c['condition']=='tool_stale_over' and c['route']=='home')
            cell=folder/str(i);cell.mkdir(exist_ok=True);s=Surface(browser,c,target,cell)
            variant=c['size']+' / '+c['color'] if c['handle']=='t-shirt' else c['size']
            assert s.setup['initial_native']['cart']['items'][0]['variant']==variant
            s.act('ui_click',{'selector':'[data-testid="nav-cart-link"]'});s.page.wait_for_url('**/cart',timeout=60000)
            helper=s.assisted_evidence();assert helper[-2]['ui_quote']==c['actual_total'] and not s.observe()
            (cell/'passed.json').write_text(json.dumps(dict(passed=True,spec=c,helper=helper),indent=2))
            s.close();print('validated',i,flush=True)
        browser.close()

def main():
    ART.mkdir(exist_ok=True)
    if (ART/'plan.json').exists():raise RuntimeError('Never replay a paid study')
    jobs=[]
    for i in ACTIVE:
        log=(ART/f'warm-validation-{i}.log').open('a');jobs.append(grouped(['validate',str(i)],log));log.close()
    codes=[p.wait() for p in jobs];(ART/'warm_validation_exit_codes.json').write_text(json.dumps(codes))
    assert not any(codes),codes
    assert len(list((ART/'warm_validation').glob('*/*/passed.json')))==12
    cfg=json.loads((ROOT/'configs/point2_v2.json').read_text());cells=matrix([m['id'] for m in cfg['models']])
    workers=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers'][:16]
    for w in workers:w['cells']=[];w['budget_usd']=2 if workers.index(w) in ACTIVE else 0
    for i,c in enumerate(cells):workers[ACTIVE[i%len(ACTIVE)]]['cells'].append(c)
    paths=[Path(__file__).resolve(),ROOT/'scripts/point2_routes_replication.py',ROOT/'research/point2_v2/ROUTE_REPLICATION_PROTOCOL_RU.md',
        ROOT/'research/point2_v2/ROUTE_EXECUTION_AMENDMENT_RU.md',ROOT/'configs/point2_v2.json']
    paths+=list((ROOT/'src/point2_v3').glob('*.py'))+list((ROOT/'src/point2_v3').glob('*.js'))+list((ROOT/'src/point2_routes_live').glob('*.py'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        f=ART/'frozen_inputs'/p.relative_to(ROOT);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(p.read_bytes())
    (ART/'plan.json').write_text(json.dumps(dict(workers=workers,cells=cells,planned=216,source_hashes=hashes,isolation='warm-store fresh-context order-boundary',paid_calls_before_amendment=0),indent=2))
    jobs=[]
    for i in ACTIVE:
        log=(ART/f'worker-{i}.log').open('w');jobs.append(grouped(['worker',str(i)],log));log.close()
    codes=[p.wait() for p in jobs];(ART/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Preserve all paid results and inspect failure')
    assert len(list(ART.glob('worker-*/*/result.json')))==216
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=216,paid_replays=0)))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='validate':validate(int(sys.argv[2]))
    elif len(sys.argv)>1 and sys.argv[1]=='worker':
        target=json.loads((ART/'plan.json').read_text())['workers'][int(sys.argv[2])];relocate(target);activate()
        run_worker(json.loads((ROOT/'configs/point2_v2.json').read_text()),target,target['cells'],ART/f'worker-{sys.argv[2]}')
    else:main()
