"""Isolate assigned evidence freshness from an agent's compensating re-reads."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import random
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import strengthen_point3 as s
OUT=s.ART/'evidence_ablation'

def execute_worker(index):
    from playwright.sync_api import sync_playwright
    plan=json.loads((OUT/'plan.json').read_text());w=plan['workers'][index]
    out=OUT/f'worker-{index}';out.mkdir(exist_ok=False);s.freeze(out)
    s.write(out/'ablation_hashes.json',{str(Path(__file__).relative_to(ROOT)):s.hashfile(Path(__file__)),
        'research/point3_strengthening/EVIDENCE_ABLATION_PROTOCOL_RU.md':s.hashfile(s.DOC/'EVIDENCE_ABLATION_PROTOCOL_RU.md')})
    for p in (Path(__file__),s.DOC/'EVIDENCE_ABLATION_PROTOCOL_RU.md'):
        dest=out/'frozen_inputs'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    actor=inspect.getsource(s.execute).replace('You have authentic earlier observations below; additional independent current reads are available.',
        'You have authentic observations below. Additional inspection is unavailable in this controlled decision stage; decide only from the supplied evidence and actual submission result.')
    actor=actor.replace("elif name in ('inspect_ui','inspect_webmcp'):","elif False:")
    actor=actor.replace("elif name=='inspect_result':o=adapter.result_read()","elif False:o=adapter.result_read()")
    (out/'generated_actor.py').write_text(actor)
    exec(compile(actor,'<locked evidence decision stage>','exec'),s.__dict__)
    original=s.inference
    def inference(model,messages,schemas,*args,**kw):
        return original(model,messages,[t for t in schemas if t['function']['name'] in ('submit','finish')],*args,**kw)
    s.inference=inference
    cfg=dict(plan['config'],started_epoch=time.time());ledger=s.Ledger(out,cfg);models={m['id']:m for m in cfg['models']}
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9243');adapter=(s.Medusa if w['app']=='medusa' else s.EA)(w['target'],browser)
        for c in w['cells']:
            ident=hashlib.sha256(s.encode(c).encode()).hexdigest()[:16]
            r=s.execute(adapter,c,out/ident,models[c['model']],ledger)
            if r['error'] and ('StopRun' in r['error'] or 'API ' in r['error']):raise RuntimeError('API error retained, no repeated paid episode')
        browser.close()

def launch():
    OUT.mkdir(exist_ok=False)
    targets=[dict(t,app_type='medusa') for t in json.loads((ROOT/'artifacts/point3_realapps/instances.json').read_text())[4:8]]
    targets += [dict(s.setup_ea(i),app_type='easyappointments') for i in (2,3)]
    cfg=json.loads((s.ART/'main_matched/plan.json').read_text())['config'];cfg=dict(cfg,budget_usd=1)
    cells=[]
    for app in ('medusa','easyappointments'):
        for model in cfg['models']:
            for arm in s.ARMS[:8]:
                for rep in range(6):
                    c=s.condition(app,model['id'],arm,rep);c['study']='locked_evidence_v1';cells.append(c)
    random.Random(2026102408).shuffle(cells);workers=[]
    for app in ('medusa','easyappointments'):
        ts=[t for t in targets if t['app_type']==app];cs=[c for c in cells if c['app']==app]
        for j,t in enumerate(ts):workers.append(dict(app=app,target=t,cells=cs[j::len(ts)]))
    s.write(OUT/'plan.json',dict(stage='evidence_ablation',out=str(OUT),config=cfg,cells=cells,workers=workers,created_epoch=time.time()))
    processes=[]
    for i,w in enumerate(workers):
        with (OUT/f'worker-{i}.log').open('w') as log:
            processes.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'worker','--index',str(i)],cwd=ROOT,stdout=log,stderr=log))
    s.write(OUT/'exit_codes.json',[p.wait() for p in processes])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['launch','worker']);ap.add_argument('--index',type=int);args=ap.parse_args()
    execute_worker(args.index) if args.command=='worker' else launch()
