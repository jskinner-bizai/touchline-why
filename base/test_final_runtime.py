"""Finalization regressions; no model client, browser or provider calls."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import app_m3
from app_m3 import Desk
from touchline_core import load_events
from durable_controller import DurableController

ROOT=Path(__file__).resolve().parent

class FinalRuntime(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'runtime.sqlite3'
        self.events=load_events(ROOT/'synthetic_match.jsonl')
        self.desk=Desk(self.events,self.db)
        self.serial=0
    def tearDown(self):
        self.desk.durable.close();self.temp.cleanup()
    def act(self,action,**fields):
        self.serial+=1
        return self.desk.control({'action':action,'operation_id':f'final-{self.serial}',**fields})
    def test_recorded_availability_tracks_exact_facts(self):
        self.assertFalse(self.desk.state()['recorded_replay']['available'])
        self.assertTrue(self.act('pattern')['recorded_replay']['available'])
        corrected=self.act('correct')
        self.assertFalse(corrected['recorded_replay']['available'])
        self.assertIn('corrections survive reset and rewind',corrected['recorded_replay']['unavailable_reason'])
        self.act('reset')
        rewound=self.act('pattern')
        self.assertFalse(rewound['recorded_replay']['available'])
        self.assertEqual(rewound['publication']['facts']['score']['Harbor Owls'],0)
        self.assertEqual(rewound['envelope']['provenance']['event_revisions']['e010'],2)
    def test_legacy_entrypoint_fails_clearly_without_starting_a_server_or_model(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'app_m2.py'),'--enable-model'],
                              capture_output=True,text=True,timeout=3)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn('controller library, not a standalone app',result.stderr)
        self.assertIn('app_m3.py --db-path',result.stderr)
    def test_expired_recording_desk_label_matches_fallback(self):
        self.act('pattern');recorded=self.act('replay3')
        now=recorded['envelope']['expires_at_ms']+1
        clock=lambda:now
        self.desk.durable.clock=clock
        self.desk.durable.controller.clock=clock
        self.desk.durable.controller.engine._clock=clock
        state=self.desk.state()
        self.assertTrue(state['publication']['card']['fallback'])
        self.assertIn('EXPIRED',state['recorded_replay']['label'])
        self.assertIn('deterministic',state['recorded_replay']['label'])
        self.assertEqual(state['recorded_replay']['status'],'recorded_replay')
    def test_maximum_valid_finish_id_is_bounded_and_idempotent(self):
        value={'action':'finish','operation_id':'x'*128}
        done=self.desk.control(value)
        self.assertEqual(done['recap']['through_ms'],130000)
        count=done['durability']['journal_count']
        self.assertEqual(count,1)
        duplicate=self.desk.control(value)
        self.assertEqual(duplicate['durability']['journal_count'],count)
        self.assertTrue(duplicate['durability']['operation']['duplicate'])
        connection=sqlite3.connect(self.db)
        try:
            rows=connection.execute('SELECT operation_id,command_json FROM commands').fetchall()
        finally:
            connection.close()
        self.assertEqual(rows,[('x'*128,'{"action":"finish"}')])
    def test_finish_retry_after_rewind_and_restart_is_bounded_and_keeps_current_facts(self):
        self.act('pattern');self.act('correct')
        self.desk.control({'action':'finish','operation_id':'first-finish'})
        before=self.act('reset')
        self.desk.durable.close()
        script="""
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from app_m3 import Desk
from touchline_core import load_events
desk=Desk(load_events(Path(sys.argv[1])/'synthetic_match.jsonl'),Path(sys.argv[2]))
state=desk.control({'action':'finish','operation_id':'first-finish'})
print(json.dumps({'position':state['position'],'through_ms':state['envelope']['through_ms'],
                  'duplicate':state['durability']['operation']['duplicate'],
                  'journal_count':state['durability']['journal_count'],
                  'revision':desk.durable.controller.engine.event_revision('e010'),
                  'corrections':state['publication']['provenance']['corrections'],
                  'label':state['recorded_replay']['label']}))
