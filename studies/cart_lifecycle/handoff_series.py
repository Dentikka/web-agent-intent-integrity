"""Post-hoc decomposition: genuine handoff exposure and scope disclosure."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random

from drift_app import DriftApp
from drift_runner import run,SYNC_POLICY


class HandoffApp(DriftApp):
    def __init__(self,workspace: Path,folder: Path,spec: dict):
        super().__init__(workspace,folder,spec)
        self.extra_instruction={
            'free':'',
            'ui_tool':'Make your first cart edit through the page controls, and create the order through site_checkout. Read and synchronization actions may use either interface.',
            'tool_ui':'Make your first cart edit through site_replace_cart, and create the order through the page checkout control. Read and synchronization actions may use either interface.'}[spec['handoff']]

    def tools(self) -> list[dict]:
        tools=super().tools()
        if self.spec['disclosure']=='standard':
            descriptions={'site_cart':'Read current cart contents and total.',
                'site_replace_cart':'Replace cart contents with this product and quantity.',
                'site_checkout':'Create one unpaid order from the cart. Avoid duplicate orders.'}
            for tool in tools:
                if tool['name'] in descriptions:tool['description']=descriptions[tool['name']]
        return tools

    def view(self) -> dict:
        v=super().view()
        if self.spec['disclosure']=='standard':v.pop('pending_form_edits')
        return v

    def html(self) -> str:
        html=super().html()
        if self.spec['disclosure']=='standard':
            html=html.replace('This page checkout submits the displayed form before creating an order. Native checkout uses the saved server cart.\nSave Cart submits form edits. Reload Cart discards the form and loads the saved cart.',
                'Select a product and quantity. Save Cart updates the cart; checkout creates one unpaid order.')
            html=html.replace('Form edits are saved immediately.','Cart form.')
            html=html.replace('Form edits require Save Cart or page checkout. Native edits do not refresh this form.','Cart form.')
            html=html.replace('Submit displayed form and create unpaid order','Create unpaid order')
        return html

    def action_error(self,name: str,args: dict) -> str | None:
        route=self.spec['handoff']
        if route=='free':return None
        if name=='site_checkout' and route=='tool_ui':return 'Assigned workflow requires page checkout.'
        if name=='ui_click' and args.get('id')=='checkout' and route=='ui_tool':return 'Assigned workflow requires native site_checkout.'
        edits=any(e['action'] in ('edit','site_replace_cart') for e in self.events)
        if not edits:
            if name=='site_checkout' or (name=='ui_click' and args.get('id')=='checkout'):
                return 'Make the assigned first cart edit before checkout.'
            if name=='site_replace_cart' and route=='ui_tool':return 'Make the first cart edit through the page, as assigned.'
            if name=='ui_click' and str(args.get('id','')).startswith('edit-') and route=='tool_ui':return 'Make the first cart edit through the native tool, as assigned.'
        return None


def matrix() -> list[dict]:
    rows=[dict(family=f,instance=i,sync=s,disclosure=d,handoff=h,mode='hybrid',policy=p)
        for f in ('quantity','variant') for i in range(2) for s in ('shared','deferred')
        for d in ('full','standard') for h in ('free','ui_tool','tool_ui')
        for p in ('baseline','synchronize')]
    random.Random(2026102403).shuffle(rows)
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('command',choices=('plan','run'))
    p.add_argument('--config',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args();design=matrix()
    if a.command=='plan':print(json.dumps(dict(episodes=len(design))));raise SystemExit()
    if not a.config or not a.out:p.error('config and out required')
    run(json.loads(a.config.read_text(encoding='utf8')),a.out,'handoff',design,HandoffApp,SYNC_POLICY,('handoff_series.py','handoff_controls.py'))
