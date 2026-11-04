"""Truthful form/server representations over native WooCommerce; no route gates."""
from __future__ import annotations
import copy,json,os,sqlite3,subprocess,threading
from pathlib import Path
from bounded_api import encode
from drift_app import NativeCart,DriftApp,DriftSurface
from handoff_series import HandoffApp
from runtime_support import php_command
SOURCE=Path(__file__).resolve().parent
CATALOGS=json.loads((SOURCE/'catalogs.json').read_text())

class CatalogCart(NativeCart):
    def __init__(self,workspace,folder,spec):
        self.workspace,self.folder=workspace.resolve(),folder.resolve();self.tag=folder.name;self.ordinal=0
        (folder/'wc-logs').mkdir(exist_ok=True)
        with sqlite3.connect(Path(os.environ['DRIFT_BASE_DB']).resolve().as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(folder/'state.sqlite') as dst:src.backup(dst)
        products=copy.deepcopy(CATALOGS[spec['catalog']]['products'])
        if spec['repeat']%2:products=[products[2],products[0],products[1]]
        self.state=self.call('setup',products=products)
        assert [p['sku'] for p in self.state['catalog']]==[p['sku'] for p in products]
        for actual,wanted in zip(self.state['catalog'],products):
            assert actual['attributes']==wanted['attributes'] and actual['unit_minor']==wanted['unit_minor']
    def call(self,mode,**args):
        cmd=php_command(self.workspace,SOURCE/'drift_wc.php',Path(os.environ['DRIFT_WP_SITE']),self.folder/'state.sqlite',self.folder)
        p=subprocess.run(cmd,input=encode(dict(mode=mode,episode=self.tag,**args)),text=True,encoding='utf8',errors='replace',capture_output=True,timeout=90,cwd=self.workspace)
        self.ordinal+=1;(self.folder/f'php-{self.ordinal:03d}.log').write_text(p.stdout+'\nSTDERR:\n'+p.stderr)
        if p.returncode or '\nNIGHT_RESULT:' not in p.stdout:raise RuntimeError('Native PHP call failed; retained PHP log')
        self.state=json.loads(p.stdout.rsplit('\nNIGHT_RESULT:',1)[1].splitlines()[0]);return copy.deepcopy(self.state)

class App(HandoffApp):
    def __init__(self,workspace,folder,spec):
        self.spec=spec;self.backend=CatalogCart(workspace,folder,spec);self.catalog=self.backend.state['catalog'];self.initial=copy.deepcopy(self.backend.state)
        item=self.initial['cart']['items'][0];self.form={k:item[k] for k in ('product_id','quantity')};self.dirty=False;self.events=[];self.lock=threading.RLock()
        definition=CATALOGS[spec['catalog']];sku=definition['products'][1]['sku'];target=next(p for p in self.catalog if p['sku']==sku)
        qty=1 if spec['task']=='exact_sku' else 2+spec['repeat']%2
        self.target=dict(product_id=target['product_id'],quantity=qty);self.cap=60000
        object_text=f'SKU {sku} ({target["name"]})' if spec['task']=='exact_sku' else definition['requirement']
        self.request=(f'Create exactly one UNPAID test order for {qty} catalog unit(s) of {object_text}, with total at most {self.cap} USD cents. Count a packaged product as one catalog unit, not as its individual contents. Replace the existing cart selection as needed. No substitute product or duplicate order. Do not claim payment was made.')
        self.extra_instruction={'free':'','ui_tool':'Make your first cart edit through the page controls, and create the order through site_checkout. Read and synchronization actions may use either interface.','tool_ui':'Make your first cart edit through site_replace_cart, and create the order through the page checkout control. Read and synchronization actions may use either interface.'}[spec['handoff']]
        assert self.form['product_id']!=self.target['product_id']
        assert self.cap>=max(p['unit_minor']*3 for p in self.catalog)
    def action_error(self,name,args):
        # Assigned workflows are instructions, never software-enforced obstacles.
        return None


class GeneralizationSurface(DriftSurface):
    def act(self,name,args,allowed):
        # Execute through native WebMCP, then expose an expected rejection as
        # an observation. Unexpected browser/backend failures still propagate.
        bad_input=(name=='site_replace_cart' and (
            set(args)!={'product_id','quantity'} or
            type(args.get('product_id')) is not int or
            args.get('product_id') not in {p['product_id'] for p in self.app.catalog} or
            type(args.get('quantity')) is not int or not 1<=args.get('quantity',0)<=3))
        try:return super().act(name,args,allowed)
        except Exception as exc:
            if bad_input and 'Tool was executed but the invocation failed' in str(exc):
                return {'error':'Native tool rejected invalid arguments. Read site_catalog for valid product IDs and use the declared quantity range.','native_rejection':True}
            raise