desk.durable.close()
"""
        result=subprocess.run([sys.executable,'-B','-c',script,str(ROOT),str(self.db)],
                              capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,0,result.stderr)
        retried=json.loads(result.stdout)
        self.assertEqual((retried['position'],retried['through_ms']),(0,0))
        self.assertTrue(retried['duplicate'])
        self.assertEqual(retried['journal_count'],before['durability']['journal_count'])
        self.assertEqual(retried['revision'],2)
        self.assertEqual(retried['corrections'],[])
        self.assertNotIn('FINAL SYNTHETIC RECAP',retried['label'])
        self.desk=Desk(self.events,self.db)
        fresh=self.desk.control({'action':'finish','operation_id':'new-finish'})
        self.assertFalse(fresh['durability']['operation']['duplicate'])
        self.assertEqual(fresh['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
        self.assertEqual(fresh['envelope']['provenance']['event_revisions']['e010'],2)
    def test_committed_finish_id_rejects_different_durable_and_transient_actions_after_restart(self):
        self.desk.control({'action':'finish','operation_id':'occupied-finish'})
        self.act('reset');self.desk.durable.close();self.desk=Desk(self.events,self.db)
        before=self.desk.state()
        for action in ('reset','next','pattern','correct','replay3','replay4','timeout','recover'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'Conflicting'):
                self.desk.control({'action':action,'operation_id':'occupied-finish'})
            after=self.desk.state()
            self.assertEqual(after['envelope']['snapshot'],before['envelope']['snapshot'])
            self.assertEqual(after['durability']['journal_count'],before['durability']['journal_count'])
    def test_committed_finish_id_blocks_optional_inference_before_any_attempt_or_dispatch(self):
        from app_final import FinalDesk
        self.desk.control({'action':'finish','operation_id':'occupied-finish'})
        self.act('pattern');self.desk.durable.close()
        selector=Mock()
        self.desk=FinalDesk(self.events,self.db,selector=selector,model_until_ms=999999,clock=lambda:1000)
        self.assertTrue(self.desk.state()['live_inference']['available'])
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            self.desk.control({'action':'infer','operation_id':'occupied-finish'})
        selector.assert_not_called()
        self.assertEqual(self.desk.live_calls,0)
        self.assertIsNone(self.desk.live_worker)
    def test_finish_precommit_failure_preserves_whole_current_state_and_retry_commits_once(self):
        self.act('pattern');self.act('correct');before=self.desk.state()
        def fail(phase):
            if phase=='before_commit':raise RuntimeError('Declared finish precommit failure')
        self.desk.durable.fault_hook=fail
        value={'action':'finish','operation_id':'atomic-finish'}
        with self.assertRaisesRegex(RuntimeError,'precommit'):self.desk.control(value)
        after=self.desk.state()
        self.assertEqual(after['envelope']['snapshot'],before['envelope']['snapshot'])
        self.assertEqual(after['position'],before['position'])
        self.assertEqual(after['durability']['journal_count'],before['durability']['journal_count'])
        self.desk.durable.fault_hook=None
        done=self.desk.control(value)
        self.assertEqual(done['durability']['journal_count'],before['durability']['journal_count']+1)
        self.assertEqual(done['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
    def test_actual_process_crashes_around_finish_commit_recover_all_or_none(self):
        script="""
import os,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,sys.argv[1])
from app_m3 import Desk
from touchline_core import load_events
desk=Desk(load_events(Path(sys.argv[1])/'synthetic_match.jsonl'),Path(sys.argv[2]))
def crash(phase):
    if phase==sys.argv[3]:os._exit(int(sys.argv[4]))
