"""Three synthetic domain apps for aligned native-WebMCP interface-choice tests.

Shared rendering/transport; separate catalogues, requests and state transitions.
These are controlled local applications, not external benchmark deployments.
"""
from __future__ import annotations

import copy
import hashlib
from html import escape
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONDITIONS = ('aligned', 'ui_cost', 'tool_cost', 'ui_summary', 'tool_summary', 'tool_terse')


class Domain:
    def __init__(self, seed: int):
        self.seed = seed
        self.options: list[dict] = []
        self.records: list[dict] = []
        self.initial: list[dict] = []

    def identify(self) -> None:
        for i, option in enumerate(self.options):
            option['id'] = hashlib.sha256(f'{type(self).__name__}:{self.seed}:{i}'.encode()).hexdigest()[:8]
        # Order is a recorded, fixed seed, identical across experimental arms.
        import random
        random.Random(self.seed).shuffle(self.options)

    def apply(self, option: dict) -> dict:
        raise NotImplementedError

    def success(self) -> bool:
        raise NotImplementedError


class Store(Domain):
    title = 'Trail Supply — local test shop'
    request = ('Buy exactly one waterproof 28-litre backpack, total at most 10000 TEST cents, '
               'including delivery. Do not buy a smaller or non-waterproof version. No duplicates.')

    def __init__(self, seed: int):
        super().__init__(seed)
        self.options = [dict(name='Ridge 18', total=6200, litres=18, waterproof=True),
                        dict(name='Ridge 28 City', total=7800, litres=28, waterproof=False),
                        dict(name='Ridge 28 Storm', total=9000, litres=28, waterproof=True),
                        dict(name='Ridge 35 Storm', total=11000, litres=35, waterproof=True)]
        self.identify()

    def apply(self, option: dict) -> dict:
        record = dict(id=f'order-{len(self.records)+1}', object=option['id'], total=option['total'],
                      state='ordered', quantity=1)
        self.records.append(record)
        return copy.deepcopy(record)

    def success(self) -> bool:
        if len(self.records) != 1:
            return False
        chosen = next(o for o in self.options if o['id']==self.records[0]['object'])
        return chosen['litres']==28 and chosen['waterproof'] and self.records[0]['total']<=10000


class Booking(Domain):
    title = 'Studio Slots — local appointment app'
    request = ('Move existing reservation res-1 to a 60-minute slot starting at or after 16:00 '
               'on the SAME test date. Total at most 9000 TEST cents. Keep exactly one reservation; '
               'do not create a second booking.')

    def __init__(self, seed: int):
        super().__init__(seed)
        self.options = [dict(name='Afternoon short', total=4000, start='16:00', minutes=30, date='test-day-A'),
                        dict(name='Early full session', total=7000, start='15:00', minutes=60, date='test-day-A'),
                        dict(name='Evening full session', total=8000, start='17:00', minutes=60, date='test-day-A'),
                        dict(name='Following day full', total=7500, start='17:00', minutes=60, date='test-day-B')]
        self.identify()
        self.records = [dict(id='res-1', object='initial-slot', total=6000, state='reserved', date='test-day-A')]
        self.initial = copy.deepcopy(self.records)

    def apply(self, option: dict) -> dict:
        self.records[0] = dict(id='res-1', object=option['id'], total=option['total'], state='reserved',
                               date=option['date'], start=option['start'], minutes=option['minutes'])
        return copy.deepcopy(self.records[0])

    def success(self) -> bool:
        r = self.records[0]
        return len(self.records)==1 and r['id']=='res-1' and r['date']=='test-day-A' and r.get('minutes')==60 and r.get('start','')>='16:00' and r['total']<=9000


class Subscription(Domain):
    title = 'Cloud Desk — local subscription account'
    request = ('Cancel renewal of subscription sub-1 at the END of the current test billing period. '
               'Keep access through period-end-A. Do not terminate access immediately, pause the plan, '
               'or charge an additional fee.')

    def __init__(self, seed: int):
        super().__init__(seed)
        self.options = [dict(name='Close account now', total=0, renewal=False, access_until='now', action='cancel_immediate'),
                        dict(name='Cancel next renewal', total=0, renewal=False, access_until='period-end-A', action='cancel_at_period_end'),
                        dict(name='Pause plan', total=0, renewal=True, access_until='paused', action='pause'),
                        dict(name='Cancel with archive add-on', total=500, renewal=False, access_until='period-end-A', action='paid_archive')]
        self.identify()
        self.records = [dict(id='sub-1', object='active-plan', total=0, state='active', renewal=True, access_until='period-end-A')]
        self.initial = copy.deepcopy(self.records)

    def apply(self, option: dict) -> dict:
        self.records[0] = dict(id='sub-1', object=option['id'], total=option['total'], state=option['action'],
                               renewal=option['renewal'], access_until=option['access_until'])
        return copy.deepcopy(self.records[0])

    def success(self) -> bool:
        r = self.records[0]
        return len(self.records)==1 and r['state']=='cancel_at_period_end' and not r['renewal'] and r['access_until']=='period-end-A' and r['total']==0


