"""Deterministic native-browser paths, including negative controls. No model calls."""
from __future__ import annotations
import argparse
import itertools
from pathlib import Path
from runtime_support import control_browser
import time

from bounded_api import encode,launch,write
from drift_app import DriftApp,DriftSurface


def run(workspace: Path,root: Path) -> None:
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True)
    rows=[]
    with sync_playwright() as p:
        browser=launch(p,control_browser())
        try:
            for family,sync,path in itertools.product(('quantity','variant'),('shared','deferred'),
                ('ui','tool','ui_to_tool_repaired','tool_to_ui_repaired','ui_to_tool_unrepaired','tool_to_ui_unrepaired')):
                folder=root/f'{family}-{sync}-{path.replace("_","-")}';folder.mkdir()
                app=DriftApp(workspace,folder,dict(family=family,sync=sync,instance=0))
                surface=DriftSurface(browser,app);allowed={s['function']['name'] for s in surface.schemas('hybrid')}
                def act(name,args):return surface.act(name,args,allowed)
                try:
                    assert app.snapshot()['form']['product_id']==app.snapshot()['saved']['items'][0]['product_id']
                    edit=f'edit-{app.target["product_id"]}-{app.target["quantity"]}'
                    if path.startswith('ui'):
                        act('ui_click',{'id':edit})
                        if path=='ui':act('ui_click',{'id':'checkout'})
                        else:
                            read=act('site_cart',{})
                            expected_quantity=app.target['quantity'] if sync=='shared' else 1
                            assert read['saved_cart']['items'][0]['quantity']==expected_quantity
                            if path.endswith('_repaired'):act('site_replace_cart',app.target)
                            act('site_checkout',{})
                    else:
                        act('site_replace_cart',app.target)
                        if path=='tool':act('site_checkout',{})
                        else:
                            if path.endswith('_repaired'):act('ui_click',{'id':'refresh'})
                            act('ui_click',{'id':'checkout'})
                    score=app.score(None)
                    expected=sync=='shared' or not path.endswith('_unrepaired')
                    assert score['task_success']==expected,(family,sync,path,score)
                    if sync=='shared':assert not score['drift_created']
                    row=dict(family=family,sync=sync,path=path,expected_success=expected,score=score)
                    rows.append(row);write(root/'controls.json',dict(rows=rows,complete=False))
                    print(encode(row),flush=True)
                finally:surface.close()
        finally:browser.close()
    write(root/'controls.json',dict(rows=rows,complete=True,total=len(rows),passed=len(rows)))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();run(args.workspace,args.out)