desk.durable.fault_hook=crash
desk.control({'action':'finish','operation_id':'crash-finish'})
"""
        for phase,code,through,count in (('before_commit',71,50000,2),('after_commit_before_apply',72,130000,3)):
            with self.subTest(phase=phase):
                path=Path(self.temp.name)/(phase+'.sqlite3')
                desk=Desk(self.events,path)
                desk.control({'action':'pattern','operation_id':'pattern'})
                desk.control({'action':'correct','operation_id':'correct'})
                desk.durable.close()
                child=subprocess.run([sys.executable,'-B','-c',script,str(ROOT),str(path),phase,str(code)],
                                     capture_output=True,text=True,timeout=3)
                self.assertEqual(child.returncode,code,child.stderr)
                restored=Desk(self.events,path)
                try:
                    state=restored.state()
                    self.assertEqual(state['envelope']['through_ms'],through)
                    self.assertEqual(state['durability']['journal_count'],count)
                    self.assertEqual(state['envelope']['provenance']['event_revisions']['e010'],2)
                    done=restored.control({'action':'finish','operation_id':'crash-finish'})
                    self.assertEqual(done['durability']['operation']['duplicate'],phase=='after_commit_before_apply')
                    self.assertEqual(done['durability']['journal_count'],3)
                    self.assertEqual(done['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
                finally:
                    restored.durable.close()
    def test_full_journal_rejects_finish_without_partial_advance(self):
        path=Path(self.temp.name)/'capacity.sqlite3'
        with DurableController(self.events,path,max_commands=2) as store:
            store.control({'action':'pattern'},'pattern')
            before=store.control({'action':'correct'},'correct')
            with self.assertRaisesRegex(ValueError,'capacity'):
                store.control({'action':'finish'},'no-room')
            after=store.state()
            self.assertEqual(after['envelope']['snapshot'],before['envelope']['snapshot'])
            self.assertEqual(after['position'],before['position'])
            self.assertEqual(after['durability']['journal_count'],2)
    def test_spanish_keeps_current_english_card_and_recap_companion(self):
        self.act('pattern');self.act('replay3')
        state=self.act('view',audience='analyst',language='es')
        self.assertEqual(state['publication']['card']['language'],'es')
        self.assertIn('Harbor Owls',state['publication']['card']['translation_en'])
        self.assertEqual(state['recap']['views']['analyst']['en'].count('Harbor Owls')>0,True)
        self.assertEqual(state['publication']['facts']['through_ms'],50000)
    def test_bad_receipt_fails_before_creating_database(self):
        self.desk.durable.close();self.db.unlink()
        with patch.object(app_m3,'ROOT',Path(self.temp.name)):
            with self.assertRaises(FileNotFoundError):Desk(self.events,self.db)
        self.assertFalse(self.db.exists())
    def test_actual_framework_trace_withheld_until_original_watermark(self):
        self.assertEqual(self.desk.state()['recorded_framework_trace']['receipts'],[])
        trace=self.act('pattern')['recorded_framework_trace']
        self.assertEqual(len(trace['receipts']),2)
        self.assertEqual(trace['withheld_receipt_count'],0)
        first=trace['receipts'][0]
        self.assertTrue(first['historical_only'])
        self.assertEqual(first['receipt_sha256'],'8c54aebccd6163337de8c703ab8d22c26b471db67f66a876044409469bddb5ab')
        self.assertTrue(any(row['source']=='Agent Framework agent middleware' for row in first['trace']))
    def test_incomplete_post_times_out_before_any_control_dispatch(self):
        handler=app_m3.Handler.__new__(app_m3.Handler)
        handler.connection=Mock()
        with patch.object(app_m3.BaseHandler,'setup'):
            handler.setup()
        handler.connection.settimeout.assert_called_once_with(4.0)
        handler.headers={'Host':'127.0.0.1:8772','Origin':'http://127.0.0.1:8772',
                         'Content-Type':'application/json','Content-Length':'100'}
        handler.server=Mock(server_port=8772)
        handler.path='/api/control'
        handler.rfile=Mock();handler.rfile.read.side_effect=TimeoutError('partial body')
        handler.controller=Mock();handler._reply=Mock()
        handler.do_POST()
        handler.controller.control.assert_not_called()
        self.assertEqual(handler._reply.call_args.args[0],408)
        self.assertTrue(handler.close_connection)

if __name__=='__main__':unittest.main()
