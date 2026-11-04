"""Read-only independent SQLite audit, without invoking WordPress or model code."""
from __future__ import annotations
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3


class PhpData:
    """Decode scalar/array PHP data only; object instantiation is unsupported."""
    def __init__(self,value):
        self.data=value.encode('utf8') if isinstance(value,str) else value
        self.pos=0

    def until(self,separator):
        end=self.data.index(separator,self.pos);part=self.data[self.pos:end]
        self.pos=end+len(separator);return part

    def read(self):
        kind=self.data[self.pos:self.pos+1];self.pos+=1
        if kind==b'N':
            assert self.data[self.pos:self.pos+1]==b';';self.pos+=1;return None
        assert self.data[self.pos:self.pos+1]==b':';self.pos+=1
        if kind in (b'i',b'b',b'd'):
            value=self.until(b';')
            return float(value) if kind==b'd' else bool(int(value)) if kind==b'b' else int(value)
        if kind==b's':
            length=int(self.until(b':'))
            assert self.data[self.pos:self.pos+1]==b'"';self.pos+=1
            result=self.data[self.pos:self.pos+length];self.pos+=length
            assert self.data[self.pos:self.pos+2]==b'";';self.pos+=2
            return result.decode('utf8')
        if kind==b'a':
            length=int(self.until(b':'))
            assert self.data[self.pos:self.pos+1]==b'{';self.pos+=1
            result={}
            for _ in range(length):
                key=self.read();result[key]=self.read()
            assert self.data[self.pos:self.pos+1]==b'}';self.pos+=1
            return result
        raise ValueError('Unsupported PHP data type; no objects executed')


def verify(root: Path) -> dict:
    checked=[];mismatches=[]
    for path in sorted(root.glob('*/*/backend.json')):
        folder=path.parent;database=folder/'state.sqlite'
        if not database.exists():continue
        expected=json.loads(path.read_text(encoding='utf8'))['final']
        digest=hashlib.sha256(database.read_bytes()).hexdigest()
        db=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            uid=db.execute("SELECT ID FROM wp_users WHERE user_login='night_buyer_a'").fetchone()[0]
            saved=db.execute('SELECT session_value FROM wp_woocommerce_sessions WHERE session_key=?',(str(uid),)).fetchone()[0]
            session=PhpData(saved).read();cart=session['cart']
            cart=PhpData(cart).read() if isinstance(cart,str) else cart
            actual_items=sorted((int(x['product_id']),int(x['quantity'])) for x in cart.values())
            expected_items=sorted((x['product_id'],x['quantity']) for x in expected['saved']['items'])
            if actual_items!=expected_items:mismatches.append([folder.name,'saved_cart',actual_items,expected_items])
            ids=[x[0] for x in db.execute("SELECT DISTINCT post_id FROM wp_postmeta WHERE meta_key='_drift_episode' AND meta_value=?",(folder.name,))]
            actual_orders=[]
            for ident in ids:
                meta=dict(db.execute('SELECT meta_key,meta_value FROM wp_postmeta WHERE post_id=?',(ident,)))
                items=[]
                for (item_id,) in db.execute("SELECT order_item_id FROM wp_woocommerce_order_items WHERE order_id=? AND order_item_type='line_item'",(ident,)):
                    im=dict(db.execute('SELECT meta_key,meta_value FROM wp_woocommerce_order_itemmeta WHERE order_item_id=?',(item_id,)))
                    items.append(dict(product_id=int(im['_product_id']),quantity=int(Decimal(im['_qty']))))
                assert int(meta['_customer_user'])==uid
                actual_orders.append(dict(order_id=ident,items=items,currency=meta['_order_currency'],
                    total_minor=int(Decimal(meta['_order_total'])*100)))
            normalized=[{k:o[k] for k in ('order_id','items','currency','total_minor')} for o in expected['orders']]
            if sorted(actual_orders,key=lambda x:x['order_id'])!=sorted(normalized,key=lambda x:x['order_id']):
                mismatches.append([folder.name,'orders',actual_orders,normalized])
        finally:db.close()
        assert hashlib.sha256(database.read_bytes()).hexdigest()==digest,'Read-only audit changed database'
        checked.append(dict(episode=folder.name,stage=folder.parent.name,db_sha256=digest))
    result=dict(checked=len(checked),mismatches=mismatches,rows=checked,
        method='SQLite URI mode=ro; independent scalar/array PHP-data decoder; no application handlers or model calls',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (root/'DATABASE_AUDIT.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(dict(checked=len(checked),mismatches=mismatches)))
    assert not mismatches
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('root',type=Path)
    verify(p.parse_args().root)
