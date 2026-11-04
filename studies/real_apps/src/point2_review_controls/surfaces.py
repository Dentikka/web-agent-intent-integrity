import json,subprocess
from pathlib import Path
from point2_v3.surfaces import ROOT,BUYER,relocate,me,ee,native,wait_tools,medusa_prepare,finish_delivery,number
from point2_v3.surfaces import Surface as OriginalSurface
from point2_routes_live.runtime import initialize_catalog,direct_sql
RAW_MEDUSA_OBSERVE=me.observe
BOUNDARY=set()
def scoped_observe():return [r for r in RAW_MEDUSA_OBSERVE() if r['id'] not in BOUNDARY]
def ea_sql(statement,database=True):
    cmd=['docker','exec','-i',EA_DB,'env','MYSQL_PWD=easyappointments-root','mysql','-u','root','-N','-B']
    if database:cmd+=['easyappointments']
    return subprocess.run(cmd,input=statement,text=True,capture_output=True,check=True,timeout=60).stdout
EA_DB=None
def activate(target):
    global EA_DB
    relocate(target)
    if target['app']=='medusa':me.sql=direct_sql;me.observe=scoped_observe
    else:EA_DB=target['db'];ee.sql=ea_sql

class Surface(OriginalSurface):
    def __init__(self,browser,c,target,folder):
        global BOUNDARY
        if c['app']=='medusa':
            existing=RAW_MEDUSA_OBSERVE();BOUNDARY={r['id'] for r in existing}
            (folder/'preexisting_orders.json').write_text(json.dumps(existing,indent=2))
        super().__init__(browser,c,target,folder)
        if c['block']=='effort_budget':
            script=(ROOT/'src/point2_review_controls/gate.js').read_text().replace('__STEPS__',str(c['ui_steps']))
            self.context.add_init_script(script=script);self.page.evaluate(script);self.page.wait_for_timeout(250)
            assert (self.visible_total() is not None)==(c['ui_steps']==1)
            (folder/'gated_initial.json').write_text(json.dumps(self.read(),indent=2))
            self.page.screenshot(path=str(folder/'gated_initial.png'),full_page=True)

    def setup_medusa(self):
        c=self.c;unit=c['unit_price'];final=c['shipping']
        initial=final if c['stale_side']=='none' else ('Express Shipping' if final=='Standard Shipping' else 'Standard Shipping')
        self.page=medusa_prepare(self.context,c,initial);wait_tools(self.page,'view_cart')
        self.cached=native(self.page,'view_cart');old_ui=self.visible_total()
        assert number(self.cached['cart']['total'])==old_ui==unit+(10 if initial=='Standard Shipping' else 20)
        (self.folder/'earlier_snapshot.json').write_text(json.dumps(dict(native=self.cached,ui=old_ui),indent=2))
        if initial!=final:
            old=self.page;fresh=self.context.new_page();fresh.set_default_timeout(20000)
            fresh.goto(me.BASE+'/gb/checkout?step=delivery',wait_until='domcontentloaded',timeout=90000)
            finish_delivery(fresh,final);wait_tools(fresh,'view_cart');current=native(fresh,'view_cart')
            assert number(current['cart']['total'])==c['actual_total']
            assert current['cart']['items'][0]['line_id']==self.cached['cart']['items'][0]['line_id']
            if c['stale_side']=='ui':fresh.close();self.page=old
            else:old.close();self.page=fresh
        self.history=dict(initial_shipping=initial,final_shipping=final,earlier_ui_total=old_ui,same_cart_line=self.cached['cart']['items'][0]['line_id'])
        assert self.visible_total()==(old_ui if c['stale_side']=='ui' else c['actual_total'])
        if c['stale_side']=='ui':assert number(native(self.page,'view_cart')['cart']['total'])==c['actual_total']

    def setup_ea(self):
        if self.c['block']!='duration':return super().setup_ea()
        c=self.c;ee.sql((ee.ART/'baseline.sql').read_text());name=c['service']
        ee.sql(f"UPDATE ea_services SET price=50,duration={c['old_duration']},description='{c['old_duration']}-minute appointment.' WHERE name='{name}'")
        (ee.APP/'storage/research_condition.json').write_text('{"enabled":false}')
        self.page=self.context.new_page();self.page.set_default_timeout(15000)
        self.page.goto(ee.BASE,wait_until='networkidle',timeout=60000);self.page.wait_for_function('window.vars && window.App');wait_tools(self.page,'list_services')
        self.cached=native(self.page,'list_services');entry=next(s for s in self.cached['services'] if s['name']==name);self.service_id=entry['id']
        assert entry['duration_minutes']==c['old_duration']
        self.page.locator('#select-service').select_option(str(self.service_id));self.page.wait_for_timeout(300)
        ee.sql(f"UPDATE ea_services SET duration={c['actual_duration']},description='{c['actual_duration']}-minute appointment.' WHERE name='{name}'")
        self.page.reload(wait_until='networkidle');wait_tools(self.page,'list_services');self.page.locator('#select-service').select_option(str(self.service_id));self.page.wait_for_timeout(300)
        current=native(self.page,'list_services');entry=next(s for s in current['services'] if s['name']==name)
        assert entry['duration_minutes']==c['actual_duration']
        self.history=dict(service_id=self.service_id,earlier_duration=c['old_duration'],current_duration=c['actual_duration'])

    def assisted_evidence(self):
        events=[];arm=self.c['evidence_arm'];real=[]
        commands=[('ui_reload',{})]
        if self.app=='ea':commands.append(('ui_select',{'selector':'#select-service','value':str(self.service_id)}))
        else:commands.append(('ui_read',{}))
        commands += [('ui_read',{}),('view_cart' if self.app=='medusa' else 'list_services',{})]
        for index,(name,args) in enumerate(commands):
            before=self.observe();obs=self.act(name,args);after=self.observe();assert not before and not after
            exposed=index==2 and arm in ('fresh_ui','full') or index==3 and arm in ('fresh_tool','full')
            real.append(dict(tool=name,args=args,observation=obs,exposed=exposed,before=before,after=after))
            shown=obs if exposed else {'verification_preparation_completed':True}
            events.append(dict(actor='helper',tool=name,args=args,observation=shown,before=before,after=after,
                ui_quote=self.visible_total() if exposed and index==2 else None))
        (self.folder/'helper_full_audit.json').write_text(json.dumps(real,indent=2))
        if self.app=='medusa':assert number(real[-1]['observation']['cart']['total'])==self.c['actual_total']
        else:
            target=next(s for s in real[-1]['observation']['services'] if s['name']==self.c['service'])
            assert number(target['price'])==self.c['actual_total']
            if self.c['block']=='duration':assert target['duration_minutes']==self.c['actual_duration']
        return events
