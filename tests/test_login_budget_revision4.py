"""R1 regression: real service, fake time and scratch grants; no provider calls."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosted_app import Config, HostedService, HttpError


class LoginBudgetRevision4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="touchline-r1-test-")
        self.addCleanup(self.temp.cleanup)
        self.now = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())
        self.config = Config(Path(self.temp.name), "https://playtest.example.invalid", max_sessions=600)
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.addCleanup(lambda: self.service.close())

    def grant(self, label, role="judge", capacity=400):
        code = "synthetic-r1-" + label + "-never-deploy-000000000000"
        grant_id = self.service.add_grant(code, role, self.now + 7200, capacity)
        return code, grant_id

    def status(self, code, peer="synthetic-shared-ingress"):
        try:
            self.service.access(code, peer)
            return 200
        except HttpError as error:
            return error.status

    def count(self, category, subject=None):
        prefix = category + ":" + (subject + ":" if subject else "")
        with self.service.db() as db:
            return db.execute("SELECT COALESCE(SUM(count),0) FROM buckets WHERE key LIKE ?", (prefix + "%",)).fetchone()[0]

    def test_original_single_code_attack_is_bounded_and_other_roles_still_enter(self):
        primary, _ = self.grant("primary")
        second, _ = self.grant("second")
        friend, _ = self.grant("friend", "friend")
        start = self.now
        statuses = []
        for window in range(5):
            self.now = start + window * 600
            statuses.extend(self.status(primary, f"untrusted-peer-{attempt}") for attempt in range(60))
        self.assertEqual(statuses.count(200), 90)
        self.assertEqual(statuses.count(429), 210)
        self.assertEqual(self.count("login-valid-role", "judge"), 90)
        self.assertEqual(self.status(second), 200)
        self.assertEqual(self.status(friend), 200)
        self.assertEqual(self.count("login-valid-role", "judge"), 91)
        self.assertEqual(self.count("login-valid-role", "friend"), 1)

    def test_hourly_grant_limit_survives_restart_and_resets_at_exact_boundary(self):
        code, _ = self.grant("hour")
        start = self.now
        for window in range(3):
            self.now = start + window * 600
            for _ in range(30):
                self.assertEqual(self.status(code), 200)
        self.now = start + 1800
        self.assertEqual(self.status(code), 429)
        self.service.close()
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.assertEqual(self.status(code, "different-untrusted-peer"), 429)
        self.now = (start // 3600 + 1) * 3600 - 1
        self.assertEqual(self.status(code), 429)
        self.now += 1
        self.assertEqual(self.status(code), 200)
        self.assertEqual(self.count("login-grant-hour"), 1)

    def test_multiple_judges_behind_one_ingress_have_independent_code_budgets(self):
        codes = [self.grant(f"same-ingress-{index}")[0] for index in range(4)]
        for code in codes:
            for _ in range(30):
                self.assertEqual(self.status(code), 200)
            self.assertEqual(self.status(code, "different-spoofed-client"), 429)
        self.assertEqual(self.count("login-valid-role", "judge"), 120)
        with self.service.db() as db:
            stored = " ".join(row[0] for row in db.execute("SELECT key FROM buckets"))
        for raw in [*codes, "synthetic-shared-ingress", "different-spoofed-client"]:
            self.assertNotIn(raw, stored)

    def test_judge_role_exhaustion_does_not_consume_friend_allowance(self):
        for index in range(10):
            code, _ = self.grant(f"role-{index}")
            for _ in range(30):
                self.assertEqual(self.status(code), 200)
        extra, _ = self.grant("extra")
        self.assertEqual(self.status(extra), 429)
        friend, _ = self.grant("reserved-friend", "friend")
        self.assertEqual(self.status(friend), 200)
        self.assertEqual(self.count("login-valid-role", "judge"), 300)
        self.assertEqual(self.count("login-valid-role", "friend"), 1)

    def test_full_grant_retries_cannot_spend_other_codes_rate_budget(self):
        full, _ = self.grant("full", capacity=1)
        self.assertEqual(self.status(full), 200)
        for _ in range(400):
            self.assertEqual(self.status(full), 429)
        self.assertEqual(self.count("login-valid-role", "judge"), 1)
        self.assertEqual(self.count("login-grant-hour"), 1)
        self.assertEqual(self.status(self.grant("unaffected")[0]), 200)

    def test_retained_global_capacity_remains_bounded_without_spending_rate_budget(self):
        self.service.close()
        self.config = Config(Path(self.temp.name), "https://playtest.example.invalid", max_sessions=1)
        self.service = HostedService(self.config, clock=lambda: self.now)
        primary, _ = self.grant("one-slot", capacity=1)
        secondary, _ = self.grant("second-code", capacity=1)
        self.assertEqual(self.status(primary), 200)
        self.assertEqual(self.status(secondary), 503)
        self.assertEqual(self.count("login-valid-role", "judge"), 1)
        self.assertEqual(self.count("login-grant-hour"), 1)
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_revocation_and_expiry_still_apply_before_valid_rate_charging(self):
        revoked, grant_id = self.grant("revoked")
        token, _ = self.service.access(revoked, "synthetic-shared-ingress")
        self.service.revoke_grant(grant_id)
        self.assertEqual(self.status(revoked), 401)
        with self.assertRaises(HttpError) as caught:
            self.service.session(token)
        self.assertEqual(caught.exception.status, 401)
        self.assertEqual(self.count("login-valid-role"), 1)
        expiring, _ = self.grant("expiring")
        self.now += 7200
        self.assertEqual(self.status(expiring), 401)
        self.assertEqual(self.count("login-valid-role"), 0)

    def test_friend_hourly_ceiling_keeps_judges_independent(self):
        code, _ = self.grant("friend-hour", "friend")
        for window in range(2):
            if window:
                self.now += 600
            for _ in range(15):
                self.assertEqual(self.status(code), 200)
        self.now += 600
        self.assertEqual(self.status(code), 429)
        self.assertEqual(self.status(self.grant("judge-after-friend")[0]), 200)
        self.assertEqual(self.count("login-valid-role", "friend"), 30)


if __name__ == "__main__":
    unittest.main()
