"""Real sequential operation receipt isolation; no model calls or fake responses."""
import argparse,ast,copy,json,secrets,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import run_point4 as p4
s=p4.base;ART=ROOT/'artifacts/story_strengthening/receipt_binding'

def main(app):
    from playwright.sync_api import sync_playwright
    target=next(t for t in json.loads((ROOT/'artifacts/point4_realapps/instances.json').read_text()) if t['app_type']==app)
    # Never share a live instance with its still-running route worker.
    plan=json.loads((ROOT/'artifacts/story_strengthening/main/plan.json').read_text())
    wi=next(i for i,w in enumerate(plan['workers']) if w['target']['app']==target['app'])
    done=list((ROOT/f'artifacts/story_strengthening/main/worker-{wi}').glob('*/result.json'))
    assert len(done)==len(plan['workers'][wi]['cells']),'Wait for this instance worker to finish'
    folder=ART/app
    version=2
    while folder.exists():
        folder=ART/(app+'_v'+str(version));version+=1
    folder.mkdir(parents=True,exist_ok=False)
    c=dict(app=app,authorized=True,color='White',size='S',guard=True,policy='F',readback='semantic',route='tool',scenario='stable',repeat=0,model='control',study='live_sequential_receipt_binding')
    checks=[]
    def check(name,value):
        assert value,name;checks.append(name)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9243');a=(p4.Medusa if app=='medusa' else p4.EA)(target,browser)
        first=folder/'operation_A';first.mkdir();a.reset(c,first);ca=copy.deepcopy(a.contract)
        s.write(first/'native_ack.json',a.submit('tool'));ra=p4.read_receipt(a);s.write(first/'receipt.json',ra);s.write(first/'backend.json',a.observe())
        check('A_has_exactly_one_satisfied_record',p4.verify(ca,ra)['verdict']=='satisfied' and len(ra['records'])==1)
        check('random_capability_404',p4.read_receipt(a,'0'*32).get('error')=='Receipt HTTP 404')
        a.close();second=folder/'operation_B';second.mkdir();cb=copy.deepcopy(ca);cb['token']=secrets.token_hex(16);a.contract=cb
        q=f"UPDATE research_contract SET token={p4.literal(cb['token'])},document={p4.literal(json.dumps(cb))}"+('::jsonb' if app=='medusa' else '')+f" WHERE token={p4.literal(ca['token'])}"
        a.sql(q) if app=='easyappointments' else s.p3.env.sql(q)
        s.write(second/'intent_contract.json',cb);empty=p4.read_receipt(a);s.write(second/'before_submit_receipt.json',empty)
        check('new_operation_does_not_alias_previous_record',empty['records']==[])
        check('empty_new_operation_unresolved',p4.verify(cb,empty)['verdict']=='unresolved')
        rejected=p4.verify(cb,ra);s.write(second/'previous_receipt_verdict.json',rejected)
        check('valid_previous_receipt_rejected_for_new_intent',rejected['verdict']=='unverified')
        old=p4.read_receipt(a,ca['token']);s.write(first/'retired_capability_response.json',old)
        check('retired_capability_404',old.get('error')=='Receipt HTTP 404')
        # Prepare a second genuine operation without resetting the database.
        a.folder=second
        if app=='medusa':
            source=(ROOT/'src/medusa_v1/environment.py').read_text();tree=ast.parse(source)
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
            prepare=ast.get_source_segment(source,node).replace('timeout=90000','timeout=300000')
            prepare=prepare.replace('page = context.new_page()', 'existing_orders = observe()\n    page = context.new_page()').replace("assert observe() == [], 'Setup must not create an order'","assert observe() == existing_orders, 'Preparation must preserve existing orders'")
            (second/'sequential_prepare.py').write_text(prepare)
            before_prepare=a.observe();exec(compile(prepare,'<sequential setup preserving existing orders>','exec'),s.p3.env.__dict__)
            a.s=s.p3.Surface(browser,a.native_c,second);a.page=a.s.page;a.context=a.s.context
            s.write(second/'preparation_snapshots.json',dict(before=before_prepare,after=a.observe()))
        else:
            a.context=browser.new_context();a.page=a.context.new_page();a.page.set_default_timeout(30000);a.slot=a.prepare_review(a.page)

        if app=='medusa':
            previous={r['id'] for r in a.observe()};args=dict(s.p3.env.BUYER);sequence=[]
            for _ in range(4):
                obs=a.s.act('complete_checkout',args);sequence.append(obs)
                if {r['id'] for r in a.observe()}-previous:break
                if obs.get('step')=='shipping':args['shipping_option_id']=next(x['id'] for x in obs['choices'] if x['name']=='Standard Shipping')
                elif obs.get('step')=='payment':args['payment_provider_id']=obs['choices'][0]['id']
                else:break
            ack=dict(callback_sequence=sequence)
        else:ack=a.submit('tool')
        s.write(second/'native_ack.json',ack);rb=p4.read_receipt(a);backend=a.observe();s.write(second/'receipt.json',rb);s.write(second/'backend.json',backend)
        check('B_has_exactly_one_satisfied_record',p4.verify(cb,rb)['verdict']=='satisfied' and len(rb['records'])==1)
        ida={str(r['id']) for r in ra['records']};idb={str(r['id']) for r in rb['records']};allids={str(r['id']) for r in backend}
        check('two_real_records_persist',len(backend)==2 and ida|idb==allids)
        check('receipts_are_operation_disjoint',not ida&idb)
        a.close();browser.close()
    result=dict(passed=True,app=app,checks=checks,check_count=len(checks),model_calls=0,native_operations=2,same_subject=True,database_reset_between_operations=False,
        scope='Sequential active contract rotation; concurrent same-subject contracts not implemented. Receipt independence from ACK, not from backend authority.')
    s.write(folder/'audit.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('app',choices=['medusa','easyappointments']);main(ap.parse_args().app)
