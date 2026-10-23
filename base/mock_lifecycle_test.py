"""Injected lifecycle demonstrations only; never contacts the Ollama server."""
import asyncio
import copy
from contextlib import suppress
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import httpx

CANONICAL = Path(os.environ.get("TOUCHLINE_REVIEW_REPO", Path(__file__).resolve().parent))
sys.path.insert(0, str(CANONICAL))
from local_selection import CandidateSelector, SelectionConfig

REQUEST = {"candidates": [
    {"candidate_id": "candidate_one", "explanation_type": "pressure_activity", "evidence_ids": ["e1", "e2"]},
    {"candidate_id": "candidate_two", "explanation_type": "shot_volume", "evidence_ids": ["e3", "e4"]},
]}


def catalog(count=2, evidence_count=1):
    return {"candidates": [
        {"candidate_id": f"candidate_{index}", "explanation_type": "pressure_activity",
         "evidence_ids": [f"event_{item}" for item in range(evidence_count)]}
        for index in range(count)]}


class CandidatePreflightTests(unittest.TestCase):
    def selector(self, **kwargs):
        return CandidateSelector(SelectionConfig(enabled=True, **kwargs),
                                 test_transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(AssertionError("No transport expected"))))

    def test_current_mode_minimum_and_catalog_boundaries(self):
        selector=self.selector()
        for count,status in ((0,'no_candidates'),(1,'insufficient_candidates'),(2,'eligible'),(8,'eligible'),(9,'invalid_request')):
            with self.subTest(count=count):
                result=selector.preflight(catalog(count))
                self.assertEqual(result['status'],status)
                self.assertEqual(result['eligible'],status=='eligible')
        self.assertTrue(self.selector(selection_mode='full_selection').preflight(catalog(1))['eligible'])
        explicit={'candidates':[],'snapshot':catalog(2)}
        self.assertEqual(selector.preflight(explicit)['status'],'no_candidates')
        self.assertTrue(selector.preflight({'snapshot':catalog(2)})['eligible'])

    def test_per_candidate_evidence_limits_and_duplicate_rules(self):
        selector=self.selector()
        for count in (1,24):
            with self.subTest(valid_evidence_count=count):
                # Sharing evidence across distinct candidates is valid.
                self.assertTrue(selector.preflight(catalog(2,count))['eligible'])
        for count in (0,25):
            with self.subTest(invalid_evidence_count=count):
                self.assertEqual(selector.preflight(catalog(2,count))['status'],'invalid_request')
        duplicate_evidence=catalog();duplicate_evidence['candidates'][0]['evidence_ids']=['e1','e1']
        duplicate_candidate=catalog();duplicate_candidate['candidates'][1]=copy.deepcopy(duplicate_candidate['candidates'][0])
        for value in (duplicate_evidence,duplicate_candidate):
            self.assertEqual(selector.preflight(value)['status'],'invalid_request')

    def test_invalid_schema_identifiers_and_snapshot_types_fail_without_exception(self):
        selector=self.selector()
        cases=[None,[],{}, {'snapshot':None},{'snapshot':[]},{'candidates':{}},{'candidates':[None]}]
        missing=catalog();del missing['candidates'][0]['explanation_type'];cases.append(missing)
        for field,value in (('candidate_id','bad/id'),('candidate_id','x'*97),('explanation_type',True),('evidence_ids',['bad/id'])):
            request=catalog();request['candidates'][0][field]=value;cases.append(request)
        for index,value in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(selector.preflight(value)['status'],'invalid_request')

    def test_catalog_byte_limit_counts_utf8_exactly(self):
        selector=self.selector()
        request=catalog();request['candidates'][0]['metrics']={'detail':''}
        def encoded(value):
            return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        padding=12000-len(encoded(selector.preflight(request)['candidates']))
        self.assertGreater(padding,1)
        request['candidates'][0]['metrics']['detail']='x'*padding
        accepted=selector.preflight(request)
        self.assertTrue(accepted['eligible']);self.assertEqual(len(encoded(accepted['candidates'])),12000)
        oversized=copy.deepcopy(request);oversized['candidates'][0]['metrics']['detail']+='x'
        self.assertEqual(selector.preflight(oversized)['status'],'invalid_request')
        multibyte=copy.deepcopy(request);multibyte['candidates'][0]['metrics']['detail']='x'*(padding-1)+'é'
        self.assertEqual(selector.preflight(multibyte)['status'],'invalid_request')

    def test_nonjson_nonfinite_and_cyclic_metrics_reject_without_budget_changes(self):
        selector=self.selector()
        cyclic={};cyclic['cycle']=cyclic
        for name,metrics in (('nan',{'bad':float('nan')}),('nonjson',{'bad':object()}),('cycle',cyclic)):
            with self.subTest(case=name):
                request=catalog();request['candidates'][0]['metrics']=metrics
                self.assertEqual(selector.preflight(request)['status'],'invalid_request')
                self.assertEqual(selector.budget_status()['attempts_started'],0)
                self.assertEqual(selector.budget_status()['wall_spent_ms'],0)

    def test_preflight_is_detached_pure_and_preserves_projection_policy(self):
        selector=self.selector()
        request=catalog();request['candidates'][0]['ignored']='not projected';request['candidates'][0]['metrics']={'count':3}
        original=copy.deepcopy(request);before=selector.budget_status()
        for _ in range(4):
            result=selector.preflight(request)
            self.assertTrue(result['eligible'])
            self.assertNotIn('ignored',result['candidates'][0])
            self.assertEqual(result['candidates'][0]['metrics'],{'count':3})
            result['candidates'][0]['evidence_ids'].append('detached')
        self.assertEqual(request,original)
        self.assertEqual(selector.budget_status(),before)
        self.assertFalse(selector._lock.locked())
        self.assertFalse(selector._inflight)
        self.assertFalse(selector._cleanup_failed)

    def test_actual_adapter_callback_rejects_large_engine_evidence_before_outer_attempt(self):
        from app_final import FinalDesk
        from touchline_core import load_events
        events=load_events(CANONICAL/'synthetic_match.jsonl')
        events += [{'id':f'extra_pressure_{index}','type':'pressure','at_ms':15000+index,
                    'team_id':'harbor','player_id':'harbor_7'} for index in range(25)]
        adapter=self.selector()
        select=Mock(side_effect=AssertionError('No model selector expected'))
        budget=Mock(side_effect=adapter.budget_status)
        with tempfile.TemporaryDirectory() as directory:
            desk=FinalDesk(events,Path(directory)/'preflight.sqlite3',selector=select,
                           model_until_ms=60000,clock=lambda:0,model_budget=budget,preflight=adapter.preflight)
            try:
                state=desk.control({'action':'pattern','operation_id':'pattern'})
                self.assertEqual(len(state['envelope']['snapshot']['candidates']),2)
                self.assertEqual(state['live_inference']['eligibility_status'],'invalid_request')
                self.assertIn('evidence IDs',state['live_inference']['eligibility_reason'])
                self.assertFalse(state['live_inference']['available'])
                tokens=len(desk.durable.controller.engine._requests)
                budget.reset_mock()
                for index in range(4):
                    operation=f'reject-{index}'
                    with self.assertRaisesRegex(ValueError,'invalid_request'):
                        desk.control({'action':'infer','operation_id':operation})
                    self.assertNotIn(operation,desk.operations)
                budget.assert_not_called();select.assert_not_called()
                self.assertEqual(desk.live_calls,0);self.assertEqual(desk.live_wall_ms,0)
                self.assertIsNone(desk.live_worker)
                self.assertEqual(len(desk.durable.controller.engine._requests),tokens)
                self.assertEqual(adapter.budget_status()['attempts_started'],0)
            finally:
                desk.close()


class AsyncPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_rejection_reuses_exact_preflight_status_without_dispatch_or_budget(self):
        calls=[]
        transport=httpx.MockTransport(lambda request:calls.append(request))
        selector=CandidateSelector(SelectionConfig(enabled=True),test_transport=transport)
        invalid=[catalog(0),catalog(1),catalog(9),catalog(2,25)]
        duplicate=catalog();duplicate['candidates'][1]['candidate_id']=duplicate['candidates'][0]['candidate_id'];invalid.append(duplicate)
        before=selector.budget_status()
        for request in invalid:
            eligibility=selector.preflight(request)
            for _ in range(4):
                result=await selector.select_candidate(request)
                self.assertEqual(result['status'],eligibility['status'])
                self.assertEqual(result['eligibility_reason'],eligibility['reason'])
                self.assertEqual(result['requests_dispatched'],0)
                self.assertEqual(result['budget'],before)
                self.assertEqual(result['trace'],[])
        self.assertEqual(calls,[])

    async def test_valid_two_candidate_sdk_path_uses_only_one_injected_dispatch(self):
        calls=[]
        def answer(request):
            calls.append(request)
            return httpx.Response(200,json={'model':'gemma4:12b','created_at':'2026-10-22T00:00:00Z',
                'message':{'role':'assistant','content':'{"candidate_id":"candidate_0"}'},
                'done':True,'done_reason':'stop','eval_count':8})
        selector=CandidateSelector(SelectionConfig(enabled=True),test_transport=httpx.MockTransport(answer))
        request=catalog(2)
        self.assertTrue(selector.preflight(request)['eligible'])
        result=await selector.select_candidate(request)
        self.assertEqual(result['status'],'selected',result)
        self.assertEqual(result['selection']['candidate_id'],'candidate_0')
        self.assertEqual(len(calls),1)
        self.assertEqual(result['requests_dispatched'],1)
        self.assertEqual(result['budget']['attempts_started'],1)
        self.assertEqual(result['budget']['real_calls_started'],0)


