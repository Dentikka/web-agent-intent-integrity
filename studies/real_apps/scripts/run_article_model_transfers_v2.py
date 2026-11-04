"""Same frozen semantic/lifecycle actors on preselected moderate model tiers."""
import argparse,copy,hashlib,json,random,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_semantic_reconciliation_v1 as sem
import run_own_writes_v1 as own
s=sem.s;A=ROOT/'artifacts/article_strengthening_v2'
MOD=json.loads((A/'moderate_models.json').read_text());Q=json.loads((ROOT/'artifacts/reviewer_qwen_v1/main/plan.json').read_text())['config']['models'][0]
def specs(study):
    if study=='semantic':
        original=sem.matrix();ids=[m['id'] for m in sem.MODELS[:2]];mapping={ids[i]:MOD[i]['id'] for i in range(2)}
        return [dict(c,model=mapping[c['model']]) for c in original if c['model'] in mapping],MOD
    original=own.matrix();base=own.MODELS[0]['id'];models=[Q]+MOD
    cells=[dict(c,model=m['id']) for c in original if c['model']==base and c['repeat'] in (4,5) for m in models]
    random.Random(2026102455).shuffle(cells);assert len(cells)==72;return cells,models
def launch(study,stage):
    root=A/('moderate_semantic' if study=='semantic' else 'lifecycle_transfer');out=root/stage;out.mkdir(parents=True,exist_ok=False);cells,models=specs(study)
    if stage=='pilot':
        if study=='semantic':cells=[next(c for c in cells if c['model']==m['id'] and c['policy']==p and c['situation']=='compatible') for m in models for p in ('ordinary','semantic')]
        else:cells=[next(c for c in cells if c['model']==m['id'] and c['policy']=='baseline' and c['timing']==t and c['target']==1) for m in models for t in ('immediate','queued')]
    if stage=='main':
        pilot=[json.loads(p.read_text()) for p in (root/'pilot').glob('worker-*/*/result.json')];assert len(pilot)==(4 if study=='semantic' else 6) and not any(r['error'] for r in pilot)
    targets=json.loads((A/('moderate_semantic_targets.json' if study=='semantic' else 'lifecycle_targets.json')).read_text())
    if study=='semantic':
        for t in targets:sem.p4.install_routes(t,'medusa')
    cfg=dict(json.loads((ROOT/'artifacts/point4_realapps/main/plan.json').read_text())['config'],models=models,budget_usd=5,hours=4,max_turns=24)
    workers=[dict(target=t,cells=cells[i::4]) for i,t in enumerate(targets)];plan=dict(study=study,stage=stage,out=str(out),config=cfg,cells=cells,workers=workers,wrapper_sha256=s.hashfile(Path(__file__)),protocol_sha256=s.hashfile(ROOT/'research/article_strengthening_v2/TRANSFERS_RU.md'));s.write(out/'plan.json',plan);(out/'frozen_transfer_runner.py').write_bytes(Path(__file__).read_bytes());ps=[]
    for i in range(4):
        log=(out/f'worker-{i}.log').open('w');ps.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'worker','--study',study,'--plan',str(out/'plan.json'),'--index',str(i)],cwd=ROOT,stdout=log,stderr=log))
    codes=[p.wait() for p in ps];s.write(out/'exit_codes.json',codes);print(study,stage,codes)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['pilot','main','worker']);ap.add_argument('--study',choices=['semantic','lifecycle'],required=True);ap.add_argument('--plan');ap.add_argument('--index',type=int);args=ap.parse_args()
    if args.command=='worker':
        cfg=json.loads(Path(args.plan).read_text())['config']
        if args.study=='semantic':sem.MODELS=cfg['models'];sem.worker(args.plan,args.index)
        else:own.worker(args.plan,args.index)
    else:launch(args.study,args.command)
