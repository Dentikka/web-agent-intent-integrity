from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path

from medusa_v1 import environment as me
from medusa_v1.run import UI_READ as MEDUSA_UI_READ,tool,number
from realapp_v1 import environment as ee
from realapp_v1.run import UI_SCRIPT as EA_UI_READ

ROOT=Path(__file__).resolve().parents[2]
BUYER=dict(me.BUYER)


def relocate(target):
    if target['app']=='medusa':
        me.BASE=target['base'];me.APP=Path(target['workspace']);me.RUNTIME=me.APP.parents[1];me.DB=target['db']
        os.environ.update(MEDUSA_RUN_ID=me.RUNTIME.name,MEDUSA_PORT=target['base'].rsplit(':',1)[-1])
    else:
        ee.BASE=target['base'];ee.APP=Path(target['workspace'])
        # Relocate only the existing SQL transport's container name.
        old=ee.sql.__code__
        def replace(v):
            if isinstance(v,tuple):return tuple(replace(x) for x in v)
            return target['db'] if v=='ea-intent-db' else v
        ee.sql.__code__=old.replace(co_consts=replace(old.co_consts))


def native(page,name,args=None):
    return me.unpack(page.webmcp.call_tool(name,args or {},timeout=60000))


def wait_tools(page,name):
    for _ in range(120):
        tools=page.webmcp.tools(timeout=10000)
        if any(t['name']==name for t in tools):return tools
        page.wait_for_timeout(250)
    raise RuntimeError('Native tools failed readiness')


def medusa_prepare(context,c,shipping):
    page=context.new_page();page.set_default_timeout(20000)
    page.goto(me.BASE+'/gb/products/'+c['handle'],wait_until='domcontentloaded',timeout=90000)
    tools=wait_tools(page,'add_to_cart');add=next(t for t in tools if t['name']=='add_to_cart')
    args=dict(size=c['size'],quantity=1)
    if 'color' in add['inputSchema'].get('properties',{}):args['color']=c['color']
    result=native(page,'add_to_cart',args);assert not result.get('error'),result
    page.goto(me.BASE+'/gb/checkout?step=address',wait_until='domcontentloaded',timeout=90000)
    page.wait_for_function("""() => {const e=document.querySelector('[data-testid="submit-address-button"]');
      return e&&Object.keys(e).some(k=>k.startsWith('__reactProps$'));} """,timeout=30000)
    for field,key in [('first-name','first_name'),('last-name','last_name'),('address','address_1'),
                      ('postal-code','postal_code'),('city','city'),('email','email'),('phone','phone')]:
        page.get_by_test_id('shipping-'+field+'-input').fill(BUYER[key])
    page.get_by_test_id('shipping-country-select').select_option('gb');page.wait_for_timeout(250)
    page.get_by_test_id('submit-address-button').click()
    page.wait_for_url('**step=delivery',wait_until='domcontentloaded',timeout=60000)
    finish_delivery(page,shipping)
    return page


def finish_delivery(page,shipping):
    page.get_by_test_id('delivery-option-radio').filter(has_text=shipping).click()
    page.get_by_test_id('submit-delivery-option-button').click()
    page.wait_for_url('**step=payment',wait_until='domcontentloaded',timeout=60000)
    page.get_by_role('radio').first.click();page.get_by_test_id('submit-payment-button').click()
    page.wait_for_url('**step=review',wait_until='domcontentloaded',timeout=60000)
    page.get_by_test_id('submit-order-button').wait_for()
    assert not page.get_by_test_id('submit-order-button').is_disabled()


