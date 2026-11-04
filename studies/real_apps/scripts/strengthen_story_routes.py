"""Fixed read/write-route replication on existing dedicated real applications."""
import argparse,hashlib,json,random,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import strengthen_point3 as s
ART=ROOT/'artifacts/story_strengthening';DOC=ROOT/'research/story_strengthening'

def evidence(adapter,c,folder):
    if c['timing']=='early':adapter.mutate()
    observation=adapter.read(c['read_route'],fresh=c['timing']=='early')
    ev=[dict(channel=c['read_route'],observation=observation)]
    s.write(folder/'assigned_evidence.json',ev);return ev

def worker(path,index):
    from playwright.sync_api import sync_playwright
    plan=json.loads(Path(path).read_text());w=plan['workers'][index];out=Path(plan['out'])/f'worker-{index}';out.mkdir(exist_ok=False);s.freeze(out)
    for p in (Path(__file__),DOC/'PROTOCOL_RU.md'):
        rel=p.relative_to(ROOT);dest=out/'frozen_inputs'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    s.write(out/'extension_hashes.json',{str(p.relative_to(ROOT)):s.hashfile(p) for p in (Path(__file__),DOC/'PROTOCOL_RU.md')})
    s.prepare_evidence=evidence
    cfg=dict(plan['config'],started_epoch=time.time());ledger=None if plan['stage']=='validation' else s.Ledger(out,cfg);models={m['id']:m for m in cfg['models']}
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9243');adapter=(s.Medusa if w['app']=='medusa' else s.EA)(w['target'],browser)
        for c in w['cells']:
            ident=hashlib.sha256(s.encode(c).encode()).hexdigest()[:16]
            r=s.execute(adapter,c,out/ident,None if ledger is None else models[c['model']],ledger)
            if r['error'] and ('StopRun' in r['error'] or 'API ' in r['error']):raise RuntimeError('API failure retained; no paid replay')
        browser.close()

def launch(stage):
    out=ART/stage;out.mkdir(exist_ok=False);cfg=json.loads((ROOT/'artifacts/point4_realapps/main/plan.json').read_text())['config'];cfg=dict(cfg,budget_usd=1.5,hours=4,max_turns=6)
    if stage=='main':
        rr=[json.loads(p.read_text()) for p in (ART/'validation').glob('worker-*/*/result.json')]
        assert len(rr)==24 and all(not r['error'] and r['scores']['submit_attempted'] and (r['scores']['valid_commit'] if r['spec']['timing']=='stable' else r['scores']['dangerous_commit']) for r in rr),'Mechanics must pass before paid main'
    targets=json.loads((ROOT/'artifacts/point4_realapps/instances.json').read_text());cells=[]
    for app in ('medusa','easyappointments'):
        for model in (['control'] if stage=='validation' else [m['id'] for m in cfg['models']]):
            for read in ('ui','tool'):
                for write in ('ui','tool'):
                    for timing in ('stable','early','late'):
                        for rep in range(1 if stage=='validation' else 4):
                            cells.append(dict(study='independent_read_write_v1',app=app,model=model,read_route=read,route=write,timing=timing,arm='late_open' if timing=='late' else 'stable_'+write,guard=False,repeat=rep,color='White' if rep%2==0 else 'Black',size='S' if rep%3 else 'M'))
    random.Random(2026102419).shuffle(cells);workers=[]
    for app in ('medusa','easyappointments'):
        ts=[t for t in targets if t['app_type']==app];cs=[c for c in cells if c['app']==app]
        for i,t in enumerate(ts):workers.append(dict(app=app,target=t,cells=cs[i::len(ts)]))
    plan=dict(stage=stage,out=str(out),config=cfg,cells=cells,workers=workers,created_epoch=time.time(),protocol_sha256=s.hashfile(DOC/'PROTOCOL_RU.md'));s.write(out/'plan.json',plan)
    procs=[]
    for i,w in enumerate(workers):
        log=(out/f'worker-{i}.log').open('w');procs.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'worker','--plan',str(out/'plan.json'),'--index',str(i)],cwd=ROOT,stdout=log,stderr=log))
    codes=[p.wait() for p in procs];s.write(out/'exit_codes.json',codes);print(stage,codes,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['validation','main','worker']);ap.add_argument('--plan');ap.add_argument('--index',type=int);a=ap.parse_args()
    worker(a.plan,a.index) if a.command=='worker' else launch(a.command)
