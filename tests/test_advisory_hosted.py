"""In-process hosted advisory checks with artificial temporary grants only.

No browser, socket, cloud, provider SDK or provider requests are used. These
exercise the actual HostedService facade, independently of HostedBoundaryTests.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosted_app import Config, HostedService, HttpError


class AdvisoryHostedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="touchline-advisory-hosted-test-")
        self.addCleanup(self.temp.cleanup)
        self.now = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())
        self.config = Config(data_dir=Path(self.temp.name),
                             origin="https://playtest.example.invalid", control_per_minute=100)
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.addCleanup(self.close_service)

    def close_service(self):
        if self.service is not None:
            self.service.close()
            self.service = None

    def restart(self, **changes):
        self.close_service()
        self.config = dataclasses.replace(self.config, **changes)
        self.service = HostedService(self.config, clock=lambda: self.now)

    def login(self, label="alice"):
        code = "synthetic-advisory-unittest-code-" + label + "-never-deploy"
        self.service.add_grant(code, expires_at=self.now + 3600, max_sessions=10)
        return self.service.access(code, "synthetic-advisory-client-" + label)

    def command(self, token, csrf, action, operation_id=None, **fields):
        return self.service.control(token, csrf, {
            "action": action, "operation_id": operation_id or uuid4().hex, **fields,
        })

    def error(self, status, action):
        with self.assertRaises(HttpError) as raised:
            action()
        self.assertEqual(raised.exception.status, status)
        return raised.exception

    def review(self, token, csrf, case_id="P03", operation_id=None):
        return self.command(token, csrf, "review_copy", operation_id=operation_id, case_id=case_id)

    def approve(self, token, csrf, state, operation_id=None):
        return self.command(token, csrf, "approve_copy", operation_id=operation_id,
                            advice_id=state["copy_review"]["advice"]["advice_id"])

    def draft(self, token, csrf, case_id="P03"):
        return self.approve(token, csrf, self.review(token, csrf, case_id))

    def assert_no_copy(self, state):
        self.assertIsNone(state["copy_review"]["advice"])
        self.assertIsNone(state["copy_review"]["producer_copy_draft"])
        self.assertEqual(state["live_model_calls"], 0)

    def assert_corrected(self, state):
        self.assertEqual(state["envelope"]["provenance"]["event_revisions"]["e010"], 2)
        self.assertEqual(state["publication"]["facts"]["score"]["Harbor Owls"], 0)

    def test_two_sessions_have_isolated_advice_and_approval_ids(self):
        alice, ac = self.login("alice")
        bob, bc = self.login("bob")
        self.command(alice, ac, "pattern")
        self.command(bob, bc, "pattern")
        before = self.service.state(alice)["publication"]
        reviewed_a = self.review(alice, ac)
        self.assert_no_copy(self.service.state(bob))
        reviewed_b = self.review(bob, bc)
        aid = reviewed_a["copy_review"]["advice"]["advice_id"]
        bid = reviewed_b["copy_review"]["advice"]["advice_id"]
        self.assertNotEqual(aid, bid)
        self.error(409, lambda: self.command(bob, bc, "approve_copy", advice_id=aid))
        self.assertEqual(self.service.state(bob)["copy_review"]["advice"]["advice_id"], bid)
        approved = self.approve(alice, ac, reviewed_a)
        self.assertIsNotNone(approved["copy_review"]["producer_copy_draft"])
        self.assertIsNone(self.service.state(bob)["copy_review"]["producer_copy_draft"])
        self.assertEqual(approved["publication"], before)
        self.assertFalse(approved["copy_review"]["producer_copy_draft"]["on_air"])

    def test_exact_copy_retries_do_not_reexecute_after_clear_restart_or_new_match(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern", operation_id="stable-pattern")
        reviewed = self.review(token, csrf, operation_id="stable-review")
        advice_id = reviewed["copy_review"]["advice"]["advice_id"]
        again = self.review(token, csrf, operation_id="stable-review")
        self.assertEqual(again["copy_review"]["advice"]["advice_id"], advice_id)
        approved = self.approve(token, csrf, reviewed, operation_id="stable-approve")
        retried = self.approve(token, csrf, reviewed, operation_id="stable-approve")
        self.assertEqual(retried["copy_review"]["producer_copy_draft"],
                         approved["copy_review"]["producer_copy_draft"])
        self.command(token, csrf, "clear_copy", operation_id="stable-clear")
        self.assert_no_copy(self.review(token, csrf, operation_id="stable-review"))
        self.restart()
        self.assert_no_copy(self.approve(token, csrf, reviewed, operation_id="stable-approve"))
        self.assert_no_copy(self.review(token, csrf, operation_id="stable-review"))
        self.command(token, csrf, "new_match")
        self.command(token, csrf, "pattern")
        self.assert_no_copy(self.review(token, csrf, operation_id="stable-review"))
        fresh = self.review(token, csrf)
        self.assertNotEqual(fresh["copy_review"]["advice"]["advice_id"], advice_id)
        no_reclear = self.command(token, csrf, "clear_copy", operation_id="stable-clear")
        self.assertEqual(no_reclear["copy_review"]["advice"]["advice_id"],
                         fresh["copy_review"]["advice"]["advice_id"])

    def test_cross_action_ids_remain_conflicts_after_restart_and_new_match(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern", operation_id="core-operation")
        self.review(token, csrf, operation_id="copy-operation")
        for stage in ("initial", "restart", "new_match"):
            with self.subTest(stage=stage):
                if stage == "restart":
                    self.restart()
                elif stage == "new_match":
                    self.command(token, csrf, "new_match")
                    self.command(token, csrf, "pattern")
                self.error(409, lambda: self.command(token, csrf, "clear_copy", operation_id="copy-operation"))
                self.error(409, lambda: self.command(token, csrf, "reset", operation_id="copy-operation"))
                self.error(409, lambda: self.review(token, csrf, operation_id="core-operation"))

    def test_correction_invalidates_copy_and_keeps_p04_raw_failure_honest(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.draft(token, csrf)
        corrected = self.command(token, csrf, "correct")
        self.assert_no_copy(corrected)
        self.assert_corrected(corrected)
        reviewed = self.review(token, csrf, "P04")
        copy_review = reviewed["copy_review"]
        self.assertEqual(copy_review["evaluation"]["strict_passes"], 3)
        self.assertEqual(copy_review["evaluation"]["total"], 4)
        self.assertEqual(copy_review["evaluation"]["status"], "NO_GO")
        self.assertEqual(copy_review["advice"]["raw_reason"], "contradicted_fact")
        self.assertEqual(copy_review["advice"]["deterministic_classification"]["reason"], "stale_revision")
        self.assertEqual(reviewed["live_model_calls"], 0)

    def test_rewind_preserves_correction_but_clears_approved_draft(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        self.draft(token, csrf, "P04")
        self.assert_no_copy(self.command(token, csrf, "reset"))
        rewound = self.command(token, csrf, "pattern")
        self.assert_no_copy(rewound)
        self.assert_corrected(rewound)
        reviewed = self.review(token, csrf, "P04")
        self.assertEqual(reviewed["copy_review"]["advice"]["case_id"], "P04")

    def test_finish_and_pattern_implicit_rewind_clear_draft_and_keep_correction(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        self.draft(token, csrf, "P04")
        finished = self.command(token, csrf, "finish")
        self.assert_no_copy(finished)
        self.assert_corrected(finished)
        self.assertEqual(finished["position"], finished["positions"] - 1)
        rewound = self.command(token, csrf, "pattern")
        self.assert_no_copy(rewound)
        self.assert_corrected(rewound)
        self.assertEqual(rewound["envelope"]["through_ms"], 50000)

    def test_view_away_and_back_never_resurrects_draft(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.draft(token, csrf)
        away = self.command(token, csrf, "view", audience="analyst", language="es")
        self.assert_no_copy(away)
        back = self.command(token, csrf, "view", audience="casual", language="en")
        self.assert_no_copy(back)
        self.assertTrue(next(row for row in back["copy_review"]["cases"] if row["case_id"] == "P03")["available"])

    def test_new_match_archives_old_facts_and_resets_only_current_user(self):
        alice, ac = self.login("alice")
        bob, bc = self.login("bob")
        for token, csrf in ((alice, ac), (bob, bc)):
            self.command(token, csrf, "pattern")
            self.command(token, csrf, "correct")
            self.draft(token, csrf, "P04")
        old_files = {path: path.read_bytes() for path in (self.config.data_dir / "sessions").rglob("match-0.sqlite3")}
        self.assertEqual(len(old_files), 2)
        fresh = self.command(alice, ac, "new_match")
        self.assert_no_copy(fresh)
        fresh = self.command(alice, ac, "pattern")
        self.assertEqual(fresh["envelope"]["provenance"]["event_revisions"]["e010"], 1)
        self.assertEqual(fresh["publication"]["facts"]["score"]["Harbor Owls"], 1)
        bob_state = self.service.state(bob)
        self.assert_corrected(bob_state)
        self.assertIsNotNone(bob_state["copy_review"]["producer_copy_draft"])
        for path, content in old_files.items():
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(len(list((self.config.data_dir / "sessions").rglob("match-1.sqlite3"))), 1)

    def test_restart_clears_advice_and_draft_while_retaining_approved_facts(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        self.draft(token, csrf, "P04")
        self.restart()
        state = self.service.state(token)
        self.assert_no_copy(state)
        self.assert_corrected(state)
        self.assertTrue(state["publication"]["card"]["fallback"])

    def test_eviction_clears_advice_and_draft_while_retaining_approved_facts(self):
        self.restart(max_desks=1)
        alice, ac = self.login("alice")
        self.command(alice, ac, "pattern")
        self.command(alice, ac, "correct")
        self.draft(alice, ac, "P04")
        bob, bc = self.login("bob")
        self.command(bob, bc, "pattern")
        state = self.service.state(alice)
        self.assert_no_copy(state)
        self.assert_corrected(state)

    def test_copy_actions_all_require_csrf_before_any_mutation(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        reviewed = self.review(token, csrf)
        advice_id = reviewed["copy_review"]["advice"]["advice_id"]
        commands = [("review_copy", {"case_id": "P03"}),
                    ("approve_copy", {"advice_id": advice_id}), ("clear_copy", {})]
        for action, fields in commands:
            with self.subTest(action=action):
                self.error(403, lambda: self.command(token, "wrong-csrf", action, **fields))
                current = self.service.state(token)["copy_review"]
                self.assertEqual(current["advice"]["advice_id"], advice_id)
                self.assertIsNone(current["producer_copy_draft"])

    def test_copy_actions_share_control_rate_limit_and_restart_does_not_reset_it(self):
        self.restart(control_per_minute=2)
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        reviewed = self.review(token, csrf)
        self.error(429, lambda: self.approve(token, csrf, reviewed))
        self.error(429, lambda: self.command(token, csrf, "clear_copy"))
        self.restart()
        self.error(429, lambda: self.review(token, csrf))
        self.now += 61
        self.review(token, csrf)

    def test_host_operation_budget_applies_to_new_copy_actions_but_allows_exact_retry(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        reviewed = self.review(token, csrf, operation_id="saved-copy-review")
        session_id = self.service._session(token)["id"]
        with self.service.db() as db:
            existing = db.execute("SELECT COUNT(*) FROM host_operations WHERE session_id=?", (session_id,)).fetchone()[0]
            db.executemany("INSERT INTO host_operations VALUES(?,?,?)", [
                (session_id, "synthetic-budget-" + str(index), "0" * 64)
                for index in range(1000 - existing)
            ])
        for action in [lambda: self.review(token, csrf),
                       lambda: self.approve(token, csrf, reviewed),
                       lambda: self.command(token, csrf, "clear_copy")]:
            self.error(409, action)
        duplicate = self.review(token, csrf, operation_id="saved-copy-review")
        self.assertEqual(duplicate["copy_review"]["advice"]["advice_id"],
                         reviewed["copy_review"]["advice"]["advice_id"])

    def test_public_projection_excludes_internal_bindings_credentials_paths_and_wire(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        state = self.draft(token, csrf, "P04")
        forbidden_keys = {"binding", "context", "session_id", "csrf", "token_hash", "code_hash",
                          "db_path", "database_path", "raw_output", "raw_request", "raw_response",
                          "request_body", "response_body", "wire"}

        def check(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & forbidden_keys, set(value) & forbidden_keys)
                for item in value.values():
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)

        check(state)
        encoded = json.dumps(state)
        private_session_id = self.service._session(token)["id"]
        for private in (token, csrf, private_session_id, str(self.config.data_dir),
                        str(self.service.db_path), "synthetic-advisory-unittest-code"):
            self.assertNotIn(private, encoded)
        self.assertIn("raw_reason", state["copy_review"]["advice"])
        self.assertEqual(state["live_model_calls"], 0)

    def test_infer_and_unknown_advisory_fields_remain_rejected(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.error(400, lambda: self.command(token, csrf, "infer"))
        for fields in ({"session_id": "another-user"}, {"db_path": "../private.sqlite"},
                       {"provider": "anything"}):
            with self.subTest(fields=fields):
                self.error(409, lambda: self.command(token, csrf, "review_copy", case_id="P03", **fields))
        self.assert_no_copy(self.service.state(token))

    def test_local_http_opt_in_is_restricted_to_http_loopback_origins(self):
        with self.assertRaises(ValueError):
            Config(data_dir=Path(self.temp.name), origin="https://playtest.example.invalid", allow_local_http=True)
        for origin in ("http://127.0.0.1:8896", "http://localhost:8896", "http://[::1]:8896"):
            with self.subTest(origin=origin):
                config = Config(data_dir=Path(self.temp.name), origin=origin, allow_local_http=True)
                self.assertTrue(config.allow_local_http)
        config = Config(data_dir=Path(self.temp.name), origin="https://playtest.example.invalid", allow_local_http=False)
        self.assertFalse(config.allow_local_http)


if __name__ == "__main__":
    unittest.main()
