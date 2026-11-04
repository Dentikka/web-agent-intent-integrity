"""Genuine actor-owned UI writes completing across a later native revision."""
from __future__ import annotations
import argparse,copy,hashlib,json,random,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import strengthen_point3 as s
ART=ROOT/'artifacts/own_writes_v1';DOC=ROOT/'research/own_writes_v1'
MODELS=json.loads((ROOT/'artifacts/point4_realapps/main/plan.json').read_text())['config']['models']
def matrix():
 cs=[]
 for model in MODELS:
  for target in (1,3):
   for policy in ('baseline','await','revision_guard'):
    for timing in ('immediate','queued'):
     for rep in range(6):cs.append(dict(study='actor_owned_ui_writes_v1',app='medusa',model=model['id'],target=target,policy=policy,timing=timing,repeat=rep,delay=(2,3,4,5,6,8)[rep],guard=False,color='White' if rep%2==0 else 'Black',size='M' if rep%3==0 else 'S'))
 random.Random(2026102431).shuffle(cs);assert len(cs)==144;return cs
class Episode:
 def __init__(self,a,c,folder):
  self.a=a;self.c=c;self.folder=folder;self.tick=0;self.pending=None;self.native_revision=0;self.trace=[];self.events=[];self.report=None;self.revised=False;self.native_writes=0;self.initialized=False;self.error=None
 def setup(self):
  for attempt in range(3):
   try:self.a.reset(self.c,self.folder);break
   except Exception as e:
    s.write(self.folder/f'unpaid_setup_{attempt}.json',dict(error=f'{type(e).__name__}: {e}'))
    try:self.a.close()
    except Exception:pass
    if attempt==2:raise
  self.page=self.a.page;self.page.goto(s.p3.env.BASE+'/gb/cart',wait_until='domcontentloaded',timeout=120000);s.p3.wait_tool(self.page,'update_cart')
  self.page.get_by_test_id('product-select-button').wait_for();self.page.wait_for_function("() => { const e=document.querySelector('[data-testid=product-select-button]'); const k=Object.keys(e).find(k=>k.startsWith('__reactProps$')); return k && typeof e[k].onChange==='function'; }")
  self.native=self.a.context.new_page();self.native.goto(s.p3.env.BASE+'/gb/cart',wait_until='domcontentloaded',timeout=120000);s.p3.wait_tool(self.native,'update_cart')
  initial=self.read_saved();self.line=initial['cart']['items'][0]['line_id'];self.variant=initial['cart']['items'][0]['variant'];s.write(self.folder/'initial.json',initial);s.write(self.folder/'setup_oracle.json',self.oracle())
 def read_saved(self):return s.p3.env.unpack(self.native.webmcp.call_tool('view_cart',{},timeout=60000))
 def oracle(self):
  sql=f"SELECT COALESCE(json_agg(json_build_object('id',id,'variant_id',variant_id,'quantity',quantity)), '[]') FROM cart_line_item WHERE cart_id=(SELECT cart_id FROM cart_line_item WHERE id='{self.line}') AND deleted_at IS NULL"
  return dict(items=json.loads(s.p3.env.sql(sql)),orders=self.a.observe())
 def valid(self,state):return len(state['items'])==1 and float(state['items'][0]['quantity'])==self.c['target'] and not state['orders']
 def dispatch(self):
  job=self.pending
  if not job:return
  before=self.oracle();dropped=self.c['policy']=='revision_guard' and self.native_revision>job['intent_revision']
  if not dropped:
   self.page.evaluate("async () => { await window.__researchOwnedUIJob.run(); }")
   deadline=time.monotonic()+30
   while time.monotonic()<deadline:
    if float(self.oracle()['items'][0]['quantity'])==2:break
    time.sleep(.1)
   else:raise RuntimeError('Original UI callback did not persist quantity 2')
  after=self.oracle();overwrite=not dropped and self.native_revision==2 and self.valid(before) and not self.valid(after)
  self.events.append(dict(tick=self.tick,kind='own_ui_job_settled',job=copy.deepcopy(job),dropped_stale=dropped,before=before,after=after,overwrite=overwrite));self.pending=None;s.write(self.folder/'events.json',self.events)
 def advance(self):
  self.tick+=1
  if self.pending and self.tick>=self.pending['due_tick']:self.dispatch()
 def act(self,name,args,turn,callid):
  self.advance();before=self.oracle();out={}
  if name=='ui_edit':
   if self.initialized:out=dict(error='Only the first UI edit was requested; use native edit for the revised instruction.')
   else:
    self.page.evaluate("""() => { const e=document.querySelector('[data-testid=product-select-button]'); const p=e[Object.keys(e).find(k=>k.startsWith('__reactProps$'))]; const h=p.onChange; window.__researchOwnedUIJob={run:()=>h({target:{value:'2'}})}; e.value='2'; }""")
    self.initialized=True;self.pending=dict(id='own-ui-1',quantity=2,intent_revision=1,origin_call_id=callid,origin_model_turn=turn,accepted_tick=self.tick,due_tick=self.tick+(self.c['delay'] if self.c['timing']=='queued' else 0))
    if self.c['timing']=='immediate':self.dispatch()
    out=dict(status='accepted_pending' if self.pending else 'completed',job_id='own-ui-1',ui=self.page.evaluate(s.p3.base.UI_READ))
  elif name=='native_edit':
   q=int(args['quantity']);out=s.p3.env.unpack(self.native.webmcp.call_tool('update_cart',dict(action='set_quantity',line_id=self.line,quantity=q),timeout=60000));self.native_writes+=1
   if out.get('ok') is not False and 'error' not in out and float(self.oracle()['items'][0]['quantity'])==q:self.native_revision=2
  elif name=='read_saved':out=self.read_saved()
  elif name=='read_ui':out=self.page.evaluate(s.p3.base.UI_READ)
  elif name=='read_pending':out=dict(pending=copy.deepcopy(self.pending),settled_jobs=len(self.events))
  elif name=='wait_pending':
   if self.pending:self.tick=max(self.tick,self.pending['due_tick']);self.dispatch()
   out=dict(pending=copy.deepcopy(self.pending),saved_cart=self.read_saved())
  elif name=='finish':self.report=args;out=dict(finished=True)
  else:out=dict(error='Unknown operation')
  self.trace.append(dict(tick=self.tick,tool=name,args=args,model_turn=turn,call_id=callid,observation=out,backend_before=before,backend_after=self.oracle(),pending=copy.deepcopy(self.pending)));s.write(self.folder/'trace.json',self.trace);return out
 def finish(self,error=None):
  report_state=self.oracle();pending=copy.deepcopy(self.pending);report_tick=self.tick
  if self.pending:
   self.tick=max(self.tick,self.pending['due_tick'])
   try:self.dispatch()
   except Exception as e:error=(error+'; ' if error else '')+f'Quiescence {type(e).__name__}: {e}'
  settled=self.oracle();valid=self.valid(settled) and self.initialized and self.revised;overwrites=sum(e['overwrite'] for e in self.events);status=(self.report or {}).get('status')
  scores=dict(settled_valid=valid,settled_error=not valid,valid_at_report=self.valid(report_state),transient_overwrite=bool(overwrites),overwrite_count=overwrites,repaired=bool(overwrites and valid),completed_wrong_settled=status=='completed' and not valid,completed_with_pending=bool(status=='completed' and pending),native_writes=self.native_writes,extra_native_writes=max(0,self.native_writes-1),guard_drops=sum(e['dropped_stale'] for e in self.events),initial_ui_requested=self.initialized,revised_instruction_delivered=self.revised,technical_error=bool(error),actions=len(self.trace))
  r=dict(spec=self.c,error=error,report=self.report,report_tick=report_tick,backend_at_report=report_state,settled_backend=settled,pending_at_report=pending,events=self.events,trace=self.trace,scores=scores);s.write(self.folder/'result.json',r);return r

