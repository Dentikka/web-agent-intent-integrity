"""Additional complete second-distractor transfer; unchanged frozen actor."""
from pathlib import Path
import sys,json,hashlib,threading,subprocess
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'src/handoff_generalization_v1';sys.path.insert(0,str(SOURCE));import run as base
from app import App,GeneralizationSurface
from bounded_api import Ledger,write,encode,launch
from drift_runner import episode,SYNC_POLICY
OUT=base.OUT;STAGE='transfer_repeat1'
def worker(index):
    base.configure();plan=json.loads((OUT/'plan.json').read_text());assert base.source_manifest()==plan['sources'];cfg=plan['config'];model=cfg['models'][index];root=base.model_root(index,model);mc=json.loads((root/'config.json').read_text());assert json.loads((root/'main/summary.json').read_text())['complete']
    design=[dict(c,repeat=1,instance=1) for c in plan['models'][index]['main']];folder=root/STAGE;folder.mkdir(exist_ok=False)
    write(folder/'manifest.json',dict(design=design,model=model,sources=plan['sources'],base_sha256=hashlib.sha256(Path(cfg['base_database']).read_bytes()).hexdigest(),policy_text=SYNC_POLICY,secondary_transfer=True))
    ledger=Ledger(root,mc);q=Queue();stop=threading.Event();errors=[];lock=threading.Lock()
    for c in design:q.put((c,folder/hashlib.sha256(encode([STAGE,c,model['id']]).encode()).hexdigest()[:16]))
    def thread():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                b=launch(p,dict(mc,browser_args=['--enable-features=WebMCP']))
                try:
                    while not stop.is_set():
                        try:c,target=q.get_nowait()
                        except Empty:return
                        r=episode(b,c,mc,target,ledger,stop,App,SYNC_POLICY,GeneralizationSurface)
                        with lock:
                            print(encode(dict(id=target.name,spec=c,error=r['error'],wrong=r['scores']['wrong_commit'])),flush=True)
                            if r['error']:errors.append(dict(id=target.name,error=r['error'],message=r['error_message']))
                finally:b.close()
        except Exception as e:
            stop.set()
            with lock:errors.append(dict(error=type(e).__name__,message=str(e)[:400]))
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for f in [pool.submit(thread) for _ in range(4)]:f.result()
    finally:
        rr=[json.loads(p.read_text()) for p in folder.glob('*/result.json')];pending=ledger.db.execute("SELECT COUNT(*) FROM calls WHERE status='pending'").fetchone()[0]
        write(folder/'summary.json',dict(assigned=96,observed=len(rr),errors=errors,pending=pending,complete=len(rr)==96 and not errors and not pending));ledger.db.close()
if __name__=='__main__':
    if len(sys.argv)>1:worker(int(sys.argv[1]))
    else:
        protocol=ROOT/'research/handoff_generalization_v1/TRANSFER_REPEAT1_RU.md';record=dict(protocol_sha256=hashlib.sha256(protocol.read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),initial_main_counts=[96,96],models=[2,3],additional_assignments=192)
        write(OUT/'transfer_repeat1_plan.json',record);ps=[]
        for i in (2,3):
            log=(OUT/f'transfer-repeat1-model-{i+1}.log').open('w');ps.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)) ,str(i)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT))
        codes=[p.wait() for p in ps];write(OUT/'transfer_repeat1_exit.json',dict(codes=codes));sys.exit(int(any(codes)))