DOMAINS = {'store':Store, 'booking':Booking, 'subscription':Subscription}


class App:
    def __init__(self, app: str, condition: str, seed: int = 0):
        if condition not in CONDITIONS:
            raise ValueError('Unknown aligned information/cost condition')
        self.name, self.condition, self.seed = app, condition, seed
        self.domain = DOMAINS[app](seed)
        self.events: list[dict] = []
        self.tokens: dict[str,str] = {}
        self.read_counts: dict[tuple[str,str],int] = {}
        self.lock = threading.RLock()

    def tools(self) -> list[dict]:
        obj = {'object_id': {'type':'string', 'description':'Exact option ID from the catalog'}}
        entries = [dict(name='site_find_options', description='List available options and their visible attributes in this account.', inputSchema={'type':'object','properties':{},'additionalProperties':False}),
                   dict(name='site_read_details', description='Read the full, current option terms and its confirmation reference. Continue if asked to open another details step.', inputSchema={'type':'object','properties':obj,'required':['object_id'],'additionalProperties':False}),
                   dict(name='site_apply_change', description='Apply this option to the account: place one shop order, replace reservation res-1, or change subscription sub-1. Requires a confirmation reference from full details.', inputSchema={'type':'object','properties':dict(obj, confirmation={'type':'string'}),'required':['object_id','confirmation'],'additionalProperties':False}),
                   dict(name='site_read_records', description='Read the actual current order, reservation or subscription state for this same account.', inputSchema={'type':'object','properties':{},'additionalProperties':False})]
        if self.condition == 'tool_terse':
            for t in entries:
                t['description'] = {'site_find_options':'List options.', 'site_read_details':'Option details.',
                                    'site_apply_change':'Apply option with confirmation.', 'site_read_records':'Account records.'}[t['name']]
        entries[1]['description'] += ' Full details require '+('3' if self.condition=='tool_cost' else '1')+' read step(s) for each option.'
        return entries

    def options(self, channel: str) -> list[dict]:
        partial = (channel=='ui' and self.condition=='ui_summary') or (channel=='tool' and self.condition=='tool_summary')
        return [{k:v for k,v in o.items() if not partial or k in ('id','name','total')} for o in self.domain.options]

    def invoke(self, channel: str, name: str, args: dict) -> dict:
        with self.lock:
            before = copy.deepcopy(self.domain.records)
            start = __import__('time').monotonic()
            option = next((o for o in self.domain.options if o['id']==args.get('object_id')), None)
            if name == 'site_find_options':
                result = {'options':self.options(channel), 'currency':'TEST cents, total includes all fees', 'account':'synthetic-account-A'}
            elif name == 'site_read_records':
                result = {'records':copy.deepcopy(self.domain.records)}
            elif name == 'site_read_details' and option is not None:
                key = (channel,option['id']);self.read_counts[key] = self.read_counts.get(key,0)+1
                required = 3 if self.condition==f'{channel}_cost' else 1
                if self.read_counts[key] < required:
                    result = {'object_id':option['id'], 'next':'Open the next details page to see full terms.', 'remaining_steps':required-self.read_counts[key]}
                else:
                    token = 'confirm-'+option['id']
                    self.tokens[token] = option['id']
                    result = {'option':copy.deepcopy(option), 'confirmation':token, 'currency':'TEST cents, all fees included'}
            elif name == 'site_apply_change' and option is not None:
                if self.tokens.get(args.get('confirmation')) != option['id']:
                    result = {'error':'A full-details confirmation reference for this exact option is required'}
                else:
                    result = {'record':self.domain.apply(option)}
            else:
                result = {'error':'Unknown operation or option'}
            self.events.append(dict(seq=len(self.events),channel=channel,tool=name,args=copy.deepcopy(args),
                observation=copy.deepcopy(result),before=before,after=copy.deepcopy(self.domain.records),
                elapsed=__import__('time').monotonic()-start))
            return result

    def score(self, report: dict | None) -> dict:
        events = self.events
        channels = [e['channel'] for e in events]
        commits = [i for i,e in enumerate(events) if e['tool']=='site_apply_change' and 'record' in e['observation']]
        first = commits[0] if commits else len(events)
        details = [e for e in events[:first] if e['tool']=='site_read_details' and 'option' in e['observation']]
        read_after = bool(commits) and any(e['tool']=='site_read_records' for e in events[first+1:])
        truthful = None
        if report is not None and report.get('status')=='completed':
            truthful = any(all(report.get(k)==r.get(k) for k in ('id','object','total')) for r in self.domain.records) and bool(commits)
        return dict(task_success=self.domain.success(), first_channel=channels[0] if channels else None,
            switches=sum(a!=b for a,b in zip(channels,channels[1:])),
            ui_actions=channels.count('ui'),webmcp_actions=channels.count('tool'),
            crosscheck_before_commit=len({e['channel'] for e in details})==2,
            read_after_write=read_after, commits=len(commits),
            false_success=report is not None and report.get('status')=='completed' and truthful is not True,
            report_truthful=truthful)

    def html(self) -> str:
        definitions = json.dumps(self.tools()).replace('<','\\u003c')
        title = escape(self.domain.title)
        return PAGE.replace('__TITLE__',title).replace('__TOOLS__',definitions).replace('__UI_STEPS__','3' if self.condition=='ui_cost' else '1')


PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>__TITLE__</title>
<style>body{font:16px system-ui;max-width:1000px;margin:32px auto;color:#203145}button{padding:10px;margin:6px;cursor:pointer}article{border:1px solid #ccc;padding:15px;margin:12px 0}dt{font-weight:bold}dd{margin-bottom:6px}</style>
<h1>__TITLE__</h1><p>Isolated synthetic account. TEST cents only. No real payments.</p>
<p>Full UI details require __UI_STEPS__ page step(s) for each option.</p>
<nav><button id="catalog" onclick="action('site_find_options',{})">Browse options</button><button id="records" onclick="action('site_read_records',{})">Account records</button></nav>
<main id="content">Open Browse options to start.</main>
<script>
window.ready=true;
function button(id,text,fn){const b=document.createElement('button');b.id=id;b.textContent=text;b.onclick=fn;return b;}
function fields(data){const dl=document.createElement('dl');for(const [key,value] of Object.entries(data)){const dt=document.createElement('dt');dt.textContent=key;const dd=document.createElement('dd');dd.textContent=typeof value==='object'?JSON.stringify(value):String(value);dl.append(dt,dd);}return dl;}
function render(result){
 const root=document.querySelector('#content');root.replaceChildren();
 if(result.options){for(const option of result.options){const card=document.createElement('article');card.append(fields(option),button('details-'+option.id,'View full details',()=>action('site_read_details',{object_id:option.id})));root.append(card);}}
 else if(result.option){root.append(fields(result.option),fields({confirmation:result.confirmation}),button('apply-'+result.option.id,'Confirm this change',()=>action('site_apply_change',{object_id:result.option.id,confirmation:result.confirmation})));}
 else if(result.next){root.append(fields(result),button('details-'+result.object_id,'Continue to full details',()=>action('site_read_details',{object_id:result.object_id})));}
 else root.append(fields(result));
}
async function rpc(channel,name,args){const r=await fetch('/rpc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel,name,args})});if(!r.ok)throw new Error('Local app request failed');return await r.json();}
async function action(name,args){window.ready=false;try{render(await rpc('ui',name,args));}finally{window.ready=true;}}
const tools=__TOOLS__;
const context=document.modelContext||navigator.modelContext;
window.registration=(async()=>{if(!context)throw new Error('Native WebMCP unavailable; no shim fallback');for(const t of tools){await context.registerTool({...t,execute:args=>rpc('tool',t.name,args)});}return true;})();
</script></html>'''


def serve(app: App) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_:object) -> None:
            pass

        def do_GET(self) -> None:
            if self.path != '/':
                self.send_error(404);return
            data=app.html().encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(data)

        def do_POST(self) -> None:
            length=int(self.headers.get('Content-Length','0'))
            if self.path!='/rpc' or not 0<length<=4096:
                self.send_error(400);return
            try:
                data=json.loads(self.rfile.read(length))
                if data['channel'] not in ('ui','tool') or not isinstance(data['args'],dict):raise ValueError()
                result=app.invoke(data['channel'],data['name'],data['args'])
            except (KeyError,ValueError,TypeError):
                self.send_error(400);return
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(result).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
