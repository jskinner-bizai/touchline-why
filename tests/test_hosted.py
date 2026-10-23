"""Independent hosted-playtest boundary tests using synthetic local grants only.

No sockets, cloud accounts, providers, credentials or canonical source are used.
These test the actual service facade; HTTP/TLS/cloud integration is separate.
"""
from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from email.message import Message
from email.parser import BytesParser
import io
import json
from pathlib import Path
import sys
import sqlite3
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosted_app import Config, HostedService, HttpError, Handler, FEEDBACK_DELETE_AT, MAX_BODY


class HostedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="touchline-hosted-security-")
        self.addCleanup(self.temp.cleanup)
        # Metadata/auth clock is intentionally fixed before the stated playtest
        # cutoff; the underlying match engine owns a separate service clock.
        self.now = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())
        self.config = Config(data_dir=Path(self.temp.name), origin="https://playtest.example.invalid")
        self.service = HostedService(self.config, clock=lambda: self.now)
        self.addCleanup(self._close)

    def _close(self):
        if self.service is not None:
            self.service.close()
            self.service = None

    def restart(self):
        self._close()
        self.service = HostedService(self.config, clock=lambda: self.now)

    def configure(self, **changes):
        self._close()
        self.config = dataclasses.replace(self.config, **changes)
        self.service = HostedService(self.config, clock=lambda: self.now)

    def login(self, label="alice", **grant_options):
        code = "synthetic-unittest-access-code-" + label + "-never-deploy"
        grant_options.setdefault("max_sessions", min(10, self.config.max_sessions))
        self.service.add_grant(code, expires_at=self.now + 3600, **grant_options)
        token, csrf = self.service.access(code, "synthetic-client-" + label)
        self.assertIsInstance(token, str)
        self.assertIsInstance(csrf, str)
        self.assertGreaterEqual(len(token), 32)
        self.assertGreaterEqual(len(csrf), 32)
        self.assertNotEqual(token, csrf)
        return token, csrf

    def command(self, token, csrf, action, **fields):
        return self.service.control(token, csrf, {"action": action, "operation_id": uuid4().hex, **fields})

    def assert_error(self, status, call):
        with self.assertRaises(HttpError) as raised:
            call()
        expected = {status} if isinstance(status, int) else set(status)
        self.assertIn(raised.exception.status, expected)
        return raised.exception

    @staticmethod
    def score(state):
        return state["publication"]["facts"]["score"]

    @staticmethod
    def revision(state, event="e010"):
        return state["envelope"]["provenance"]["event_revisions"][event]

    @staticmethod
    def feedback_payload(**changes):
        value = {
            "feedback_id": uuid4().hex,
            "consent": True,
            "ratings": {"clarity": 4, "usefulness": 3, "trust": 5},
            "role": "both",
            "comment": "Synthetic test feedback; no personal data.",
            "viewport": "phone",
        }
        value.update(changes)
        return value

    def test_two_users_cannot_change_each_others_match(self):
        a, ac = self.login("alice")
        b, bc = self.login("bob")
        self.command(a, ac, "pattern")
        corrected = self.command(a, ac, "correct")
        self.assertEqual(self.score(corrected)["Harbor Owls"], 0)
        self.assertEqual(self.revision(corrected), 2)
        bob = self.command(b, bc, "pattern")
        self.assertEqual(self.score(bob)["Harbor Owls"], 1)
        self.assertEqual(self.revision(bob), 1)
        self.assertNotEqual(corrected["publication"]["stream_id"], bob["publication"]["stream_id"])
        self.command(b, bc, "finish")
        self.assertEqual(self.service.state(a)["publication"]["event_time"]["through_ms"], 50000)

    def test_concurrent_users_have_independent_approved_facts(self):
        a, ac = self.login("alice")
        b, bc = self.login("bob")

        def alice():
            self.command(a, ac, "pattern")
            self.command(a, ac, "correct")
            return self.command(a, ac, "finish")

        def bob():
            self.command(b, bc, "pattern")
            return self.command(b, bc, "finish")

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a, future_b = executor.submit(alice), executor.submit(bob)
            result_a, result_b = future_a.result(timeout=15), future_b.result(timeout=15)
        self.assertEqual(self.score(result_a), {"Harbor Owls": 0, "Meadow Foxes": 1})
        self.assertEqual(self.score(result_b), {"Harbor Owls": 1, "Meadow Foxes": 1})
        self.assertEqual(self.revision(result_a), 2)
        self.assertEqual(self.revision(result_b), 1)

    def test_rewind_keeps_correction_but_explicit_new_match_is_only_local(self):
        a, ac = self.login("alice")
        b, bc = self.login("bob")
        self.command(a, ac, "pattern")
        self.command(a, ac, "correct")
        self.command(b, bc, "pattern")
        self.command(b, bc, "correct")
        self.command(a, ac, "reset")
        rewound = self.command(a, ac, "pattern")
        self.assertEqual(self.score(rewound)["Harbor Owls"], 0)
        self.assertEqual(self.revision(rewound), 2)
        self.command(a, ac, "new_match")
        fresh = self.command(a, ac, "pattern")
        self.assertEqual(self.score(fresh)["Harbor Owls"], 1)
        self.assertEqual(self.revision(fresh), 1)
        self.assertEqual(self.revision(self.service.state(b)), 2)

    def test_new_match_duplicate_does_not_discard_current_progress(self):
        token, csrf = self.login()
        command = {"action": "new_match", "operation_id": "synthetic-new-match-once"}
        self.service.control(token, csrf, command)
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        duplicate = self.service.control(token, csrf, command)
        self.assertEqual(self.revision(duplicate), 2)
        self.assertEqual(self.score(duplicate)["Harbor Owls"], 0)
        self.restart()
        duplicate_after_restart = self.service.control(token, csrf, command)
        self.assertEqual(self.revision(duplicate_after_restart), 2)
        self.assertEqual(self.score(duplicate_after_restart)["Harbor Owls"], 0)

    def test_wrong_csrf_does_not_mutate_match_or_allocate_new_one(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        before = self.service.state(token)
        files_before = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        for bad in ("", "incorrect-csrf", None):
            self.assert_error(403, lambda bad=bad: self.command(token, bad, "correct"))
            self.assert_error(403, lambda bad=bad: self.command(token, bad, "new_match"))
        after = self.service.state(token)
        self.assertEqual(before["publication"]["state_digest"], after["publication"]["state_digest"])
        files_after = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        self.assertEqual(files_before, files_after)

    def test_unknown_auth_cannot_read_or_write_or_allocate_replay(self):
        files_before = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        for token in ("", "made-up-token", "../another.sqlite3"):
            self.assert_error(401, lambda token=token: self.service.state(token))
            self.assert_error(401, lambda token=token: self.command(token, "made-up-csrf", "pattern"))
            self.assert_error(401, lambda token=token: self.service.feedback(token, "made-up-csrf", self.feedback_payload()))
        files_after = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        self.assertEqual(files_before, files_after)

    def test_invalid_access_code_does_not_allocate_a_match(self):
        files_before = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        for code in ("", "unknown-synthetic-code", "../../other", "x" * 2000):
            self.assert_error((400, 401), lambda code=code: self.service.access(code, "synthetic-client-invalid"))
        files_after = {p.relative_to(self.config.data_dir) for p in self.config.data_dir.rglob("*") if p.is_file()}
        self.assertEqual(files_before, files_after)

    def test_grant_and_session_expiry_apply_to_existing_sessions(self):
        code = "synthetic-expiring-grant-never-deploy-0000000"
        self.service.add_grant(code, expires_at=self.now + 30)
        token, csrf = self.service.access(code, "synthetic-expiry-client")
        self.service.state(token)
        self.now += 31
        self.assert_error(401, lambda: self.service.state(token))
        self.assert_error(401, lambda: self.command(token, csrf, "pattern"))
        self.assert_error(401, lambda: self.service.access(code, "synthetic-expiry-client"))

    def test_grant_revocation_invalidates_existing_session(self):
        code = "synthetic-revoked-grant-never-deploy-0000000"
        grant = self.service.add_grant(code, expires_at=self.now + 3600)
        token, csrf = self.service.access(code, "synthetic-revocation-client")
        self.service.state(token)
        self.service.revoke_grant(grant)
        self.assert_error(401, lambda: self.service.state(token))
        self.assert_error(401, lambda: self.command(token, csrf, "pattern"))
        self.assert_error(401, lambda: self.service.access(code, "synthetic-revocation-client"))

    def test_session_timeout_is_not_renewed_by_reads(self):
        self.configure(session_seconds=20)
        token, csrf = self.login()
        self.now += 15
        self.service.state(token)
        self.now += 6
        self.assert_error(401, lambda: self.service.state(token))
        self.assert_error(401, lambda: self.service.feedback(token, csrf, self.feedback_payload()))

    def test_persistent_session_and_correction_survive_service_restart(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        self.command(token, csrf, "correct")
        self.restart()
        state = self.service.state(token)
        self.assertEqual(self.score(state)["Harbor Owls"], 0)
        self.assertEqual(self.revision(state), 2)
        self.assertTrue(state["publication"]["card"]["fallback"])
        self.assertFalse(state["recorded_replay"]["available"])

    def test_selected_insight_not_renewed_by_restart(self):
        token, csrf = self.login()
        self.command(token, csrf, "pattern")
        selected = self.command(token, csrf, "replay3")
        self.assertFalse(selected["publication"]["card"]["fallback"])
        stream = selected["publication"]["stream_id"]
        self.restart()
        state = self.service.state(token)
        self.assertTrue(state["publication"]["card"]["fallback"])
        self.assertNotEqual(stream, state["publication"]["stream_id"])
        self.assertEqual(self.score(state)["Harbor Owls"], 1)

    def test_read_and_control_rate_limits_persist_across_restart(self):
        self.configure(read_per_minute=1, control_per_minute=1)
        token, csrf = self.login()
        self.service.state(token)
        self.assert_error(429, lambda: self.service.state(token))
        self.command(token, csrf, "pattern")
        self.assert_error(429, lambda: self.command(token, csrf, "correct"))
        self.restart()
        self.assert_error(429, lambda: self.command(token, csrf, "correct"))
        self.now += 61
        self.command(token, csrf, "correct")

    def test_grant_session_cap_and_total_session_cap(self):
        self.configure(max_sessions=2)
        code = "synthetic-single-session-access-code-never-deploy"
        self.service.add_grant(code, expires_at=self.now + 3600, max_sessions=1)
        self.service.access(code, "synthetic-client-one")
        self.assert_error((429, 503), lambda: self.service.access(code, "synthetic-client-two"))
        self.login("second-grant")
        another = "synthetic-third-grant-never-deploy-00000000"
        self.service.add_grant(another, expires_at=self.now + 3600, max_sessions=2)
        self.assert_error((429, 503), lambda: self.service.access(another, "synthetic-client-three"))

    def test_evicted_in_memory_desk_retains_approved_correction(self):
        self.configure(max_desks=1)
        a, ac = self.login("alice")
        self.command(a, ac, "pattern")
        self.command(a, ac, "correct")
        b, bc = self.login("bob")
        self.command(b, bc, "pattern")
        again = self.service.state(a)
        self.assertEqual(self.revision(again), 2)
        self.assertEqual(self.score(again)["Harbor Owls"], 0)

    def test_new_match_count_is_bounded(self):
        self.configure(max_matches=3)
        token, csrf = self.login()
        accepted = 0
        for _ in range(5):
            try:
                self.command(token, csrf, "new_match")
                accepted += 1
            except HttpError as error:
                self.assertIn(error.status, (429, 409))
                break
        self.assertLessEqual(accepted, 3)
        self.assertLess(accepted, 5)

    def test_feedback_requires_explicit_consent_and_strict_schema(self):
        token, csrf = self.login()
        invalid = [
            self.feedback_payload(consent=False), self.feedback_payload(consent=1),
            self.feedback_payload(comment="x" * 2001), self.feedback_payload(role="email_me"),
            self.feedback_payload(viewport="precise-device-fingerprint"),
            self.feedback_payload(ratings={"clarity": True, "usefulness": 3, "trust": 5}),
            self.feedback_payload(ratings={"clarity": 6, "usefulness": 3, "trust": 5}),
            self.feedback_payload(ratings={"clarity": 4, "trust": 5}),
            self.feedback_payload(email="synthetic@example.invalid"),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assert_error(400, lambda payload=payload: self.service.feedback(token, csrf, payload))

    def test_feedback_auth_csrf_quota_and_private_delete(self):
        self.configure(feedback_per_day=1)
        a, ac = self.login("alice")
        b, bc = self.login("bob")
        self.assert_error(403, lambda: self.service.feedback(a, "wrong", self.feedback_payload()))
        result = self.service.feedback(a, ac, self.feedback_payload(comment="ALICE_SYNTHETIC_PRIVATE_MARKER"))
        self.assertIsInstance(result, dict)
        self.assert_error(429, lambda: self.service.feedback(a, ac, self.feedback_payload()))
        self.service.feedback(b, bc, self.feedback_payload(comment="BOB_SYNTHETIC_PRIVATE_MARKER"))
        public_bob = json.dumps(self.service.state(b))
        self.assertNotIn("ALICE_SYNTHETIC_PRIVATE_MARKER", public_bob)
        self.assertNotIn("BOB_SYNTHETIC_PRIVATE_MARKER", public_bob)
        self.assert_error(403, lambda: self.service.delete_feedback(a, "wrong"))
        self.service.delete_feedback(a, ac)
        with closing(sqlite3.connect(self.service.db_path)) as db:
            comments = {row[0] for row in db.execute("SELECT comment FROM feedback")}
        self.assertNotIn("ALICE_SYNTHETIC_PRIVATE_MARKER", comments)
        self.assertIn("BOB_SYNTHETIC_PRIVATE_MARKER", comments)

    def test_feedback_retention_purge_removes_rows_and_collection_stops(self):
        self.configure(session_seconds=40 * 86400)
        code = "synthetic-retention-code-never-deploy-0000000"
        self.service.add_grant(code, expires_at=FEEDBACK_DELETE_AT + 86400)
        token, csrf = self.service.access(code, "synthetic-retention-client")
        self.service.feedback(token, csrf, self.feedback_payload(comment="SYNTHETIC_RETENTION_MARKER"))
        with closing(sqlite3.connect(self.service.db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 1)
        self.now = FEEDBACK_DELETE_AT + 1
        self.service.purge_feedback()
        with closing(sqlite3.connect(self.service.db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.assert_error(410, lambda: self.service.feedback(token, csrf, self.feedback_payload()))

    def test_request_cannot_select_another_session_or_local_path(self):
        token, csrf = self.login()
        for extra in ({"session_id": "other"}, {"db_path": "../other.sqlite3"}, {"role": "owner"}):
            self.assert_error((400, 409), lambda extra=extra: self.command(token, csrf, "pattern", **extra))
        for action in ("infer", "admin", "export", "signup", "load_fixture"):
            self.assert_error(400, lambda action=action: self.command(token, csrf, action))

    def test_service_state_does_not_reflect_access_credentials(self):
        token, csrf = self.login()
        state = json.dumps(self.service.state(token))
        self.assertNotIn(token, state)
        self.assertNotIn(csrf, state)
        self.assertNotIn("synthetic-unittest-access-code", state)
        self.assertEqual(self.service.state(token)["live_model_calls"], 0)

    def test_private_owner_cli_lists_triages_and_exports_without_credentials(self):
        token, csrf = self.login()
        self.service.feedback(token, csrf, self.feedback_payload(comment="SYNTHETIC_OWNER_REVIEW_MARKER"))
        prefix = [sys.executable, "-B", str(ROOT / "feedback_admin.py"), "--data-dir", str(self.config.data_dir)]
        listed = subprocess.run([*prefix, "list"], check=True, capture_output=True, text=True, timeout=10)
        records = [json.loads(line) for line in listed.stdout.splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["comment"], "SYNTHETIC_OWNER_REVIEW_MARKER")
        for private in ("session_id", "token_hash", "csrf", "code_hash", "grant_id"):
            self.assertNotIn(private, records[0])
        subprocess.run([*prefix, "triage", records[0]["id"], "actioned"], check=True, capture_output=True, text=True, timeout=10)
        with tempfile.TemporaryDirectory(prefix="touchline-private-test-export-") as export_dir:
            export = Path(export_dir) / "synthetic-feedback.jsonl"
            subprocess.run([*prefix, "export", "--output", str(export)], check=True, capture_output=True, text=True, timeout=10)
            exported = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(exported[0]["status"], "actioned")
            self.assertNotIn(token, export.read_text(encoding="utf-8"))
            self.assertNotIn(csrf, export.read_text(encoding="utf-8"))
            # Exporting cannot silently overwrite a previous private review copy.
            overwrite = subprocess.run([*prefix, "export", "--output", str(export)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(overwrite.returncode, 0)

    def handler(self, path, method="GET", body=b"", headers=()):
        """Exercise the real handler guards/replies without creating a socket."""
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(service=self.service, peer_key=b"synthetic-unittest-peer-key-never-deploy")
        handler.client_address = ("198.51.100.42", 12345)
        handler.path, handler.command = path, method
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.close_connection = True
        handler.wfile, handler.rfile = io.BytesIO(), io.BytesIO(body)
        handler.headers = Message()
        handler.headers.add_header("Host", "playtest.example.invalid")
        for key, value in headers:
            handler.headers.add_header(key, value)
        return handler

    @staticmethod
    def response(handler):
        raw = handler.wfile.getvalue()
        head, body = raw.split(b"\r\n\r\n", 1)
        status_line, headers = head.split(b"\r\n", 1)
        return int(status_line.split()[1]), BytesParser().parsebytes(headers), body

    def test_http_guards_reject_wrong_origin_duplicate_host_and_oversize_body(self):
        wrong_origin = self.handler("/api/access", "POST", b"{}", headers=[("Origin", "https://evil.example.invalid")])
        self.assert_error(403, lambda: wrong_origin._validate(mutation=True))
        duplicate_host = self.handler("/", headers=[("Host", "evil.example.invalid")])
        self.assert_error(403, lambda: duplicate_host._validate())
        duplicate_origin = self.handler("/api/access", "POST", headers=[("Origin", self.config.origin), ("Origin", "https://evil.example.invalid")])
        self.assert_error(403, lambda: duplicate_origin._validate(mutation=True))
        too_large = self.handler("/api/access", "POST", headers=[("Content-Type", "application/json"), ("Content-Length", str(MAX_BODY + 1))])
        self.assert_error(413, lambda: too_large._body())
        duplicate_length = self.handler("/api/access", "POST", b"{}", headers=[("Content-Type", "application/json"), ("Content-Length", "2"), ("Content-Length", "3")])
        self.assert_error(413, lambda: duplicate_length._body())

    def test_http_json_rejects_duplicate_fields_nonfinite_and_wrong_types(self):
        for body in (b'{"code":"a","code":"b"}', b'{"x":NaN}', b'[]', b'null', b'{'):
            with self.subTest(body=body):
                handler = self.handler("/api/access", "POST", body, headers=[("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
                self.assert_error(400, lambda: handler._body())

    def test_http_private_and_debug_routes_are_not_publicly_enumerable(self):
        for path in ("/api/feedback", "/api/admin", "/api/export", "/.env", "/base/touchline_core.py", "/playtest.sqlite3", "/../playtest.sqlite3"):
            with self.subTest(path=path):
                handler = self.handler(path)
                self.assert_error(404, lambda: handler._get())
        handler = self.handler("/api/state")
        self.assert_error(401, lambda: handler._get())
        query = self.handler("/?access_code=must-not-be-accepted")
        self.assert_error(400, lambda: query._validate())

    def test_http_cookie_and_response_headers_and_secure_logout(self):
        code = "synthetic-http-cookie-code-never-deploy-0000"
        self.service.add_grant(code, expires_at=self.now + 3600)
        body = json.dumps({"code": code}).encode()
        handler = self.handler("/api/access", "POST", body, headers=[("Origin", self.config.origin), ("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        handler._post()
        status, headers, response_body = self.response(handler)
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"]
        for flag in ("__Host-touchline_session=", "Path=/", "HttpOnly", "SameSite=Strict", "Secure"):
            self.assertIn(flag, cookie)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn(code.encode(), response_body)
        csrf = json.loads(response_body)["csrf"]
        cookie_pair = cookie.split(";", 1)[0]
        logout = self.handler("/api/logout", "POST", b"{}", headers=[("Origin", self.config.origin), ("Content-Type", "application/json"), ("Content-Length", "2"), ("Cookie", cookie_pair), ("X-CSRF-Token", csrf)])
        logout._post()
        logout_status, logout_headers, _ = self.response(logout)
        self.assertEqual(logout_status, 200)
        self.assertIn("Max-Age=0", logout_headers["Set-Cookie"])
        self.assertIn("Secure", logout_headers["Set-Cookie"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
