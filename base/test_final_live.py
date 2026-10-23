"""Optional final entry point: all selection calls are controlled mocks."""
import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

import app_final
from app_final import FinalDesk
from touchline_core import load_events

ROOT = Path(__file__).resolve().parent


def selected(request):
    candidate = next((row for row in request['candidates'] if row['explanation_type'] == 'shot_volume'), request['candidates'][0])
    return {'status': 'selected', 'selection': {key: copy.deepcopy(candidate[key]) for key in ('candidate_id', 'explanation_type', 'evidence_ids')},
            'trace': [{'source': 'test mock; no SDK execution'}], 'model_id': 'mock'}


class FinalLive(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.events = load_events(ROOT/'synthetic_match.jsonl')
        self.desks = []
        self.release = threading.Event()
        self.serial = 0
        self.now = int(time.time()*1000)

    def tearDown(self):
        self.release.set()
        for desk in self.desks:
            desk.close()
        self.temp.cleanup()

    def desk(self, selector=None, **kwargs):
        desk = FinalDesk(self.events, Path(self.temp.name)/f'{len(self.desks)}.sqlite3',
                         selector=selector, model_until_ms=self.now+60000,
                         clock=lambda: self.now, **kwargs)
        self.desks.append(desk)
        return desk

    def act(self, desk, action, **fields):
        self.serial += 1
        return desk.control({'action': action, 'operation_id': f'live-{self.serial}', **fields})

    def wait(self, desk):
        desk.live_worker.join(timeout=2)
        self.assertFalse(desk.live_worker.is_alive(), 'mock worker did not finish')
        return desk.state()

    def test_default_import_and_demo_never_import_provider(self):
        code = "import app_final,sys; assert 'local_selection' not in sys.modules; assert 'agent_framework' not in sys.modules; print('no SDK imported')"
        proc = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        desk = self.desk()
        self.act(desk, 'pattern')
        with self.assertRaises(ValueError): self.act(desk, 'infer')
        self.assertEqual(desk.state()['real_model_calls'], 0)
        self.assertFalse(desk.state()['live_inference']['enabled'])

    def test_explicit_one_call_is_idempotent_and_honestly_labelled(self):
        calls = []
        desk = self.desk(lambda request: (calls.append(request), selected(request))[1])
        self.act(desk, 'pattern')
        eligible=desk.state()['live_inference']
        self.assertTrue(eligible['available'])
        self.assertEqual(eligible['eligibility_status'],'eligible')
        value = {'action': 'infer', 'operation_id': 'one-live-request'}
        desk.control(value)
        state = self.wait(desk)
        desk.control(value)
        self.assertEqual(len(calls), 1)
        self.assertEqual(state['live_inference']['job']['status'], 'accepted')
        self.assertEqual(state['real_model_calls'], 1)
        self.assertIn('LIVE LOCAL', state['publication']['card']['replay_label'])
        self.assertEqual(state['publication']['facts']['through_ms'], 50000)
        self.assertEqual(state['historical_model_calls']['attempts'], 4)
        self.assertEqual(len(state['recorded_framework_trace']['receipts']), 2)
        self.assertEqual(state['live_inference']['job']['result']['model_id'], 'mock')

    def test_zero_and_one_candidate_rejections_preserve_attempts_tokens_and_worker(self):
        for through_ms,expected in ((0,'no_candidates'),(35000,'insufficient_candidates')):
            with self.subTest(through_ms=through_ms):
                calls=[]
                budget=Mock(return_value={'wall_spent_ms':0})
                desk=self.desk(lambda request:(calls.append(request),selected(request))[1],model_budget=budget)
                for _ in range(len(desk.durable.controller.times)):
                    if desk.state()['envelope']['through_ms']>=through_ms:break
                    self.act(desk,'next')
                state=desk.state()
                self.assertEqual(state['envelope']['through_ms'],through_ms)
                self.assertEqual(len(state['envelope']['snapshot']['candidates']),0 if through_ms==0 else 1)
                self.assertFalse(state['live_inference']['available'])
                self.assertEqual(state['live_inference']['eligibility_status'],expected)
                reason=state['live_inference']['eligibility_reason']
                tokens=len(desk.durable.controller.engine._requests)
                budget.reset_mock()
                for attempt in range(4):
                    value={'action':'infer','operation_id':f'rejected-{through_ms}-{attempt}'}
                    with self.assertRaisesRegex(ValueError,expected):desk.control(value)
                    self.assertNotIn(value['operation_id'],desk.operations)
                budget.assert_not_called()
                self.assertEqual(calls,[])
                self.assertEqual(desk.live_calls,0)
                self.assertEqual(desk.live_wall_ms,0)
                self.assertIsNone(desk.live_worker)
                self.assertEqual(desk.live_job,{'status':'idle'})
                self.assertEqual(len(desk.durable.controller.engine._requests),tokens)
                self.assertEqual(desk.state()['live_inference']['eligibility_reason'],reason)

    def test_configured_preflight_reason_is_shared_before_tokens_budget_or_dispatch(self):
        calls=[]
        seen=[]
        reason='Controlled catalog is outside the adapter evidence limit.'
        def preflight(request):
            seen.append(copy.deepcopy(request))
            return {'eligible':False,'status':'invalid_request','reason':reason}
        budget=Mock(return_value={'wall_spent_ms':0})
        desk=self.desk(lambda request:(calls.append(request),selected(request))[1],model_budget=budget,preflight=preflight)
        self.act(desk,'pattern')
        state=desk.state()
        self.assertFalse(state['live_inference']['available'])
        self.assertEqual(state['live_inference']['eligibility_reason'],reason)
        before=len(desk.durable.controller.engine._requests)
        budget.reset_mock()
        with self.assertRaisesRegex(ValueError,'invalid_request'):
            self.act(desk,'infer')
        budget.assert_not_called()
        self.assertEqual(calls,[])
        self.assertEqual(desk.live_calls,0)
        self.assertIsNone(desk.live_worker)
        self.assertEqual(len(desk.durable.controller.engine._requests),before)
        self.assertEqual(seen[-1]['candidates'],state['envelope']['snapshot']['candidates'])

    def test_intervening_commands_reject_callback_including_reset_aba(self):
        for command in ('correct', 'reset', 'view', 'recover'):
            with self.subTest(command=command):
                entered = threading.Event()
                release = threading.Event()
                def slow(request):
                    entered.set()
                    if not release.wait(2): raise RuntimeError('mock test barrier timed out')
                    return selected(request)
                desk = self.desk(slow)
                self.act(desk, 'pattern'); self.act(desk, 'infer')
                self.assertTrue(entered.wait(1))
                if command == 'view': self.act(desk, command, audience='analyst', language='es')
                else: self.act(desk, command)
                if command == 'reset': self.act(desk, 'pattern')
                release.set()
                state = self.wait(desk)
                self.assertEqual(state['live_inference']['job']['status'], 'stale_rejected')
                self.assertTrue(state['publication']['card']['fallback'])
                self.assertNotIn('LIVE LOCAL', state['publication']['card']['replay_label'])

    def test_one_inflight_and_timeout_fallback_without_retry(self):
        calls = []
        entered = threading.Event()
        def timeout(request):
            calls.append(request); entered.set(); self.release.wait(2)
            return {'status': 'timeout', 'selection': None, 'trace': []}
        desk = self.desk(timeout)
        self.act(desk, 'pattern'); self.act(desk, 'replay3'); self.act(desk, 'infer')
        self.assertTrue(entered.wait(1))
        with self.assertRaises(ValueError): self.act(desk, 'infer')
        self.release.set()
        state = self.wait(desk)
        self.assertEqual(state['live_inference']['job']['status'], 'timeout')
        self.assertTrue(state['publication']['card']['fallback'])
        self.assertEqual(len(calls), 1)
        self.assertFalse(state['live_inference']['server_cancellation_verified'])

    def test_four_attempt_budget_cannot_reset_with_match_or_recovery(self):
        desk = self.desk(selected)
        self.act(desk, 'pattern')
        for _ in range(4): self.act(desk, 'infer'); self.wait(desk)
        self.act(desk, 'reset'); self.act(desk, 'pattern'); self.act(desk, 'recover')
        with self.assertRaises(ValueError): self.act(desk, 'infer')
        self.assertEqual(desk.state()['live_inference']['attempts'], 4)
        self.assertTrue(desk.state()['publication']['card']['fallback'])

    def test_wall_budget_and_cutoff_fail_closed(self):
        desk = self.desk(selected, model_budget=lambda: {'wall_spent_ms': 49750, 'wall_budget_ms': 50000})
        self.act(desk, 'pattern')
        with self.assertRaises(ValueError): self.act(desk, 'infer')
        other = self.desk(selected)
        self.act(other, 'pattern')
        self.now += 60001
        with self.assertRaises(ValueError): self.act(other, 'infer')
        self.assertEqual(other.live_calls, 0)

    def test_failed_cleanup_disables_new_attempt_without_dispatch(self):
        desk = self.desk(selected, model_budget=lambda: {'wall_spent_ms': 0, 'cleanup_failed': True})
        self.act(desk, 'pattern')
        self.assertFalse(desk.state()['live_inference']['available'])
        with self.assertRaises(ValueError): self.act(desk, 'infer')
        self.assertEqual(desk.live_calls, 0)

    def test_explicit_actions_keep_their_label_after_an_accepted_live_job(self):
        desk = self.desk(selected)
        self.act(desk, 'pattern'); self.act(desk, 'infer'); self.wait(desk)
        injected = self.act(desk, 'timeout')
        self.assertIn('INJECTED TIMEOUT', injected['recorded_replay']['label'])
        recovered = self.act(desk, 'recover')
        self.assertIn('DURABLE REOPEN', recovered['recorded_replay']['label'])
        finished = self.act(desk, 'finish')
        self.assertIn('FINAL SYNTHETIC RECAP', finished['recorded_replay']['label'])

    def test_recorded_replay_and_expiry_never_become_live(self):
        desk = self.desk(selected)
        self.act(desk, 'pattern'); self.act(desk, 'infer'); self.wait(desk)
        recorded = self.act(desk, 'replay3')
        self.assertIn('RECORDED', recorded['publication']['card']['replay_label'])
        self.act(desk, 'infer')
        accepted = self.wait(desk)
        deadline = accepted['envelope']['expires_at_ms']+1
        desk.durable.clock = lambda: deadline
        desk.durable.controller.clock = lambda: deadline
        desk.durable.controller.engine._clock = lambda: deadline
        expired = desk.state()
        self.assertTrue(expired['publication']['card']['fallback'])
        self.assertNotIn('LIVE LOCAL', expired['recorded_replay']['label'])

    def test_reset_withholds_future_live_result_and_stale_callback_details(self):
        desk = self.desk(selected)
        self.act(desk, 'pattern'); self.act(desk, 'infer'); self.wait(desk)
        reset = self.act(desk, 'reset')
        self.assertEqual(reset['publication']['facts']['through_ms'], 0)
        self.assertNotIn('result', reset['live_inference']['job'])
        self.assertIn('result_withheld', reset['live_inference']['job'])
        # Even returning to the identical facts is a different replay epoch.
        self.assertNotIn('result', self.act(desk, 'pattern')['live_inference']['job'])
        entered = threading.Event()
        def slow(request):
            entered.set(); self.release.wait(2); return selected(request)
        other = self.desk(slow)
        self.act(other, 'pattern'); self.act(other, 'infer')
        self.assertTrue(entered.wait(1)); self.act(other, 'reset'); self.release.set()
        late = self.wait(other)
        self.assertEqual(late['live_inference']['job']['status'], 'stale_rejected')
        self.assertNotIn('result', late['live_inference']['job'])

    def test_durable_verification_fails_before_dispatch_and_before_publish(self):
        calls = []
        desk = self.desk(lambda request: (calls.append(request), selected(request))[1])
        self.act(desk, 'pattern')
        with patch.object(desk.durable, 'state', side_effect=RuntimeError('mock poisoned journal')):
            with self.assertRaises(RuntimeError): self.act(desk, 'infer')
        self.assertEqual(calls, [])
        self.assertEqual(desk.live_calls, 0)
        entered = threading.Event()
        def slow(request):
            entered.set(); self.release.wait(2); return selected(request)
        other = self.desk(slow)
        self.act(other, 'pattern'); self.act(other, 'infer'); self.assertTrue(entered.wait(1))
        with patch.object(other.durable, 'state', side_effect=RuntimeError('mock poisoned journal')):
            self.release.set(); other.live_worker.join(timeout=2)
            self.assertEqual(other.live_job['status'], 'durability_unavailable')
        self.assertTrue(other.state()['publication']['card']['fallback'])

    def test_fact_ids_and_english_companion_survive_live_language_view(self):
        desk = self.desk(selected)
        self.act(desk, 'pattern'); self.act(desk, 'infer')
        english = self.wait(desk)
        spanish = self.act(desk, 'view', audience='analyst', language='es')
        self.assertEqual(english['publication']['fact_id'], spanish['publication']['fact_id'])
        self.assertEqual(english['publication']['facts'], spanish['publication']['facts'])
        self.assertIn('Harbor Owls', spanish['publication']['card']['translation_en'])
        self.assertIn('LIVE LOCAL', spanish['publication']['card']['replay_label'])

    def test_invalid_or_exceptional_result_preserves_verified_fallback(self):
        def broken(_): raise RuntimeError('mock failure')
        for callback in (broken, lambda _: {'status': 'selected', 'selection': {'candidate_id': 'invented'}}):
            desk = self.desk(callback)
            self.act(desk, 'pattern'); self.act(desk, 'infer')
            state = self.wait(desk)
            self.assertTrue(state['publication']['card']['fallback'])
            self.assertIn(state['live_inference']['job']['status'], {'model_error', 'stale_or_invalid_rejected'})

    def test_opt_in_cli_constructs_fixed_local_adapter_but_does_not_call_it(self):
        calls = []
        adapters=[]
        class FakeConfig:
            def __init__(self, **kwargs): calls.append(('config', kwargs))
        class FakeAdapter:
            def __init__(self, config): calls.append(('adapter', config));adapters.append(self)
            def budget_status(self): return {'wall_spent_ms': 0}
            def preflight(self, request):
                raise AssertionError('startup ran request preflight')
            async def select_candidate(self, request): raise AssertionError('startup contacted provider')
        class FakeServer:
            def __init__(self, address, handler): calls.append(('server', address))
            def serve_forever(self): pass
            def server_close(self): pass
        args = ['app_final.py', '--enable-model', '--model-until-ms', str(self.now+10000), '--db-path', str(Path(self.temp.name)/'cli.sqlite3')]
        with patch.dict(sys.modules, {'local_selection': types.SimpleNamespace(CandidateSelector=FakeAdapter, SelectionConfig=FakeConfig)}), patch.object(app_final, 'ThreadingHTTPServer', FakeServer), patch.object(sys, 'argv', args):
            app_final.main()
        config = calls[0][1]
        self.assertEqual(config['max_calls'], 4)
        self.assertEqual(config['wall_budget_s'], 50)
        self.assertEqual(config['model_id'], 'gemma4:12b')
        self.assertNotIn('endpoint', config)  # adapter's literal loopback default
        self.assertEqual([row for row in calls if row[0] == 'server'][0][1][0], '127.0.0.1')
        self.assertEqual(app_final.Handler.controller.selector_preflight,adapters[0].preflight)


if __name__ == '__main__':
    unittest.main()
