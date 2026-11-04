"""Validate and run the fixed, truthful-representation follow-up."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from point2_semantics.design import matrix
from point2_semantics.surfaces import Surface,relocate,native
from point2_semantics.run import run_worker,quote
ART=ROOT/'artifacts/point2_semantics'

def validate(target,app,only_index=None):
    from playwright.sync_api import sync_playwright
    relocate(target);cfg=json.loads((ROOT/'configs/point2_v2.json').read_text())
    cells=[c for c in matrix([cfg['models'][0]['id']]) if c['app']==app and c['policy']=='caution']
    # Validate all six templates and both feasibility states in transformed form,
    # plus an ordinary representation control. No model is invoked.
    cells=[c for c in cells if c['representation']=='equivalent' or (c['task_id']==0 and c['feasible'])]
    if only_index is not None:cells=[cells[only_index]]
    results=[];port=target['base'].rsplit(':',1)[-1]
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp('http://127.0.0.1:'+('9235' if app=='medusa' else '9234'))
        for i,c in enumerate(cells):
            folder=ART/'validation'/port/app/str(only_index if only_index is not None else i);folder.mkdir(parents=True,exist_ok=True)
            s=Surface(browser,c,target,folder)
            if app=='medusa':
                assert quote(c,s.quote())==c['actual_total']
                assert s.visible_total()==c['actual_total']
                native_data=s.quote()['cart']
                if c['representation']=='equivalent':
                    assert 'total' not in native_data
                    components=native_data['amount_components']
                    assert components['items']==c['unit_price']
                    assert components['items']+components['delivery_and_other_charges']==c['actual_total']
                s.page.get_by_test_id('submit-order-button').click()
                for _ in range(100):
                    records=s.observe()
                    if records:break
                    s.page.wait_for_timeout(100)
                assert len(records)==1 and float(records[0]['totals']['current_order_total'])==c['actual_total']
                detail=dict(native=native_data,backend=records)
            else:
                obs=native(s.page,'check_availability',dict(service_id=s.service_id,provider_id=2,date=c['day'],days=1))
                local=datetime.fromisoformat(c['day']+'T09:00:00').replace(tzinfo=ZoneInfo(c['zone']))
                expected=local.astimezone(timezone.utc) if c['representation']=='equivalent' else local
                day=next(d for d in obs['days'] if d['date']==expected.strftime('%Y-%m-%d'))
                assert (expected.strftime('%H:%M') in day['open_slots'])==c['feasible'],obs
                # UI must actually show the corresponding local calendar slots.
                for _ in range(80):
                    ui=s.page.locator('#available-hours .available-hour')
                    if ui.count():break
                    s.page.wait_for_timeout(100)
                local_slots=s.page.locator('#available-hours .available-hour').evaluate_all('(els)=>els.map(e=>String($(e).data("value")))')
                assert ('09:00' in local_slots)==c['feasible'] and local_slots
                if c['representation']=='equivalent':
                    converted=[datetime.fromisoformat(d['date']+'T'+t+':00+00:00').astimezone(ZoneInfo(c['zone'])).strftime('%H:%M')
                        for d in obs['days'] for t in d['open_slots']]
                    assert sorted(converted)==sorted(local_slots),(converted,local_slots)
                booking=native(s.page,'book_appointment',dict(service_id=s.service_id,provider_id=2,
                    date=expected.strftime('%Y-%m-%d'),time=expected.strftime('%H:%M'),
                    first_name='Alex',last_name='Research',email='ea.point2.v2@example.com',phone_number='+15550199',
                    address='10 Test Street',city='London',zip_code='SW1A 1AA',notes=''))
                records=s.observe()
                assert bool(records)==c['feasible'],booking
                if records:assert records[0]['start'].startswith(c['day']+' 09:00')
                detail=dict(native=obs,local_slots=local_slots,booking=booking,backend=records)
            (folder/'passed.json').write_text(json.dumps(dict(passed=True,spec=c,detail=detail),indent=2))
            results.append(dict(condition=c['condition'],task=c['task_id'],representation=c['representation'],passed=True))
            s.close()
        browser.close()
    (ART/f'validation_{app}_{port}_{only_index}.json').write_text(json.dumps(results,indent=2))

def start():
    # User requested the truthful block after finishing the main series.
    assert (ROOT/'artifacts/point2_v2/ea_continuations/complete.json').exists()
    assert (ROOT/'artifacts/point2_v3_medusa/complete.json').exists()
    ART.mkdir(parents=True,exist_ok=True)
    if (ART/'plan.json').exists():raise RuntimeError('Never overwrite or repeat a paid follow-up')
    cfg=json.loads((ROOT/'configs/point2_v2.json').read_text())
    workers=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers']
    validators=[]
    for index in list(range(13))+[16]:
        with (ART/f'validation-{index}.log').open('w') as log:
            validators.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'validate-main',str(index)],
                cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log))
    validation_codes=[p.wait() for p in validators]
    (ART/'validation_exit_codes.json').write_text(json.dumps(validation_codes))
    if any(validation_codes):raise RuntimeError('Validation failed before paid calls')
    for t in workers:t['cells']=[];t['budget_usd']=2 if t['app']=='ea' else .5
    slots={app:[i for i,t in enumerate(workers) if t['app']==app] for app in ('ea','medusa')}
    counts=dict(ea=0,medusa=0);cells=matrix([m['id'] for m in cfg['models']])
    for c in cells:
        indices=slots[c['app']];i=indices[counts[c['app']]%len(indices)];counts[c['app']]+=1;workers[i]['cells'].append(c)
    paths=list((ROOT/'src/point2_semantics').glob('*.py'))+list((ROOT/'src/point2_semantics').glob('*.js'))
    paths += [Path(__file__).resolve(),ROOT/'research/point2_semantics/PROTOCOL_RU.md',ROOT/'configs/point2_v2.json']
    paths += [ROOT/'src/point2_v3/design.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        dest=ART/'frozen_inputs'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    (ART/'plan.json').write_text(json.dumps(dict(workers=workers,cells=cells,source_hashes=hashes,planned=192,started_epoch=time.time()),indent=2))
    processes=[]
    for i in range(20):
        with (ART/f'worker-{i}.log').open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'worker',str(i)],
                cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),stdout=log,stderr=log))
    codes=[p.wait() for p in processes];(ART/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('Follow-up stopped: keep every result and inspect infrastructure')
    assert len(list(ART.glob('worker-*/*/result.json')))==192
    (ART/'complete.json').write_text(json.dumps(dict(complete=True,episodes=192)))

if __name__=='__main__':
    ART.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        i=int(sys.argv[2]);target=json.loads((ART/'plan.json').read_text())['workers'][i]
        run_worker(json.loads((ROOT/'configs/point2_v2.json').read_text()),target,target['cells'],ART/f'worker-{i}')
    elif len(sys.argv)>1 and sys.argv[1]=='validate-ea-spare':
        validate(dict(app='ea',base='http://127.0.0.1:8765',workspace=str(ROOT/'vendor/easyappointments-image'),db='ea-intent-db'),'ea')
    elif len(sys.argv)>1 and sys.argv[1]=='validate-ea-one':
        validate(dict(app='ea',base='http://127.0.0.1:8765',workspace=str(ROOT/'vendor/easyappointments-image'),db='ea-intent-db'),'ea',0)
    elif len(sys.argv)>1 and sys.argv[1]=='validate-main':
        i=int(sys.argv[2]);target=json.loads((ROOT/'artifacts/point2_v2/plan.json').read_text())['workers'][i]
        validate(target,target['app'],i if i<16 else 0)
    elif len(sys.argv)>1 and sys.argv[1]=='wait-main':
        while not ((ROOT/'artifacts/point2_v2/ea_continuations/complete.json').exists() and
                   (ROOT/'artifacts/point2_v3_medusa/complete.json').exists()):time.sleep(2)
        start()
    else:start()
