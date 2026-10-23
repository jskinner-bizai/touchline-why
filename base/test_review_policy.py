"""Offline timeout/recovery copy policy, separate from durable match authority."""
import copy
from pathlib import Path
import tempfile
import unittest

from app_advisory import AdvisoryDesk
from touchline_core import load_events

ROOT = Path(__file__).resolve().parent


class ReviewInvalidationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.desk = AdvisoryDesk(load_events(ROOT / 'synthetic_match.jsonl'),
                                 Path(self.scratch.name) / 'desk.sqlite')
        self.sequence = 0
        self.command('pattern')

    def tearDown(self):
        self.desk.close()
        self.scratch.cleanup()

    def command(self, action, **fields):
        self.sequence += 1
        return self.desk.control({'action': action, 'operation_id': f'policy-{self.sequence}', **fields})

    def approve(self, case_id='P03'):
        state = self.command('review_copy', case_id=case_id)
        advice_id = state['copy_review']['advice']['advice_id']
        self.sequence += 1
        command = {'action': 'approve_copy', 'advice_id': advice_id,
                   'operation_id': f'policy-{self.sequence}'}
        approved = self.desk.control(command)
        self.assertIsNotNone(approved['copy_review']['producer_copy_draft'])
        return approved, command

    def assert_cleared(self, state):
        self.assertEqual(state['copy_review']['status'], 'cleared')
        self.assertIsNone(state['copy_review']['advice'])
        self.assertIsNone(state['copy_review']['producer_copy_draft'])
        self.assertEqual(state['copy_review']['new_provider_requests'], 0)

    def test_timeout_clears_approved_copy_without_changing_facts(self):
        approved, approval = self.approve()
        snapshot = copy.deepcopy(approved['envelope']['snapshot'])
        state = self.command('timeout')
        self.assert_cleared(state)
        self.assertEqual(state['envelope']['snapshot'], snapshot)
        self.assert_cleared(self.desk.control(approval))

    def test_timeout_clears_unapproved_advice(self):
        self.command('review_copy', case_id='P03')
        self.assert_cleared(self.command('timeout'))

    def test_timeout_retry_does_not_restore_copy(self):
        self.approve()
        timeout = {'action': 'timeout', 'operation_id': 'policy-timeout-retry'}
        self.assert_cleared(self.desk.control(timeout))
        self.assert_cleared(self.desk.control(timeout))
        self.assert_cleared(self.desk.state())

    def test_new_review_after_timeout_is_not_cleared_by_old_retry(self):
        self.approve()
        timeout = {'action': 'timeout', 'operation_id': 'policy-old-timeout'}
        self.desk.control(timeout)
        approved, _ = self.approve()
        retried = self.desk.control(timeout)
        self.assertEqual(retried['copy_review']['producer_copy_draft'],
                         approved['copy_review']['producer_copy_draft'])

    def test_recover_explicitly_clears_copy_and_preserves_approved_correction(self):
        self.command('correct')
        approved, approval = self.approve('P04')
        snapshot = copy.deepcopy(approved['envelope']['snapshot'])
        self.assertEqual(approved['copy_review']['advice']['raw_reason'], 'contradicted_fact')
        self.assertEqual(approved['copy_review']['advice']['deterministic_classification']['reason'],
                         'stale_revision')
        state = self.command('recover')
        self.assert_cleared(state)
        self.assertEqual(state['envelope']['snapshot'], snapshot)
        self.assertEqual(state['envelope']['provenance']['event_revisions']['e010'], 2)
        self.assertFalse(next(event for event in snapshot['events'] if event['id'] == 'e010')['goal'])
        self.assert_cleared(self.desk.control(approval))
        self.assertEqual(state['copy_review']['evaluation']['status'], 'NO_GO')
        self.assertEqual(state['copy_review']['evaluation']['strict_passes'], 3)
        self.assertEqual(state['copy_review']['evaluation']['total'], 4)

    def test_recover_clears_unapproved_advice(self):
        self.command('review_copy', case_id='P03')
        self.assert_cleared(self.command('recover'))

    def test_rejected_timeout_does_not_discard_current_approval(self):
        approved, _ = self.approve()
        with self.assertRaises(ValueError):
            self.command('timeout', unexpected=True)
        self.assertEqual(self.desk.state()['copy_review']['producer_copy_draft'],
                         approved['copy_review']['producer_copy_draft'])

    def test_conflicting_recovery_id_does_not_discard_current_approval(self):
        approved, _ = self.approve()
        with self.assertRaises(ValueError):
            self.desk.control({'action': 'recover', 'operation_id': 'policy-1'})
        self.assertEqual(self.desk.state()['copy_review']['producer_copy_draft'],
                         approved['copy_review']['producer_copy_draft'])

    def test_poll_and_overlay_republication_keep_current_copy(self):
        approved, _ = self.approve()
        for _ in range(3):
            state = self.desk.state()
            self.assertEqual(state['copy_review']['producer_copy_draft'],
                             approved['copy_review']['producer_copy_draft'])


if __name__ == '__main__':
    unittest.main()
