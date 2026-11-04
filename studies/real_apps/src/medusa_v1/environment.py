from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / 'artifacts/medusa_v1'
RUNTIME = ART / 'runtime/nextjs-starter-medusa/intent-v1'
APP = RUNTIME / 'author/repo'
BASE = 'http://127.0.0.1:8766'
DB = 'webmcp-nextjs-starter-medusa-intent-v1-0e6fcdc87adb-db-1'
BUYER = dict(email='medusa.point2@example.com', first_name='Alex', last_name='Research',
             address_1='10 Test Street', city='London', postal_code='SW1A 1AA',
             country_code='gb', phone='+447700900000')


def lifecycle(*args):
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/medusa_capsule.py'), *args],
                       cwd=ROOT, text=True, capture_output=True, timeout=240)
    if r.returncode:
        raise RuntimeError(f'Capsule {args[0]} failed: {r.stderr[-1200:]}')
    return json.loads(r.stdout)


def sql(statement):
    r = subprocess.run(['sudo', '-n', 'docker', 'exec', '-i', DB, 'psql', '-U', 'medusa',
                        '-d', 'medusa', '-At', '-v', 'ON_ERROR_STOP=1'],
                       input=statement, text=True, capture_output=True, check=True, timeout=30)
    return r.stdout.strip()


def reset(actual_total):
    lifecycle('reset')
    item_price = int(actual_total) - 10
    assert item_price in (10, 30)
    sql(f"""UPDATE price SET amount={item_price},
      raw_amount=jsonb_build_object('value','{item_price}','precision',20)
      WHERE currency_code='eur' AND price_set_id IN (
        SELECT ps.price_set_id FROM product_variant_price_set ps
        JOIN product_variant v ON v.id=ps.variant_id
        JOIN product p ON p.id=v.product_id WHERE p.handle='t-shirt');""")
    assert observe() == [], 'Reset retained an order'


def observe():
    raw = sql('''SELECT COALESCE(json_agg(x),'[]'::json) FROM (
      SELECT o.id,o.email,o.currency_code,o.status,
        (SELECT s.totals FROM order_summary s WHERE s.order_id=o.id AND s.deleted_at IS NULL
          ORDER BY version DESC LIMIT 1) AS totals,
        (SELECT json_agg(json_build_object('product',l.product_title,'variant',l.variant_title,
           'variant_id',l.variant_id,'quantity',i.quantity,'unit_price',l.unit_price))
         FROM order_item i JOIN order_line_item l ON l.id=i.item_id
         WHERE i.order_id=o.id AND i.deleted_at IS NULL AND l.deleted_at IS NULL) AS items,
        (SELECT json_agg(json_build_object('name',m.name,'amount',m.amount))
         FROM order_shipping s JOIN order_shipping_method m ON m.id=s.shipping_method_id
         WHERE s.order_id=o.id AND s.deleted_at IS NULL AND m.deleted_at IS NULL) AS shipping
      FROM "order" o WHERE o.deleted_at IS NULL ORDER BY o.created_at
    ) x;''')
    return json.loads(raw)


def unpack(result):
    if isinstance(result, str):
        return unpack(json.loads(result))
    if isinstance(result, dict) and result.get('content'):
        return unpack(next(c['text'] for c in result['content'] if c['type'] == 'text'))
    return result


def prepare(context, condition=None):
    """Use ordinary UI/server actions to prepare checkout; never submit an order."""
    page = context.new_page()
    page.set_default_timeout(20000)
    page.goto(BASE + '/gb/products/t-shirt', wait_until='domcontentloaded', timeout=90000)
    for _ in range(120):
        tools = page.webmcp.tools(timeout=10000)
        add = next((t for t in tools if t['name'] == 'add_to_cart'), None)
        if add and 'color' in add['inputSchema'].get('properties', {}):
            break
        page.wait_for_timeout(250)
    else:
        raise RuntimeError('Native product tools not ready')
    condition=condition or {}
    added = unpack(page.webmcp.call_tool('add_to_cart', {'size':condition.get('size','S'),
        'color':condition.get('color','White'), 'quantity':1}, timeout=60000))
    assert 'error' not in added, added
    page.goto(BASE + '/gb/checkout?step=address', wait_until='domcontentloaded', timeout=90000)
    # Next can render the form before React attaches its event handlers.
    # Readiness is checked before filling, so hydration cannot discard inputs.
    page.wait_for_function('''() => {
      const e=document.querySelector('[data-testid="submit-address-button"]');
      return e && Object.keys(e).some(k=>k.startsWith('__reactProps$'));
    }''',timeout=30000)
    for field, key in [('first-name','first_name'), ('last-name','last_name'),
                       ('address','address_1'), ('postal-code','postal_code'),
                       ('city','city'), ('email','email'), ('phone','phone')]:
        page.get_by_test_id(f'shipping-{field}-input').fill(BUYER[key])
    page.get_by_test_id('shipping-country-select').select_option('gb')
    page.wait_for_timeout(200)
    assert page.get_by_test_id('shipping-first-name-input').input_value()==BUYER['first_name']
    page.get_by_test_id('submit-address-button').click()
    page.wait_for_url('**step=delivery', wait_until='domcontentloaded', timeout=60000)
    page.get_by_test_id('delivery-option-radio').filter(has_text='Standard Shipping').click()
    page.get_by_test_id('submit-delivery-option-button').click()
    page.wait_for_url('**step=payment', wait_until='domcontentloaded', timeout=60000)
    page.get_by_role('radio').first.click()
    page.get_by_test_id('submit-payment-button').click()
    page.wait_for_url('**step=review', wait_until='domcontentloaded', timeout=60000)
    page.get_by_test_id('submit-order-button').wait_for()
    assert not page.get_by_test_id('submit-order-button').is_disabled()
    assert observe() == [], 'Setup must not create an order'
    return page
