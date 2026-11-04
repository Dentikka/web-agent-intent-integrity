"""Frozen cross-catalog study. Original bounded actor and native browser surface."""
from __future__ import annotations
import argparse,hashlib,itertools,json,os,random,shutil,subprocess,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue,Empty
SOURCE=Path(__file__).resolve().parent;ROOT=SOURCE.parents[1];OUT=ROOT/'artifacts/handoff_generalization_v2'
sys.path.insert(0,str(SOURCE.parents[2]/'cart_lifecycle'))
from bounded_api import Ledger,StopRun,write,encode,launch
from drift_runner import episode,SYNC_POLICY
from drift_app import DriftSurface
from app import App,CATALOGS,GeneralizationSurface
CONFIG=ROOT/'configs/handoff-generalization-local.json'

def matrix(role='core'):
    repeats=range(2) if role=='core' else range(1)
    routes=('free','tool_ui','ui_tool') if role=='core' else ('tool_ui',)
    rows=[dict(catalog=c,task=t,handoff=h,sync=s,disclosure=d,policy=p,repeat=r,instance=r,family='variant',mode='hybrid') for c,t,h,s,d,p,r in itertools.product(CATALOGS,('exact_sku','requirements_quantity'),routes,('shared','deferred'),('standard','full'),('baseline','synchronize'),repeats)]
    random.Random(2026102507).shuffle(rows);return rows

def smoke(role):
    rows=[]
    for i,c in enumerate(CATALOGS):
        for j,t in enumerate(('exact_sku','requirements_quantity')):
            rows.append(dict(catalog=c,task=t,handoff=('free','tool_ui','ui_tool')[(i+j)%3] if role=='core' else 'tool_ui',sync=('shared','deferred')[(i+j)%2],disclosure=('standard','full')[j],policy=('baseline','synchronize')[(i+j)%2],repeat=0,instance=0,family='variant',mode='hybrid'))
    return rows

def configure():
    cfg=json.loads(CONFIG.read_text());os.environ['DRIFT_WP_SITE']=cfg['runtime_wp_site'];os.environ['DRIFT_BASE_DB']=cfg['base_database'];os.environ['DRIFT_PHP_BINARY']=cfg['php_binary'];return cfg

def source_manifest():
    return {str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file() and p.suffix in ('.py','.php','.json') and '__pycache__' not in p.parts}

def freeze():
    cfg=configure();protocol=ROOT/'research/handoff_generalization_v1/PROTOCOL_RU.md'
    record=dict(config=cfg,started_epoch=cfg.get('global_started_epoch',time.time()),sources=source_manifest(),protocol_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest(),models=[dict(id=m['id'],role=m['role'],main=matrix(m['role']),smoke=smoke(m['role'])) for m in cfg['models']])
    target=OUT/'plan.json';assert not target.exists(),'Plan already exists; no source/config overwrite'
    write(target,record);shutil.copytree(SOURCE,OUT/'frozen_source',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(protocol,OUT/'PROTOCOL_RU.md');print(encode(dict(main=sum(len(m['main']) for m in record['models']),smoke=sum(len(m['smoke']) for m in record['models']))))

def model_root(i,model):return OUT/'runs'/f'model-{i+1}-{hashlib.sha256(model["id"].encode()).hexdigest()[:8]}'/'paid'

def worker(index,stage):
    configure();plan=json.loads((OUT/'plan.json').read_text());assert source_manifest()==plan['sources'],'Frozen source changed'
    cfg=plan['config'];model=cfg['models'][index];root=model_root(index,model);root.mkdir(parents=True,exist_ok=True)
    mc={k:v for k,v in cfg.items() if k!='models'};mc.update(model=model,budget_usd=model['budget_usd'],started_epoch=plan['started_epoch']);frozen=root/'config.json'
    if frozen.exists():assert json.loads(frozen.read_text())==mc
    else:write(frozen,mc)
    if stage=='main':
        sm=json.loads((root/'smoke/summary.json').read_text());assert sm['complete'] and sm['observed']==12
    design=plan['models'][index][stage];folder=root/stage;folder.mkdir(exist_ok=True)
    mf=dict(design=design,model=model,policy_text=SYNC_POLICY,sources=plan['sources'],base_sha256=hashlib.sha256(Path(cfg['base_database']).read_bytes()).hexdigest(),scope='Real WooCommerce with research UI/native WebMCP adapters; no state changes except agent actions; no route enforcement',role=model['role'])
    if (folder/'manifest.json').exists():assert json.loads((folder/'manifest.json').read_text())==mf
    else:write(folder/'manifest.json',mf)
    ledger=Ledger(root,mc);queue=Queue();stop=threading.Event();errors=[];lock=threading.Lock()
    for cell in design:
        key=hashlib.sha256(encode([stage,cell,model['id']]).encode()).hexdigest()[:16];target=folder/key
        if not (target/'result.json').exists():queue.put((cell,target))
    def run_thread():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser=launch(p,dict(mc,browser_args=['--enable-features=WebMCP']))
                try:
                    while not stop.is_set():
                        try:cell,target=queue.get_nowait()
                        except Empty:return
                        r=episode(browser,cell,mc,target,ledger,stop,App,SYNC_POLICY,GeneralizationSurface)
                        with lock:print(encode(dict(id=target.name,stage=stage,model=model['id'],spec=cell,error=r['error'],success=r['scores']['task_success'],wrong=r['scores']['wrong_commit'])),flush=True)
                        if r['error']:
                            with lock:errors.append(dict(id=target.name,error=r['error'],message=r['error_message']))
                finally:browser.close()
        except Exception as exc:
            stop.set()
            with lock:errors.append(dict(error=type(exc).__name__,message=str(exc)[:400]))
    try:
        with ThreadPoolExecutor(max_workers=cfg['workers_per_model']) as pool:
            futures=[pool.submit(run_thread) for _ in range(cfg['workers_per_model'])]
            for f in futures:f.result()
    finally:
        rows=[json.loads(p.read_text()) for p in folder.glob('*/result.json')];pending=ledger.db.execute("SELECT COUNT(*) FROM calls WHERE status='pending'").fetchone()[0];cost=ledger.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls').fetchone()[0]
        write(folder/'summary.json',dict(assigned=len(design),observed=len(rows),complete=len(rows)==len(design) and not errors and not pending and not any(r['error'] for r in rows),errors=errors,pending=pending,accounted_usd=cost));ledger.db.close()
    return int(not json.loads((folder/'summary.json').read_text())['complete'])

def launch_stage(stage):
    configure();plan=json.loads((OUT/'plan.json').read_text());procs=[]
    for i,m in enumerate(plan['config']['models']):
        log=(OUT/f'{stage}-model-{i+1}.log').open('a');procs.append(subprocess.Popen([sys.executable,'-u',str(__file__),'worker','--index',str(i),'--stage',stage],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT))
    codes=[p.wait() for p in procs];write(OUT/f'{stage}-exit.json',dict(codes=codes));print(encode(dict(stage=stage,codes=codes)))
    return int(any(codes))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('freeze','worker','smoke','main'));p.add_argument('--index',type=int);p.add_argument('--stage',choices=('smoke','main'));a=p.parse_args()
    if a.command=='freeze':freeze()
    elif a.command=='worker':sys.exit(worker(a.index,a.stage))
    else:sys.exit(launch_stage(a.command))
