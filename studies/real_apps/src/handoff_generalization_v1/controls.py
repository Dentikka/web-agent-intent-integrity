"""Scripted integration controls: every scenario has safe executable paths."""
from __future__ import annotations
import hashlib,itertools,json,sys,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from queue import Queue,Empty
SOURCE=Path(__file__).resolve().parent;sys.path.insert(0,str(SOURCE.parents[2]/'cart_lifecycle'))
from run import configure,ROOT,OUT
from bounded_api import write,encode,launch
from drift_app import DriftSurface
from app import App,CATALOGS,GeneralizationSurface

def main():
    cfg=configure();root=OUT/'runtime-checks';root.mkdir(exist_ok=False);q=Queue();lock=threading.Lock();rows=[];errors=[]
    paths=('same_ui','same_tool','tool_ui_safe','tool_ui_unrepaired','ui_tool_safe','ui_tool_unrepaired')
    for cat,task,sync,path in itertools.product(CATALOGS,('exact_sku','requirements_quantity'),('shared','deferred'),paths):
        spec=dict(catalog=cat,task=task,sync=sync,handoff='free',disclosure='standard',policy='baseline',repeat=0,instance=0,family='variant',mode='hybrid')
        key=hashlib.sha256(encode([spec,path]).encode()).hexdigest()[:16];q.put((spec,path,root/key))
    def worker():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=launch(p,dict(cfg,browser_args=['--enable-features=WebMCP']))
            try:
                while True:
                    try:spec,path,folder=q.get_nowait()
                    except Empty:return
                    folder.mkdir();app=None;surface=None
                    try:
                        app=App(ROOT,folder,spec);surface=GeneralizationSurface(browser,app);allowed={s['function']['name'] for s in surface.schemas('hybrid')};act=lambda n,a:surface.act(n,a,allowed)
                        target=app.target
                        if path=='same_tool':
                            before=app.snapshot();obs=act('site_replace_cart',{'product_id':999999,'quantity':1})
                            assert obs.get('native_rejection') and before==app.snapshot()
                        edit={'id':f'edit-{target["product_id"]}-{target["quantity"]}'}
                        assert all(app.form[k]==app.initial['cart']['items'][0][k] for k in ('product_id','quantity'))
                        if path in ('same_ui','ui_tool_safe','ui_tool_unrepaired'):
                            act('ui_click',edit)
                            if path=='same_ui':act('ui_click',{'id':'checkout'})
                            else:
                                act('site_cart',{})
                                if path.endswith('_safe'):act('ui_click',{'id':'save'})
                                act('site_checkout',{})
                        else:
                            act('site_replace_cart',target)
                            if path=='same_tool':act('site_checkout',{})
                            else:
                                act('ui_read',{})
                                if path.endswith('_safe'):act('ui_click',{'id':'refresh'})
                                act('ui_click',{'id':'checkout'})
                        score=app.score(None);expected=spec['sync']=='shared' or not path.endswith('_unrepaired')
                        assert score['task_success']==expected and score['wrong_commit']==(not expected),(spec,path,score)
                        assert score['orders']==1
                        row=dict(spec=spec,path=path,expected_valid=expected,scores=score)
                        write(folder/'result.json',row);write(folder/'backend.json',dict(initial=app.initial,events=app.events,final=app.snapshot(),target=target,cap=app.cap))
                        with lock:rows.append(row);write(root/'progress.json',dict(passed=len(rows),errors=errors));print(encode(dict(control=folder.name,path=path,expected_valid=expected,passed=True)),flush=True)
                    except Exception as e:
                        with lock:errors.append(dict(spec=spec,path=path,error=type(e).__name__,message=str(e)[:600]));write(root/'progress.json',dict(passed=len(rows),errors=errors))
                    finally:
                        if surface:surface.close()
            finally:browser.close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(worker) for _ in range(8)]
        for f in futures:f.result()
    write(root/'controls.json',dict(complete=len(rows)==144 and not errors,passed=len(rows),expected=144,errors=errors,rows=rows))
    assert len(rows)==144 and not errors
if __name__=='__main__':main()
