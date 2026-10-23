"""Portable independent M3 checks. No provider calls; app source stays unchanged."""
import copy
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
SOURCE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import durable_controller
from durable_controller import DurableController, DurableIntegrityError, CommittedCommandError
from touchline_core import load_events, snapshot_at
from recap import build_recap, normalize_recorded_receipt
from app_m3 import Desk, Handler

class Clock:
    def __init__(self): self.value=100000
    def __call__(self): self.value+=1;return self.value

class Review(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'review.sqlite'
        self.events=load_events(SOURCE/'synthetic_match.jsonl');self.clock=Clock();self.controllers=[]
        self.receipts=[{'receipt_id':name,'receipt_bytes':(SOURCE/'evidence'/name).read_bytes()} for name in ('m2-third-ui-call.json','m2-fourth-ui-call.json')]
    def tearDown(self):
        for c in self.controllers:c.close()
        self.tmp.cleanup()
    def owner(self,**kwargs):
        c=DurableController(self.events,self.db,clock=self.clock,**kwargs);self.controllers.append(c);return c
    def test_future_correction_audit_does_not_expose_future_body(self):
        c=self.owner();s=c.control({'action':'correct'},'future-correction')
        self.assertEqual(s['envelope']['through_ms'],0)
        self.assertEqual(s['envelope']['provenance']['corrections'],[])
        self.assertEqual(s['recovery_audit']['corrections'],[])
    def test_retry_returns_present_state_without_rewind(self):
        c=self.owner();c.control({'action':'pattern'},'pattern');last=c.control({'action':'next'},'next')
        result=c.control({'action':'pattern'},'pattern')
        self.assertEqual(result['envelope']['through_ms'],last['envelope']['through_ms'])
        self.assertTrue(result['durability']['operation']['duplicate'])
        self.assertEqual(result['durability']['journal_count'],2)
    def test_operation_id_conflict_does_not_mutate(self):
        c=self.owner();s=c.control({'action':'pattern'},'same')
        with self.assertRaises(ValueError):c.control({'action':'correct'},'same')
        self.assertEqual(c.state()['envelope']['snapshot'],s['envelope']['snapshot'])
        self.assertEqual(c.state()['durability']['journal_count'],1)
    def test_stale_owner_read_and_write_fail_closed(self):
        first=self.owner();second=self.owner();first.control({'action':'pattern'},'first')
        with self.assertRaises(DurableIntegrityError):second.state()
        with self.assertRaises(DurableIntegrityError):second.control({'action':'next'},'stale')
    def test_precommit_exception_rolls_back(self):
        def fault(phase):
            if phase=='before_commit':raise RuntimeError('injected')
        c=self.owner(fault_hook=fault)
        with self.assertRaises(RuntimeError):c.control({'action':'pattern'},'precommit')
        self.assertEqual(c.state()['durability']['journal_count'],0)
        c.close();restored=self.owner();self.assertEqual(restored.state()['envelope']['through_ms'],0)
    def test_postcommit_exception_poisoned_until_reopen(self):
        def fault(phase):
            if phase=='after_commit_before_apply':raise RuntimeError('injected')
        c=self.owner(fault_hook=fault)
        with self.assertRaises(CommittedCommandError):c.control({'action':'pattern'},'postcommit')
        with self.assertRaises(CommittedCommandError):c.state()
        c.close();restored=self.owner();self.assertEqual(restored.state()['envelope']['through_ms'],50000)
        self.assertEqual(restored.state()['durability']['journal_count'],1)
    def test_actual_recorded_selection_never_restored(self):
        c=self.owner();c.control({'action':'pattern'},'pattern')
        hist=normalize_recorded_receipt(**self.receipts[0])
        request=c.controller.engine.selection_request('casual','en')
        c.controller.engine.apply_selection(request,hist['selection'])
        selected=c.state();self.assertFalse(selected['publication']['card']['fallback'])
        c.control({'action':'view','audience':'analyst','language':'es'},'view')
        c.close();recovered=self.owner().state()
        self.assertTrue(recovered['publication']['card']['fallback'])
        self.assertEqual(recovered['model_job']['status'],'recovered_fallback')
        self.assertNotEqual(recovered['publication']['stream_id'],selected['publication']['stream_id'])
        self.assertEqual(recovered['audience'],'analyst');self.assertEqual(recovered['language'],'es')
    def test_tail_deletion_rejected(self):
        c=self.owner();c.control({'action':'pattern'},'pattern');c.close()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('DELETE FROM commands');db.commit()
        with self.assertRaises(DurableIntegrityError):self.owner()
    def test_wrong_fixture_rejected(self):
        c=self.owner();c.close();events=copy.deepcopy(self.events);events[-1]['at_ms']+=1
        with self.assertRaises(DurableIntegrityError):DurableController(events,self.db,clock=self.clock)
    def test_runtime_source_change_rejected(self):
        # Mock only the fingerprint boundary. The original isolated review also
        # exercised a real source-file edit; this judge test must not alter code.
        c=self.owner(); changed=dict(durable_controller._sources())
        changed['app_m2']='0'*64
        with patch.object(durable_controller, '_sources', return_value=changed):
            with self.assertRaises(DurableIntegrityError):c.state()
    def test_recorded_receipt_tamper_rejected(self):
        row=self.receipts[0]
        with self.assertRaises(ValueError):normalize_recorded_receipt(row['receipt_id'],row['receipt_bytes']+b' ')
    def test_future_recorded_facts_withheld(self):
        c=self.owner();s=c.state();r=build_recap(s['envelope']['snapshot'],s['envelope']['provenance'],self.receipts)
        self.assertEqual(r['through_ms'],0);self.assertEqual(r['recorded_moment_count'],0)
        self.assertEqual(r['withheld_recorded_receipt_count'],2)
        self.assertEqual(r['recorded_selections'],[])
        self.assertNotIn('e010',r['evidence_ids'])
    def test_two_receipts_are_one_distinct_moment(self):
        c=self.owner();s=c.control({'action':'pattern'},'pattern');r=build_recap(s['envelope']['snapshot'],s['envelope']['provenance'],self.receipts)
        self.assertEqual(r['recorded_receipt_count'],2);self.assertEqual(r['recorded_moment_count'],1)
    def test_corrected_score_and_still_supported_shot_pattern_are_separate(self):
        c=self.owner();c.control({'action':'pattern'},'pattern');s=c.control({'action':'correct'},'correct')
        r=build_recap(s['envelope']['snapshot'],s['envelope']['provenance'],self.receipts)
        self.assertEqual(r['facts']['teams'][0]['totals']['goals'],0)
        self.assertEqual(len(r['withdrawn_claims']),1)
        self.assertEqual(r['withdrawn_claims'][0]['event_id'],'e010')
        self.assertEqual(r['recorded_selections'][0]['changed_evidence_ids'],['e010'])
        self.assertTrue(r['recorded_selections'][0]['claim_supported_after_corrections'])
    def test_forged_recap_numbers_rejected(self):
        snapshot=json.loads(json.dumps(snapshot_at(self.events,50000)));snapshot['stats']['total']['teams']['harbor']['goals']=999
        with self.assertRaises(ValueError):build_recap(snapshot)

class DeskReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'desk.sqlite'
        self.desk=Desk(load_events(SOURCE/'synthetic_match.jsonl'),self.db)
    def tearDown(self):
        self.desk.durable.close();self.tmp.cleanup()
    def action(self,action,operation_id=None):
        return self.desk.control({'action':action,'operation_id':operation_id or action})
    def test_recorded_replay_exact_original_facts_only(self):
        with self.assertRaises(ValueError):self.action('replay3')
        self.action('pattern');s=self.action('replay3')
        self.assertFalse(s['publication']['card']['fallback'])
        self.assertIn('RECORDED',s['publication']['card']['replay_label'])
        self.assertEqual(s['live_model_calls_this_milestone'],0)
    def test_recorded_replay_after_correction_rejected(self):
        self.action('pattern');self.action('correct')
        with self.assertRaises(ValueError):self.action('replay3')
        self.assertEqual(self.desk.state()['publication']['facts']['score']['Harbor Owls'],0)
    def test_duplicate_replay_operation_does_not_renew_ttl(self):
        self.action('pattern');first=self.action('replay3');second=self.action('replay3')
        self.assertEqual(first['publication']['expires_at_ms'],second['publication']['expires_at_ms'])
        self.assertEqual(first['publication']['sequence'],second['publication']['sequence'])
    def test_conflicting_transient_operation_rejected(self):
        self.action('pattern');self.action('replay3','same')
        with self.assertRaises(ValueError):self.action('timeout','same')
    def test_recovery_discards_recorded_insight_and_preserves_correction(self):
        self.action('pattern');old=self.action('replay3');self.action('correct');s=self.action('recover')
        self.assertTrue(s['publication']['card']['fallback'])
        self.assertEqual(s['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertNotEqual(s['publication']['stream_id'],old['publication']['stream_id'])
        self.assertEqual(s['publication']['facts']['score']['Harbor Owls'],0)
    def test_finish_recap_preserves_late_correction(self):
        self.action('pattern');self.action('correct');s=self.action('finish')
        self.assertEqual(s['envelope']['through_ms'],130000)
        self.assertEqual(s['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
        self.assertEqual(s['recap']['recorded_receipt_count'],2)
        self.assertEqual(s['recap']['recorded_moment_count'],1)
    def test_injected_timeout_uses_fallback_and_no_provider(self):
        self.action('pattern');self.action('replay3');s=self.action('timeout')
        self.assertTrue(s['publication']['card']['fallback'])
        self.assertEqual(s['model_job']['status'],'timeout')
        self.assertTrue(s['model_job']['injected'])
        self.assertNotIn('local_selection',sys.modules)

class HandlerReview(unittest.TestCase):
    def request(self,error):
        class Harness(Handler):
            def __init__(self):
                self.server=SimpleNamespace(server_port=8770)
                data=json.dumps({'action':'pattern','operation_id':'id'}).encode()
                self.headers={'Host':'127.0.0.1:8770','Origin':'http://127.0.0.1:8770','Content-Type':'application/json','Content-Length':str(len(data))}
                self.path='/api/control';self.rfile=io.BytesIO(data)
                class Unavailable:
                    def control(self,value):raise error
                self.controller=Unavailable()
            def _reply(self,status,data,content_type=None):self.reply=(status,data)
        handler=Harness();handler.do_POST();return handler.reply
    def test_integrity_failure_structured_503(self):
        code,data=self.request(DurableIntegrityError('tamper'))
        self.assertEqual(code,503);self.assertIn('reopen',data['error'])
    def test_commit_uncertainty_not_presented_uncommitted(self):
        code,data=self.request(CommittedCommandError('committed'))
        self.assertEqual(code,503);self.assertIs(data['committed'],True)

if __name__=='__main__':unittest.main(verbosity=2)
