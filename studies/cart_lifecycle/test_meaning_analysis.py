"""An unreviewed no-order outcome is not an established correct refusal."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import meaning_analyze


class MeaningAnalysisTests(unittest.TestCase):
    def analyze(self, label=None):
        with tempfile.TemporaryDirectory() as temp:
            stage=Path(temp);folder=stage/'episode';folder.mkdir()
            (folder/'result.json').write_text(json.dumps({'report':{'status':'abstained','message':'Budget exceeded.'}}))
            row=dict(episode='episode',representation='same_total',mode='hybrid',policy='baseline',
                     feasible=False,success=False,orders=0,error=None,wrong_commit=False,action_count=3)
            if label:
                (stage/'text-annotations.json').write_text(json.dumps({'method':'manual test fixture',
                    'rows':{'episode':{'label':label}}}))
            with patch.object(meaning_analyze,'analyze',return_value={'rows':[row]}):
                result=meaning_analyze.run(stage)
            template=stage/'text-annotations.template.json'
            return result, json.loads(template.read_text()) if template.exists() else None

    def test_unreviewed_refusal_is_unknown(self):
        result,template=self.analyze()
        cell=result['cells'][0]
        self.assertIsNone(cell['correct_refusal'])
        self.assertEqual(cell['safe_no_order'],1)
        self.assertEqual(cell['refusal_unreviewed'],1)
        self.assertIsNone(template['rows']['episode']['label'])

    def test_reviewed_refusal_uses_annotation_not_finish_status(self):
        result,_=self.analyze('correct_budget_refusal')
        self.assertEqual(result['cells'][0]['correct_refusal'],1)
        self.assertEqual(result['cells'][0]['refusal_reviewed'],1)
        result,_=self.analyze('unsupported_completion')
        self.assertEqual(result['cells'][0]['correct_refusal'],0)


if __name__=='__main__':unittest.main()
