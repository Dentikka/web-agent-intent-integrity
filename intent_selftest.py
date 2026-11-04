"""Native-browser control checks for the RQ2-RQ4 scenarios. No model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from api_client import launch
from intent_cases import IntentApp,matrix
from intent_surface import IntentSurface


def check(cfg: dict,out: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright
    cells={json.dumps({k:v for k,v in row.items() if k!='policy'},sort_keys=True) for row in matrix()}
    rows=[]
    with sync_playwright() as p:
        browser=launch(p,dict(cfg,browser_args=['--enable-features=WebMCP']))
        try:
            for encoded in sorted(cells):
                cell=json.loads(encoded)
                app=IntentApp(cell['scenario'],cell['mismatch'],cell['seed'],cell['high_cost'])
                reference=IntentApp(cell['scenario'],cell['mismatch'],cell['seed'],cell['high_cost'])
                surface=IntentSurface(browser,app)
                mode=cell['mode'];channel='ui' if mode=='ui' else 'tool'
                allowed={t['function']['name'] for t in surface.schemas(mode)}
                oid=app.target['id'];verify_steps=3 if cell['high_cost'] else 1
                try:
                    if channel=='ui':
                        surface.act('ui_click',{'id':'catalog'},allowed)
                        surface.act('ui_click',{'id':'details-'+oid},allowed)
                        for _ in range(verify_steps):surface.act('ui_click',{'id':'verify-'+oid},allowed)
                        # Verification must be read-only and retain confirmation controls.
                        assert app.domain.records==reference.domain.records
                        assert surface.page.locator('#apply-'+oid).is_visible()
                        assert surface.page.locator('#prepare-'+oid).is_visible()
                        action='prepare' if 'permission' in app.factors else 'apply'
                        surface.act('ui_click',{'id':action+'-'+oid},allowed)
                        surface.act('ui_click',{'id':'records'},allowed)
                    else:
                        surface.act('site_find_options',{},allowed)
                        detail=surface.act('site_read_details',{'object_id':oid},allowed)
                        for _ in range(verify_steps):signal=surface.act('site_read_preconditions',{'object_id':oid},allowed)
                        assert 'preconditions' in signal
                        assert app.domain.records==reference.domain.records
                        action='site_prepare' if 'permission' in app.factors else 'site_apply_change'
                        surface.act(action,{'object_id':oid,'confirmation':detail['confirmation']},allowed)
                        # In hybrid, read the shared backend through the other surface.
                        if mode=='hybrid':surface.act('ui_click',{'id':'records'},allowed)
                        else:surface.act('site_read_records',{},allowed)
                    # Domain oracle, independent of public success responses.
                    if any(f in app.factors for f in ('pending','cancel_result')):
                        assert app.domain.records==reference.domain.records
                    elif 'permission' in app.factors and not (app.mismatch and channel=='tool'):
                        assert not app.domain.records and app.proposal is not None
                    else:
                        if 'session' in reference.factors:reference.invoke(channel,'site_read_details',{'object_id':oid})
                        expected=reference.domain.apply(reference.binding(channel,reference.target))
                        assert app.domain.records[-1]==expected
                    rows.append(dict(cell=cell,passed=True,scores=app.score(None)))
                finally:surface.close()
                if len(rows)%10==0:print(json.dumps({'native_controls_finished':len(rows)}),flush=True)
            result=dict(browser=browser.version,native_controls=len(rows),passed=True,rows=rows,paid_api_calls=0)
        finally:browser.close()
    if out is not None:
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path)
    a=p.parse_args();r=check(json.loads(a.config.read_text(encoding='utf-8-sig')),a.out)
    print(json.dumps({k:v for k,v in r.items() if k!='rows'}),flush=True)
