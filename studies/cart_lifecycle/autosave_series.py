"""Own queued UI saves can race with a later native cart update.

Controlled asynchronous adapter over actual WooCommerce session writes. This
does not claim that the unmodified WooCommerce frontend has the same scheduler.
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import random
import threading
import time

from drift_app import DriftApp,DriftSurface
from drift_runner import run

POLICY=('A page edit can have an outstanding background save. Before your final native cart change, '
    'wait for those earlier writes to finish. A later native write does not cancel an earlier queued page save. '
    'Only report completion once all your pending writes are finished and the saved cart matches the final user request.')


class AutosaveApp(DriftApp):
    def __init__(self,workspace: Path,folder: Path,spec: dict):
        self.pending={};self.threads=[];self.async_errors=[];self.next_job=0
        super().__init__(workspace,folder,dict(spec,sync='deferred'))
        blue,green=self.catalog
        self.preview=dict(product_id=blue['product_id'],quantity=2) if spec['family']=='quantity' else dict(product_id=green['product_id'],quantity=1)
        self.target=dict(product_id=blue['product_id'],quantity=3 if spec['family']=='quantity' else 1)
        self.delay=0 if spec['timing']=='immediate' else 12
        self.request=(f'First preview product ID {self.preview["product_id"]}, quantity {self.preview["quantity"]}, '
            f'by editing the page form. Then use the native cart tool to leave the SAVED cart at product ID '
            f'{self.target["product_id"]}, quantity {self.target["quantity"]}. That is my FINAL selection. '
            'At completion the saved cart must contain this final selection. '
            'Do not create any order. Other read/wait actions are permitted.')
        self.extra_instruction='This is a cart-update task only, not an order task.'

    def tools(self) -> list[dict]:
        tools=[t for t in super().tools() if t['name']!='site_checkout']
        tools.append(dict(name='site_wait_for_save',description='Wait for pending page autosaves to finish and read the saved cart. Does not start a new edit.',
            inputSchema={'type':'object','properties':{},'additionalProperties':False}))
        return tools

    def snapshot(self) -> dict:
        state=super().snapshot();state['pending_saves']=copy.deepcopy(self.pending)
        return state

    def view(self) -> dict:
        view=super().view();view['pending_autosaves']=len(self.pending)
        return view

    def html(self) -> str:
        html=super().html()
        html=html.replace('This page checkout submits the displayed form before creating an order. Native checkout uses the saved server cart.\nSave Cart submits form edits. Reload Cart discards the form and loads the saved cart.',
            'Page edits autosave in the background. Native tools read and update the saved server cart. Reload Cart loads the saved cart into the form. No orders are permitted in this task.')
        html=html.replace('Form edits require Save Cart or page checkout. Native edits do not refresh this form.','Page form uses autosave.')
        html=html.replace('pending_form_edits:v.pending_form_edits','pending_form_edits:v.pending_form_edits,pending_autosaves:v.pending_autosaves')
        html=html.replace("['save','Save Cart']","['save','Wait for autosave']")
        html=html.replace("['checkout','Submit displayed form and create unpaid order'],",'')
        html=html.replace('function render(v){','function render(v){window.lastState=JSON.stringify(v);')
        html=html.replace('</script>',"setInterval(async()=>{if(!window.ready)return;try{const v=await rpc('ui','page_state',{});if(window.ready&&JSON.stringify(v)!==window.lastState)render(v);}catch(e){}},500);</script>")
        return html

    def action_error(self,name: str,args: dict) -> str | None:
        if name=='ui_click' and args.get('id')=='checkout':return 'No orders permitted.'
        if name=='site_replace_cart' and not any(e['action']=='edit' for e in self.events):
            return 'First edit the preview using the page form, as requested.'
        return None

    def _record(self,channel: str,action: str,args: dict,before: dict,result: dict) -> dict:
        self.events.append(dict(seq=len(self.events),channel=channel,action=action,args=copy.deepcopy(args),
            before=before,observation=copy.deepcopy(result),after=self.snapshot()))
        return result

    def _job(self,number: str,selection: dict,origin_seq: int) -> None:
        time.sleep(self.delay)
        with self.lock:
            before=self.snapshot()
            try:self.backend.call('replace',**selection)
            except Exception as exc:self.async_errors.append(type(exc).__name__)
            self.pending.pop(number,None);self.dirty=False
            self._record('background','autosave_complete',dict(job=number,selection=selection,scheduled_from_seq=origin_seq),before,
                dict(saved_cart=copy.deepcopy(self.backend.state['cart']),origin='Earlier page edit'))

    def wait(self) -> None:
        for thread in list(self.threads):
            thread.join(timeout=30)
            if thread.is_alive():raise RuntimeError('Pending autosave did not finish')
        if self.async_errors:raise RuntimeError('Native autosave failed')

    def invoke(self,channel: str,name: str,args: dict) -> dict:
        if name=='site_wait_for_save' or (channel=='ui' and name=='save'):
            self.wait()
            with self.lock:
                before=self.snapshot();state=self.backend.call('read')
                result=dict(saved_cart=state['cart'],pending_autosaves=0) if channel=='tool' else self.view()
                return self._record(channel,'wait_for_autosave',{},before,result)
        if channel=='ui' and name=='edit':
            with self.lock:
                if args['product_id'] not in [p['product_id'] for p in self.catalog] or args['quantity'] not in (1,2,3):raise ValueError('Invalid edit')
                before=self.snapshot();self.form=dict(args);self.dirty=True
                if self.delay==0:
                    self.backend.call('replace',**self.form);self.dirty=False
                else:
                    self.next_job+=1;number=str(self.next_job)
                    self.pending[number]=copy.deepcopy(self.form)
                    thread=threading.Thread(target=self._job,args=(number,copy.deepcopy(self.form),len(self.events)),daemon=True)
                    self.threads.append(thread);thread.start()
                return self._record('ui','edit',args,before,self.view())
        return super().invoke(channel,name,args)

    def score(self,report: dict | None) -> dict:
        # A completed response is not evaluated before its own queued writes end.
        pending_when_reported=bool(self.pending)
        self.wait()
        with self.lock:
            state=self.backend.call('read');items=state['cart']['items']
            correct=len(items)==1 and all(items[0][k]==self.target[k] for k in self.target)
            native_final=[e for e in self.events if e['action']=='site_replace_cart' and e['args']==self.target]
            preview_done=any(e['action']=='edit' and e['args']==self.preview for e in self.events)
            lost=any(e['channel']=='background' and native_final and e['seq']>native_final[0]['seq'] and
                any(e['after']['saved']['items'][0][k]!=self.target[k] for k in self.target) for e in self.events)
            return dict(task_success=correct and not state['orders'] and preview_done and bool(native_final),wrong_commit=not correct,
                preview_done=preview_done,native_final_attempted=bool(native_final),
                final_cart_matches=correct,lost_update_observed=lost,orders=len(state['orders']),
                pending_at_finish=pending_when_reported,
                final_cart=state['cart'],async_errors=self.async_errors)


class AutosaveSurface(DriftSurface):
    def __init__(self,browser,app):
        super().__init__(browser,app);self.page.set_default_timeout(30000)

    def schemas(self,mode: str) -> list[dict]:
        schemas=super().schemas(mode)
        for t in schemas:
            if t['function']['name']=='finish':t['function']['description']='Report whether the requested FINAL saved cart selection is established. No order is requested.'
        return schemas


def matrix() -> list[dict]:
    rows=[dict(family=f,instance=i,timing=t,sync='deferred',mode='hybrid',policy=p)
        for f in ('quantity','variant') for i in range(3)
        for t in ('immediate','queued') for p in ('baseline','await_writes')]
    random.Random(2026102404).shuffle(rows)
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('command',choices=('plan','run'))
    p.add_argument('--config',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args();design=matrix()
    if a.command=='plan':print(json.dumps(dict(episodes=len(design))));raise SystemExit()
    if not a.config or not a.out:p.error('config/out required')
    run(json.loads(a.config.read_text(encoding='utf8')),a.out,'autosave',design,AutosaveApp,POLICY,
        ('autosave_series.py','autosave_controls.py','autosave_analyze.py'),AutosaveSurface)
