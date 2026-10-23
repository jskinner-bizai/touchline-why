"""Offline composition checks: no sockets, SDK import, or provider calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from app_advisory import AdvisoryDesk
from touchline_core import load_events

ROOT = Path(__file__).resolve().parent


class AdvisoryCompositionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.db = Path(self.scratch.name) / 'desk.sqlite'
        self.desk = AdvisoryDesk(load_events(ROOT / 'synthetic_match.jsonl'), self.db)
        self.counter = 0

    def tearDown(self):
        self.desk.close()
        self.scratch.cleanup()

    def command(self, action, **fields):
        self.counter += 1
        return self.desk.control({'action': action, 'operation_id': 'test-' + str(self.counter), **fields})

    def test_default_has_no_live_selector_or_provider_calls(self):
        state = self.desk.state()
        self.assertFalse(state['live_inference']['enabled'])
        self.assertEqual(state['real_model_calls'], 0)
        self.assertFalse(state['copy_review']['live_available'])
        self.assertIsNone(self.desk.selector)

    def test_no_early_review_or_future_advice(self):
        self.assertIsNone(self.desk.state()['copy_review']['advice'])
        with self.assertRaises(ValueError):
            self.command('review_copy', case_id='P03')
        self.assertIsNone(self.desk.state()['copy_review']['producer_copy_draft'])

    def test_review_approval_never_mutate_facts_or_overlay(self):
        before = self.command('pattern')
        snapshot = copy.deepcopy(before['envelope']['snapshot'])
        publication = copy.deepcopy(before['publication'])
        reviewed = self.command('review_copy', case_id='P03')
        self.assertIsNone(reviewed['copy_review']['producer_copy_draft'])
        advice = reviewed['copy_review']['advice']
        approved = self.command('approve_copy', advice_id=advice['advice_id'])
        self.assertIsNotNone(approved['copy_review']['producer_copy_draft'])
        self.assertEqual(approved['envelope']['snapshot'], snapshot)
        self.assertEqual(approved['publication'], publication)
        self.assertEqual(approved['real_model_calls'], 0)

    def test_copy_operation_ids_cannot_cross_core_command_boundary(self):
        self.desk.control({'action': 'pattern', 'operation_id': 'core-id'})
        with self.assertRaises(ValueError):
            self.desk.control({'action': 'review_copy', 'case_id': 'P03', 'operation_id': 'core-id'})
        self.desk.control({'action': 'review_copy', 'case_id': 'P03', 'operation_id': 'copy-id'})
        with self.assertRaises(ValueError):
            self.desk.control({'action': 'reset', 'operation_id': 'copy-id'})

    def test_durable_correction_and_recap_survive_advisory_restart(self):
        self.command('pattern')
        self.command('correct')
        reviewed = self.command('review_copy', case_id='P04')
        self.command('approve_copy', advice_id=reviewed['copy_review']['advice']['advice_id'])
        self.desk.close()
        self.desk = AdvisoryDesk(load_events(ROOT / 'synthetic_match.jsonl'), self.db)
        state = self.desk.state()
        self.assertIsNone(state['copy_review']['advice'])
        self.assertIsNone(state['copy_review']['producer_copy_draft'])
        self.assertEqual(state['envelope']['provenance']['event_revisions']['e010'], 2)
        self.assertFalse(next(row for row in state['envelope']['snapshot']['events'] if row['id'] == 'e010')['goal'])

    def test_no_sdk_import_in_recorded_entry_point(self):
        result = subprocess.run([sys.executable, '-B', '-c',
            "import sys;import app_advisory;assert not any(n=='agent_framework' or n.startswith('agent_framework.') or n=='ollama' for n in sys.modules)"],
            cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
