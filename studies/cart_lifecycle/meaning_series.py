"""Truthful cross-interface price scopes, without price/state falsification."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import random

from drift_app import DriftApp
from drift_runner import run

POLICY=('When both interfaces are available, read the displayed form and saved cart before creating an order. '
    'Compare the same product and quantity. Normalize the meaning of each amount (per-item versus cart total); '
    'different numeric amounts with different scopes need not conflict. Enforce the user total budget. '
    'When only one interface is available, use its labelled data. Report the actual result.')


class MeaningApp(DriftApp):
    def __init__(self,workspace: Path,folder: Path,spec: dict):
        super().__init__(workspace,folder,dict(spec,sync='shared',family='quantity'))
        total=self.catalog[0]['unit_minor']*self.target['quantity']
        self.cap=total+500 if spec['feasible'] else total-500
        self.request=self.request.replace('at most 10000 USD cents',f'at most {self.cap} USD cents')

    def scoped(self,channel: str,total: int,quantity: int) -> dict:
        unit=(self.spec['representation']=='ui_unit' and channel=='ui') or (
            self.spec['representation']=='tool_unit' and channel=='tool')
        return dict(price_minor=total//quantity if unit else total,
            price_scope='per_item' if unit else 'cart_total',currency='USD')

    def view(self) -> dict:
        result=super().view();form=result['form']
        total=form.pop('total_minor');form.pop('unit_minor')
        form.update(self.scoped('ui',total,form['quantity']))
        return result

    def invoke(self,channel: str,name: str,args: dict) -> dict:
        result=super().invoke(channel,name,args)
        if channel=='tool' and 'saved_cart' in result:
            cart=result['saved_cart'];quantity=sum(i['quantity'] for i in cart['items'])
            cart.update(self.scoped('tool',cart.pop('total_minor'),quantity))
            for item in cart['items']:item.pop('unit_minor',None)
            # Public observation must match what the actor actually receives.
            self.events[-1]['observation']=copy.deepcopy(result)
        return result


def matrix() -> list[dict]:
    rows=[dict(family='quantity',sync='shared',representation=r,feasible=f,mode=m,policy=p,instance=i)
        for r in ('same_total','ui_unit','tool_unit') for f in (True,False)
        for m,p in (('ui','baseline'),('tool','baseline'),('hybrid','baseline'),('hybrid','reconcile'))
        for i in range(2)]
    random.Random(2026102402).shuffle(rows)
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('command',choices=('plan','run'))
    p.add_argument('--config',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args();design=matrix()
    if a.command=='plan':print(json.dumps(dict(episodes=len(design))));raise SystemExit()
    if not a.config or not a.out:p.error('config/out required')
    run(json.loads(a.config.read_text(encoding='utf8')),a.out,'meaning',design,
        MeaningApp,POLICY,('meaning_series.py','meaning_controls.py','meaning_analyze.py'))
