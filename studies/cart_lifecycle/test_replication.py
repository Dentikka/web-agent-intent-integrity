"""Replication safety and portability tests: no model API calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import replicate
from bounded_api import Ledger, StopRun
from runtime_support import php_command


def configuration() -> dict:
    model = dict(id='gpt-test', base_url='https://provider.example/v1', key_env='TEST_KEY',
                 input_per_million=1, output_per_million=2,
                 byte_token_bound_verified=True, max_output_tokens=768)
    return dict(models=[model, dict(model, id='claude-test')],
                budget_usd=20, hours=1, workers=1, max_turns=14, workspace='.')


class ReplicationTests(unittest.TestCase):
    def test_frozen_design_and_replacement_count(self):
        result = replicate.plan(configuration(), list(replicate.STAGES))
        self.assertEqual(result['total_model_episodes'], 588)
        self.assertEqual(result['research_per_model'], 288)
        self.assertEqual(result['episodes_per_model'], replicate.COUNTS)
        for stage in replicate.STAGES:
            cells = replicate.design(stage)
            self.assertEqual(len(cells), len({json.dumps(c, sort_keys=True) for c in cells}))
            reference = json.loads(Path(__file__).with_name('reference-designs.json').read_text())
            digest = hashlib.sha256(json.dumps(cells, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(digest, reference[stage]['sha256'])

    def test_invalid_budget_and_credentials_fail_before_run(self):
        for value in (float('nan'), float('inf'), 0, -1, 21):
            cfg = configuration(); cfg['budget_usd'] = value
            with self.assertRaises(ValueError):
                replicate.validate(cfg, paid=True)
        cfg = configuration(); cfg['models'][0]['extra_body'] = {'api_key': 'not-a-real-key'}
        with self.assertRaises(ValueError):
            replicate.validate(cfg)

    def test_provider_cap_and_endpoint_validation(self):
        for change in ({'base_url': 'http://provider.example/v1'},
                       {'base_url': 'https://openrouter.ai/api/v1'},
                       {'byte_token_bound_verified': False},
                       {'input_per_million': float('nan')},
                       {'extra_body': {'tools': []}}):
            cfg = configuration(); cfg['models'][0].update(change)
            with self.assertRaises(ValueError):
                replicate.validate(cfg, paid=True)

    def test_global_budget_allocated_once_across_models(self):
        allocations = {}
        with tempfile.TemporaryDirectory() as temp:
            def fake_run(cfg, root, stage, *args):
                root.mkdir(parents=True, exist_ok=True)
                allocations.setdefault(str(root), cfg['budget_usd'])
                (root / stage).mkdir(exist_ok=True)
                (root / stage / 'summary.json').write_text('{"complete": true}')
            with patch.object(replicate.drift_runner, 'run', side_effect=fake_run):
                replicate.run(configuration(), Path(temp), list(replicate.STAGES))
        self.assertEqual(len(allocations), 2)
        self.assertEqual(sum(allocations.values()), 20)

    def test_failed_smoke_stops_later_stages_and_models(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            def fail(cfg, root, stage, *args):
                calls.append(stage); (root / stage).mkdir(parents=True)
                (root / stage / 'summary.json').write_text('{"complete": false}')
            with patch.object(replicate.drift_runner, 'run', side_effect=fail):
                with self.assertRaises(StopRun):
                    replicate.run(configuration(), Path(temp), list(replicate.STAGES))
        self.assertEqual(calls, ['smoke'])

    def test_plan_does_not_read_credentials_or_call_api(self):
        with patch.object(replicate.drift_runner, 'api', side_effect=AssertionError('Network called')):
            cfg = configuration(); cfg['models'][0]['key_file'] = '/missing/key/file'
            self.assertEqual(replicate.plan(cfg, ['main'])['total_model_episodes'], 240)

    def test_portable_php_keeps_process_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'php'; binary.touch()
            with patch.dict(os.environ, {'DRIFT_PHP_BINARY': str(binary)}):
                command = php_command(Path(temp), Path(temp) / 'fixture.php', 'site', 'db')
            self.assertIn('allow_url_fopen=0', command)
            self.assertTrue(any(x.startswith('disable_functions=mail,') for x in command))
            self.assertEqual(command[-2:], ['site', 'db'])

    def test_unknown_charge_prevents_a_new_stage(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            cfg = dict(budget_usd=1, hours=1, started_epoch=time.time())
            ledger = Ledger(Path(temp), cfg); ledger.reserve('interrupted', .1); ledger.db.close()
            with self.assertRaises(StopRun):
                Ledger(Path(temp), cfg)

    def test_explicit_allocations_cannot_increase_the_total(self):
        cfg = configuration()
        cfg['models'][0]['budget_usd'] = 8
        cfg['models'][1]['budget_usd'] = 12
        replicate.validate(cfg)
        self.assertEqual(replicate.allocations(cfg), [8, 12])
        cfg['models'][1]['budget_usd'] = 13
        with self.assertRaises(ValueError):
            replicate.validate(cfg)


if __name__ == '__main__':
    unittest.main()
