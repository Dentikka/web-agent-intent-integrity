"""Validate and execute the fixed two-model, real-history strengthening study."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/point2_v2'
sys.path.insert(0,str(ROOT/'src'))
from point2_v2.design import matrix,task
from point2_v2.surfaces import Surface,relocate,BUYER
from point2_v2.run import run_worker


def targets():
    med=[]
    for filename in ('point2_parallel','point2_cost_extension'):
        source=json.loads((ROOT/f'artifacts/medusa_v1/{filename}/plan.json').read_text())['workers']
        for t in source:
            med.append(dict(app='medusa',base=f'http://127.0.0.1:{t["port"]}',workspace=t['app'],db=t['db'],budget_usd=1.5))
    ea=[dict(app='ea',base=f'http://127.0.0.1:{8780+i}',workspace=str(ROOT/f'vendor/easyappointments-p2-w{i}'),
             db=f'ea-intent-p2-w{i}-db',budget_usd=4) for i in range(4)]
    return med+ea


def validate(index):
    from playwright.sync_api import sync_playwright
    target=targets()[index];relocate(target)
    folder=ART/'validation'/f'worker-{index}';folder.mkdir(parents=True,exist_ok=True)
    c=task(target['app'],index%6,['aligned_under','aligned_over','ui_stale_under','ui_stale_over','tool_stale_under','tool_stale_over'][index%6])
    if index in (12,13,14,15):c=task('medusa',index%6,'tool_stale_over',route='home' if index%2 else 'cart',study='natural_route')
    with sync_playwright() as p:
        b=p.chromium.connect_over_cdp('http://127.0.0.1:'+('9235' if target['app']=='medusa' else '9234'))
        s=Surface(b,c,target,folder)
        initial=s.setup
        q=initial['initial_native'];from point2_v2.run import quote
        native_value=quote(c,q)
        if c['stale_side']=='tool':assert native_value!=c['actual_total']
        else:assert native_value==c['actual_total']
        if c['route']=='home':
            s.act('ui_click',{'selector':'[data-testid="nav-cart-link"]'})
            s.page.wait_for_url('**/cart',wait_until='domcontentloaded',timeout=60000)
        helper=s.assisted_evidence()
        assert helper[-2]['ui_quote']==c['actual_total']
        assert quote(c,helper[-1]['observation'])==c['actual_total']
        assert not s.observe()
        # Real write gold on one instance per app. These are evaluator-only
        # checks, never model episodes, and all constraints are recorded.
        committed=[]
        if index in (0,16):
            if c['app']=='medusa':
                s.page.get_by_test_id('submit-order-button').click()
                for _ in range(60):
                    committed=s.observe()
                    if committed:break
                    s.page.wait_for_timeout(250)
                assert committed and float(committed[0]['totals']['current_order_total'])==c['actual_total']
            else:
                from point2_v2.surfaces import native
                avail=native(s.page,'check_availability',dict(service_id=s.service_id,provider_id=2,date=c['day'],days=1))
                d=next(d for d in avail['days'] if d.get('open_slots'))
                result=native(s.page,'book_appointment',dict(service_id=s.service_id,provider_id=2,date=d['date'],time=d['open_slots'][0],
                    first_name='Alex',last_name='Research',email='ea.point2.v2@example.com',phone_number='+15550199',
                    address='10 Test Street',city='London',zip_code='SW1A 1AA',notes=''))
                committed=s.observe();assert committed and float(committed[0]['service_tariff'])==c['actual_total'],result
        s.close();b.close()
    (folder/'passed.json').write_text(json.dumps(dict(passed=True,condition=c,initial=initial,helper=helper,committed=committed),indent=2))
    print(json.dumps(dict(index=index,passed=True)),flush=True)


def validate_all():
    ART.mkdir(exist_ok=True);processes=[]
    for i in range(20):
        logfile=ART/f'validation-{i}.log'
        with logfile.open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'validate-worker',str(i)],
                cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log))
    codes=[p.wait() for p in processes]
    (ART/'validation_exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Validation failed; no primary API calls launched')


def start():
    config=json.loads((ROOT/'configs/point2_v2.json').read_text())
    assert all((ART/f'validation/worker-{i}/passed.json').exists() for i in range(20))
    if (ART/'plan.json').exists():raise RuntimeError('Do not overwrite/repeat the frozen primary study')
    all_cells=matrix([m['id'] for m in config['models']]);workers=targets();slots={app:[] for app in ('ea','medusa')}
    for index,t in enumerate(workers):slots[t['app']].append(index);t['cells']=[]
    counters=dict(ea=0,medusa=0)
    for c in all_cells:
        app=c['app'];index=slots[app][counters[app]%len(slots[app])];counters[app]+=1;workers[index]['cells'].append(c)
    sources=list((ROOT/'src/point2_v2').glob('*.py'))+list((ROOT/'src/point2_v2').glob('*.js'))
    sources += [ROOT/'scripts/point2_v2.py',ROOT/'configs/point2_v2.json',ROOT/'research/point2_v2/PROTOCOL_RU.md',
                ROOT/'vendor/colleague-intent-integrity/webmcp-intent-integrity-main/api_client.py']
    sources += list((ROOT/'src/medusa_v1').glob('*.py'))+list((ROOT/'src/realapp_v1').glob('*.py'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for p in sources:
        frozen=ART/'frozen_inputs'/p.relative_to(ROOT);frozen.parent.mkdir(parents=True,exist_ok=True);frozen.write_bytes(p.read_bytes())
    plan=dict(cells=all_cells,workers=workers,source_hashes=hashes,started_epoch=time.time(),planned=720,
              total_budget_cap=sum(t['budget_usd'] for t in workers),model_names=[m['id'] for m in config['models']])
    (ART/'plan.json').write_text(json.dumps(plan,indent=2))
    processes=[]
    for i in range(20):
        with (ART/f'worker-{i}.log').open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'worker',str(i)],
                cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log))
    codes=[p.wait() for p in processes];(ART/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Paid episode or infrastructure failure: inspect before continuing')
    assert len(list(ART.glob('worker-*/*/result.json')))==720
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=720)))


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['validate','validate-worker','run','worker']);p.add_argument('index',nargs='?',type=int)
    args=p.parse_args()
    if args.command=='validate':validate_all()
    elif args.command=='validate-worker':validate(args.index)
    elif args.command=='run':start()
    else:
        plan=json.loads((ART/'plan.json').read_text());config=json.loads((ROOT/'configs/point2_v2.json').read_text());t=plan['workers'][args.index]
        run_worker(config,t,t['cells'],ART/f'worker-{args.index}')

if __name__=='__main__':main()
