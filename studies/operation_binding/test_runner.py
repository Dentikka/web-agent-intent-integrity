"""Budget, isolation and decision-context tests; no provider or PHP calls."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import run
from design import score


def configuration():
    model = dict(id='model-a', base_url='https://provider.example/v1', key_env='MODEL_TEST_KEY',
                 input_per_million=1, output_per_million=2, byte_token_bound_verified=True,
                 max_output_tokens=768)
    return dict(models=[model, dict(model, id='model-b')], budget_usd=5, hours=1,
                workers=1, max_turns=4, workspace='.', base_database='unused', runtime_wp_site='unused')


class LauncherTests(unittest.TestCase):
    def test_bad_model_arguments_are_visible_errors_without_execution(self):
        from binding_app import BindingApp
        self.assertIsNotNone(BindingApp.action_error('site_checkout', {'operation_id': 'invented'}))
        self.assertIsNotNone(BindingApp.action_error('ui_click', {'id': 7}))
        self.assertIsNone(BindingApp.action_error('site_checkout', {}))
        self.assertIsNone(BindingApp.action_error('ui_click', {'id': 'checkout'}))

    def test_analysis_does_not_create_a_missing_ledger(self):
        import sqlite3
        from analyze import analyze
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp)/'model-1'
            model.mkdir()
            (model/'config.json').write_text('{"model":{"id":"test"}}')
            with self.assertRaises(sqlite3.OperationalError):
                analyze(Path(tmp))
            self.assertFalse((model/'usage.sqlite').exists())

    def test_loopback_server_does_not_consult_reverse_dns(self):
        from binding_app import serve_local
        with patch('socket.getfqdn', side_effect=AssertionError('Reverse DNS requested')):
            server = serve_local(FakeApp())
            try:
                self.assertEqual(server.server_name, 'localhost')
                self.assertGreater(server.server_port, 0)
            finally:
                server.shutdown()
                server.server_close()

    def test_plan_research_and_smoke_counts_without_credentials(self):
        cfg = configuration()
        cfg['models'][0]['key_file'] = '/missing/key'
        with patch.object(run, 'api', side_effect=AssertionError('API called')):
            self.assertEqual(run.plan(cfg, ['receipt', 'consent'])['total_model_episodes'], 224)
            self.assertEqual(run.plan(cfg, ['smoke', 'receipt', 'consent'])['total_model_episodes'], 228)

    def test_budget_is_shared_across_stages_not_multiplied(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            def stage(cfg, root, name, sources):
                calls.append((str(root), cfg['budget_usd'], name, cfg['started_epoch']))
                return {'complete': True}
            with patch.object(run, 'run_stage', side_effect=stage):
                run.run(configuration(), Path(tmp), ['smoke', 'receipt', 'consent'])
        self.assertEqual(len(calls), 6)
        self.assertEqual(len({x[3] for x in calls}), 1)
        self.assertEqual(sum({x[0]: x[1] for x in calls}.values()), 5)

    def test_technical_smoke_failure_stops_before_research(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            def stage(cfg, root, name, sources):
                calls.append(name)
                return {'complete': False}
            with patch.object(run, 'run_stage', side_effect=stage):
                with self.assertRaises(run.StopRun):
                    run.run(configuration(), Path(tmp), ['smoke', 'receipt', 'consent'])
        self.assertEqual(calls, ['smoke'])


CURRENT = dict(operation_id='op-current', subject=7, product_id=3, quantity=1,
               currency='USD', total_minor=1800)
ORDER = dict(order_id=5, operation_id='op-current', role='current', subject=7,
             items=[dict(product_id=3, quantity=1)], currency='USD', total_minor=1800, paid=False)


class FakeApp:
    def __init__(self, *args):
        self.current = CURRENT
        self.request = 'Verify this operation'
        self.initial = {}
        self.events = []

    def outcome(self, report, prior):
        return score(CURRENT, [ORDER], True, report, prior, 'receipt')

    def snapshot(self):
        return {}


class FakeSurface:
    def __init__(self, *args):
        pass

    def schemas(self):
        return [{'function': {'name': n}} for n in ('site_receipt', 'finish')]

    def act(self, *args):
        return {'receipt': dict(operation_id='op-current', subject=7, orders=[ORDER])}

    def close(self):
        pass


def call(name, args, identifier):
    return dict(id=identifier, type='function', function=dict(name=name, arguments=json.dumps(args)))


class DecisionContextTests(unittest.TestCase):
    def run_actor(self, responses):
        browser = type('Browser', (), {'version': 'test-native'})()
        def api(*args):
            return dict(model='model-a', choices=[dict(message=dict(role='assistant', content=None,
                                                                   tool_calls=responses.pop(0)))])
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(workspace='.', model={'id': 'model-a'}, max_turns=4)
            cell = dict(series='receipt', evidence='foreign', route='cross', policy='baseline', repeat=0)
            with patch.object(run, 'BindingApp', FakeApp), patch.object(run, 'BindingSurface', FakeSurface), patch.object(run, 'api', side_effect=api):
                return run.episode(browser, cell, cfg, Path(tmp)/'episode', None, threading.Event())

    def test_read_and_finish_in_one_response_is_not_prior_evidence(self):
        finish = dict(status='completed', order_id=5, message='Verified')
        r = self.run_actor([[call('site_receipt', {}, 'read'), call('finish', finish, 'done')]])
        self.assertIsNone(r['error'])
        self.assertTrue(r['scores']['unsupported_completed'])
        self.assertFalse(r['scores']['grounded_completed'])

    def test_returned_record_in_previous_turn_supports_finish(self):
        finish = dict(status='completed', order_id=5, message='Verified')
        r = self.run_actor([[call('site_receipt', {}, 'read')], [call('finish', finish, 'done')]])
        self.assertIsNone(r['error'])
        self.assertTrue(r['scores']['grounded_completed'])


if __name__ == '__main__':
    unittest.main()
