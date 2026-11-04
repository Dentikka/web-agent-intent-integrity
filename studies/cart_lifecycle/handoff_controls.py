"""Free controls for assigned handoffs and truthful compact documentation."""
import argparse
import itertools
from pathlib import Path
from runtime_support import control_browser

from bounded_api import launch,write,encode
from drift_app import DriftSurface
from handoff_series import HandoffApp


def run(workspace: Path,root: Path) -> None:
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True);rows=[]
    with sync_playwright() as p:
        browser=launch(p,control_browser())
        try:
            for sync,disclosure,route in itertools.product(('shared','deferred'),('full','standard'),('ui_tool','tool_ui')):
                folder=root/f'{sync}-{disclosure}-{route.replace("_","-")}';folder.mkdir()
                spec=dict(family='quantity',instance=0,sync=sync,disclosure=disclosure,handoff=route)
                app=HandoffApp(workspace,folder,spec);surface=DriftSurface(browser,app)
                allowed={s['function']['name'] for s in surface.schemas('hybrid')}
                def act(n,a):return surface.act(n,a,allowed)
                try:
                    if disclosure=='standard':assert 'Native checkout uses the saved server cart' not in act('ui_read',{})['text']
                    if route=='ui_tool':
                        assert 'error' in act('site_replace_cart',app.target)
                        act('ui_click',{'id':f'edit-{app.target["product_id"]}-{app.target["quantity"]}'})
                        act('ui_click',{'id':'save'})
                        assert 'error' in act('ui_click',{'id':'checkout'})
                        act('site_checkout',{})
                    else:
                        assert 'error' in act('ui_click',{'id':f'edit-{app.target["product_id"]}-{app.target["quantity"]}'})
                        act('site_replace_cart',app.target);act('ui_click',{'id':'refresh'})
                        assert 'error' in act('site_checkout',{})
                        act('ui_click',{'id':'checkout'})
                    score=app.score(None);assert score['task_success'] and not score['wrong_commit']
                    row=dict(spec=spec,score=score);rows.append(row);print(encode(row),flush=True)
                finally:surface.close()
        finally:browser.close()
    write(root/'controls.json',dict(total=len(rows),passed=len(rows),complete=True,rows=rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.workspace,a.out)
