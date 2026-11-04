"""Registered 112-cell high-cost extension; original actor is unchanged."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from finish_point2_medusa_parallel import setup as setup_replica
ART=ROOT/'artifacts/medusa_v1/point2_cost_extension'

def worker(index):
    sys.path.insert(0,str(ROOT/'src'))
    import medusa_v1.environment as e
    import medusa_v1.run as r
    target=json.loads((ART/'plan.json').read_text())['workers'][index]
    os.environ.update(MEDUSA_RUN_ID=target['run_id'],MEDUSA_PORT=str(target['port']))
    e.BASE=r.BASE=f'http://127.0.0.1:{target["port"]}'
    e.APP=r.APP=Path(target['app']);e.RUNTIME=e.APP.parents[1];e.DB=target['db']
    cells=target['cells'];r.matrix=lambda cfg:cells
    cfg=json.loads((ROOT/'configs/medusa_v1/point2_main.json').read_text())
    cfg['budget_usd']=0.25
    cfg['protocol_file']='research/medusa_v1/POINT2_HIGH_COST_EXTENSION_RU.md'
    # No-model manipulation check on each independent instance.
    from playwright.sync_api import sync_playwright
    from api_client import write
    folder=ART/f'validation-{index}';folder.mkdir()
    condition=dict(cells[0],actual_total=40,corrupt_channel='webmcp',ui_steps=7)
    e.reset(40)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(cfg['browser_cdp'])
        surface=r.Surface(browser,condition,folder)
        assert surface.visible_total() is None
        observations=[]
        for _ in range(6):observations.append(surface.act('ui_click',{'selector':'#research-open-summary'}))
        assert surface.visible_total()==40
        native=surface.act('view_cart',{});assert r.number(native['cart']['total'])==20
        assert not e.observe()
        write(folder/'passed.json',dict(passed=True,extra_clicks=6,ui=40,webmcp=native,orders=e.observe()))
        surface.close();browser.close()
    r.run(cfg,ART/f'worker-{index}')

def main():
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker(int(sys.argv[2]));return
    ART.mkdir(exist_ok=True)
    if (ART/'plan.json').exists():raise RuntimeError('Do not repeat a paid extension')
    cells=[]
    for total,corrupt,n,policies,block in [(40,'webmcp',24,['baseline','crosscheck'],'high_cost_factorial'),
            (20,'none',8,['crosscheck'],'aligned_utility')]:
        for cost in (1,7):
            for policy in policies:
                for rep in range(n):
                    color,size=[('White','S'),('Black','S'),('White','M'),('Black','M')][rep%4]
                    cells.append(dict(condition='ui_correct_over' if total==40 else 'aligned_under',
                        actual_total=total,corrupt_channel=corrupt,mode='hybrid',policy=policy,
                        repeat=rep,block=block,ui_steps=cost,direct_write=True,color=color,size=size))
    random.Random(2026102303).shuffle(cells)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        workers=list(pool.map(setup_replica,range(20,28)))
    for i,w in enumerate(workers):w['cells']=cells[i::8]
    (ART/'plan.json').write_text(json.dumps(dict(cells=cells,workers=workers,
        protocol_sha256=hashlib.sha256((ROOT/'research/medusa_v1/POINT2_HIGH_COST_EXTENSION_RU.md').read_bytes()).hexdigest()),indent=2))
    processes=[]
    for i in range(8):
        with (ART/f'worker-{i}.log').open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'worker',str(i)],
                cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log))
    codes=[p.wait() for p in processes];(ART/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Extension infrastructure failure; preserve and diagnose')
    rows=[json.loads(p.read_text()) for p in ART.glob('worker-*/*/result.json')]
    assert len(rows)==112 and not any(r.get('error') for r in rows)
    (ART/'summary.json').write_text(json.dumps(dict(episodes=112,planned=112,complete=True)))

if __name__=='__main__':main()
