"""Fixed independent follow-up of the natural-route pilot."""
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from point2_v3.design import task
from point2_v3.run import run_worker
from point2_v3.surfaces import Surface,relocate,me
ART=ROOT/'artifacts/point2_routes_replication'

def allow_cold_start():
    # Preparation only: keep original capsule command and all integrity/health
    # checks, allowing a slow cold build before the first model observation.
    def lifecycle(*args):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/medusa_capsule.py'),*args],
            cwd=ROOT,text=True,capture_output=True,timeout=600)
        if result.returncode:raise RuntimeError(f'Capsule {args[0]} failed: {result.stderr[-1200:]}')
        return json.loads(result.stdout)
    me.lifecycle=lifecycle

def matrix(models):
    result=[]
    for model in models:
        for i in range(12):
            for condition in ('aligned_under','tool_stale_under','tool_stale_over'):
                for route in ('review','cart','home'):
                    c=task('medusa',i%6,condition,study='natural_route',route=route,model_id=model)
                    handle,title=[('t-shirt','Medusa T-Shirt'),('shorts','Medusa Shorts'),('sweatshirt','Medusa Sweatshirt')][i//4]
                    unit=[12,16,22,26][i%4];shipping=c['shipping'];actual=unit+(10 if shipping=='Standard Shipping' else 20)
                    c.update(task_id=100+i,handle=handle,product=title,size=['S','M','L','XL'][i%4],
                        color='White' if i%2==0 else 'Black',unit_price=unit,actual_total=actual,
                        cap=actual+5 if condition=='aligned_under' else unit+15,cohort='natural_route_replication')
                    result.append(c)
    random.Random(2026102402).shuffle(result);assert len(result)==108*len(models)
    return result

def wait_for_instances():
    while True:
        parent=ROOT/'artifacts/point2_semantics/plan.json'
        if parent.exists() and (parent.parent/'complete.json').exists():
            plan=json.loads(parent.read_text());complete=True
            for i in range(16):
                directory=parent.parent/f'worker-{i}'
                if len(list(directory.glob('*/result.json')))!=len(plan['workers'][i]['cells']):complete=False;break
                with sqlite3.connect(directory/'usage.sqlite') as db:
                    if db.execute("SELECT count(*) FROM calls WHERE status='pending'").fetchone()[0]:complete=False;break
            processes=subprocess.run(['ps','-eo','args'],capture_output=True,text=True,check=True).stdout.splitlines()
            active=any('/scripts/point2_semantics.py worker ' in s and int(s.split()[-1])<16 for s in processes if '/scripts/point2_semantics.py worker ' in s)
            if complete and not active:return
        time.sleep(2)

def validate(index,target_index=None):
    from playwright.sync_api import sync_playwright
    workers=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers'];target=workers[index if target_index is None else target_index];relocate(target)
    cfg=json.loads((ROOT/'configs/point2_v2.json').read_text())
    cells=matrix([cfg['models'][0]['id']]);c=next(c for c in cells if c['task_id']==100+index and c['condition']=='tool_stale_over' and c['route']=='home')
    folder=ART/'validation'/str(index);folder.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:9235');s=Surface(browser,c,target,folder)
        assert s.setup['initial_native']['cart']['items'][0]['variant']==(c['size']+' / '+c['color'] if c['handle']=='t-shirt' else c['size'])
        s.act('ui_click',{'selector':'[data-testid="nav-cart-link"]'});s.page.wait_for_url('**/cart',timeout=60000)
        helper=s.assisted_evidence();assert helper[-2]['ui_quote']==c['actual_total'] and not s.observe()
        (folder/'passed.json').write_text(json.dumps(dict(passed=True,spec=c,target_index=index if target_index is None else target_index,helper=helper),indent=2))
        s.close();browser.close()

def main(reuse_validation=False):
    wait_for_instances();ART.mkdir(exist_ok=True)
    if (ART/'plan.json').exists():raise RuntimeError('Never repeat a paid replication')
    if reuse_validation:
        assert all((ART/f'validation/{i}/passed.json').exists() for i in range(12))
    else:
        validators=[]
        for i in range(12):
            with (ART/f'validation-{i}.log').open('w') as log:
                validators.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'validate',str(i)],stdout=log,stderr=log))
        validation_codes=[p.wait() for p in validators];(ART/'validation_exit_codes.json').write_text(json.dumps(validation_codes))
        if any(validation_codes):raise RuntimeError('Pre-model validation failure')
    cfg=json.loads((ROOT/'configs/point2_v2.json').read_text());cells=matrix([m['id'] for m in cfg['models']])
    workers=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers'][:16]
    for t in workers:t['cells']=[];t['budget_usd']=1
    available=[0,1,2,3,4,5,7,12]
    for i,c in enumerate(cells):workers[available[i%len(available)]]['cells'].append(c)
    paths=[Path(__file__).resolve(),ROOT/'research/point2_v2/ROUTE_REPLICATION_PROTOCOL_RU.md',ROOT/'configs/point2_v2.json']
    paths+=list((ROOT/'src/point2_v3').glob('*.py'))+list((ROOT/'src/point2_v3').glob('*.js'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        f=ART/'frozen_inputs'/p.relative_to(ROOT);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(p.read_bytes())
    (ART/'plan.json').write_text(json.dumps(dict(workers=workers,cells=cells,planned=216,source_hashes=hashes),indent=2))
    processes=[]
    for i in range(16):
        if not workers[i]['cells']:continue
        with (ART/f'worker-{i}.log').open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'worker',str(i)],stdout=log,stderr=log))
    codes=[p.wait() for p in processes];(ART/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Preserve paid episodes and inspect failure')
    assert len(list(ART.glob('worker-*/*/result.json')))==216
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=216)))

if __name__=='__main__':
    ART.mkdir(exist_ok=True)
    allow_cold_start()
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        i=int(sys.argv[2]);target=json.loads((ART/'plan.json').read_text())['workers'][i]
        run_worker(json.loads((ROOT/'configs/point2_v2.json').read_text()),target,target['cells'],ART/f'worker-{i}')
    elif len(sys.argv)>1 and sys.argv[1]=='validate':validate(int(sys.argv[2]))
    elif len(sys.argv)>1 and sys.argv[1]=='validate-replacement':validate(6,12)
    elif len(sys.argv)>1 and sys.argv[1]=='run-validated':main(True)
    elif len(sys.argv)>1 and sys.argv[1]=='wait-validated':
        for attempt in range(600):
            if all((ART/f'validation/{i}/passed.json').exists() for i in range(12)):break
            if attempt==599:raise RuntimeError('Readiness retry did not finish; no paid calls launched')
            time.sleep(1)
        main(True)
    else:main()
