from point2_review_controls.surfaces import Surface as BaseSurface,ROOT
from point2_review_controls import run as actor
class Surface(BaseSurface):
    def __init__(self,browser,c,target,folder):
        super().__init__(browser,c,target,folder)
        script=(ROOT/'src/point2_effort_full_gate/gate.js').read_text().replace('__STEPS__',str(c['ui_steps']))
        self.context.add_init_script(script=script);self.page.evaluate(script);self.page.wait_for_timeout(250)
        body=self.read();(folder/'gated_initial.json').write_text(__import__('json').dumps(body,indent=2))
        if c['ui_steps']==7:assert '€' not in body['text'] and self.visible_total() is None
        else:assert self.visible_total()==c['actual_total']
        assert c['product'] in body['text'] and c['shipping'] in body['text']
        self.page.screenshot(path=str(folder/'gated_initial.png'),full_page=True)
def activate():actor.Surface=Surface
