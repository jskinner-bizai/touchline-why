"""File-only tests: no SDK, provider process, device or network calls."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pilot_budget import BudgetError, BudgetSession, POLICY


NOW = 1800000000000


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="touchline-budget-test-", dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "authorization.json"
        self.clock = patch("pilot_budget._now_ms", return_value=NOW)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.root_state = {
            "schema_version": 1, "pilot_id": "test-pilot",
            "authorized_at_ms": NOW - 1000, "expires_at_ms": NOW + 899000,
            "policy": copy.deepcopy(POLICY), "attempts": [],
            "stopped": False, "stop_reason": None,
        }

    def initialize(self, state=None):
        self.path.write_text(json.dumps(state or self.root_state), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def binding(self, number=1):
        return {"input_sha256": hashlib.sha256(str(number).encode()).hexdigest(),
                "snapshot_digest": "b" * 64, "watermark_ms": 50000,
                "event_revisions": {"e010": 2, "e011": 1}}

    def complete(self, number=1, **options):
        with BudgetSession(self.path, "test-pilot") as budget:
            budget.reserve(self.binding(number))
            return budget.finish("accepted", 25, **dict(success=True, **options))

    def test_root_must_initialize_authorization(self):
        with self.assertRaisesRegex(BudgetError, "authorization_unavailable"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_exact_policy_no_resource_overrides(self):
        self.assertEqual(set(POLICY), {"model", "endpoint", "max_attempts", "per_call_timeout_ms",
                                     "cumulative_reserved_ms", "max_output_tokens", "max_request_bytes", "think"})
        for field, value in [("num_gpu", 0), ("num_ctx", 4096), ("num_thread", 1),
                             ("max_attempts", True), ("max_output_tokens", 193), ("think", 0)]:
            with self.subTest(field=field):
                state = copy.deepcopy(self.root_state)
                state["policy"][field] = value
                self.initialize(state)
                before = self.path.read_bytes()
                with self.assertRaisesRegex(BudgetError, "policy_mismatch"):
                    with BudgetSession(self.path, "test-pilot"):
                        self.fail("must not enter")
                self.assertEqual(before, self.path.read_bytes())

    def test_unknown_root_and_duplicate_json_rejected_without_write(self):
        state = copy.deepcopy(self.root_state)
        state["extra"] = True
        self.initialize(state)
        with self.assertRaisesRegex(BudgetError, "invalid_root_fields"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")
        self.initialize()
        raw = self.path.read_text()
        self.path.write_text(raw[:-1] + ',"stopped":false}')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(BudgetError, "duplicate_json_key"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")
        self.assertEqual(before, self.path.read_bytes())

    def test_invalid_windows_and_wrong_pilot(self):
        for expiry in [NOW - 1000, NOW + 899001, True]:
            with self.subTest(expiry=expiry):
                state = copy.deepcopy(self.root_state)
                state["expires_at_ms"] = expiry
                self.initialize(state)
                with self.assertRaisesRegex(BudgetError, "invalid_authorization_window"):
                    with BudgetSession(self.path, "test-pilot"):
                        self.fail("must not enter")
        self.initialize()
        with self.assertRaisesRegex(BudgetError, "pilot_id_mismatch"):
            with BudgetSession(self.path, "other-pilot"):
                self.fail("must not enter")

    def test_concurrent_sessions_refuse_and_leave_own_lock(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as first:
            lock = first.lock_path.read_bytes()
            with self.assertRaisesRegex(BudgetError, "budget_locked_no_reclaim"):
                with BudgetSession(self.path, "test-pilot"):
                    self.fail("must not enter")
            self.assertEqual(lock, first.lock_path.read_bytes())
        self.assertFalse(first.lock_path.exists())

    def test_old_lock_never_reclaimed(self):
        self.initialize()
        lock = self.path.with_name(self.path.name + ".lock")
        lock.write_text("old-owner")
        with self.assertRaisesRegex(BudgetError, "budget_locked_no_reclaim"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")
        self.assertEqual(lock.read_text(), "old-owner")

    def test_reservation_is_persisted_before_return_and_copies_detached(self):
        self.initialize()
        binding = self.binding()
        with BudgetSession(self.path, "test-pilot") as budget:
            with patch("pilot_budget.os.fsync", wraps=__import__("os").fsync) as sync:
                reservation = budget.reserve(binding)
                self.assertGreaterEqual(sync.call_count, 1)
            disk = self.read()["attempts"][0]
            self.assertEqual(disk, reservation)
            self.assertEqual(disk["status"], "reserved")
            self.assertEqual(disk["reserved_ms"], 25000)
            reservation["event_revisions"]["e010"] = 999
            binding["event_revisions"]["e010"] = 999
            snapshot = budget.snapshot()
            snapshot["attempts"].clear()
            self.assertEqual(budget.snapshot()["attempts"][0]["event_revisions"]["e010"], 2)
            budget.finish({"state": "validated"}, 100, True)
        self.assertEqual(list(self.path.parent.glob("*.tmp.*")), [])

    def test_four_attempts_across_restarts_are_not_refunded(self):
        self.initialize()
        for number in range(1, 5):
            self.complete(number)
        self.assertEqual(len(self.read()["attempts"]), 4)
        self.assertEqual(sum(a["reserved_ms"] for a in self.read()["attempts"]), 100000)
        with self.assertRaisesRegex(BudgetError, "reservation_budget_exhausted"):
            with BudgetSession(self.path, "test-pilot") as budget:
                budget.reserve(self.binding(5))
        self.assertTrue(self.read()["stopped"])
        self.assertEqual(len(self.read()["attempts"]), 4)

    def test_tampered_reserved_amount_rejected(self):
        self.initialize()
        self.complete()
        state = self.read()
        state["attempts"][0]["reserved_ms"] = 25001
        self.initialize(state)
        with self.assertRaisesRegex(BudgetError, "invalid_reservation"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")

    def test_prior_reserved_stops_and_no_second_reservation(self):
        self.initialize()
        # Persist a reservation, then emulate process death without __exit__.
        budget = BudgetSession(self.path, "test-pilot").__enter__()
        budget.reserve(self.binding())
        budget._release()
        with self.assertRaisesRegex(BudgetError, "unfinished_prior_reservation"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")
        self.assertEqual(self.read()["stop_reason"], "unfinished_prior_reservation")
        self.assertEqual(len(self.read()["attempts"]), 1)

    def test_unfinished_exit_stops_pilot(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as budget:
            budget.reserve(self.binding())
        self.assertEqual(self.read()["stop_reason"], "unfinished_reservation_on_exit")
        with self.assertRaisesRegex(BudgetError, "pilot_stopped"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")

    def test_exception_stops_even_after_success(self):
        self.initialize()
        with self.assertRaisesRegex(ValueError, "injected"):
            with BudgetSession(self.path, "test-pilot") as budget:
                budget.reserve(self.binding())
                budget.finish("accepted", 10, True)
                raise ValueError("injected")
        self.assertEqual(self.read()["stop_reason"], "exception_in_session")

    def test_failed_and_uncertain_completion_stop(self):
        for success, uncertain, reason in [(False, False, "attempt_failed"),
                                          (True, True, "uncertain_completion")]:
            with self.subTest(reason=reason):
                self.initialize()
                with BudgetSession(self.path, "test-pilot") as budget:
                    budget.reserve(self.binding())
                    result = budget.finish("invalid_output", 30, success, uncertain)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.read()["stop_reason"], reason)

    def test_client_deadline_includes_cleanup_and_never_refunds(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as budget:
            budget.reserve(self.binding())
            result = budget.finish("cleanup_late", 25001, True)
        self.assertFalse(result["success"])
        self.assertTrue(result["uncertain"])
        self.assertEqual(self.read()["stop_reason"], "client_deadline_exceeded")
        self.assertEqual(result["reserved_ms"], 25000)

    def test_wall_time_can_exceed_reported_elapsed(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as budget:
            budget.reserve(self.binding())
            self.now.return_value = NOW + 25001
            result = budget.finish("accepted", 10, True)
        self.assertEqual(result["status"], "failed")

    def test_expired_or_insufficient_window_refuses_before_reserve(self):
        for offset in [899001, 874001]:
            with self.subTest(offset=offset):
                self.initialize()
                self.now.return_value = NOW + offset
                with self.assertRaisesRegex(BudgetError, "authorization_window_exhausted"):
                    with BudgetSession(self.path, "test-pilot"):
                        self.fail("must not enter")
                self.assertEqual(self.read()["attempts"], [])
                self.assertTrue(self.read()["stopped"])

    def test_time_can_expire_between_enter_and_reserve(self):
        self.initialize()
        with self.assertRaisesRegex(BudgetError, "authorization_window_exhausted"):
            with BudgetSession(self.path, "test-pilot") as budget:
                self.now.return_value = NOW + 874001
                budget.reserve(self.binding())
        self.assertEqual(self.read()["attempts"], [])

    def test_duplicate_case_rejected_across_restarts(self):
        self.initialize()
        self.complete()
        with self.assertRaisesRegex(BudgetError, "duplicate_case_forbidden"):
            with BudgetSession(self.path, "test-pilot") as budget:
                budget.reserve(self.binding())
        self.assertEqual(len(self.read()["attempts"]), 1)

    def test_external_journal_change_is_not_overwritten(self):
        self.initialize()
        budget = BudgetSession(self.path, "test-pilot").__enter__()
        outside = copy.deepcopy(self.root_state)
        outside["stopped"] = True
        outside["stop_reason"] = "external_owner_stop"
        self.initialize(outside)
        with self.assertRaisesRegex(BudgetError, "journal_changed_outside_session"):
            budget.reserve(self.binding())
        budget._release()
        self.assertEqual(self.read(), outside)

    def test_persistence_failure_never_returns_dispatch_reservation(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as budget:
            with patch("pilot_budget.os.replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(BudgetError, "journal_persistence_failed"):
                    budget.reserve(self.binding())
            self.assertEqual(self.read()["attempts"], [])
            for operation in [lambda: budget.reserve(self.binding(2)),
                              lambda: budget.finish("accepted", 1, True), budget.snapshot]:
                with self.assertRaisesRegex(BudgetError, "session_persistence_uncertain"):
                    operation()
        self.assertTrue(self.read()["stopped"])
        self.assertEqual(self.read()["attempts"][0]["reserved_ms"], 25000)

    def test_derived_case_collision_rejected(self):
        self.initialize()
        self.complete()
        binding = self.binding()
        binding["input_sha256"] = binding["input_sha256"][:16] + "0" * 48
        with self.assertRaisesRegex(BudgetError, "duplicate_case_forbidden"):
            with BudgetSession(self.path, "test-pilot") as budget:
                budget.reserve(binding)
        self.assertEqual(len(self.read()["attempts"]), 1)

    def test_lock_tampering_never_deletes_other_owner_lock(self):
        self.initialize()
        budget = BudgetSession(self.path, "test-pilot").__enter__()
        budget.lock_path.write_text("another-owner")
        with self.assertRaisesRegex(BudgetError, "lock_ownership_uncertain"):
            budget._release()
        self.assertEqual(budget.lock_path.read_text(), "another-owner")

    def test_binding_and_completion_validation(self):
        self.initialize()
        with BudgetSession(self.path, "test-pilot") as budget:
            for change in [{"watermark_ms": True}, {"input_sha256": "not-a-digest"},
                           {"event_revisions": {"e010": True}}]:
                binding = self.binding()
                binding.update(change)
                with self.assertRaises(BudgetError):
                    budget.reserve(binding)
            budget.reserve(self.binding())
            with self.assertRaisesRegex(BudgetError, "invalid_completion"):
                budget.finish("accepted", True, True)
            budget.finish("accepted", 1, True)
            with self.assertRaisesRegex(BudgetError, "no_active_reservation"):
                budget.finish("accepted", 1, True)

    def test_nonfinite_json_rejected(self):
        self.initialize()
        raw = self.path.read_text().replace('"stopped": false', '"stopped": NaN')
        self.path.write_text(raw)
        with self.assertRaisesRegex(BudgetError, "nonfinite_json"):
            with BudgetSession(self.path, "test-pilot"):
                self.fail("must not enter")


if __name__ == "__main__":
    unittest.main()
