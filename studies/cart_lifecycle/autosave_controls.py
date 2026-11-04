"""Scripted own-write race controls; never model episodes."""
import argparse
import itertools
import hashlib
import shutil
from pathlib import Path
from runtime_support import control_browser

from bounded_api import launch,write,encode
from autosave_series import AutosaveApp,AutosaveSurface


def run(workspace: Path,root: Path) -> None:
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True);rows=[]
    sources=root/'source';sources.mkdir(exist_ok=True)
    names=('autosave_controls.py','autosave_series.py','drift_app.py','drift_wc.php','night_wc_bootstrap.php')
    write(root/'sources.json',{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names})
    for n in names:shutil.copyfile(Path(__file__).with_name(n),sources/n)
    with sync_playwright() as p:
        browser=launch(p,control_browser())
        try:
            for family,timing,wait in itertools.product(('quantity','variant'),('immediate','queued'),(False,True)):
                folder=root/f'{family}-{timing}-{str(wait).lower()}';folder.mkdir()
                spec=dict(family=family,instance=0,timing=timing,sync='deferred')
                app=AutosaveApp(workspace,folder,spec);surface=AutosaveSurface(browser,app)
                allowed={s['function']['name'] for s in surface.schemas('hybrid')}
                def act(n,args):return surface.act(n,args,allowed)
                try:
                    act('ui_click',{'id':f'edit-{app.preview["product_id"]}-{app.preview["quantity"]}'})
                    if wait:act('site_wait_for_save',{})
                    act('site_replace_cart',app.target)
                    immediate=app.backend.state['cart']
                    assert all(immediate['items'][0][k]==app.target[k] for k in app.target)
                    score=app.score(None)
                    expected=timing=='immediate' or wait
                    assert score['task_success']==expected,(spec,wait,score)
                    assert score['orders']==0
                    row=dict(spec=spec,wait=wait,immediate_cart=immediate,score=score)
                    rows.append(row);write(folder/'result.json',row)
                    write(folder/'backend.json',dict(initial=app.initial,events=app.events,target=app.target,final=app.snapshot()))
                    print(encode(row),flush=True)
                finally:app.wait();surface.close()
        finally:browser.close()
    write(root/'controls.json',dict(total=len(rows),passed=len(rows),complete=True,scope='Scripted native controls; no model calls',rows=rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.workspace,a.out)
