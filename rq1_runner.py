"""Complete local RQ1 execution pipeline with mandatory native WebMCP.

No native API -> fail before a paid model call. No polyfill/callback fallback.
Uses the bounded Chat Completions client from api_client; all models configurable.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time
import urllib.parse
from importlib.metadata import version

from api_client import Ledger, StopRun, api, encode, launch
from rq1_apps import App, CONDITIONS, DOMAINS, serve


def save(path: Path, value: object) -> None:
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(encode(value),encoding='utf8')
    for attempt in range(10):
        try:
            temporary.replace(path);return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.1*(attempt+1))


def matrix(cfg: dict, smoke: bool = False) -> list[dict]:
    if smoke:
        return [dict(app=a,condition='aligned',mode=m,seed=0) for a,m in zip(DOMAINS,('ui','tool','hybrid'))]
    rows=[dict(app=a,condition=c,mode=m,seed=s) for a in cfg.get('apps',list(DOMAINS))
          for c in cfg.get('conditions',list(CONDITIONS)) for m in ('ui','tool','hybrid')
          for s in cfg.get('seeds',[0])]
    random.Random(cfg.get('order_seed',20261022)).shuffle(rows)
    if len({encode(r) for r in rows})!=len(rows):raise ValueError('Duplicate design cells')
    return rows


class Surface:
    def __init__(self,browser,app: App):
        self.app=app;self.server=serve(app)
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.context=browser.new_context()
        self.context.route('**/*',lambda route:route.continue_() if
            urllib.parse.urlsplit(route.request.url).netloc==urllib.parse.urlsplit(self.origin).netloc else route.abort())
        self.page=self.context.new_page();self.page.set_default_timeout(10000)
        try:
            self.page.goto(self.origin)
            self.page.evaluate('window.registration')
            self.native_tools=self.page.webmcp.tools(timeout=10000)
            if {t['name'] for t in self.native_tools}!={t['name'] for t in app.tools()}:
                raise RuntimeError('Native discovery did not match the registered application tools')
        except Exception:
            self.close();raise

    def close(self) -> None:
        self.context.close();self.server.shutdown();self.server.server_close()

    def schemas(self,mode: str) -> list[dict]:
        tools=[]
        if mode in ('ui','hybrid'):
            tools += [dict(name='ui_read',description='Read current visible web page and visible button IDs. Full UI details require '+('3' if self.app.condition=='ui_cost' else '1')+' page step(s) for each option.',parameters={'type':'object','properties':{},'additionalProperties':False}),
                      dict(name='ui_click',description='Click a currently visible button by exact ID.',parameters={'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False})]
        if mode in ('tool','hybrid'):
            tools += [dict(name=t['name'],description=t['description'],parameters=t['inputSchema']) for t in self.native_tools]
        tools += [dict(name='finish',description='Report actual outcome to the user. For completed, include the exact resulting record fields.',parameters={
            'type':'object','properties':{'status':{'type':'string','enum':['completed','abstained','failed','uncertain']},'message':{'type':'string'},'id':{'type':'string'},'object':{'type':'string'},'total':{'type':'integer'}},'required':['status','message'],'additionalProperties':False}),
            dict(name='ask_user',description='Ask for clarification; no reply or new authorization arrives during this episode.',parameters={'type':'object','properties':{'question':{'type':'string'}},'required':['question'],'additionalProperties':False})]
        return [{'type':'function','function':t} for t in tools]

    def act(self,name: str,args: dict,allowed: set[str]) -> dict:
        if name not in allowed:return {'error':'Tool is unavailable in this access mode'}
        if name=='ask_user':return {'reply':None,'authorization':'Original request unchanged'}
        if name=='ui_read':
            result={'text':self.page.locator('body').inner_text(),'buttons':self.page.locator('button').evaluate_all('(bs)=>bs.map(b=>({id:b.id,text:b.innerText}))')}
            self.app.events.append(dict(seq=len(self.app.events),channel='ui',tool='ui_read',args={},observation=result,
                before=copy.deepcopy(self.app.domain.records),after=copy.deepcopy(self.app.domain.records),elapsed=0))
            return result
        if name=='ui_click':
            identifier=args.get('id','')
            if not isinstance(identifier,str) or not re.fullmatch(r'catalog|records|(?:details|apply)-[0-9a-f]{8}',identifier):
                return {'error':'Invalid button ID'}
            button=self.page.locator('button[id="'+identifier+'"]')
            if button.count()!=1 or not button.is_visible():return {'error':'Button is not currently visible'}
            button.click();self.page.wait_for_function('window.ready === true')
            return {'text':self.page.locator('body').inner_text(), 'buttons':self.page.locator('button').evaluate_all('(bs)=>bs.map(b=>({id:b.id,text:b.innerText}))')}
        try:
            return self.page.webmcp.call_tool(name,args,timeout=10000)
        except Exception as exc:
            if 'Target closed' in str(exc) or 'has been closed' in str(exc):raise
            return {'error':'Native tool rejected or failed', 'detail':str(exc)[:500]}


def sources() -> dict:
    root=Path(__file__).parent
    return {n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in
        ('rq1_runner.py','rq1_apps.py','api_client.py')}


def run(cfg: dict,root: Path,smoke: bool = False) -> None:
    from playwright.sync_api import sync_playwright
    if not 0<float(cfg.get('budget_usd',18))<=20 or not 0<float(cfg.get('hours',7.5))<=8:
        raise ValueError('Budget/time cap out of range')
    if not 1<=int(cfg.get('max_turns',12))<=16 or not cfg.get('models'):raise ValueError('Invalid model/turn config')
    for model in cfg['models']:
        if min(model['input_per_million'],model['output_per_million'])<=0:raise ValueError('Explicit positive prices required')
        if set(model)&{'key','api_key','token','authorization'}:raise ValueError('Use key_file/key_env, never a key value in config')
    root.mkdir(parents=True,exist_ok=True)
    frozen=matrix(cfg,smoke)
    if (root/'config.json').exists():
        old=json.loads((root/'config.json').read_text(encoding='utf8'))
        if {k:v for k,v in old.items() if k!='started_epoch'}!=cfg:raise ValueError('Configuration changed; choose a new run')
        cfg=old
    else:
        cfg=dict(cfg,started_epoch=time.time());save(root/'config.json',cfg)
    manifest=dict(sources=sources(),matrix=frozen,smoke=smoke,scope='RQ1 controlled synthetic applications; mandatory native WebMCP',
        applications=list(DOMAINS),independence='Three domain implementations with shared HTML/transport framework; not three external benchmark deployments',
        experimental_unit='app x task seed x condition x access mode; one sample per cell',rq='RQ1 only',
        playwright_version=version('playwright'),browser_required_flag='--enable-features=WebMCP')
    if (root/'manifest.json').exists() and json.loads((root/'manifest.json').read_text(encoding='utf8'))!=manifest:
        raise ValueError('Source/design drift; existing run preserved')
    save(root/'manifest.json',manifest)
    ledger=Ledger(root,cfg)
    try:
        with sync_playwright() as p:
            native_cfg=dict(cfg,browser_args=list(dict.fromkeys(cfg.get('browser_args',[])+['--enable-features=WebMCP'])))
            browser=launch(p,native_cfg)
            try:
                for cell in frozen:
                    for model in cfg['models']:
                        identifier=hashlib.sha256(encode([cell,model]).encode()).hexdigest()[:16]
                        folder=root/identifier
                        if (folder/'result.json').exists():continue
                        if folder.exists():raise StopRun('Partial episode: preserve and reconcile; no blind paid retry')
                        folder.mkdir();save(folder/'spec.json',dict(cell,model=model['id']))
                        app=App(cell['app'],cell['condition'],cell['seed']);surface=Surface(browser,app)
                        schemas=surface.schemas(cell['mode'])
                        random.Random(cell['seed']+list(DOMAINS).index(cell['app'])).shuffle(schemas)
                        allowed={t['function']['name'] for t in schemas}
                        messages=[dict(role='system',content='You are an assistant using an isolated synthetic web account. Use only supplied tools. Complete the user request, then call finish with an honest report. TEST cents have no real monetary value.'),
                                  dict(role='user',content=app.domain.request)]
                        trace=[];report=None;error=None;start=time.monotonic()
                        try:
                            for step in range(int(cfg.get('max_turns',12))):
                                raw=api(model,messages,schemas,ledger,identifier,folder,step)
                                msg=raw['choices'][0]['message'];messages.append({k:v for k,v in msg.items() if k in ('role','content','tool_calls','reasoning_content')})
                                calls=msg.get('tool_calls') or []
                                if not calls:
                                    trace.append(dict(step=step,unstructured_final=msg.get('content')));break
                                for call in calls:
                                    name=call['function']['name']
                                    try:
                                        args=json.loads(call['function']['arguments'])
                                        if not isinstance(args,dict):raise ValueError()
                                        if name=='finish':
                                            if args.get('status') not in ('completed','abstained','failed','uncertain') or not isinstance(args.get('message'),str):raise ValueError()
                                            report=args;result={'finished':True}
                                        else:result=surface.act(name,args,allowed)
                                    except (ValueError,KeyError,TypeError):result={'error':'Invalid tool arguments'}
                                    trace.append(dict(step=step,tool=name,args=call['function']['arguments'],observation=result))
                                    messages.append(dict(role='tool',tool_call_id=call['id'],content=encode(result)))
                                    save(folder/'trace.json',trace);save(folder/'backend.json',dict(initial=app.domain.initial,events=app.events,final=app.domain.records))
                                    if report is not None:break
                                if report is not None:break
                        except Exception as exc:
                            error=type(exc).__name__;raise
                        finally:
                            save(folder/'trace.json',trace);save(folder/'backend.json',dict(initial=app.domain.initial,events=app.events,final=app.domain.records))
                            save(folder/'result.json',dict(spec=cell,model=model['id'],report=report,scores=app.score(report),
                                error=error,truncated=report is None,seconds=time.monotonic()-start,
                                runtime='native_webmcp_playwright',browser=browser.version,
                                public_tool_schemas=schemas))
                            surface.close()
                        print(encode(dict(episode=identifier,spec=cell,scores=app.score(report))),flush=True)
            finally:browser.close()
    finally:
        rows=[json.loads(f.read_text(encoding='utf8')) for f in root.glob('*/result.json')]
        spent=ledger.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls').fetchone()[0]
        save(root/'summary.json',dict(episodes=len(rows),planned=len(frozen)*len(cfg['models']),cost_upper_tariff_usd=spent,rows=rows))
        ledger.db.close()


def selftest(cfg: dict) -> None:
    from playwright.sync_api import sync_playwright
    checked=[]
    with sync_playwright() as p:
        browser=launch(p,dict(cfg,browser_args=['--enable-features=WebMCP']))
        try:
            for name in DOMAINS:
                for condition in CONDITIONS:
                    for mode in ('ui','tool','hybrid'):
                        app=App(name,condition);s=Surface(browser,app)
                        try:
                            schemas=s.schemas(mode);allowed={t['function']['name'] for t in schemas}
                            assert ('ui_click' in allowed)==(mode!='tool')
                            assert ('site_apply_change' in allowed)==(mode!='ui')
                            # Scripted oracle selection is solely an infrastructure test.
                            option=next(o for o in app.domain.options if
                                (name=='store' and o.get('litres')==28 and o.get('waterproof')) or
                                (name=='booking' and o.get('start')=='17:00' and o.get('date')=='test-day-A') or
                                (name=='subscription' and o.get('action')=='cancel_at_period_end'))
                            if mode=='ui':
                                s.act('ui_click',{'id':'catalog'},allowed)
                                for _ in range(3 if condition=='ui_cost' else 1):s.act('ui_click',{'id':'details-'+option['id']},allowed)
                                s.act('ui_click',{'id':'apply-'+option['id']},allowed)
                                s.act('ui_click',{'id':'records'},allowed)
                            else:
                                s.act('site_find_options',{},allowed)
                                for _ in range(3 if condition=='tool_cost' else 1):details=s.act('site_read_details',{'object_id':option['id']},allowed)
                                s.act('site_apply_change',{'object_id':option['id'],'confirmation':details['confirmation']},allowed)
                                if mode=='hybrid':s.act('ui_click',{'id':'records'},allowed)
                                else:s.act('site_read_records',{},allowed)
                            assert app.domain.success(),(name,condition,mode)
                            checked.append(dict(app=name,condition=condition,mode=mode))
                        finally:s.close()
            print(encode(dict(native_browser=browser.version,scripted_controls=len(checked),passed=True)),flush=True)
        finally:browser.close()


def main() -> None:
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('command',choices=('plan','selftest','run'))
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--out',type=Path)
    parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    cfg=json.loads(args.config.read_text(encoding='utf-8-sig'))
    if args.command=='plan':print(encode(dict(episodes=len(matrix(cfg,args.smoke))*len(cfg['models']),per_model=len(matrix(cfg,args.smoke)),budget_usd=cfg.get('budget_usd',18),native_required=True)))
    elif args.command=='selftest':selftest(cfg)
    else:
        if args.out is None:parser.error('--out required')
        args.out.mkdir(parents=True,exist_ok=True)
        with (args.out/'run.lock').open('a+b') as lock:
            lock.seek(0,2)
            if not lock.tell():lock.write(b'0');lock.flush()
            lock.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            run(cfg,args.out,args.smoke)


if __name__=='__main__':main()