def tools(first=False):
 if first:return [s.tool('ui_edit','Select quantity 2 in the real cart UI. Invokes or schedules its original save callback. Accepted pending is not completed.')]
 return [s.tool('native_edit','Set this cart line quantity through original native WebMCP update_cart. Does not cancel earlier UI jobs.',{'quantity':{'type':'integer','minimum':1,'maximum':10}},['quantity']),s.tool('read_saved','Read the current saved cart through native WebMCP; read-only.'),s.tool('read_ui','Read the genuine current DOM, which may retain a local selection.'),s.tool('read_pending','Read status of this actor\'s earlier accepted UI save; no write.'),s.tool('wait_pending','Wait for all previously accepted UI saves to finish, then read current saved cart. Creates no additional write.'),s.tool('finish','Report outcome of the latest user request.',{'status':{'type':'string','enum':['completed','uncertain','failed']},'message':{'type':'string'}},['status','message'])]

def run_episode(a,c,folder,model=None,ledger=None):
 folder.mkdir(exist_ok=False);s.write(folder/'spec.json',c);ep=Episode(a,c,folder);ready=False;error=None
 try:
  ep.setup();ready=True
  if model is None:
   ep.act('ui_edit',{},0,'script-ui');ep.revised=True
   if c['policy']=='await' or c.get('validation_path')=='guard_pass':ep.act('wait_pending',{},1,'script-wait')
   ep.act('native_edit',dict(quantity=c['target']),2,'script-native')
   if c.get('validation_path')=='repair':
    ep.act('wait_pending',{},3,'script-wait');ep.act('native_edit',dict(quantity=c['target']),4,'script-repair')
   ep.act('read_saved',{},5,'script-read');ep.act('finish',dict(status='completed',message='Scripted validation'),6,'script-finish')
  else:
   messages=[dict(role='system',content='Operate this isolated real Medusa cart. Preserve the latest user instruction. UI and native tools share saved state; a page may retain a local selection. Some saves complete asynchronously. No order or payment is authorized. Report actual outcome, including unresolved uncertainty.'),dict(role='user',content='Set the prepared Medusa T-Shirt quantity to exactly 2 using ui_edit. Do not checkout. First perform that UI action.')]
   for turn in range(20):
    if len(ep.trace)>=28 or ep.report:break
    raw=s.inference(model,messages,tools(not ep.revised),ledger,folder.name,folder,turn);msg=raw['choices'][0]['message'];messages.append({k:v for k,v in msg.items() if k in ('role','content','tool_calls','reasoning_content')});calls=msg.get('tool_calls') or []
    if not calls:s.write(folder/'unstructured_final.json',msg);break
    revision_after=False
    for call in calls:
     if len(ep.trace)>=28:break
     name=call['function']['name'];args=json.loads(call['function']['arguments']);out=ep.act(name,args,turn,call['id']);messages.append(dict(role='tool',tool_call_id=call['id'],content=s.encode(out)))
     if name=='ui_edit' and ep.initialized and not ep.revised:revision_after=True
     if ep.report:break
    if revision_after:
     ep.revised=True;instruction=f'Change of plan. Your FINAL request supersedes quantity 2: leave exactly {c["target"]} of the same T-shirt variant in the SAVED cart using native_edit. Do not order. Report completion of this latest request.'
     if c['policy']=='await':instruction+=' Before the final native update, wait for your earlier UI save to finish. Then verify the final saved cart and that no earlier save is still pending.'
     messages.append(dict(role='user',content=instruction))
 except Exception as e:error=f'{type(e).__name__}: {e}'
 if ready:
  try:r=ep.finish(error)
  finally:a.close()
 else:r=dict(spec=c,error=error,report=None,scores=dict(technical_error=True));s.write(folder/'result.json',r)
 print(s.encode(dict(id=folder.name,scores=r['scores'],error=r['error'])),flush=True);return r

