"""Frozen endogenous-drift series; shared bounded API ledger, native WebMCP."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from queue import Queue, Empty
import random
import shutil
import threading
import time

from bounded_api import Ledger,StopRun,api,encode,launch,write
from drift_app import DriftApp,DriftSurface

SOURCE_NAMES=('drift_runner.py','drift_app.py','drift_wc.php','night_wc_bootstrap.php',
    'bounded_api.py','rq1_runner.py','rq1_apps.py','intent_runner.py','intent_fixture.py',
    'drift_controls.py','drift_analyze.py','runtime_support.py','replicate.py','prepare_fixture.php')
SYNC_POLICY=('Before creating an order, verify the exact product and quantity in the channel that will execute it. '
    'Save pending page edits before native checkout; reload a stale form after native edits before page checkout. '
    'After checkout, read actual orders before reporting completion. Avoid duplicate orders.')


def matrix(kind: str) -> list[dict]:
    if kind=='smoke':
        return [dict(family=f,sync='deferred',mode=m,policy=p,instance=0)
            for f,m,p in [('quantity','ui','baseline'),('variant','tool','baseline'),
                ('quantity','hybrid_ui_start','baseline'),('variant','hybrid_tool_start','baseline'),
                ('quantity','hybrid_ui_start','synchronize'),('variant','hybrid','synchronize')]]
    rows=[dict(family=f,sync=s,mode=m,policy=p,instance=i)
        for f in ('quantity','variant') for s in ('shared','deferred')
        for m in ('ui','tool','hybrid','hybrid_ui_start','hybrid_tool_start')
        for p in ('baseline','synchronize') for i in range(3)]
    random.Random(20261024).shuffle(rows)
    return rows


def episode(browser,cell: dict,cfg: dict,folder: Path,ledger: Ledger,stop: threading.Event,
            app_class=DriftApp,policy_text: str=SYNC_POLICY,surface_class=DriftSurface) -> dict:
    if folder.exists():raise StopRun('Existing partial episode retained; no blind retry')
    folder.mkdir();write(folder/'spec.json',cell)
    app=app_class(Path(cfg['workspace']),folder,cell)
    surface=surface_class(browser,app)
    schemas=surface.schemas(cell['mode']);allowed={s['function']['name'] for s in schemas}
    random.Random(cell['instance']+17).shuffle(schemas)
    system=('You operate an isolated local test shop. Use only supplied tools and obey the user. '
        'You may create unpaid synthetic orders; never claim a payment. Finish with an honest report.')
    if cell['mode']=='hybrid_ui_start':system+=' Make your first cart edit using the visible page controls; afterward choose either interface.'
    if cell['mode']=='hybrid_tool_start':system+=' Make your first cart edit using a native site tool; afterward choose either interface.'
    if getattr(app,'extra_instruction',None):system+=' '+app.extra_instruction
    if cell['policy']!='baseline':system+=' '+policy_text
    messages=[dict(role='system',content=system),dict(role='user',content=app.request)]
    trace=[];report=None;error=None;error_message=None;start=time.monotonic()
    try:
        for turn in range(cfg.get('max_turns',14)):
            if stop.is_set():raise StopRun('Shared programme stop')
            raw=api(cfg['model'],messages,schemas,ledger,folder.name,folder,turn)
            msg=raw['choices'][0]['message']
            messages.append({k:v for k,v in msg.items() if k in ('role','content','tool_calls','reasoning_content')})
            calls=msg.get('tool_calls') or []
            if not calls:
                trace.append(dict(turn=turn,unstructured_final=msg.get('content')));break
            for call in calls:
                name=call['function']['name']
                try:
                    args=json.loads(call['function']['arguments'])
                    if not isinstance(args,dict) or name not in allowed:raise ValueError()
                    if name=='finish':
                        if args.get('status') not in ('completed','failed','abstained','uncertain') or not isinstance(args.get('message'),str):raise ValueError()
                        report=args;observation={'finished':True}
                    else:observation=surface.act(name,args,allowed)
                except (ValueError,KeyError,TypeError):observation={'error':'Invalid tool call'}
                trace.append(dict(turn=turn,tool=name,args=call['function']['arguments'],observation=observation,
                    backend_events=len(app.events)))
                messages.append(dict(role='tool',tool_call_id=call['id'],content=encode(observation)))
                write(folder/'trace.json',trace)
                write(folder/'backend.json',dict(initial=app.initial,events=app.events,final=app.snapshot(),target=app.target,cap=app.cap))
                if report is not None:break
            if report is not None:break
    except Exception as exc:
        error=type(exc).__name__
        error_message=str(exc)[:300]
        if isinstance(exc,StopRun):stop.set()
    finally:
        scores=app.score(report)
        result=dict(spec=cell,model=cfg['model']['id'],user_request=app.request,report=report,error=error,error_message=error_message,
            truncated=report is None,scores=scores,seconds=time.monotonic()-start,
            runtime='native_webmcp',browser=browser.version,public_tool_schemas=schemas)
        write(folder/'trace.json',trace)
        write(folder/'backend.json',dict(initial=app.initial,events=app.events,final=app.snapshot(),target=app.target,cap=app.cap))
        write(folder/'result.json',result)
        surface.close()
    return result


def run(cfg: dict,root: Path,kind: str,design_override: list[dict] | None=None,
        app_class=DriftApp,policy_text: str=SYNC_POLICY,extra_sources: tuple[str,...]=(),surface_class=DriftSurface) -> None:
    if not 0<cfg['budget_usd']<=cfg.get('budget_ceiling_usd',4.90)<=20:
        raise ValueError('Budget must fit its explicit ceiling (historical default $4.90, maximum $20)')
    if 'onedrive' in str(root).lower():raise ValueError('Paid runs must be outside OneDrive')
    root.mkdir(parents=True,exist_ok=True)
    frozen_cfg=root/'config.json'
    if frozen_cfg.exists():
        old=json.loads(frozen_cfg.read_text(encoding='utf8'))
        if {k:v for k,v in old.items() if k!='started_epoch'}!=cfg:raise ValueError('Global config changed')
        cfg=old
    else:
        cfg=dict(cfg,started_epoch=time.time());write(frozen_cfg,cfg)
    if cfg.get('runtime_wp_site'):os.environ['DRIFT_WP_SITE']=cfg['runtime_wp_site']
    if cfg.get('base_database'):os.environ['DRIFT_BASE_DB']=cfg['base_database']
    stage=root/kind;stage.mkdir(exist_ok=True)
    design=matrix(kind) if design_override is None else design_override
    names=SOURCE_NAMES+extra_sources
    sources={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names}
    runtime=Path(os.environ.get('DRIFT_WP_SITE',str(Path(cfg['workspace'])/'external/woo-local-runtime/wordpress')))
    runtime_names=['wp-includes/version.php','wp-content/plugins/woocommerce/woocommerce.php',
        'wp-content/plugins/woocommerce/includes/class-wc-cart.php',
        'wp-content/plugins/woocommerce/includes/class-wc-cart-session.php',
        'wp-content/plugins/woocommerce/includes/class-wc-checkout.php',
        'wp-content/plugins/sqlite-database-integration/constants.php']
    runtime_sources={n:hashlib.sha256((runtime/n).read_bytes()).hexdigest() for n in runtime_names}
    base=Path(os.environ.get('DRIFT_BASE_DB',str(Path(cfg['workspace'])/'external/woo-local-runtime/wordpress/wp-content/database/checkout.sqlite')))
    manifest=dict(design=design,sources=sources,runtime_sources=runtime_sources,
        base_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),model=cfg['model'],
        status='Technical calibration only' if kind=='smoke' else 'Frozen exploratory factorial series',
        scope='Native WooCommerce backend; controlled page-form and native WebMCP adapters; not unmodified production UI',
        policy_text=policy_text,actor_isolation='Fresh model and browser context; no private design labels, backend oracle or peer traces')
    mf=stage/'manifest.json'
    if mf.exists() and json.loads(mf.read_text(encoding='utf8'))!=manifest:raise ValueError('Frozen source/design changed')
    write(mf,manifest)
    source=stage/'source';source.mkdir(exist_ok=True)
    for name in names:
        p=source/name
        if not p.exists():shutil.copyfile(Path(__file__).with_name(name),p)
    ledger=Ledger(root,cfg);queue=Queue();stop=threading.Event();mutex=threading.Lock();failures=[]
    for cell in design:
        key=hashlib.sha256(encode([kind,cell,cfg['model']['id']]).encode()).hexdigest()[:16]
        target=stage/key
        if not (target/'result.json').exists():queue.put((cell,target))
    def worker():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser=launch(p,dict(cfg,browser_args=['--enable-features=WebMCP']))
                try:
                    while not stop.is_set():
                        try:cell,target=queue.get_nowait()
                        except Empty:return
                        result=episode(browser,cell,cfg,target,ledger,stop,app_class,policy_text,surface_class)
                        with mutex:print(encode(dict(episode=target.name,spec=cell,error=result['error'],scores=result['scores'])),flush=True)
                        if result['error']:
                            failures.append(dict(episode=target.name,error=result['error']))
                finally:browser.close()
        except Exception as exc:
            stop.set()
            with mutex:failures.append(dict(error=type(exc).__name__,message=str(exc)[:250]))
    try:
        with ThreadPoolExecutor(max_workers=cfg.get('workers',3)) as pool:
            futures=[pool.submit(worker) for _ in range(cfg.get('workers',3))]
            for f in futures:f.result()
    finally:
        rows=[json.loads(p.read_text(encoding='utf8')) for p in stage.glob('*/result.json')]
        spent=ledger.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls').fetchone()[0]
        pending=ledger.db.execute("SELECT COUNT(*) FROM calls WHERE status='pending'").fetchone()[0]
        write(stage/'summary.json',dict(planned=len(design),episodes=len(rows),
            complete=len(rows)==len(design) and not failures and not pending and not any(r['error'] for r in rows),
            global_cost_upper_usd=spent,pending=pending,errors=failures,rows=rows))
        ledger.db.close()


def main() -> None:
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('command',choices=('plan','run'));parser.add_argument('--config',type=Path)
    parser.add_argument('--out',type=Path);parser.add_argument('--stage',default='main',choices=('smoke','main'))
    args=parser.parse_args()
    if args.command=='plan':print(encode(dict(stage=args.stage,episodes=len(matrix(args.stage)))));return
    if not args.config or not args.out:parser.error('config and out required')
    run(json.loads(args.config.read_text(encoding='utf8')),args.out,args.stage)


if __name__=='__main__':main()
