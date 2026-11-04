"""Warm-store session isolation for the prospectively fixed route replication."""
import json
import subprocess
from point2_v3 import run as actor
from point2_v3.surfaces import Surface as OriginalSurface
from point2_v3.surfaces import me, medusa_prepare, native, number, wait_tools, finish_delivery

RAW_OBSERVE = me.observe
BOUNDARY = set()

def direct_sql(statement):
    r = subprocess.run(['docker','exec','-i',me.DB,'psql','-U','medusa','-d','medusa',
        '-At','-v','ON_ERROR_STOP=1'], input=statement,text=True,capture_output=True,check=True,timeout=30)
    return r.stdout.strip()

def episode_observe():
    return [r for r in RAW_OBSERVE() if r['id'] not in BOUNDARY]

def initialize_catalog():
    me.sql("""UPDATE price p SET amount=CASE split_part(v.title,' / ',1)
      WHEN 'S' THEN 12 WHEN 'M' THEN 16 WHEN 'L' THEN 22 WHEN 'XL' THEN 26 END,
      raw_amount=jsonb_build_object('value',CASE split_part(v.title,' / ',1)
      WHEN 'S' THEN '12' WHEN 'M' THEN '16' WHEN 'L' THEN '22' WHEN 'XL' THEN '26' END,'precision',20)
      FROM product_variant_price_set ps JOIN product_variant v ON v.id=ps.variant_id
      JOIN product prod ON prod.id=v.product_id
      WHERE ps.price_set_id=p.price_set_id AND p.currency_code='eur'
      AND prod.handle IN ('t-shirt','shorts','sweatshirt')
      AND split_part(v.title,' / ',1) IN ('S','M','L','XL');""")
    me.sql("""UPDATE price p SET amount=CASE so.name WHEN 'Standard Shipping' THEN 10 ELSE 20 END,
      raw_amount=jsonb_build_object('value',CASE so.name WHEN 'Standard Shipping' THEN '10' ELSE '20' END,'precision',20)
      FROM shipping_option_price_set ps JOIN shipping_option so ON so.id=ps.shipping_option_id
      WHERE ps.price_set_id=p.price_set_id AND p.currency_code='eur'
      AND so.name IN ('Standard Shipping','Express Shipping');""")
    return me.sql("""SELECT json_agg(x) FROM (SELECT prod.handle,v.title,p.amount
      FROM product_variant_price_set ps JOIN product_variant v ON v.id=ps.variant_id
      JOIN product prod ON prod.id=v.product_id JOIN price p ON p.price_set_id=ps.price_set_id
      WHERE p.currency_code='eur' AND prod.handle IN ('t-shirt','shorts','sweatshirt')
      ORDER BY prod.handle,v.title) x;""")

class Surface(OriginalSurface):
    def __init__(self,browser,c,target,folder):
        global BOUNDARY
        records=RAW_OBSERVE();BOUNDARY={r['id'] for r in records}
        (folder/'preexisting_orders.json').write_text(json.dumps(records,indent=2))
        super().__init__(browser,c,target,folder)

    def setup_medusa(self):
        c=self.c;unit=c['unit_price'];final=c['shipping']
        initial=final if c['stale_side']=='none' else ('Express Shipping' if final=='Standard Shipping' else 'Standard Shipping')
        self.page=medusa_prepare(self.context,c,initial);wait_tools(self.page,'view_cart')
        self.cached=native(self.page,'view_cart');old_ui=self.visible_total()
        (self.folder/'earlier_snapshot.json').write_text(json.dumps(dict(native=self.cached,ui=old_ui),indent=2))
        assert number(self.cached['cart']['total'])==unit+(10 if initial=='Standard Shipping' else 20)
        assert old_ui==number(self.cached['cart']['total'])
        if initial!=final:
            old=self.page;fresh=self.context.new_page();fresh.set_default_timeout(20000)
            fresh.goto(me.BASE+'/gb/checkout?step=delivery',wait_until='domcontentloaded',timeout=90000)
            finish_delivery(fresh,final);wait_tools(fresh,'view_cart');current=native(fresh,'view_cart')
            assert number(current['cart']['total'])==c['actual_total']
            assert current['cart']['items'][0]['line_id']==self.cached['cart']['items'][0]['line_id']
            old.close();self.page=fresh
        self.history=dict(initial_shipping=initial,final_shipping=final,earlier_ui_total=old_ui,
            same_cart_line=self.cached['cart']['items'][0]['line_id'],isolation='fresh_context_and_order_id_boundary')
        if c['route']!='review':
            self.page.goto(me.BASE+('/gb/cart' if c['route']=='cart' else '/gb'),wait_until='domcontentloaded',timeout=90000)
            wait_tools(self.page,'view_cart')

def activate():
    me.sql=direct_sql;me.observe=episode_observe;actor.Surface=Surface