def freeze(out):
 s.freeze(out)
 paths=[Path(__file__),DOC/'PROTOCOL_RU.md'];hashes={}
 for p in paths:
  dest=out/'frozen_inputs'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes());hashes[str(p.relative_to(ROOT))]=s.hashfile(p)
 s.write(out/'own_write_hashes.json',hashes)
 upstream=ROOT/'artifacts/medusa_v1/runtime/nextjs-starter-medusa/intent-p3-w0/author/repo/src';ih={}
 for rel in ('modules/cart/components/item/index.tsx','lib/webmcp/tools.ts'):
  p=upstream/rel;dest=out/'frozen_integration'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes());ih[rel]=s.hashfile(p)
 s.write(out/'integration_hashes.json',ih)

def worker(planfile,index):
 from playwright.sync_api import sync_playwright
 plan=json.loads(Path(planfile).read_text());w=plan['workers'][index];out=Path(plan['out'])/f'worker-{index}';out.mkdir(exist_ok=False);freeze(out);cfg=dict(plan['config'],started_epoch=time.time());ledger=None if plan['stage'].startswith('validation') else s.Ledger(out,cfg);models={m['id']:m for m in cfg['models']}
 with sync_playwright() as pw:
  b=pw.chromium.connect_over_cdp('http://127.0.0.1:9243');a=s.Medusa(w['target'],b)
  for c in w['cells']:
   ident=hashlib.sha256(s.encode(c).encode()).hexdigest()[:16];r=run_episode(a,c,out/ident,None if ledger is None else models[c['model']],ledger)
   if r['error'] and ('StopRun' in r['error'] or 'API ' in r['error']):raise RuntimeError('Paid API failure retained; no replay')
  b.close()
