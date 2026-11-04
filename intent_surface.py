"""Native WebMCP/UI surface for all extended scenarios; no fallback."""
from __future__ import annotations

import re

from rq1_runner import Surface


class IntentSurface(Surface):
    def schemas(self,mode: str) -> list[dict]:
        schemas=super().schemas(mode)
        for entry in schemas:
            t=entry['function']
            if t['name']=='finish':
                t['parameters']['properties']['object']['description']='Exact selected option ID, not the order/reservation/account ID.'
                t['parameters']['properties']['id']['description']='Exact resulting backend record ID if a record exists.'
            elif t['name']=='ui_click':
                t['description']+=' Verification and preparation buttons are available on full-details pages.'
        return schemas

    def act(self,name: str,args: dict,allowed: set[str]) -> dict:
        if name=='ui_click' and name in allowed:
            identifier=args.get('id','')
            if isinstance(identifier,str) and re.fullmatch(r'(?:verify|prepare)-[0-9a-f]{8}',identifier):
                button=self.page.locator('button[id="'+identifier+'"]')
                if button.count()!=1 or not button.is_visible():return {'error':'Button is not currently visible'}
                button.click();self.page.wait_for_function('window.ready === true')
                return {'text':self.page.locator('body').inner_text(),
                        'buttons':self.page.locator('button').evaluate_all('(bs)=>bs.map(b=>({id:b.id,text:b.innerText}))')}
        return super().act(name,args,allowed)
