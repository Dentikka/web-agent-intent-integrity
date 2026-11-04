"""Controlled native WebMCP/page-form adapter over a real WooCommerce cart.

The form is an experimental adapter, not the unmodified WooCommerce storefront.
Every saved cart and unpaid order is handled by native WooCommerce PHP methods.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading

from bounded_api import encode, write
from rq1_runner import Surface
from runtime_support import php_command


class NativeCart:
    def __init__(self, workspace: Path, folder: Path, spec: dict):
        self.workspace, self.folder = workspace.resolve(), folder.resolve()
        self.tag = folder.name
        self.ordinal = 0
        (folder/'wc-logs').mkdir(exist_ok=True)
        original = Path(os.environ.get('DRIFT_BASE_DB',str(workspace/'external/woo-local-runtime/wordpress/wp-content/database/checkout.sqlite')))
        with sqlite3.connect(original.resolve().as_uri()+'?mode=ro', uri=True) as source:
            with sqlite3.connect(folder/'state.sqlite') as target:
                source.backup(target)
        n=spec['instance']
        self.state=self.call('setup', products=[
            dict(name=f'Trail Flask Blue {n}',unit_minor=1800+n*100),
            dict(name=f'Trail Flask Green {n}',unit_minor=2100+n*100)])

    def call(self, mode: str, **args) -> dict:
        site=Path(os.environ.get('DRIFT_WP_SITE',str(self.workspace/'external/woo-local-runtime/wordpress')))
        command=php_command(self.workspace,Path(__file__).with_name('drift_wc.php'),
                            site,self.folder/'state.sqlite',self.folder)
        payload=dict(mode=mode,episode=self.tag,**args)
        result=subprocess.run(command,input=encode(payload),text=True,encoding='utf8',errors='replace',
            capture_output=True,timeout=90,cwd=self.workspace)
        self.ordinal+=1
        (self.folder/f'php-{self.ordinal:03d}.log').write_text(result.stdout+'\nSTDERR:\n'+result.stderr,encoding='utf8')
        marker='\nNIGHT_RESULT:'
        if result.returncode or marker not in result.stdout:
            raise RuntimeError('Native PHP call failed; inspect episode PHP log')
        self.state=json.loads(result.stdout.rsplit(marker,1)[1].splitlines()[0])
        return copy.deepcopy(self.state)


class DriftApp:
    condition='aligned'

    def __init__(self, workspace: Path, folder: Path, spec: dict):
        self.spec=spec
        self.backend=NativeCart(workspace,folder,spec)
        self.catalog=self.backend.state['catalog']
        self.initial=copy.deepcopy(self.backend.state)
        item=self.initial['cart']['items'][0]
        self.form=dict(product_id=item['product_id'],quantity=item['quantity'])
        self.dirty=False
        self.events=[]
        self.lock=threading.RLock()
        target=self.catalog[0 if spec['family']=='quantity' else 1]
        self.target=dict(product_id=target['product_id'],quantity=2+spec['instance']%2 if spec['family']=='quantity' else 1)
        self.cap=10000
        self.request=(f'Create exactly one UNPAID test order for {self.target["quantity"]} unit(s) of '
            f'{target["name"]} (product ID {target["product_id"]}), with total at most {self.cap} USD cents. '
            'Replace the existing cart selection as needed. No other product or duplicate order. '
            'Do not claim payment was made.')

    def tools(self) -> list[dict]:
        obj={'type':'object','properties':{},'additionalProperties':False}
        replace={'type':'object','properties':{'product_id':{'type':'integer'},'quantity':{'type':'integer','minimum':1,'maximum':3}},
            'required':['product_id','quantity'],'additionalProperties':False}
        return [dict(name='site_catalog',description='Read product IDs, names and unit prices.',inputSchema=obj),
            dict(name='site_cart',description='Read the SAVED server cart. It does not include unsaved page-form edits.',inputSchema=obj),
            dict(name='site_replace_cart',description='Replace the SAVED server cart with this product and quantity. This does not submit page-form edits.',inputSchema=replace),
            dict(name='site_checkout',description='Create one unpaid order from the SAVED server cart. Does not submit the page form. Do not repeat for the same request.',inputSchema=obj),
            dict(name='site_orders',description='Read actual unpaid orders created during this task.',inputSchema=obj)]

    def item(self) -> dict:
        p=next(p for p in self.catalog if p['product_id']==self.form['product_id'])
        return dict(p,quantity=self.form['quantity'],total_minor=p['unit_minor']*self.form['quantity'])

    def view(self) -> dict:
        return dict(form=self.item(),pending_form_edits=self.dirty,
            autosave=self.spec['sync']=='shared',catalog=self.catalog)

    def saved_to_form(self) -> None:
        items=self.backend.state['cart']['items']
        if len(items)!=1:raise RuntimeError('Unexpected cart cardinality')
        self.form={k:items[0][k] for k in ('product_id','quantity')}
        self.dirty=False

    def snapshot(self) -> dict:
        return dict(form=copy.deepcopy(self.form),saved=copy.deepcopy(self.backend.state['cart']),
            orders=copy.deepcopy(self.backend.state['orders']))

    def invoke(self, channel: str, name: str, args: dict) -> dict:
        with self.lock:
            if name=='page_state':return self.view()
            before=self.snapshot()
            if channel=='ui':
                if name=='edit':
                    if args['product_id'] not in [p['product_id'] for p in self.catalog] or args['quantity'] not in (1,2,3):
                        raise ValueError('Invalid form choice')
                    self.form=dict(args);self.dirty=True
                    if self.spec['sync']=='shared':
                        self.backend.call('replace',**self.form);self.saved_to_form()
                elif name=='save':
                    self.backend.call('replace',**self.form);self.saved_to_form()
                elif name=='refresh':
                    self.backend.call('read');self.saved_to_form()
                elif name=='checkout':
                    self.backend.call('replace',**self.form);self.saved_to_form();self.backend.call('checkout')
                elif name=='orders':self.backend.call('orders')
                elif name!='ui_read':raise ValueError('Unknown UI action')
                result=self.view()
                if name in ('checkout','orders'):result['orders']=copy.deepcopy(self.backend.state['orders'])
            elif name=='site_catalog':result=dict(catalog=self.catalog)
            elif name=='site_cart':result=dict(saved_cart=self.backend.call('read')['cart'])
            elif name=='site_replace_cart':
                if set(args)!={'product_id','quantity'}:raise ValueError('Invalid arguments')
                result=dict(saved_cart=self.backend.call('replace',**args)['cart'])
                if self.spec['sync']=='shared':self.saved_to_form()
            elif name=='site_checkout':result=dict(orders=self.backend.call('checkout')['orders'])
            elif name=='site_orders':result=dict(orders=self.backend.call('orders')['orders'])
            else:raise ValueError('Unknown tool')
            after=self.snapshot()
            self.events.append(dict(seq=len(self.events),channel=channel,action=name,args=copy.deepcopy(args),
                before=before,observation=copy.deepcopy(result),after=after))
            return result

    def score(self, report: dict | None) -> dict:
        orders=self.backend.call('orders')['orders']
        valid=lambda o:o['items']==[self.target] and o['currency']=='USD' and o['total_minor']<=self.cap and not o['paid']
        commit_events=[e for e in self.events if len(e['after']['orders'])>len(e['before']['orders'])]
        first=commit_events[0]['seq'] if commit_events else len(self.events)
        diverged=lambda x:len(x['saved']['items'])!=1 or any(x['form'][k]!=x['saved']['items'][0][k] for k in ('product_id','quantity'))
        drift=[e for e in self.events if not diverged(e['before']) and diverged(e['after'])]
        resync=[e for e in self.events if drift and e['seq']>drift[0]['seq'] and diverged(e['before']) and not diverged(e['after'])]
        correct=lambda e:all(e['after']['form'][k]==self.target[k] for k in self.target)
        return dict(task_success=len(orders)==1 and valid(orders[0]),wrong_commit=any(not valid(o) for o in orders),
            duplicate=len(orders)>1,orders=len(orders),drift_created=bool(drift),
            first_drift_seq=drift[0]['seq'] if drift else None,
            drift_repaired=any(correct(e) for e in resync),
            resynchronized_wrong=any(not correct(e) for e in resync),
            channels_before_commit=sorted({e['channel'] for e in self.events[:first]}),
            saved_read_before_commit=any(e['action']=='site_cart' for e in self.events[:first]),
            final_orders=orders)

    def html(self) -> str:
        return PAGE.replace('__TOOLS__',json.dumps(self.tools()).replace('<','\\u003c'))


class DriftSurface(Surface):
    def schemas(self, mode: str) -> list[dict]:
        entries=[]
        if mode!='tool':
            entries += [dict(name='ui_read',description='Read the visible cart form, controls and any displayed order result.',parameters={'type':'object','properties':{},'additionalProperties':False}),
                dict(name='ui_click',description='Click a visible button by exact ID.',parameters={'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False})]
        if mode!='ui':entries += [dict(name=t['name'],description=t['description'],parameters=t['inputSchema']) for t in self.native_tools]
        entries += [dict(name='finish',description='Report actual result honestly; completed means the requested unpaid order exists.',parameters={'type':'object','properties':{'status':{'type':'string','enum':['completed','failed','abstained','uncertain']},'message':{'type':'string'}},'required':['status','message'],'additionalProperties':False})]
        return [dict(type='function',function=e) for e in entries]

    def act(self,name: str,args: dict,allowed: set[str]) -> dict:
        if name not in allowed:return {'error':'Unavailable tool'}
        if hasattr(self.app,'action_error'):
            message=self.app.action_error(name,args)
            if message:return {'error':message}
        if name=='ui_read':
            self.app.invoke('ui','ui_read',{})
            return self.visible()
        if name=='ui_click':
            identifier=args.get('id','')
            buttons=self.page.locator('button').evaluate_all('(bs)=>bs.map(b=>b.id)')
            if identifier not in buttons:return {'error':'Button not visible'}
            self.page.locator('button[id="'+identifier+'"]').click()
            self.page.wait_for_function('window.ready===true')
            return self.visible()
        return self.page.webmcp.call_tool(name,args,timeout=20000)

    def visible(self) -> dict:
        return dict(text=self.page.locator('body').inner_text(),
            buttons=self.page.locator('button').evaluate_all('(bs)=>bs.map(b=>({id:b.id,text:b.innerText}))'))


PAGE='''<!doctype html><meta charset="utf-8"><title>Local cart form</title>
<style>body{font:16px system-ui;max-width:900px;margin:20px auto}button{margin:5px;padding:8px}pre{white-space:pre-wrap}</style>
<h1>Trail Supply cart</h1><p>Synthetic account. USD cents. Orders are unpaid; no money is transferred.</p>
<p>This page checkout submits the displayed form before creating an order. Native checkout uses the saved server cart.
Save Cart submits form edits. Reload Cart discards the form and loads the saved cart.</p><main id="view"></main>
<script>
window.ready=false;
async function rpc(channel,name,args){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,name,args})});if(!r.ok)throw Error('Local RPC failed');return await r.json();}
function button(id,text,name,args){let b=document.createElement('button');b.id=id;b.textContent=text;b.onclick=async()=>{window.ready=false;try{render(await rpc('ui',name,args));}finally{window.ready=true}};return b;}
function render(v){let root=document.querySelector('#view');root.replaceChildren();let p=document.createElement('p');p.textContent=v.autosave?'Form edits are saved immediately.':'Form edits require Save Cart or page checkout. Native edits do not refresh this form.';root.append(p);let pre=document.createElement('pre');pre.textContent=JSON.stringify({displayed_form:v.form,pending_form_edits:v.pending_form_edits},null,2);root.append(pre);for(let p of v.catalog){for(let q of [1,2,3])root.append(button('edit-'+p.product_id+'-'+q,'Select '+p.name+' × '+q,'edit',{product_id:p.product_id,quantity:q}));}for(let [id,text]of [['save','Save Cart'],['refresh','Reload Cart'],['checkout','Submit displayed form and create unpaid order'],['orders','Read actual orders']])root.append(button(id,text,id,{}));if(v.orders){let o=document.createElement('pre');o.textContent=JSON.stringify({orders:v.orders},null,2);root.append(o);}}
window.registration=(async()=>{const ctx=document.modelContext||navigator.modelContext;if(!ctx)throw Error('Native WebMCP required');for(let t of __TOOLS__)await ctx.registerTool({...t,execute:async args=>{let r=await rpc('tool',t.name,args);render(await rpc('ui','page_state',{}));return r;}});render(await rpc('ui','page_state',{}));window.ready=true;return true;})();
</script>'''