class MockBackendTransport(httpx.AsyncBaseTransport):
    """A fake backend may either honor disconnects or keep an independent task."""
    def __init__(self, honor_disconnect):
        self.honor_disconnect = honor_disconnect
        self.closed = False
        self.client_cancelled = False
        self.backend_stopped = False
        self.stop_owned_mock = asyncio.Event()
        self.backend_task = None

    async def backend(self):
        try:
            await self.stop_owned_mock.wait()
        finally:
            self.backend_stopped = True

    async def handle_async_request(self, request):
        self.backend_task = asyncio.create_task(self.backend())
        try:
            # Detached work represents a different process, not the HTTP caller.
            await asyncio.shield(self.backend_task)
            return httpx.Response(500, json={"error": "mock lifecycle ended"})
        except asyncio.CancelledError:
            self.client_cancelled = True
            if self.honor_disconnect:
                self.backend_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.backend_task
            raise

    async def aclose(self):
        self.closed = True

    async def finish_owned_mock(self):
        self.stop_owned_mock.set()
        if self.backend_task:
            with suppress(asyncio.CancelledError):
                await self.backend_task


class MockDisconnectLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, honor_disconnect):
        transport = MockBackendTransport(honor_disconnect)
        selector = CandidateSelector(SelectionConfig(enabled=True, timeout_s=.04), test_transport=transport)
        try:
            result = await selector.select_candidate(REQUEST)
            self.assertEqual(result["status"], "timeout", result)
            self.assertTrue(result["cleanup"]["client_closed"])
            self.assertTrue(result["cleanup"]["transport_closed"])
            self.assertTrue(transport.client_cancelled)
            self.assertEqual(result["budget"]["real_calls_started"], 0)
            self.assertIn("injected", result["evidence_mode"])
            self.assertEqual(result["cleanup"]["server_cancellation"], "not measured; no cancellation claim")
            return transport.backend_stopped
        finally:
            await transport.finish_owned_mock()

    async def test_cooperative_mock_backend_observes_disconnect(self):
        self.assertTrue(await self.exercise(honor_disconnect=True))

    async def test_detached_mock_backend_can_continue_after_client_closed(self):
        self.assertFalse(await self.exercise(honor_disconnect=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
