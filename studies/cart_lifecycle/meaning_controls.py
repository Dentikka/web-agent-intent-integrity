"""Free native controls for truthful unit/cart price representations."""
import argparse
import itertools
from pathlib import Path
from runtime_support import control_browser

from bounded_api import launch,write,encode
from drift_app import DriftSurface
from meaning_series import MeaningApp


def run(workspace: Path,root: Path) -> None:
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True);rows=[]
    with sync_playwright() as p:
        browser=launch(p,control_browser())
        try:
            for representation,feasible in itertools.product(('same_total','ui_unit','tool_unit'),(True,False)):
                folder=root/(representation.replace('_','-')+'-'+str(feasible).lower());folder.mkdir()
                spec=dict(representation=representation,feasible=feasible,instance=0,sync='shared',family='quantity')
                app=MeaningApp(workspace,folder,spec);surface=DriftSurface(browser,app)
                allowed={x['function']['name'] for x in surface.schemas('hybrid')}
                try:
                    surface.act('site_replace_cart',app.target,allowed)
                    tool=surface.act('site_cart',{},allowed)['saved_cart']
                    form=app.view()['form'];ui=surface.act('ui_read',{},allowed)
                    def total(v,q):return v['price_minor']*q if v['price_scope']=='per_item' else v['price_minor']
                    actual=app.backend.state['cart']['total_minor'];q=app.target['quantity']
                    assert total(form,q)==total(tool,q)==actual
                    assert form['price_scope'] in ui['text']
                    assert (actual<=app.cap)==feasible
                    # Deliberate negative control proves that the oracle catches
                    # the same correct object at an impermissible total.
                    surface.act('site_checkout',{},allowed)
                    score=app.score(None)
                    assert score['task_success']==feasible and score['wrong_commit']==(not feasible)
                    row=dict(spec=spec,form=form,tool=tool,actual_total=actual,cap=app.cap,score=score)
                    rows.append(row);print(encode(row),flush=True)
                finally:surface.close()
        finally:browser.close()
    write(root/'controls.json',dict(total=len(rows),passed=len(rows),complete=True,rows=rows))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.workspace,a.out)