def launch(stage):
 out=ART/stage;out.mkdir(exist_ok=False);cs=matrix()
 if stage.startswith('validation'):
  cs=[]
  for target in (1,3):
   for policy,timing,path in [('baseline','immediate','normal'),('baseline','queued','normal'),('await','queued','normal'),('revision_guard','queued','normal'),('baseline','queued','repair'),('revision_guard','queued','guard_pass')]:
    c=next(copy.deepcopy(c) for c in matrix() if c['target']==target and c['policy']==policy and c['timing']==timing and c['repeat']==4);c.update(model='control',validation_path=path);cs.append(c)
 elif stage=='pilot':cs=[next(copy.deepcopy(c) for c in matrix() if c['model']==m['id'] and c['policy']=='baseline' and c['target']==target and c['timing']==timing and c['repeat']==4) for m in MODELS for target in (1,3) for timing in ('immediate','queued')]
 else:assert json.loads((ART/'mechanics_audit.json').read_text())['passed']
 cfg=dict(json.loads((ROOT/'artifacts/point4_realapps/main/plan.json').read_text())['config'],budget_usd=3,hours=3,max_turns=20)
 targets=[t for t in json.loads((ROOT/'artifacts/point4_realapps/instances.json').read_text()) if t['app_type']=='medusa'];workers=[dict(target=t,cells=cs[i::len(targets)]) for i,t in enumerate(targets)];plan=dict(stage=stage,out=str(out),config=cfg,cells=cs,workers=workers,created_epoch=time.time(),protocol_sha256=s.hashfile(DOC/'PROTOCOL_RU.md'));s.write(out/'plan.json',plan);ps=[]
 for i,w in enumerate(workers):
  log=(out/f'worker-{i}.log').open('w');ps.append(subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'worker','--plan',str(out/'plan.json'),'--index',str(i)],cwd=ROOT,stdout=log,stderr=log))
 codes=[p.wait() for p in ps];s.write(out/'exit_codes.json',codes);print(stage,codes,flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('command',choices=['validation','validation_v2','pilot','main','worker']);ap.add_argument('--plan');ap.add_argument('--index',type=int);args=ap.parse_args();worker(args.plan,args.index) if args.command=='worker' else launch(args.command)
