"""Offline advisory acceptance and stale-state regressions. No SDK/model calls."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import advisory_review as module
from advisory_review import AdvisoryReview, _context, _stale_goal
from app_m3 import Desk
from touchline_core import load_events, snapshot_at

ROOT=Path(__file__).resolve().parent
EVIDENCE=ROOT/"evidence"/"claim-review"


class AdvisoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT,prefix="advisory-test-")
        self.addCleanup(self.tmp.cleanup)
        self.desk=Desk(load_events(ROOT/"synthetic_match.jsonl"),Path(self.tmp.name)/"facts.sqlite3")
        self.addCleanup(lambda:self.desk.durable.close())
        self.service=AdvisoryReview(EVIDENCE)
        self.counter=0

    def core(self,action,**kwargs):
        self.counter+=1
        return self.desk.control({"action":action,"operation_id":f"core-{self.counter}",**kwargs})

    def command(self,action,**kwargs):
        self.counter+=1
        return self.service.control({"action":action,"operation_id":f"copy-{self.counter}",**kwargs},self.desk.state())

    def review(self,case_id="P01"):
        return self.command("review_copy",case_id=case_id)

    def approve(self,state):
        return self.command("approve_copy",advice_id=state["advice"]["advice_id"])

    def test_no_future_draft_output_or_trace_before_exact_50s(self):
        for _ in range(10):
            state=self.service.state(self.desk.state())
            self.assertIsNone(state["advice"]);self.assertIsNone(state["producer_copy_draft"])
            self.assertFalse(any(row["available"] for row in state["cases"]))
            encoded=json.dumps(state)
            for hidden in ("Every Harbor attempt", "Harbor lead one-nil", "OllamaChatClient", "contradicted_fact", "C1"):
                self.assertNotIn(hidden,encoded)
            with self.assertRaisesRegex(ValueError,"context unavailable"):self.review()
            self.core("next")

    def test_review_then_explicit_approval_only_creates_transient_producer_draft(self):
        self.core("pattern");before=self.desk.state()
        state=self.review();self.assertEqual(state["status"],"reviewed")
        self.assertIsNone(state["producer_copy_draft"])
        self.assertTrue(state["advice"]["can_approve"])
        self.assertFalse(state["live_available"]);self.assertEqual(state["new_provider_requests"],0)
        state=self.approve(state);draft=state["producer_copy_draft"]
        self.assertEqual(draft["text"],"Every Harbor attempt so far has been on target.")
        self.assertFalse(draft["on_air"]);self.assertIn("not on air",draft["label"])
        self.assertEqual(state["status"],"approved_copy_draft");self.assertFalse(state["advice"]["can_approve"])
        after=self.desk.state()
        for key in ("publication","durability","position","history"):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after["envelope"]["snapshot"],before["envelope"]["snapshot"])
        self.assertEqual(after["envelope"]["provenance"],before["envelope"]["provenance"])
        self.assertEqual(draft["binding"]["context"]["source_digest"],module.SOURCE_DIGEST)
        self.assertEqual(draft["binding"]["context"]["source_id"],module.SOURCE_ID)

    def test_withhold_never_becomes_approvable_despite_adapter_publishable_true(self):
        self.core("pattern");state=self.review("P02")
        self.assertEqual(state["advice"]["decision"],"withhold")
        self.assertFalse(state["advice"]["can_approve"]);self.assertEqual(state["advice"]["facts"],[])
        self.assertEqual(state["advice"]["raw_reason"],"unsupported_causality")
        self.assertEqual(state["advice"]["deterministic_classification"]["reason"],"unclassified")
        with self.assertRaisesRegex(ValueError,"approvable advice"):self.approve(state)
        self.assertIsNone(self.service.state(self.desk.state())["producer_copy_draft"])

    def test_partial_copy_keeps_original_supported_clause_with_current_evidence(self):
        self.core("pattern");state=self.review("P03");advice=state["advice"]
        self.assertEqual(advice["keep"],["C1"]);self.assertEqual(advice["drop"],["C2"])
        self.assertEqual(advice["clauses"][0]["evidence_ids"],["e008","e010"])
        self.assertEqual(advice["facts"][0]["event_revisions"],{"e008":1,"e010":1})
        self.assertTrue(advice["historical_only"]);self.assertFalse(advice["test_mode"])
        self.assertTrue(any(row["source"]=="Agent Framework agent middleware" for row in advice["recorded_trace"]))
        state=self.approve(state)
        self.assertEqual(state["producer_copy_draft"]["text"],"Harbor have two shots on target.")
        self.assertNotIn("Meadow have not completed",state["producer_copy_draft"]["text"])

    def test_actual_goal_correction_qualifies_stale_reason_without_rewriting_model(self):
        self.core("pattern");self.core("correct");state=self.review("P04");advice=state["advice"]
        self.assertEqual(advice["raw_reason"],"contradicted_fact")
        self.assertEqual(advice["deterministic_classification"]["reason"],"stale_revision")
        self.assertEqual(advice["deterministic_classification"]["evidence_ids"],["e010"])
        self.assertEqual(advice["deterministic_classification"]["to_revision"],2)
        self.assertEqual(state["evaluation"]["strict_passes"],3);self.assertEqual(state["evaluation"]["status"],"NO_GO")
        self.assertEqual(self.approve(state)["producer_copy_draft"]["text"],"Both efforts were on target.")

    def test_correction_presence_alone_cannot_classify_an_unrelated_removed_clause(self):
        self.core("pattern");self.core("correct");desk_state=self.desk.state();context=_context(desk_state)
        case=copy.deepcopy(self.service._cases["P04"]);output=copy.deepcopy(self.service._receipts["P04"]["validated_output"])
        for text in ("Meadow have not completed a pass.","Harbor's work off the ball manufactured both chances.",
                     "Meadow lead one-nil.","Both efforts were on target."):
            with self.subTest(text=text):
                case["draft_clauses"][0]["text"]=text
                self.assertIsNone(_stale_goal(case,output,desk_state,context))

    def test_preserved_on_target_clause_cannot_be_mislabeled_a_stale_goal(self):
        self.core("pattern");self.core("correct");state=self.desk.state()
        case=self.service._cases["P04"]
        output={"decision":"revise","keep":["C1"],"drop":["C2"],"facts":["F_SCORE"],"reason":"contradicted_fact"}
        self.assertIsNone(_stale_goal(case,output,state,_context(state)))

    def test_goal_withdrawn_then_restored_does_not_keep_stale_classification(self):
        self.core("pattern");self.core("correct");state=self.desk.state()
        provenance=state["envelope"]["provenance"]
        before=copy.deepcopy(next(event for event in state["envelope"]["snapshot"]["events"] if event["id"]=="e010"))
        after={**copy.deepcopy(before),"goal":True}
        provenance["corrections"].append({"correction_id":"restored-goal","target_event_id":"e010",
            "from_revision":2,"to_revision":3,"before":before,"after":after,"source_id":"synthetic_match"})
        provenance["event_revisions"]["e010"]=3
        provenance["evidence_records"]=[copy.deepcopy(after) if event["id"]=="e010" else event for event in provenance["evidence_records"]]
        events=[copy.deepcopy(after) if event["id"]=="e010" else event for event in state["envelope"]["snapshot"]["events"]]
        snapshot=snapshot_at(events,50000)
        state["envelope"]["snapshot"]=snapshot;state["envelope"]["state_digest"]=snapshot["state_digest"]
        state["publication"]["state_digest"]=snapshot["state_digest"]
        context=_context(state)
        self.assertIsNone(_stale_goal(self.service._cases["P04"],self.service._receipts["P04"]["validated_output"],state,context))

    def test_forged_noncontiguous_or_wrong_current_audit_fails_closed(self):
        self.core("pattern");self.core("correct");base=self.desk.state()
        for field,value in (("to_revision",3),("source_id","other")):
            state=copy.deepcopy(base);state["envelope"]["provenance"]["corrections"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):_context(state)
        state=copy.deepcopy(base)
        state["envelope"]["provenance"]["corrections"][0]["after"]["goal"]=True
        self.assertIsNone(_stale_goal(self.service._cases["P04"],self.service._receipts["P04"]["validated_output"],state,_context(base)))
        with self.assertRaises(ValueError):self.service.control({"action":"review_copy","case_id":"P04","operation_id":"forged"},state)

    def test_stale_approval_after_current_correction_is_rejected_and_cleared(self):
        self.core("pattern");state=self.review();advice_id=state["advice"]["advice_id"]
        self.core("correct")
        with self.assertRaisesRegex(ValueError,"stale or withheld"):
            self.command("approve_copy",advice_id=advice_id)
        current=self.service.state(self.desk.state())
        self.assertEqual(current["status"],"stale");self.assertIsNone(current["advice"]);self.assertIsNone(current["producer_copy_draft"])

    def test_approved_draft_clears_when_watermark_or_view_changes(self):
        self.core("pattern");state=self.approve(self.review());self.assertIsNotNone(state["producer_copy_draft"])
        self.core("next");self.assertIsNone(self.service.state(self.desk.state())["producer_copy_draft"])
        self.core("pattern");state=self.approve(self.review())
        self.core("view",audience="analyst",language="es")
        current=self.service.state(self.desk.state())
        self.assertIsNone(current["producer_copy_draft"]);self.assertIsNone(current["advice"])
        self.assertFalse(any(row["available"] for row in current["cases"]))

    def test_view_away_and_back_cannot_resurrect_approval_even_without_intermediate_poll(self):
        self.core("pattern");state=self.review();advice_id=state["advice"]["advice_id"]
        self.core("view",audience="analyst",language="en")
        self.core("view",audience="casual",language="en")
        with self.assertRaisesRegex(ValueError,"stale or withheld"):self.command("approve_copy",advice_id=advice_id)

    def test_reset_then_identical_facts_and_implicit_rewind_reject_old_epoch(self):
        for action in ("reset","finish"):
            with self.subTest(action=action):
                self.core("pattern");state=self.review();advice=state["advice"]
                self.core(action);self.core("pattern")
                fresh=self.desk.state()
                self.assertEqual(fresh["envelope"]["snapshot"]["state_digest"],advice["binding"]["context"]["state_digest"])
                self.assertNotEqual(fresh["envelope"]["engine_epoch"],advice["binding"]["context"]["engine_epoch"])
                with self.assertRaisesRegex(ValueError,"stale or withheld"):
                    self.command("approve_copy",advice_id=advice["advice_id"])

    def test_duplicate_corrections_and_rewind_preserve_revision_two(self):
        self.core("pattern");self.core("correct");self.core("correct")
        state=self.review("P04");self.approve(state)
        self.core("reset");self.core("pattern")
        fresh=self.desk.state();current=self.service.state(fresh)
        self.assertIsNone(current["producer_copy_draft"])
        self.assertEqual(fresh["envelope"]["provenance"]["event_revisions"]["e010"],2)
        self.assertEqual(self.review("P04")["advice"]["raw_reason"],"contradicted_fact")

    def test_restart_and_reopen_never_restore_copy_advice_or_approval(self):
        self.core("pattern");state=self.approve(self.review());old_id=state["advice"]["advice_id"]
        replacement=AdvisoryReview(EVIDENCE)
        self.assertIsNone(replacement.state(self.desk.state())["producer_copy_draft"])
        with self.assertRaisesRegex(ValueError,"approvable advice"):
            replacement.control({"action":"approve_copy","advice_id":old_id,"operation_id":"old-approval"},self.desk.state())
        self.core("recover")
        self.assertIsNone(self.service.state(self.desk.state())["producer_copy_draft"])

    def test_exact_operation_retry_acknowledges_current_state_without_replaying_action(self):
        self.core("pattern");command={"action":"review_copy","case_id":"P01","operation_id":"review-once"}
        state=self.service.control(command,self.desk.state());advice_id=state["advice"]["advice_id"]
        retry=self.service.control(command,self.desk.state());self.assertEqual(retry["advice"]["advice_id"],advice_id)
        self.command("clear_copy")
        retry=self.service.control(command,self.desk.state());self.assertIsNone(retry["advice"])
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            self.service.control({**command,"case_id":"P03"},self.desk.state())

    def test_replayed_approval_after_context_change_never_recreates_draft(self):
        self.core("pattern");state=self.review()
        command={"action":"approve_copy","advice_id":state["advice"]["advice_id"],"operation_id":"approve-once"}
        self.service.control(command,self.desk.state());self.core("reset");self.core("pattern")
        retry=self.service.control(command,self.desk.state())
        self.assertIsNone(retry["producer_copy_draft"]);self.assertIsNone(retry["advice"])

    def test_source_change_and_forged_snapshot_stats_cannot_replay_receipt(self):
        self.core("pattern");base=self.desk.state()
        state=copy.deepcopy(base);state["durability"]["fixture_sha256"]="b"*64
        self.assertFalse(any(row["available"] for row in self.service.state(state)["cases"]))
        state=copy.deepcopy(base);state["envelope"]["snapshot"]["stats"]["total"]["teams"]["harbor"]["goals"]=9
        self.assertFalse(any(row["available"] for row in self.service.state(state)["cases"]))
        with self.assertRaises(ValueError):self.service.control({"action":"review_copy","case_id":"P01","operation_id":"forged-stats"},state)

    def test_evidence_tamper_clears_draft_blocks_actions_and_rejects_restart(self):
        directory=Path(self.tmp.name)/"evidence";directory.mkdir()
        for name in module.EVIDENCE_SHA256:shutil.copy2(EVIDENCE/name,directory/name)
        service=AdvisoryReview(directory);self.core("pattern")
        state=service.control({"action":"review_copy","case_id":"P01","operation_id":"review"},self.desk.state())
        service.control({"action":"approve_copy","advice_id":state["advice"]["advice_id"],"operation_id":"approve"},self.desk.state())
        with (directory/"RECEIPT_P01.json").open("ab") as handle:handle.write(b" ")
        state=service.state(self.desk.state());self.assertEqual(state["status"],"evidence_error")
        self.assertIsNone(state["producer_copy_draft"]);self.assertIsNone(state["advice"])
        with self.assertRaises(ValueError):service.control({"action":"clear_copy","operation_id":"clear"},self.desk.state())
        with self.assertRaisesRegex(ValueError,"hash mismatch"):AdvisoryReview(directory)

    def test_injected_receipts_are_explicitly_labeled_and_raw_reason_consistency_validated(self):
        directory=Path(self.tmp.name)/"injected";directory.mkdir();pins={}
        for name in module.EVIDENCE_SHA256:
            value=json.loads((EVIDENCE/name).read_text())
            if name!="cases.json":value["evidence_mode"]="injected transport"
            raw=json.dumps(value).encode();(directory/name).write_bytes(raw);pins[name]=hashlib.sha256(raw).hexdigest()
        with patch.object(module,"EVIDENCE_SHA256",pins):
            service=AdvisoryReview(directory);self.core("pattern")
            state=service.control({"action":"review_copy","case_id":"P01","operation_id":"injected-review"},self.desk.state())
            self.assertTrue(state["advice"]["test_mode"]);self.assertEqual(state["advice"]["evidence_mode"],"injected transport")
            value=json.loads((directory/"RECEIPT_P04.json").read_text());value["validated_output"]["reason"]="stale_revision"
            raw=json.dumps(value).encode();(directory/"RECEIPT_P04.json").write_bytes(raw)
            pins["RECEIPT_P04.json"]=hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError,"Raw recorded reason"):AdvisoryReview(directory)

    def test_operation_schema_case_and_identifier_limits_fail_without_mutation(self):
        self.core("pattern");before=self.service.state(self.desk.state())
        for command in ({"action":"review_copy","case_id":"P99","operation_id":"badcase"},
                        {"action":"review_copy","case_id":"P01","operation_id":"x"*129},
                        {"action":"review_copy","case_id":"P01","operation_id":"extra","live":True},
                        {"action":"approve_copy","advice_id":"unknown","operation_id":"badapprove"}):
            with self.assertRaises(ValueError):self.service.control(command,self.desk.state())
        self.assertEqual(self.service.state(self.desk.state()),before)

    def test_import_path_has_no_sdk_or_provider_dependencies(self):
        script="import advisory_review,sys; assert not any(n=='agent_framework' or n.startswith('agent_framework.') or n=='ollama' or n=='httpx' for n in sys.modules); print('SDK-free')"
        result=subprocess.run([sys.executable,"-B","-c",script],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn("SDK-free",result.stdout)


if __name__=="__main__":unittest.main()
