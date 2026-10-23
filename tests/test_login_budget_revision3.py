"""N1 regressions: actual service/handler, synthetic Temp grants, no sockets/providers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.message import Message
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosted_app import Config, Handler, HostedService, HttpError


class LoginBudgetRevision3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="touchline-n1-test-")
        self.addCleanup(self.temp.cleanup)
        self.now = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())
        self.config = Config(Path(self.temp.name), "https://playtest.example.invalid", max_sessions=400)
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.addCleanup(lambda: self.service.close())

    def grant(self, label="judge", role="judge", max_sessions=100):
        code = "synthetic-n1-test-" + label + "-never-deploy-000000000"
        self.service.add_grant(code, role=role, expires_at=self.now + 7200, max_sessions=max_sessions)
        return code

    def error(self, status, call):
        with self.assertRaises(HttpError) as caught:
            call()
        self.assertEqual(caught.exception.status, status)
        if status == 429:
            self.assertIn("sign-in", str(caught.exception))
            self.assertNotIn("match has been kept", str(caught.exception))
        return caught.exception

    def bucket_count(self, category):
        with self.service.db() as db:
            return db.execute("SELECT COALESCE(SUM(count),0) FROM buckets WHERE key LIKE ?", (category + ":%",)).fetchone()[0]

    def http_access(self, code, forwarded="198.51.100.20", peer="198.51.100.42"):
        body = json.dumps({"code": code}).encode()
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(service=self.service, peer_key=b"synthetic-n1-test-peer")
        handler.client_address = (peer, 12345)
        handler.path = "/api/access"; handler.command = "POST"; handler.request_version = "HTTP/1.1"
        handler.requestline = "POST /api/access HTTP/1.1"; handler.close_connection = True
        handler.wfile = io.BytesIO(); handler.rfile = io.BytesIO(body); handler.headers = Message()
        for key, value in (("Host", "playtest.example.invalid"), ("Origin", self.config.origin),
                           ("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                           ("X-Forwarded-For", forwarded), ("Forwarded", "for=" + forwarded + ";proto=https")):
            handler.headers.add_header(key, value)
        handler.do_POST()
        head, response_body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        return int(head.split(b" ", 2)[1]), json.loads(response_body)

    def test_actual_400_junk_http_requests_then_valid_judge_succeeds(self):
        code = self.grant()
        statuses = [self.http_access(f"synthetic-invalid-n1-{i:04}-never-deploy-000000")[0] for i in range(400)]
        self.assertEqual(statuses[:60], [401] * 60)
        self.assertEqual(statuses[60:], [429] * 340)
        self.assertEqual(self.bucket_count("login-valid-role"), 0)
        status, body = self.http_access(code)
        self.assertEqual(status, 200)
        self.assertTrue(body["authenticated"])
        self.assertNotIn(code, json.dumps(body))
        self.assertEqual(self.bucket_count("login-valid-role"), 1)
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_malformed_requests_never_spend_valid_budget(self):
        for _ in range(400):
            status, body = self.http_access("bad-shape")
            self.assertIn(status, (401, 429))
            if status == 429:
                self.assertIn("sign-in", body["error"])
        self.assertEqual(self.bucket_count("login-valid-role"), 0)
        self.assertEqual(self.http_access(self.grant())[0], 200)

    def test_per_guess_cap_survives_peer_and_forwarding_changes(self):
        guess = "synthetic-same-invalid-guess-never-deploy-000000"
        for i in range(5):
            self.assertEqual(self.http_access(guess, f"203.0.113.{i+1}", f"192.0.2.{i+1}")[0], 401)
        status, body = self.http_access(guess, "203.0.113.200", "192.0.2.200")
        self.assertEqual(status, 429)
        self.assertIn("sign-in", body["error"])
        self.assertEqual(self.http_access("synthetic-other-invalid-guess-never-deploy-00000")[0], 401)
        self.assertEqual(self.http_access(self.grant())[0], 200)

    def test_global_invalid_cap_and_exact_window_boundary(self):
        for i in range(60):
            self.error(401, lambda i=i: self.service.access(f"synthetic-invalid-window-{i:04}-never-deploy", "same-proxy"))
        self.error(429, lambda: self.service.access("synthetic-next-invalid-window-never-deploy", "another-proxy"))
        boundary = (self.now // 600 + 1) * 600
        self.now = boundary - 1
        self.error(429, lambda: self.service.access("synthetic-next-invalid-window-never-deploy", "new-proxy"))
        self.now = boundary
        self.error(401, lambda: self.service.access("synthetic-next-invalid-window-never-deploy", "new-proxy"))
        self.assertEqual(self.bucket_count("login-failed-global"), 1)
        self.assertEqual(self.bucket_count("login-valid-role"), 0)

    def test_friend_and_judge_caps_remain_independent_and_ignore_client_key(self):
        friend = self.grant("friend", "friend"); judge = self.grant("judge", "judge")
        for i in range(15):
            self.service.access(friend, f"claimed-peer-{i}")
        self.error(429, lambda: self.service.access(friend, "new-claimed-peer"))
        for i in range(30):
            self.service.access(judge, f"claimed-peer-{i}")
        self.error(429, lambda: self.service.access(judge, "another-peer"))
        self.assertIsInstance(self.service.access(self.grant("second-judge"), "same-proxy")[0], str)

    def test_rejected_per_grant_retries_cannot_burn_other_valid_grants_budget(self):
        friend = self.grant("friend", "friend")
        for _ in range(15):
            self.service.access(friend, "same-proxy")
        for _ in range(400):
            self.error(429, lambda: self.service.access(friend, "same-proxy"))
        self.assertEqual(self.bucket_count("login-valid-role"), 15)
        self.service.access(self.grant("unaffected-judge"), "same-proxy")
        self.assertEqual(self.bucket_count("login-valid-role"), 16)

    def test_valid_role_cap_remains_and_reopens_at_hour_boundary(self):
        codes = [self.grant(f"global-judge-{i}") for i in range(11)]
        for code in codes[:10]:
            for _ in range(30):
                self.service.access(code, "same-proxy")
        self.assertEqual(self.bucket_count("login-valid-role"), 300)
        self.error(429, lambda: self.service.access(codes[10], "same-proxy"))
        boundary = (self.now // 3600 + 1) * 3600
        self.now = boundary - 1
        self.error(429, lambda: self.service.access(codes[10], "same-proxy"))
        self.now = boundary
        self.assertIsInstance(self.service.access(codes[10], "same-proxy")[0], str)
        self.assertEqual(self.bucket_count("login-valid-role"), 1)

    def test_grant_ten_minute_window_resets_without_resetting_hourly_total(self):
        code = self.grant("friend", "friend")
        for _ in range(15):
            self.service.access(code, "same-proxy")
        boundary = (self.now // 600 + 1) * 600
        self.now = boundary - 1
        self.error(429, lambda: self.service.access(code, "same-proxy"))
        self.now = boundary
        self.service.access(code, "same-proxy")
        self.assertEqual(self.bucket_count("login-valid-role"), 16)

    def test_disabled_and_expired_codes_use_only_invalid_budgets(self):
        disabled = self.grant("disabled")
        with self.service.db() as db:
            db.execute("UPDATE grants SET disabled=1")
        expired = "synthetic-expired-n1-code-never-deploy-00000"
        self.service.add_grant(expired, expires_at=self.now + 1)
        self.now += 1
        self.error(401, lambda: self.service.access(disabled, "same-proxy"))
        self.error(401, lambda: self.service.access(expired, "same-proxy"))
        self.assertEqual(self.bucket_count("login-valid-role"), 0)
        self.assertEqual(self.http_access(self.grant("active"))[0], 200)

    def test_limits_persist_across_service_restart(self):
        code = self.grant("friend", "friend")
        guess = "synthetic-restart-invalid-guess-never-deploy-000"
        for _ in range(15):
            self.service.access(code, "same-proxy")
        for _ in range(5):
            self.error(401, lambda: self.service.access(guess, "same-proxy"))
        self.service.close()
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.error(429, lambda: self.service.access(code, "new-proxy"))
        self.error(429, lambda: self.service.access(guess, "new-proxy"))
        self.assertEqual(self.http_access(self.grant("another-judge"))[0], 200)

    def test_legacy_mixed_bucket_is_preserved_but_cannot_lock_out_valid_login(self):
        with self.service.db() as db:
            db.execute("INSERT INTO buckets VALUES(?,?,?)", (f"login-global:all:{self.now // 3600}", 300, (self.now // 3600 + 1) * 3600))
        self.assertEqual(self.http_access(self.grant())[0], 200)
        self.assertEqual(self.bucket_count("login-global"), 300)
        self.assertEqual(self.bucket_count("login-valid-role"), 1)

    def test_concurrent_logins_cannot_exceed_friend_cap(self):
        code = self.grant("concurrent", "friend")
        def login(_):
            try:
                self.service.access(code, "same-proxy")
                return 200
            except HttpError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(login, range(16)))
        self.assertEqual(statuses.count(200), 15)
        self.assertEqual(statuses.count(429), 1)
        self.assertEqual(self.bucket_count("login-valid-role"), 15)


if __name__ == "__main__":
    unittest.main()
