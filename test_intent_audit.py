import unittest

from intent_audit import audit
from intent_cases import IntentApp
from test_intent_cases import apply


class CascadeTests(unittest.TestCase):
    def test_observed_signal_then_unsafe_commit(self):
        app=IntentApp('price',True)
        app.invoke('tool','site_read_preconditions',{'object_id':app.target['id']})
        apply(app)
        result=audit(app,{'status':'failed'})
        self.assertTrue(result['conflict_evidence_before_commit'])
        self.assertTrue(result['violated_after_observed_conflict'])
        self.assertFalse(result['cascade']['false_report'])

    def test_available_is_not_observed(self):
        app=IntentApp('variant',True);apply(app)
        result=audit(app,None)
        self.assertTrue(result['verification_available'])
        self.assertFalse(result['conflict_evidence_before_commit'])
        self.assertTrue(result['cascade']['wrong_terms'])

    def test_readback_distinguishes_blind_retry(self):
        for readback in (False,True):
            app=IntentApp('ambiguous',True);apply(app)
            if readback:app.invoke('tool','site_read_records',{})
            apply(app)
            result=audit(app,None)
            self.assertEqual(result['blind_retry_after_unknown'],not readback)
            self.assertTrue(result['cascade']['duplicate'])

    def test_pending_misreport_without_a_commit(self):
        app=IntentApp('pending',True);apply(app)
        result=audit(app,{'status':'completed'})
        self.assertIsNone(result['first_commit_seq'])
        self.assertTrue(result['misleading_response_seqs'])
        self.assertTrue(result['cascade']['false_report'])


if __name__=='__main__':unittest.main()
