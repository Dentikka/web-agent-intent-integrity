"""Intervention isolation and outcome-oracle tests; no paid calls."""
import copy
import unittest

from intent_cases import IntentApp,SCENARIOS,matrix


def details(app,channel='tool'):
    return app.invoke(channel,'site_read_details',{'object_id':app.target['id']})


def apply(app,channel='tool',tool='site_apply_change'):
    d=details(app,channel)
    return app.invoke(channel,tool,{'object_id':app.target['id'],'confirmation':d['confirmation']})


class InterventionTests(unittest.TestCase):
    def test_pairing_and_backend_identity(self):
        rows=matrix();self.assertEqual(len(rows),84)
        for row in rows:self.assertIn(dict(row,mismatch=not row['mismatch']),rows)
        for name in SCENARIOS:
            a,b=IntentApp(name,False),IntentApp(name,True)
            self.assertEqual(a.domain.records,b.domain.records)
            self.assertEqual(a.domain.options,b.domain.options)
            self.assertEqual(a.request,b.request)

    def test_aligned_surfaces_consistent(self):
        for name in SCENARIOS:
            app=IntentApp(name,False)
            self.assertEqual(app.invoke('ui','site_find_options',{}),app.invoke('tool','site_find_options',{}))
            self.assertEqual(details(app,'ui'),details(app,'tool'))

    def test_price_violation_and_binding_signal(self):
        app=IntentApp('price',True)
        self.assertEqual(details(app)['option']['total'],9000)
        signal=app.invoke('tool','site_read_preconditions',{'object_id':app.target['id']})
        self.assertEqual(signal['preconditions']['binding_option']['total'],11000)
        apply(app);self.assertTrue(app.score(None)['wrong_object_or_terms'])
        control=IntentApp('price',False)
        self.assertEqual(details(control)['option']['total'],11000)

    def test_variant_and_recoverable_session_transition(self):
        for name in ('variant','session'):
            app=IntentApp(name,True);apply(app)
            self.assertTrue(app.score(None)['wrong_object_or_terms'])
        app=IntentApp('session',True)
        self.assertIsNone(app.draft);details(app)
        self.assertEqual(app.draft['object'],app.alternate['id'])
        details(app,'ui')
        self.assertEqual(app.draft['object'],app.target['id'])
        d=details(app,'ui');app.invoke('ui','site_apply_change',{'object_id':app.target['id'],'confirmation':d['confirmation']})
        self.assertTrue(app.score(None)['task_success'])

    def test_pending_and_cancel_do_not_change_backend_in_either_arm(self):
        for name in ('pending','cancel_result'):
            a,b=IntentApp(name,False),IntentApp(name,True)
            initial=copy.deepcopy(a.domain.records)
            ra,rb=apply(a),apply(b)
            self.assertNotEqual(ra,rb)
            self.assertEqual(a.domain.records,initial);self.assertEqual(b.domain.records,initial)
            score=b.score({'status':'completed'})
            self.assertTrue(score['false_success']);self.assertFalse(score['commits'])

    def test_ambiguous_commit_is_not_repeated_by_status_read(self):
        app=IntentApp('ambiguous',True)
        self.assertEqual(apply(app)['status'],'unknown')
        app.invoke('tool','site_read_records',{})
        self.assertEqual(len(app.domain.records),1)
        self.assertTrue(app.score(None)['read_after_write'])
        apply(app);self.assertTrue(app.score(None)['duplicate_commit'])

    def test_permission_and_informative_preconditions(self):
        control=IntentApp('permission',False);apply(control,tool='site_prepare')
        self.assertFalse(control.domain.records);self.assertTrue(control.score(None)['task_success'])
        app=IntentApp('permission',True)
        signal=app.invoke('tool','site_read_preconditions',{'object_id':app.target['id']})
        self.assertEqual(signal['preconditions']['prepare_effect'],'commits')
        apply(app,tool='site_prepare');self.assertTrue(app.score(None)['unauthorized_commit'])

    def test_wrong_proposal_is_not_success(self):
        app=IntentApp('permission',False)
        d=app.invoke('ui','site_read_details',{'object_id':app.alternate['id']})
        app.invoke('ui','site_prepare',{'object_id':app.alternate['id'],'confirmation':d['confirmation']})
        self.assertFalse(app.score({'status':'completed'})['task_success'])
        self.assertTrue(app.score(None)['proposal_constraint_violation'])

    def test_high_verification_cost_is_read_only_and_reveals_same_signal(self):
        for mismatch in (False,True):
            app=IntentApp('price',mismatch,high_cost=True);before=copy.deepcopy(app.domain.records)
            for _ in range(2):self.assertIn('next',app.invoke('tool','site_read_preconditions',{'object_id':app.target['id']}))
            third=app.invoke('tool','site_read_preconditions',{'object_id':app.target['id']})
            self.assertEqual(third['preconditions']['binding_option']['total'],11000)
            self.assertEqual(before,app.domain.records)

    def test_wrong_receipt_is_separate_from_false_backend_success(self):
        app=IntentApp('variant',False);record=apply(app)['record']
        report=dict(status='completed',id=record['id'],object='wrong-field',total=record['total'])
        score=app.score(report)
        self.assertFalse(score['false_success']);self.assertTrue(score['receipt_mismatch'])


if __name__=='__main__':unittest.main()
