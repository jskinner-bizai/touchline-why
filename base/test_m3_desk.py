"""Integration acceptance for recorded-only desk and real local HTTP boundary."""
import copy,json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from app_m3 import Desk,Handler
from touchline_core import load_events
ROOT=Path(__file__).resolve().parent

class DeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'desk.db'
        self.events=load_events(ROOT/'synthetic_match.jsonl');self.desk=Desk(self.events,self.db);self.n=0
    def tearDown(self):self.desk.durable.close();self.tmp.cleanup()
    def control(self,action,**extra):
        self.n+=1;return self.desk.control({'action':action,'operation_id':f'case-{self.n}',**extra})
    def test_current_fact_gate_prevents_future_recording_replay(self):
        before=self.desk.state()
        with self.assertRaises(ValueError):self.control('replay3')
        self.assertEqual(before['envelope']['snapshot'],self.desk.state()['envelope']['snapshot'])
    def test_actual_receipt_replay_is_explicit_and_never_provider_available(self):
        self.control('pattern');s=self.control('replay3')
        self.assertFalse(s['publication']['card']['fallback']);self.assertIn('RECORDED',s['publication']['card']['replay_label'])
        self.assertEqual(s['live_model_calls_this_milestone'],0);self.assertFalse(s['model_available'])
        self.assertEqual(s['recap']['recorded_receipt_count'],2);self.assertEqual(s['recap']['recorded_moment_count'],1)
    def test_recording_cannot_replay_after_fact_correction(self):
        self.control('pattern');self.control('replay4');s=self.control('correct')
        self.assertTrue(s['publication']['card']['fallback']);self.assertEqual(s['publication']['facts']['score']['Harbor Owls'],0)
        self.assertEqual(len(s['recap']['withdrawn_claims']),1)
        with self.assertRaises(ValueError):self.control('replay3')
    def test_restart_restores_facts_view_correction_and_discards_selected_insight(self):
        self.control('pattern');self.control('replay3');old=self.desk.state()['publication']['stream_id']
        self.desk.durable.close();self.desk=Desk(self.events,self.db);s=self.desk.state()
        self.assertNotEqual(old,s['publication']['stream_id']);self.assertTrue(s['publication']['card']['fallback'])
        self.assertFalse(s['recovery_info']['insight_restored'])
        self.control('correct');self.control('view',audience='analyst',language='es');s=self.control('recover')
        self.assertEqual(s['language'],'es');self.assertEqual(s['audience'],'analyst');self.assertEqual(s['publication']['facts']['score']['Harbor Owls'],0)
    def test_injected_timeout_is_labelled_and_continues_facts(self):
        self.control('pattern');self.control('replay3');s=self.control('timeout')
        self.assertTrue(s['publication']['card']['fallback']);self.assertIn('INJECTED',s['recorded_replay']['label'])
        self.assertEqual(s['model_job']['note'],'Declared local failure injection. No provider request or cancellation claim.')
    def test_transient_duplicate_does_not_renew_ttl_or_version(self):
        self.control('pattern');v={'action':'replay3','operation_id':'same-replay'}
        s=self.desk.control(v);other=self.desk.control(copy.deepcopy(v))
        self.assertEqual(s['publication'],other['publication'])
        with self.assertRaises(ValueError):self.desk.control({'action':'replay4','operation_id':'same-replay'})
    def test_future_correction_audit_is_not_public(self):
        s=self.control('correct');self.assertEqual(s['recovery_audit']['corrections'],[])
        self.assertEqual(s['envelope']['provenance']['evidence_records'],[self.events[0]])
        self.assertEqual(s['recap']['recorded_selections'],[])
    def test_final_recap_exact_corrected_totals_and_shared_attribution(self):
        self.control('pattern');self.control('correct');s=self.control('finish')
        self.assertEqual(s['recap']['through_ms'],130000)
        self.assertEqual([t['totals']['goals'] for t in s['recap']['facts']['teams']],[0,1])
        self.assertEqual([t['totals']['pass_accuracy'] for t in s['recap']['facts']['teams']],[{'numerator':2,'denominator':3}]*2)
        self.assertEqual(s['recap']['recorded_moment_count'],1)
    def test_implicit_rewind_preserves_approved_correction_and_final_score(self):
        self.control('pattern');self.control('correct');finished=self.control('finish')
        old=finished['publication']['overlay_id']
        rewound=self.control('pattern')
        self.assertEqual(rewound['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':0})
        self.assertEqual(rewound['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertEqual(len(rewound['recovery_audit']['corrections']),1)
        self.assertIn(old,rewound['publication']['retracts'])
        self.assertFalse(rewound['recorded_replay']['available'])
        with self.assertRaises(ValueError):self.control('replay3')
        final=self.control('finish')
        self.assertEqual(final['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
        self.assertEqual(len(final['recap']['withdrawn_claims']),1)
    def test_explicit_rewind_preserves_correction_but_withholds_future_audit(self):
        self.control('pattern');self.control('correct');rewound=self.control('reset')
        self.assertEqual(rewound['envelope']['through_ms'],0)
        self.assertEqual(self.desk.durable.controller.engine.event_revision('e010'),2)
        self.assertEqual(rewound['envelope']['provenance']['corrections'],[])
        self.assertNotIn('e010',rewound['envelope']['provenance']['event_revisions'])
        self.assertEqual(rewound['envelope']['provenance']['evidence_records'],[self.events[0]])
        self.control('pattern');final=self.control('finish')
        self.assertEqual(final['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
        self.assertEqual(final['envelope']['provenance']['event_revisions']['e010'],2)
    def test_correction_retry_after_rewind_and_recovery_does_not_increment_revision(self):
        self.control('pattern');self.control('correct');self.control('reset');self.control('pattern')
        retried=self.control('correct')
        self.assertEqual(retried['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertEqual(len(retried['recovery_audit']['corrections']),1)
        recovered=self.control('recover')
        self.assertEqual(recovered['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertEqual(recovered['recovery_audit']['corrections'],retried['recovery_audit']['corrections'])
        self.assertTrue(recovered['publication']['card']['fallback'])
        after=self.control('correct')
        self.assertEqual(after['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertEqual(len(after['recovery_audit']['corrections']),1)
        self.assertFalse(after['recorded_replay']['available'])
    def test_no_live_inference_action_or_unbounded_operation_id(self):
        for value in ({'action':'infer','operation_id':'bad'},{'action':'timeout','operation_id':'x'*129}):
            with self.assertRaises(ValueError):self.desk.control(value)

class HTTPTests(DeskTests):
    def setUp(self):
        super().setUp();self.handler=type('TestHandler',(Handler,),{'controller':self.desk})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
    def request(self,path,body=None,origin=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json',**({'Origin':origin} if origin else {})})
        try:
            with urllib.request.urlopen(req,timeout=3)as response:return response.status,json.load(response)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_cross_origin_control_refused(self):self.assertEqual(self.request('/api/control',{'action':'pattern','operation_id':'outside'},'https://example.org')[0],403)
    def test_http_no_future_fixture_or_private_file_routes(self):
        for path in ('/synthetic_match.jsonl','/../ledger.json','/PRIVATE_REGISTRATION.md','/api/state?future=1'):
            self.assertEqual(self.request(path)[0],404)
    def test_integrity_error_reports503(self):
        self.desk.durable.controller.engine.advance(50000)
        self.assertEqual(self.request('/api/state')[0],503)
        self.assertEqual(self.request('/api/control',{'action':'next','operation_id':'broken'},self.url)[0],503)
    def test_http_reset_and_implicit_rewind_keep_corrected_score_and_revision(self):
        actions=('pattern','correct','finish','pattern','reset','pattern','finish')
        for index,action in enumerate(actions):
            status,state=self.request('/api/control',{'action':action,'operation_id':f'http-h1-{index}'},self.url)
            self.assertEqual(status,200)
            if index in {3,5}:
                self.assertEqual(state['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':0})
                self.assertEqual(state['envelope']['provenance']['event_revisions']['e010'],2)
                self.assertEqual(len(state['publication']['provenance']['corrections']),1)
                self.assertFalse(state['recorded_replay']['available'])
            if action=='reset':
                self.assertEqual(state['envelope']['through_ms'],0)
                self.assertEqual(state['publication']['provenance']['corrections'],[])
                self.assertNotIn('e010',state['envelope']['provenance']['event_revisions'])
        status,current=self.request('/api/state')
        self.assertEqual(status,200)
        self.assertEqual(current['publication']['facts']['score'],{'Harbor Owls':0,'Meadow Foxes':1})
        self.assertEqual(current['envelope']['provenance']['event_revisions']['e010'],2)
        self.assertEqual(len(current['recap']['withdrawn_claims']),1)

if __name__=='__main__':unittest.main()
