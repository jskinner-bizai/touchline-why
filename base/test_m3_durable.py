"""Actual SQLite durability, crash boundaries, concurrency and fail-closed checks."""
import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import app_m2

from durable_controller import DurableController, DurableIntegrityError, CommittedCommandError, _hash, _json
from touchline_core import load_events

M2_ROOT = Path(app_m2.__file__).resolve().parent
FIXTURE = M2_ROOT / "synthetic_match.jsonl"


class Clock:
    def __init__(self, now=1_000_000): self.now = now
    def __call__(self): return self.now


def factual(state):
    return {"snapshot": state["envelope"]["snapshot"],
            "revisions": state["envelope"]["provenance"]["event_revisions"],
            "corrections": state["recovery_audit"]["corrections"],
            "position": state["position"], "audience": state["audience"], "language": state["language"]}


def selection(request):
    return {key: copy.deepcopy(request["candidates"][0][key]) for key in ("candidate_id", "explanation_type", "evidence_ids")}


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "journal.sqlite3"
        self.events = load_events(FIXTURE)
        self.clock = Clock()
        self.store = DurableController(self.events, self.path, clock=self.clock)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def reopen(self, **kwargs):
        self.store.close()
        self.store = DurableController(self.events, self.path, clock=self.clock, **kwargs)
        return self.store

    def dbhash(self): return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def mutate_db(self, sql, parameters=()):
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection: connection.execute(sql, parameters)

    def test_real_close_reopen_restores_facts_revisions_and_view(self):
        self.store.control({"action": "pattern"}, "pattern-1")
        self.store.control({"action": "correct"}, "correct-1")
        before = self.store.control({"action": "view", "audience": "analyst", "language": "es"}, "view-1")
        old_stream = before["publication"]["stream_id"]
        after = self.reopen().state()
        self.assertEqual(factual(after), factual(before))
        self.assertEqual(after["envelope"]["provenance"]["event_revisions"]["e010"], 2)
        self.assertNotEqual(after["publication"]["stream_id"], old_stream)
        self.assertTrue(after["envelope"]["card"]["fallback"])
        self.assertEqual(after["envelope"]["reason"], "recovered")
        self.assertEqual(after["durability"]["journal_count"], 3)

    def test_current_correction_lineage_and_before_after_survive_recovery(self):
        self.store.control({"action": "pattern"}, "pattern")
        result = self.store.control({"action": "correct"}, "correct")
        row = result["envelope"]["provenance"]["corrections"][0]
        self.assertEqual((row["from_revision"], row["to_revision"]), (1, 2))
        self.assertTrue(row["before"]["goal"])
        self.assertFalse(row["after"]["goal"])
        self.assertEqual(self.reopen().state()["recovery_audit"]["corrections"], [row])

    def test_future_correction_audit_not_exposed_in_current_overlay(self):
        result = self.store.control({"action": "correct"}, "future-correct")
        self.assertEqual(result["envelope"]["provenance"]["corrections"], [])
        self.assertEqual(result["recovery_audit"]["corrections"], [])
        self.assertNotIn("e010", result["envelope"]["snapshot"]["event_ids"])

    def test_reset_rewinds_time_preserves_correction_revision_and_selected_view(self):
        self.store.control({"action": "pattern"}, "pattern")
        self.store.control({"action": "correct"}, "correct")
        self.store.control({"action": "view", "audience": "analyst", "language": "es"}, "view")
        result = self.store.control({"action": "reset"}, "reset")
        self.assertEqual(result["envelope"]["through_ms"], 0)
        self.assertEqual(result["recovery_audit"]["corrections"], [])
        self.assertEqual(self.store.controller.engine.event_revision("e010"), 2)
        self.assertEqual(factual(self.reopen().state()), factual(result))
        pattern = self.store.control({"action": "pattern"}, "pattern-after-reset")
        self.assertEqual(pattern["publication"]["facts"]["score"]["Harbor Owls"], 0)
        self.assertEqual(pattern["envelope"]["provenance"]["event_revisions"]["e010"], 2)
        self.assertEqual(len(pattern["recovery_audit"]["corrections"]), 1)

    def test_implicit_rewind_and_correction_retry_recover_one_approved_revision(self):
        self.store.control({"action": "pattern"}, "pattern")
        self.store.control({"action": "correct"}, "correct")
        serial = 0
        while self.store.controller.position < len(self.store.controller.times) - 1:
            self.store.control({"action": "next"}, f"advance-{serial}")
            serial += 1
        rewound = self.store.control({"action": "pattern"}, "implicit-rewind")
        self.assertEqual(rewound["publication"]["facts"]["score"]["Harbor Owls"], 0)
        before = factual(rewound)
        recovered = self.reopen().state()
        self.assertEqual(factual(recovered), before)
        retry = self.store.control({"action": "correct"}, "new-operation-same-correction")
        self.assertEqual(retry["envelope"]["provenance"]["event_revisions"]["e010"], 2)
        self.assertEqual(len(retry["recovery_audit"]["corrections"]), 1)
        count, dbhash = retry["durability"]["journal_count"], self.dbhash()
        duplicate = self.store.control({"action": "correct"}, "new-operation-same-correction")
        self.assertTrue(duplicate["durability"]["operation"]["duplicate"])
        self.assertEqual(duplicate["durability"]["journal_count"], count)
        self.assertEqual(self.dbhash(), dbhash)
        self.assertEqual(factual(self.reopen().state()), factual(retry))

    def test_transient_recorded_insight_never_persists_or_changes_postfact_hash(self):
        self.store.control({"action": "pattern"}, "pattern")
        with self.store.lock:
            request = self.store.controller.engine.selection_request()
            self.store.controller.engine.apply_selection(request, selection(request))
            self.store.controller.job = {"status": "recorded_replay", "label": "Explicit recorded replay; no model call"}
        selected = self.store.state()
        self.assertFalse(selected["envelope"]["card"]["fallback"])
        result = self.store.control({"action": "duplicate"}, "duplicate-after-recording")
        before = factual(result)
        after = self.reopen().state()
        self.assertEqual(factual(after), before)
        self.assertTrue(after["envelope"]["card"]["fallback"])
        self.assertEqual(after["model_job"]["status"], "recovered_fallback")
        self.assertFalse(after["durability"]["insight_persisted"])
        self.assertFalse(after["model_available"])
        with closing(sqlite3.connect(self.path)) as connection:
            text = " ".join(row[0] for row in connection.execute("SELECT command_json FROM commands"))
        self.assertNotIn("candidate", text)
        self.assertNotIn(request["token_id"], text)

    def test_duplicate_operation_is_idempotent_and_returns_present_state(self):
        self.store.control({"action": "next"}, "first")
        current = self.store.control({"action": "pattern"}, "second")
        before_hash = self.dbhash()
        duplicate = self.store.control({"action": "next"}, "first")
        self.assertEqual(factual(duplicate), factual(current))
        self.assertTrue(duplicate["durability"]["operation"]["duplicate"])
        self.assertEqual(duplicate["durability"]["journal_count"], 2)
        self.assertEqual(self.dbhash(), before_hash)

    def test_conflicting_operation_refused_without_db_or_state_changes(self):
        self.store.control({"action": "next"}, "same")
        before, before_hash = self.store.state(), self.dbhash()
        with self.assertRaisesRegex(ValueError, "Conflicting"): self.store.control({"action": "pattern"}, "same")
        self.assertEqual(self.store.state(), before)
        self.assertEqual(self.dbhash(), before_hash)

    def test_invalid_commands_leave_database_and_live_state_unchanged(self):
        before, before_hash = self.store.state(), self.dbhash()
        invalid = [None, [], {}, {"action": "infer"}, {"action": "inject_timeout"},
                   {"action": "next", "extra": 1}, {"action": True},
                   {"action": "view", "audience": [], "language": "en"},
                   {"action": "view", "audience": "analyst", "language": "xx"}]
        for index, value in enumerate(invalid):
            with self.subTest(value=value), self.assertRaises(ValueError): self.store.control(value, f"bad-{index}")
            self.assertEqual(self.store.state(), before)
            self.assertEqual(self.dbhash(), before_hash)

    def test_controller_level_rejection_is_atomic(self):
        self.store.close()
        changed = copy.deepcopy(self.events)
        next(event for event in changed if event["id"] == "e010")["goal"] = False
        alternate = Path(self.temp.name) / "alternate.sqlite3"
        with DurableController(changed, alternate, clock=self.clock) as store:
            before, dbhash = store.state(), hashlib.sha256(alternate.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): store.control({"action": "correct"}, "invalid-target")
            self.assertEqual(store.state(), before)
            self.assertEqual(hashlib.sha256(alternate.read_bytes()).hexdigest(), dbhash)

    def test_before_commit_fault_rolls_back_db_and_live_state(self):
        before, before_hash = self.store.state(), self.dbhash()
        def fail(phase):
            if phase == "before_commit": raise RuntimeError("Declared precommit failure")
        self.store.fault_hook = fail
        with self.assertRaisesRegex(RuntimeError, "precommit"): self.store.control({"action": "pattern"}, "precommit")
        self.assertEqual(self.store.state(), before)
        self.assertEqual(self.dbhash(), before_hash)

    def test_after_commit_fault_refuses_stale_reads_and_recovers_once(self):
        def fail(phase):
            if phase == "after_commit_before_apply": raise RuntimeError("Declared postcommit failure")
        self.store.fault_hook = fail
        with self.assertRaises(CommittedCommandError) as caught: self.store.control({"action": "pattern"}, "postcommit")
        self.assertTrue(caught.exception.committed)
        with self.assertRaises(CommittedCommandError): self.store.state()
        result = self.reopen().state()
        self.assertEqual(result["envelope"]["through_ms"], 50000)
        retry = self.store.control({"action": "pattern"}, "postcommit")
        self.assertTrue(retry["durability"]["operation"]["duplicate"])
        self.assertEqual(retry["durability"]["journal_count"], 1)

    def run_crash(self, phase, exit_code):
        self.store.close()
        script = """
import os,sys
from pathlib import Path
from touchline_core import load_events
from durable_controller import DurableController
def fail(phase):
    if phase == sys.argv[2]: os._exit(int(sys.argv[3]))
store=DurableController(load_events(Path(sys.argv[4])/'synthetic_match.jsonl'),sys.argv[1],clock=lambda:1_000_000,fault_hook=fail)
store.control({'action':'pattern'},'process-crash')
"""
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).resolve().parent), str(M2_ROOT), environment.get("PYTHONPATH", "")])
        result = subprocess.run([sys.executable, "-c", script, str(self.path), phase, str(exit_code), str(M2_ROOT)],
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, exit_code, result.stderr)
        self.store = DurableController(self.events, self.path, clock=self.clock)
        return self.store.state()

    def test_actual_process_crash_after_commit_before_apply_recovers(self):
        state = self.run_crash("after_commit_before_apply", 91)
        self.assertEqual(state["envelope"]["through_ms"], 50000)
        self.assertEqual(state["durability"]["journal_count"], 1)

    def test_actual_process_crash_before_commit_recovers_prior_state(self):
        state = self.run_crash("before_commit", 90)
        self.assertEqual(state["envelope"]["through_ms"], 0)
        self.assertEqual(state["durability"]["journal_count"], 0)

    def test_concurrent_unique_commands_commit_in_serial_order(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: self.store.control({"action": "next"}, f"thread-{n}"), range(20)))
        self.assertEqual(sorted(result["durability"]["operation"]["sequence"] for result in results), list(range(1, 21)))
        final = self.store.state()
        self.assertEqual(final["envelope"]["through_ms"], 130000)
        self.assertEqual(final["durability"]["journal_count"], 20)
        self.assertEqual(factual(self.reopen().state()), factual(final))

    def test_concurrent_same_operation_commits_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.control({"action": "next"}, "one-operation"), range(20)))
        self.assertEqual(sum(not result["durability"]["operation"]["duplicate"] for result in results), 1)
        self.assertEqual(self.store.state()["durability"]["journal_count"], 1)
        self.assertEqual(self.store.state()["envelope"]["through_ms"], 1000)

    def test_second_owner_cannot_overwrite_a_newer_commit(self):
        second = DurableController(self.events, self.path, clock=self.clock)
        try:
            self.store.control({"action": "next"}, "first-owner")
            before_hash = self.dbhash()
            with self.assertRaisesRegex(DurableIntegrityError, "Another owner"):
                second.control({"action": "pattern"}, "stale-owner")
            self.assertEqual(self.dbhash(), before_hash)
        finally: second.close()
        self.assertEqual(self.reopen().state()["durability"]["journal_count"], 1)

    def test_fixture_change_fails_closed(self):
        self.store.close()
        changed = copy.deepcopy(self.events); changed[1]["success"] = False
        before_hash = self.dbhash()
        with self.assertRaisesRegex(DurableIntegrityError, "fingerprint"):
            DurableController(changed, self.path, clock=self.clock)
        self.assertEqual(self.dbhash(), before_hash)

    def test_rehashed_source_fingerprint_change_still_fails_closed(self):
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                header = json.loads(connection.execute("SELECT value FROM meta WHERE key='header'").fetchone()[0])
                header["source_sha256"]["app_m2"] = "0" * 64
                header["header_sha256"] = _hash({key: value for key, value in header.items() if key != "header_sha256"})
                connection.execute("UPDATE meta SET value=? WHERE key='header'", (_json(header),))
                checkpoint = DurableController._checkpoint(0, header["header_sha256"], header["created_at_ms"], header["initial_state_sha256"])
                connection.execute("UPDATE meta SET value=? WHERE key='checkpoint'", (_json(checkpoint),))
        with self.assertRaisesRegex(DurableIntegrityError, "fingerprint"): self.reopen()

    def test_schema_version_tamper_fails_closed(self):
        self.mutate_db("PRAGMA user_version=999")
        with self.assertRaisesRegex(DurableIntegrityError, "schema"): self.reopen()

    def test_added_schema_object_fails_closed(self):
        self.mutate_db("CREATE INDEX extra_index ON commands(accepted_at_ms)")
        with self.assertRaisesRegex(DurableIntegrityError, "object"): self.reopen()

    def test_header_hash_tamper_fails_closed(self):
        self.mutate_db("UPDATE meta SET value='{}' WHERE key='header'")
        with self.assertRaises(DurableIntegrityError): self.reopen()

    def test_command_payload_tamper_fails_closed(self):
        self.store.control({"action": "pattern"}, "pattern")
        self.mutate_db("UPDATE commands SET command_json=? WHERE sequence=1", (_json({"action": "reset"}),))
        with self.assertRaisesRegex(DurableIntegrityError, "hash chain"): self.reopen()

    def test_logical_tail_truncation_fails_checkpoint(self):
        self.store.control({"action": "next"}, "first")
        self.store.control({"action": "pattern"}, "last")
        self.mutate_db("DELETE FROM commands WHERE sequence=2")
        with self.assertRaisesRegex(DurableIntegrityError, "checkpoint"): self.reopen()

    def test_rehashed_wrong_fact_state_fails_semantic_replay(self):
        self.store.control({"action": "pattern"}, "pattern")
        self.store.close()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                raw = connection.execute("SELECT sequence,operation_id,command_json,accepted_at_ms,previous_hash FROM commands").fetchone()
                body = dict(zip(("sequence", "operation_id", "command", "accepted_at_ms", "previous_hash"), raw))
                body["command"] = json.loads(body["command"])
                body["state_hash"] = "0" * 64
                changed_hash = _hash(body)
                connection.execute("UPDATE commands SET state_hash=?,entry_hash=?", (body["state_hash"], changed_hash))
                checkpoint = DurableController._checkpoint(1, changed_hash, raw[3], body["state_hash"])
                connection.execute("UPDATE meta SET value=? WHERE key='checkpoint'", (_json(checkpoint),))
        with self.assertRaisesRegex(DurableIntegrityError, "Replayed fact"): self.reopen()

    def test_physically_truncated_database_fails_closed(self):
        self.store.close()
        self.path.write_bytes(self.path.read_bytes()[:64])
        with self.assertRaises(DurableIntegrityError): self.reopen()

    def test_empty_existing_database_is_not_silently_recreated(self):
        self.store.close(); self.path.write_bytes(b"")
        with self.assertRaisesRegex(DurableIntegrityError, "empty"): self.reopen()
        self.assertEqual(self.path.read_bytes(), b"")

    def test_journal_bound_rejects_new_operation_but_allows_exact_retry(self):
        self.store.close()
        alternate = Path(self.temp.name) / "bounded.sqlite3"
        with DurableController(self.events, alternate, clock=self.clock, max_commands=3) as store:
            for index in range(3): store.control({"action": "duplicate"}, f"bounded-{index}")
            before = store.state()
            with self.assertRaisesRegex(ValueError, "capacity"): store.control({"action": "next"}, "overflow")
            self.assertEqual(store.state(), before)
            self.assertTrue(store.control({"action": "duplicate"}, "bounded-0")["durability"]["operation"]["duplicate"])

    def test_detached_return_values_and_inputs_cannot_modify_store(self):
        value = {"action": "view", "audience": "analyst", "language": "es"}
        result = self.store.control(value, "view")
        value["language"] = "en"
        result["envelope"]["snapshot"]["events"].clear()
        self.assertEqual(self.store.state()["language"], "es")
        self.assertTrue(self.store.state()["envelope"]["snapshot"]["events"])

    def test_invalid_operation_ids_and_clock_leave_db_unchanged(self):
        before, before_hash = self.store.state(), self.dbhash()
        for value in (None, True, 1, "", "bad id", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError): self.store.control({"action": "next"}, value)
        self.clock.now -= 1
        with self.assertRaises(ValueError): self.store.control({"action": "next"}, "clock-regression")
        self.clock.now += 1
        self.assertEqual(self.store.state(), before)
        self.assertEqual(self.dbhash(), before_hash)

    def test_closed_controller_refuses_reads_and_writes(self):
        self.store.close()
        with self.assertRaisesRegex(RuntimeError, "closed"): self.store.state()
        with self.assertRaisesRegex(RuntimeError, "closed"): self.store.control({"action": "next"}, "closed")

    def test_unjournalled_fact_mutation_is_refused_but_not_persisted(self):
        before_hash = self.dbhash()
        with self.store.lock: self.store.controller.engine.advance(50000)
        with self.assertRaisesRegex(DurableIntegrityError, "outside the durable journal"): self.store.state()
        with self.assertRaises(DurableIntegrityError): self.store.control({"action": "next"}, "unsafe-direct-change")
        self.assertEqual(self.dbhash(), before_hash)
        self.assertEqual(self.reopen().state()["envelope"]["through_ms"], 0)


if __name__ == "__main__": unittest.main()