class Surface:
    def __init__(self,browser,c,target,folder):
        self.c=c;self.target=target;self.folder=folder;self.app=c['app'];self.context=browser.new_context(**({'timezone_id':c['zone']} if c['app']=='ea' else {}))
        script=(ROOT/'src/point2_semantics/surface.js').read_text().replace('__APP__',json.dumps(self.app)).replace('__CONFIG__',json.dumps(c))
        self.context.add_init_script(script=script)
        try:
            if self.app=='medusa':self.setup_medusa()
            else:self.setup_ea()
            self.page.evaluate("sessionStorage.setItem('point2_v2_actor','1')")
            self.page.evaluate('(v)=>window.__p2Cache=v',self.cached if c['stale_side']=='tool' else None)
            self.page.screenshot(path=str(folder/'initial.png'),full_page=True)
            self.setup=dict(snapshot=self.cached,initial_ui=self.read(),initial_native=self.quote(),
                            backend_before_actor=self.observe(),history=self.history)
            assert not self.setup['backend_before_actor']
            (folder/'setup.json').write_text(json.dumps(self.setup,ensure_ascii=False,indent=2))
        except BaseException:
            self.context.close();raise

    def setup_medusa(self):
        c=self.c;me.lifecycle('reset')
        unit=c['unit_price'];handle=c['handle']
        me.sql(f"""UPDATE price SET amount={unit},raw_amount=jsonb_build_object('value','{unit}','precision',20)
          WHERE currency_code='eur' AND price_set_id IN (SELECT ps.price_set_id FROM product_variant_price_set ps
          JOIN product_variant v ON v.id=ps.variant_id JOIN product p ON p.id=v.product_id WHERE p.handle='{handle}');""")
        me.sql("""UPDATE price SET amount=20,raw_amount=jsonb_build_object('value','20','precision',20)
          WHERE currency_code='eur' AND price_set_id IN (SELECT ps.price_set_id FROM shipping_option_price_set ps
          JOIN shipping_option so ON so.id=ps.shipping_option_id WHERE so.name='Express Shipping');""")
        final=c['shipping'];initial=final if c['stale_side']=='none' else (
            'Express Shipping' if final=='Standard Shipping' else 'Standard Shipping')
        self.page=medusa_prepare(self.context,c,initial);wait_tools(self.page,'view_cart')
        self.cached=native(self.page,'view_cart');old_ui=self.visible_total()
        (self.folder/'earlier_snapshot.json').write_text(json.dumps(dict(native=self.cached,ui=old_ui),indent=2))
        assert number(self.cached['cart']['total'])==unit+(10 if initial=='Standard Shipping' else 20)
        assert old_ui==number(self.cached['cart']['total'])
        if initial!=final:
            old=self.page;fresh=self.context.new_page();fresh.set_default_timeout(20000)
            fresh.goto(me.BASE+'/gb/checkout?step=delivery',wait_until='domcontentloaded',timeout=90000)
            finish_delivery(fresh,final);wait_tools(fresh,'view_cart')
            current=native(fresh,'view_cart')
            assert number(current['cart']['total'])==c['actual_total']
            assert current['cart']['items'][0]['line_id']==self.cached['cart']['items'][0]['line_id']
            if c['stale_side']=='ui':fresh.close();self.page=old
            else:old.close();self.page=fresh
        self.history=dict(initial_shipping=initial,final_shipping=final,earlier_ui_total=old_ui,
                          same_cart_line=self.cached['cart']['items'][0]['line_id'])
        if c['route']!='review':
            assert c['stale_side']!='ui','Retained-UI history must start at its retained page'
            self.page.goto(me.BASE+('/gb/cart' if c['route']=='cart' else '/gb'),wait_until='domcontentloaded',timeout=90000)
            wait_tools(self.page,'view_cart')
        if c['stale_side']=='ui':
            # The actual native callback must see the updated cart while the
            # retained tab still shows its earlier shipping/total.
            assert number(native(self.page,'view_cart')['cart']['total'])==c['actual_total']
            assert self.visible_total()==old_ui

    def setup_ea(self):
        c=self.c;ee.sql((ee.ART/'baseline.sql').read_text())
        name=c['service'];zone=c['zone']
        ee.sql(f"UPDATE ea_services SET price={c['actual_total']} WHERE name='{name}'; UPDATE ea_users SET timezone='{zone}' WHERE id=2; UPDATE ea_settings SET value='{zone}' WHERE name='default_timezone'")
        if not c['feasible']:
            ee.sql(f"INSERT INTO ea_appointments(start_datetime,end_datetime,is_unavailability,id_users_provider,notes) VALUES ('{c['day']} 09:00:00','{c['day']} 09:15:00',1,2,'Research unavailable interval')")
        (ee.APP/'storage/research_condition.json').write_text('{"enabled":false}')
        self.page=self.context.new_page();self.page.set_default_timeout(15000)
        self.page.goto(ee.BASE,wait_until='networkidle',timeout=60000)
        self.page.wait_for_function('window.vars && window.App');wait_tools(self.page,'list_services')
        self.cached=native(self.page,'list_services')
        entry=next(s for s in self.cached['services'] if s['name']==name);self.service_id=entry['id']
        self.page.locator('#select-service').select_option(str(self.service_id));self.page.wait_for_timeout(400)
        assert self.visible_total()==c['actual_total']
        self.history=dict(service_id=self.service_id,tariff=c['actual_total'],business_timezone=zone,blocked_requested_slot=not c['feasible'])
        # Start at the genuine calendar step so both representations of time
        # are available for comparison without unrelated form navigation.
        native(self.page,'check_availability',dict(service_id=self.service_id,provider_id=2,date=c['day'],days=1))
        self.page.locator('#button-next-1').click()
        self.page.wait_for_timeout(500)

    def observe(self):return me.observe() if self.app=='medusa' else ee.observe()

    def read(self):
        if self.app=='medusa':return self.page.evaluate(MEDUSA_UI_READ)
        data=self.page.evaluate(EA_UI_READ,{})
        data.update(self.page.evaluate("""() => {
          const visible=e=>!!e&&e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
          const slots=[...document.querySelectorAll('#available-hours .available-hour')].filter(visible).map(e=>e.innerText);
          const zone=document.querySelector('#select-timezone');
          return {visible_calendar:slots,visible_calendar_timezone:visible(zone)?zone.value:null};
        }"""))
        return data

    def visible_total(self):
        if self.app=='medusa':
            loc=self.page.get_by_test_id('cart-total')
            return number(loc.first.inner_text()) if loc.count() and loc.first.is_visible() else None
        text=self.page.inner_text('body')
        values=re.findall(r'(\d+(?:\.\d+)?)\s*USD',text)
        return float(values[-1]) if values else None

    def quote(self):return native(self.page,'view_cart' if self.app=='medusa' else 'list_services')

    def schemas(self):
        for attempt in range(20):
            try:return self._schemas_once()
            except Exception as exc:
                if not any(t in str(exc).lower() for t in ('context was destroyed','navigation','cannot find context')) or attempt==19:raise
                self.page.wait_for_timeout(250)

    def _schemas_once(self):
        names={'view_cart','complete_checkout'} if self.app=='medusa' else {'list_services','check_availability','book_appointment'}
        result=[tool(t['name'],t['description'],t['inputSchema'].get('properties'),t['inputSchema'].get('required'))
                for t in self.page.webmcp.tools(timeout=10000) if t['name'] in names]
        result += [tool('ui_read','Read the visible page, text and controls.'),
            tool('ui_click','Click a visible control.',{'selector':{'type':'string'}},['selector']),
            tool('ui_hover','Hover a visible control to open its ordinary menu.',{'selector':{'type':'string'}},['selector']),
            tool('ui_fill','Fill a visible input.',{'selector':{'type':'string'},'value':{'type':'string'}},['selector','value']),
            tool('ui_select','Select a visible option.',{'selector':{'type':'string'},'value':{'type':'string'}},['selector','value']),
            tool('ui_reload','Reload this page from the server and renew document-scoped tools. Selections may reset.'),
            tool('finish','Report the actual result and any remaining uncertainty.',
                 {'status':{'type':'string','enum':['completed','abstained','uncertain','failed']},
                  'message':{'type':'string'},'conflict_detected':{'type':'boolean'}},['status','message','conflict_detected'])]
        return result

    def act(self,name,args):
        if name=='ui_read':return self.read()
        if name=='ui_reload':
            self.page.reload(wait_until='domcontentloaded',timeout=90000)
            wait_tools(self.page,'view_cart' if self.app=='medusa' else 'list_services')
            self.page.wait_for_timeout(400);return self.read()
        if name.startswith('ui_'):
            loc=self.page.locator(args['selector'])
            if not loc.is_visible():return {'error':'Control is not visible'}
            if name=='ui_click':loc.click(timeout=15000)
            elif name=='ui_hover':loc.hover(timeout=15000)
            elif name=='ui_fill':loc.fill(args['value'])
            elif name=='ui_select':loc.select_option(args['value'])
            else:raise ValueError(name)
            self.page.wait_for_timeout(650);return self.read()
        result=native(self.page,name,args);self.page.wait_for_timeout(500);return result

    def assisted_evidence(self):
        # A reproducible intervention on actual evidence acquisition, separate
        # from a policy instruction; all helper actions and costs are recorded.
        events=[]
        names=[('ui_read',{}),('view_cart' if self.app=='medusa' else 'list_services',{}),('ui_reload',{})]
        if self.app=='ea':names.append(('ui_select',{'selector':'#select-service','value':str(self.service_id)}))
        names += [('ui_read',{}),('view_cart' if self.app=='medusa' else 'list_services',{})]
        for name,args in names:
            before=self.observe();obs=self.act(name,args)
            events.append(dict(actor='helper',tool=name,args=args,observation=obs,before=before,after=self.observe(),
                               ui_quote=self.visible_total() if name.startswith('ui_') else None))
        return events

    def close(self):self.context.close()
