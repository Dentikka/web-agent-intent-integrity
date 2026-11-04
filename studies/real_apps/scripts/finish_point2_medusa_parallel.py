"""Complete the frozen 384 cells on byte-identical isolated replicas.

Scheduling alone changes. Each original cell is assigned once, independently
of outcomes. The original actor run() remains unmodified and runs each shard.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/medusa_v1'
MAIN=ART/'point2_main_seed1'
SERIES=ART/'point2_parallel'

def helper(command,run_id,port,log):
    env=dict(os.environ,MEDUSA_RUN_ID=run_id,MEDUSA_PORT=str(port))
    p=subprocess.run([sys.executable,str(ROOT/'scripts/medusa_capsule.py'),command],
        env=env,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=600)
    with log.open('a') as f:f.write(p.stdout+'\n'+p.stderr+'\n')
    if p.returncode:raise RuntimeError(f'{run_id} {command} failed; see {log}')
    return p.stdout

def setup(index):
    run_id='intent-v1' if index==0 else f'intent-p2-w{index}'
    port=8766 if index==0 else 8770+index
    log=SERIES/f'setup-{index}.log'
    if index:
        helper('prepare',run_id,port,log)
        helper('patch',run_id,port,log)
        helper('up',run_id,port,log)
    status=json.loads(helper('status',run_id,port,log))
    if not status['healthy']:raise RuntimeError('Replica unhealthy')
    app=Path(status['workspace'])
    manifest=json.loads((MAIN/'manifest.json').read_text())
    prefix='artifacts/medusa_v1/runtime/nextjs-starter-medusa/intent-v1/author/repo/'
    verified={}
    for filename,digest in manifest['source_hashes'].items():
        file=app/filename[len(prefix):] if filename.startswith(prefix) else ROOT/filename
        got=hashlib.sha256(file.read_bytes()).hexdigest()
        if got!=digest:raise RuntimeError(f'Frozen source mismatch: {file}')
        verified[filename]=got
    return dict(index=index,run_id=run_id,port=port,app=str(app),
        db=status['runtime']['composeProject']+'-db-1',source_hashes=verified,
        source_revision=status['sourceRevision'])

def worker(index):
    sys.path.insert(0,str(ROOT/'src'))
    import medusa_v1.environment as e
    import medusa_v1.run as r
    plan=json.loads((SERIES/'plan.json').read_text())
    target=plan['workers'][index]
    os.environ.update(MEDUSA_RUN_ID=target['run_id'],MEDUSA_PORT=str(target['port']))
    e.BASE=r.BASE=f'http://127.0.0.1:{target["port"]}'
    e.APP=r.APP=Path(target['app'])
    e.RUNTIME=e.APP.parents[1]
    e.DB=target['db']
    cells=target['cells']
    r.matrix=lambda cfg:cells
    cfg=json.loads((ROOT/'configs/medusa_v1/point2_main.json').read_text())
    # Eight shard caps plus already spent calls remain below the original $7.
    cfg['budget_usd']=0.8
    r.run(cfg,SERIES/f'worker-{index}')

def main():
    if len(sys.argv)>1 and sys.argv[1]=='worker':
        worker(int(sys.argv[2]));return
    SERIES.mkdir(exist_ok=True)
    if (SERIES/'plan.json').exists():raise RuntimeError('Plan exists: do not repeat paid episodes')
    # The original runner exits only after persisting a complete episode.
    while True:
        try:os.kill(110997,0)
        except ProcessLookupError:break
        time.sleep(2)
    import sqlite3
    with sqlite3.connect(MAIN/'usage.sqlite') as db:
        if db.execute("SELECT count(*) FROM calls WHERE status='pending'").fetchone()[0]:
            raise RuntimeError('Original ledger has pending calls')
        spent=db.execute('SELECT SUM(COALESCE(actual,reserve)) FROM calls').fetchone()[0]
        if spent+8*0.8>7:raise RuntimeError('Combined cap exceeds registered budget')
    manifest=json.loads((MAIN/'manifest.json').read_text())
    completed={p.parent.name for p in MAIN.glob('*/result.json')}
    assignments=[[] for _ in range(8)]
    remaining=[]
    for c in manifest['cells']:
        identifier=hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
        if identifier in completed:continue
        if (MAIN/identifier).exists():raise RuntimeError('Partial original episode')
        assignments[len(remaining)%8].append(c);remaining.append(identifier)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        workers=list(pool.map(setup,range(8)))
    for w,cells in zip(workers,assignments):w['cells']=cells
    plan=dict(original_manifest_sha256=hashlib.sha256((MAIN/'manifest.json').read_bytes()).hexdigest(),
        previously_completed=sorted(completed),remaining=remaining,workers=workers,
        scheduling='Original shuffled remaining cells, round-robin by index; no outcome filtering',
        original_actor_unchanged=True,started_epoch=time.time(),original_spent=spent,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (SERIES/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
    processes=[]
    for i in range(8):
        with (SERIES/f'worker-{i}.log').open('w') as log:
            p=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'worker',str(i)],
                stdout=log,stderr=log,cwd=ROOT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src')))
        processes.append(p)
    codes=[p.wait() for p in processes]
    (SERIES/'exit_codes.json').write_text(json.dumps(codes))
    if any(codes):raise RuntimeError('A shard stopped: retain all results and diagnose')
    # Link immutable per-episode records into the registered parent for its
    # existing analyzer. All billing ledgers stay separate and auditable.
    for i in range(8):
        for result in (SERIES/f'worker-{i}').glob('*/result.json'):
            target=MAIN/result.parent.name
            if target.exists():raise RuntimeError('Duplicate episode ID')
            target.symlink_to(result.parent.resolve(),target_is_directory=True)
    rows=[json.loads(p.read_text()) for p in MAIN.glob('*/result.json')]
    if len(rows)!=len(manifest['cells']):raise RuntimeError('Missing episodes')
    (MAIN/'summary.json').write_text(json.dumps(dict(episodes=len(rows),planned=len(manifest['cells']),rows=rows)))
    subprocess.run([sys.executable,str(ROOT/'scripts/analyze_medusa_point2.py'),'--run',str(MAIN)],check=True,cwd=ROOT)
    (ROOT/'research/medusa_v1/POINT2_RESULTS_RU.md').write_text((MAIN/'REPORT_RU.md').read_text())
    (ART/'point2_series_status.json').write_text(json.dumps(dict(phase='complete',episodes=len(rows),parallel_plan=str(SERIES/'plan.json'))))

if __name__=='__main__':main()
