import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from intent_cases import IntentApp
from program_runner import matrix
from program_analyze import analyze


class ProgrammeTests(unittest.TestCase):
    def test_full_design_and_distinct_calibration(self):
        self.assertEqual(len(matrix({})),138)
        self.assertEqual(len(matrix({'sections':['intent']})),84)
        cells=matrix({'calibration':True})
        self.assertEqual(len(cells),3)
        self.assertTrue(any(c['mode']=='ui' for c in cells))
        self.assertTrue(any(c['high_cost'] for c in cells))
        self.assertTrue(any(c['scenario']=='permission' for c in cells))

    def test_paired_analysis_and_pricing_from_durable_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);specs=[]
            with closing(sqlite3.connect(root/'usage.sqlite')) as db,db:
                db.execute('CREATE TABLE calls(episode TEXT,reserve REAL,actual REAL,status TEXT,usage TEXT)')
                for i,mismatch in enumerate((False,True)):
                    app=IntentApp('permission',mismatch);oid=app.target['id']
                    detail=app.invoke('tool','site_read_details',{'object_id':oid})
                    app.invoke('tool','site_prepare',{'object_id':oid,'confirmation':detail['confirmation']})
                    spec=dict(section='intent',scenario='permission',mismatch=mismatch,policy='baseline',mode='hybrid',high_cost=False,seed=0)
                    specs.append(spec);folder=root/str(i);folder.mkdir()
                    report=dict(status='completed',object=oid)
                    (folder/'result.json').write_text(json.dumps(dict(model='test-model',spec=spec,report=report,scores=app.score(report),error=None,truncated=False,seconds=1)))
                    (folder/'backend.json').write_text(json.dumps(dict(initial=app.domain.initial,events=app.events,final=app.domain.records)))
                    db.execute('INSERT INTO calls VALUES(?,?,?,?,?)',(str(i),.01,.01,'done',json.dumps({'prompt_tokens':100,'completion_tokens':10})))
            (root/'summary.json').write_text(json.dumps(dict(complete=True,planned=2,cost_upper_tariff_usd=.02,errors=[],pending_calls=0)))
            (root/'config.json').write_text(json.dumps({'workers':4}))
            (root/'source').mkdir();(root/'source/source.py').write_bytes(b'fixture')
            (root/'manifest.json').write_text(json.dumps(dict(matrix=specs,models=[{'id':'test-model'}],sources={'source.py':hashlib.sha256(b'fixture').hexdigest()})))
            result=analyze(root)
            self.assertTrue(result['coverage_complete'])
            self.assertEqual(result['paired_contrasts'][0]['deltas']['unauthorized_commit'],1)
            self.assertAlmostEqual(result['pricing_scenarios'][0]['combined_usd'],.0018)
            (root/'source/source.py').write_bytes(b'drift')
            with self.assertRaises(ValueError):analyze(root)


if __name__=='__main__':unittest.main()
