"""Finite native controls: state convergence versus preservation of intent.

These are scripted application paths, NOT model-agent reliability episodes.
"""
import argparse
import hashlib
import itertools
from pathlib import Path
from runtime_support import control_browser

from bounded_api import launch,write,encode
from drift_app import DriftApp,DriftSurface


def run(workspace: Path,root: Path) -> None:
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True);rows=[]
    names=('resync_controls.py','drift_app.py','drift_wc.php','night_wc_bootstrap.php')
    write(root/'sources.json',{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in names})
    with sync_playwright() as p:
        browser=launch(p,control_browser())
        try:
            for family,entry,sync_action in itertools.product(('quantity','variant'),('ui','tool'),('save','refresh')):
                folder=root/f'{family}-{entry}-{sync_action}';folder.mkdir()
                app=DriftApp(workspace,folder,dict(family=family,instance=0,sync='deferred'))
                surface=DriftSurface(browser,app);allowed={x['function']['name'] for x in surface.schemas('hybrid')}
                def act(n,args):return surface.act(n,args,allowed)
                try:
                    if entry=='ui':act('ui_click',{'id':f'edit-{app.target["product_id"]}-{app.target["quantity"]}'})
                    else:act('site_replace_cart',app.target)
                    diverged=app.snapshot()
                    assert any(diverged['form'][k]!=diverged['saved']['items'][0][k] for k in app.target)
                    act('ui_click',{'id':sync_action})
                    before=app.snapshot()
                    agree=all(before['form'][k]==before['saved']['items'][0][k] for k in app.target)
                    matches=all(before['form'][k]==app.target[k] for k in app.target)
                    assert agree and matches==((entry=='ui')==(sync_action=='save'))
                    act('site_checkout',{})
                    score=app.score(None)
                    assert score['task_success']==matches and score['wrong_commit']==(not matches)
                    row=dict(family=family,entry=entry,synchronization=sync_action,
                        agree_before_commit=agree,intent_before_commit=matches,score=score)
                    rows.append(row)
                    write(folder/'backend.json',dict(initial=app.initial,events=app.events,
                        target=app.target,converged_before_commit=before,final=app.snapshot()))
                    write(folder/'result.json',row);print(encode(row),flush=True)
                finally:surface.close()
        finally:browser.close()
    write(root/'controls.json',dict(total=len(rows),passed=len(rows),complete=True,
        scope='Scripted native application controls, no model calls',rows=rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.workspace,a.out)
