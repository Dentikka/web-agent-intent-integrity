"""Additional served model on the same frozen reviewer protocol."""
import argparse,copy,hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_reviewer_v1 as r
MODEL=copy.deepcopy(r.MODELS[0]);MODEL.update(id='qwen/qwen3.8-flash',input_per_million=.15,output_per_million=.47)
MODEL['extra_body'].pop('reasoning',None)
r.MODELS=[MODEL];r.ART=ROOT/'artifacts/reviewer_qwen_v1'
def launch(stage):
    out=r.ART/stage;out.mkdir(parents=True,exist_ok=False)
    (out/'replication_runner.py').write_bytes(Path(__file__).read_bytes())
    cells=[c for c in r.matrix_unchecked() if c['repeat']<2]
    if stage=='pilot':cells=[next(c for c in cells if c['experiment']=='T' and c['timing']=='concurrent' and c['workload']=='harmful'),next(c for c in cells if c['experiment']=='U' and c['policy']=='operation_guard' and c['workload']=='stable')]
    if stage=='main':
        controls=[json.loads(p.read_text()) for p in (r.ART/'pilot').glob('worker-*/*/result.json')]
        assert len(controls)==2 and not any(x['error'] for x in controls)
    cfg=dict(json.loads((ROOT/'artifacts/point4_realapps/main/plan.json').read_text())['config'],models=[MODEL],budget_usd=1,hours=3,max_turns=24)
    targets=[t for t in json.loads((ROOT/'artifacts/point4_realapps/instances.json').read_text()) if t['app_type']=='medusa']
    workers=[dict(target=t,cells=cells[i::4]) for i,t in enumerate(targets)]
    plan=dict(stage=stage,out=str(out),config=cfg,cells=cells,workers=workers,protocol_sha256=r.s.hashfile(r.DOC/'PROTOCOL_RU.md'),replication_protocol_sha256=r.s.hashfile(r.DOC/'QWEN_REPLICATION_RU.md'),wrapper_sha256=r.s.hashfile(Path(__file__)));r.s.write(out/'plan.json',plan)
    procs=[]
    for i in range(4):
        log=(out/f'worker-{i}.log').open('w');procs.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'worker','--plan',str(out/'plan.json'),'--index',str(i)],cwd=ROOT,stdout=log,stderr=log))
    codes=[p.wait() for p in procs];r.s.write(out/'exit_codes.json',codes);print(stage,codes)
def cells():
    # Exact same factors, two repetitions per cell. Keep the frozen original
    # actor's matrix assertion intact instead of editing its paid-run source.
    original=r.MODELS;r.MODELS=r.b.MODELS
    try:base=r.matrix()
    finally:r.MODELS=original
    return [dict(c,model=MODEL['id']) for c in base if c['model']==r.b.MODELS[0]['id']]
r.matrix_unchecked=cells
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['pilot','main','worker']);ap.add_argument('--plan');ap.add_argument('--index',type=int);args=ap.parse_args()
    if args.command=='worker':r.worker(args.plan,args.index)
    else:launch(args.command)
