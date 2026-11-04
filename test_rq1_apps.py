"""Checks of aligned semantics, independent domain transitions and factor isolation."""
import unittest

from rq1_apps import App,CONDITIONS,DOMAINS
from rq1_runner import matrix


class RQ1Tests(unittest.TestCase):
    def test_full_details_match_across_channels_and_factors(self):
        for name in DOMAINS:
            baseline=App(name,'aligned')
            for condition in CONDITIONS:
                app=App(name,condition)
                for option in app.domain.options:
                    results=[]
                    for channel in ('ui','tool'):
                        for _ in range(3 if condition==channel+'_cost' else 1):
                            details=app.invoke(channel,'site_read_details',{'object_id':option['id']})
                        results.append(details)
                    self.assertEqual(results[0],results[1])
                    self.assertEqual(results[0]['option'],next(o for o in baseline.domain.options if o['id']==option['id']))
                self.assertEqual(app.domain.records,baseline.domain.records)

    def test_summary_omits_fields_without_changing_values(self):
        for name in DOMAINS:
            for channel in ('ui','tool'):
                app=App(name,channel+'_summary')
                self.assertTrue(all(set(o)=={'id','name','total'} for o in app.options(channel)))
                other='tool' if channel=='ui' else 'ui'
                self.assertTrue(all(len(o)>3 for o in app.options(other)))

    def test_exact_reference_required_and_shared(self):
        app=App('store','aligned');option=app.domain.options[0]
        self.assertIn('error',app.invoke('tool','site_apply_change',{'object_id':option['id'],'confirmation':'missing'}))
        details=app.invoke('ui','site_read_details',{'object_id':option['id']})
        app.invoke('tool','site_apply_change',{'object_id':option['id'],'confirmation':details['confirmation']})
        self.assertEqual(app.invoke('ui','site_read_records',{})['records'],app.domain.records)

    def test_wrong_domain_options_do_not_satisfy_request(self):
        for name in DOMAINS:
            for i in range(4):
                app=App(name,'aligned');option=app.domain.options[i]
                app.domain.apply(option)
                correct=(name=='store' and option.get('litres')==28 and option.get('waterproof') or
                         name=='booking' and option.get('date')=='test-day-A' and option.get('start')=='17:00' or
                         name=='subscription' and option.get('action')=='cancel_at_period_end')
                self.assertEqual(app.domain.success(),bool(correct),(name,option))

    def test_matrix_pairing(self):
        rows=matrix({});self.assertEqual(len(rows),54)
        for row in rows:
            for mode in ('ui','tool','hybrid'):self.assertIn(dict(row,mode=mode),rows)
        self.assertEqual(len(matrix({'seeds':[0,1]})),108)


if __name__=='__main__':unittest.main()
