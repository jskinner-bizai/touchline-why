"""Rapid review regressions. Artificial grants and private data exist in Temp only."""
from concurrent.futures import ThreadPoolExecutor
import dataclasses
from datetime import datetime, timezone
from email.message import Message
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hosted_app import Config,HostedService,HttpError,Handler,FEEDBACK_DELETE_AT


class ReviewBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="touchline-review-backend-test-")
        self.addCleanup(self.tmp.cleanup)
        self.now=int(datetime(2026,10,22,tzinfo=timezone.utc).timestamp())
        self.config=Config(Path(self.tmp.name),"https://playtest.example.invalid")
        self.service=HostedService(self.config,clock=lambda:self.now)
        self.addCleanup(self.close)

    def close(self):
        if self.service is not None:self.service.close();self.service=None

    def restart(self,**changes):
        self.close();self.config=dataclasses.replace(self.config,**changes)
        self.service=HostedService(self.config,clock=lambda:self.now)

    def grant(self,label="alice",role="friend",max_sessions=10,expires_at=None):
        code="synthetic-review-code-"+label+"-never-deploy-000000"
        self.service.add_grant(code,role=role,expires_at=expires_at or self.now+3600,max_sessions=max_sessions)
        return code

    def login(self,label="alice",**kwargs):
        code=self.grant(label,**kwargs)
        return self.service.access(code,"synthetic-one-shared-proxy-peer")

    def payload(self,**changes):
        value={"feedback_id":uuid4().hex,"consent":True,"ratings":{"clarity":4,"usefulness":3,"trust":5},
               "role":"both","comment":"Synthetic private test feedback.","viewport":"phone"}
        value.update(changes);return value

    def error(self,status,callback):
        with self.assertRaises(HttpError) as raised:callback()
        self.assertEqual(raised.exception.status,status)

    def feedback_counts(self):
        with self.service.db() as db:
            return (db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
                    db.execute("SELECT COUNT(*) FROM feedback_requests").fetchone()[0])

    def command(self,token,csrf,action):
        return self.service.control(token,csrf,{"action":action,"operation_id":uuid4().hex})

    def http_login(self,code,forwarded):
        body=json.dumps({"code":code}).encode()
        handler=Handler.__new__(Handler)
        handler.server=SimpleNamespace(service=self.service,peer_key=b"synthetic-test-proxy-key")
        handler.client_address=("198.51.100.42",12345)
        handler.path="/api/access";handler.command="POST";handler.request_version="HTTP/1.1"
        handler.requestline="POST /api/access HTTP/1.1";handler.close_connection=True
        handler.wfile=io.BytesIO();handler.rfile=io.BytesIO(body);handler.headers=Message()
        for key,value in (("Host","playtest.example.invalid"),("Origin",self.config.origin),
                          ("Content-Type","application/json"),("Content-Length",str(len(body))),
                          ("X-Forwarded-For",forwarded),("Forwarded",f"for={forwarded};proto=https")):
            handler.headers.add_header(key,value)
        handler.do_POST()
        return int(handler.wfile.getvalue().split(b" ",2)[1])

    def test_identical_feedback_retry_preserves_receipt_status_and_quotas_across_restart(self):
        self.restart(feedback_per_day=1,max_feedback=1)
        token,csrf=self.login();payload=self.payload()
        first=self.service.feedback(token,csrf,payload)
        self.assertFalse(first["duplicate"]);self.assertTrue(first["saved"])
        self.assertRegex(first["receipt_id"],r"^[0-9a-f]{32}$")
        with self.service.db() as db:
            db.execute("UPDATE feedback SET status='reviewing' WHERE id=?",(first["receipt_id"],))
            before=[tuple(row) for row in db.execute("SELECT key,count,expires_at FROM buckets ORDER BY key")]
        self.restart()
        second=self.service.feedback(token,csrf,payload)
        self.assertEqual(second["receipt_id"],first["receipt_id"]);self.assertTrue(second["duplicate"])
        self.assertEqual(self.feedback_counts(),(1,1))
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT status FROM feedback").fetchone()[0],"reviewing")
            self.assertEqual([tuple(row) for row in db.execute("SELECT key,count,expires_at FROM buckets ORDER BY key")],before)
        for private in (token,csrf,payload["comment"],payload["feedback_id"]):self.assertNotIn(private,json.dumps(second))

    def test_same_feedback_id_with_changed_valid_content_conflicts_without_spending_quota(self):
        token,csrf=self.login();payload=self.payload()
        first=self.service.feedback(token,csrf,payload)
        self.error(409,lambda:self.service.feedback(token,csrf,{**payload,"comment":"Different synthetic feedback."}))
        self.assertEqual(self.feedback_counts(),(1,1))
        self.assertEqual(self.service.feedback(token,csrf,payload)["receipt_id"],first["receipt_id"])
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT count FROM buckets WHERE key LIKE 'feedback:%'").fetchone()[0],1)

    def test_concurrent_identical_requests_commit_one_feedback_and_one_receipt(self):
        token,csrf=self.login();payload=self.payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.service.feedback(token,csrf,payload),range(2)))
        self.assertEqual(len({row["receipt_id"] for row in results}),1)
        self.assertEqual(sorted(row["duplicate"] for row in results),[False,True])
        self.assertEqual(self.feedback_counts(),(1,1))

    def test_client_feedback_ids_are_scoped_per_session(self):
        alice,ac=self.login("alice");bob,bc=self.login("bob");payload=self.payload()
        a=self.service.feedback(alice,ac,payload);b=self.service.feedback(bob,bc,payload)
        self.assertNotEqual(a["receipt_id"],b["receipt_id"]);self.assertEqual(self.feedback_counts(),(2,2))
        self.assertNotIn(a["receipt_id"],json.dumps(self.service.state(bob)))

    def test_additive_migration_preserves_legacy_feedback_status_and_core_journal(self):
        token,csrf=self.login();self.command(token,csrf,"pattern");self.command(token,csrf,"correct")
        session_id=self.service._session(token)["id"]
        with self.service.db() as db:
            db.execute("DROP TABLE feedback_requests")  # Temp-only legacy database fixture.
            db.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("legacy-receipt",session_id,self.now,1,5,4,3,"both","Legacy synthetic feedback.","phone","actioned"))
            before=[tuple(row) for row in db.execute("SELECT * FROM feedback")]
            operations=[tuple(row) for row in db.execute("SELECT * FROM host_operations ORDER BY operation_id")]
        self.restart()
        with self.service.db() as db:
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM feedback")],before)
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM host_operations ORDER BY operation_id")],operations)
            self.assertEqual(len(list(db.execute("PRAGMA table_info(feedback)"))),11)
        self.assertEqual(self.service.state(token)["envelope"]["provenance"]["event_revisions"]["e010"],2)
        self.service.feedback(token,csrf,self.payload());self.assertEqual(self.feedback_counts(),(2,1))

    def test_explicit_delete_scrubs_payload_hash_and_stale_retry_cannot_resurrect_feedback(self):
        token,csrf=self.login();payload=self.payload();self.service.feedback(token,csrf,payload)
        self.service.delete_feedback(token,csrf);self.assertEqual(self.feedback_counts(),(0,1))
        self.error(410,lambda:self.service.feedback(token,csrf,payload))
        with self.service.db() as db:
            row=db.execute("SELECT payload_hash,deleted FROM feedback_requests").fetchone()
            self.assertIsNone(row["payload_hash"]);self.assertEqual(row["deleted"],1)
        self.service.feedback(token,csrf,self.payload());self.assertEqual(self.feedback_counts(),(1,2))

    def test_orphaned_owner_deleted_feedback_is_not_acknowledged_as_saved(self):
        token,csrf=self.login();payload=self.payload();self.service.feedback(token,csrf,payload)
        with self.service.db() as db:db.execute("DELETE FROM feedback")
        self.restart();self.error(410,lambda:self.service.feedback(token,csrf,payload))
        with self.service.db() as db:self.assertIsNone(db.execute("SELECT payload_hash FROM feedback_requests").fetchone()[0])

    def test_actual_private_cli_purge_scrubs_retry_hashes_and_keeps_deleted_tombstones(self):
        token,csrf=self.login();payload=self.payload();self.service.feedback(token,csrf,payload)
        result=subprocess.run([sys.executable,"-B",str(ROOT/"feedback_admin.py"),"--data-dir",str(self.config.data_dir),"purge"],
            input="DELETE PLAYTEST FEEDBACK\n",text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('"deleted": 1',result.stdout)
        self.assertEqual(self.feedback_counts(),(0,1))
        with self.service.db() as db:
            row=db.execute("SELECT payload_hash,deleted FROM feedback_requests").fetchone()
            self.assertIsNone(row["payload_hash"]);self.assertEqual(row["deleted"],1)
        self.error(410,lambda:self.service.feedback(token,csrf,payload))

    def test_retention_cutoff_removes_feedback_and_retry_metadata(self):
        self.restart(session_seconds=40*86400)
        token,csrf=self.login(expires_at=FEEDBACK_DELETE_AT+86400)
        payload=self.payload();self.service.feedback(token,csrf,payload)
        self.now=FEEDBACK_DELETE_AT+1;self.service.purge_feedback()
        self.assertEqual(self.feedback_counts(),(0,0))
        self.error(410,lambda:self.service.feedback(token,csrf,payload))

    def test_feedback_id_is_required_and_bounded_and_receipt_budget_cannot_grow_by_deleting(self):
        self.restart(max_feedback=1)
        token,csrf=self.login()
        for identifier in (None,"","x"*129,"bad/id"):
            value=self.payload(feedback_id=identifier)
            self.error(400,lambda value=value:self.service.feedback(token,csrf,value))
        missing=self.payload();del missing["feedback_id"]
        self.error(400,lambda:self.service.feedback(token,csrf,missing))
        self.assertEqual(self.feedback_counts(),(0,0))
        self.service.feedback(token,csrf,self.payload());self.service.delete_feedback(token,csrf)
        self.error(503,lambda:self.service.feedback(token,csrf,self.payload()))
        self.assertEqual(self.feedback_counts(),(0,1))

    def test_twenty_four_valid_distinct_judge_grants_share_one_proxy_peer(self):
        codes=[]
        for index in range(24):
            code=self.grant(f"judge-{index}",role="judge",max_sessions=1);codes.append(code)
            self.assertEqual(self.http_login(code,"203.0.113.55"),200)
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],24)
            keys=" ".join(row[0] for row in db.execute("SELECT key FROM buckets"))
        for secret in [*codes,"198.51.100.42","203.0.113.55"]:self.assertNotIn(secret,keys)

    def test_one_valid_judge_grant_accepts_twenty_logins_behind_one_peer(self):
        code=self.grant("shared-judge",role="judge",max_sessions=60)
        for index in range(21):self.assertEqual(self.http_login(code,f"203.0.113.{index}"),200)
        with self.service.db() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],21)

    def test_forwarding_headers_and_peer_changes_cannot_bypass_friend_grant_limit(self):
        code=self.grant("bounded-friend",max_sessions=50)
        for index in range(15):self.assertEqual(self.http_login(code,f"203.0.113.{index}"),200)
        self.assertEqual(self.http_login(code,"192.0.2.222"),429)
        self.restart();self.error(429,lambda:self.service.access(code,"new-proxy-peer"))
        self.now+=601;self.service.access(code,"new-proxy-peer")

    def test_invalid_guess_limits_do_not_consume_recognized_grant_allowance(self):
        valid=self.grant("valid-after-failures",role="judge",max_sessions=1)
        for index in range(60):
            self.error(401,lambda index=index:self.service.access(f"synthetic-invalid-code-{index:03d}-never-deploy-0000","one-proxy"))
        self.error(429,lambda:self.service.access("synthetic-next-invalid-code-never-deploy-000000","changed-peer"))
        self.assertEqual(len(self.service.access(valid,"one-proxy")),2)

    def test_invalid_per_code_and_valid_role_caps_persist_and_ignore_forwarding(self):
        invalid="synthetic-repeat-invalid-code-never-deploy-0000"
        for index in range(5):self.assertEqual(self.http_login(invalid,f"203.0.113.{index}"),401)
        self.assertEqual(self.http_login(invalid,"192.0.2.1"),429)
        self.restart();self.assertEqual(self.http_login(invalid,"192.0.2.2"),429)
        valid=self.grant("global-cap",role="judge",max_sessions=10)
        self.assertEqual(self.http_login(valid,"new-forwarded-value"),200)
        with self.service.db() as db:
            db.execute("UPDATE buckets SET count=300 WHERE key=?",(f"login-valid-role:judge:{self.now//3600}",))
        self.assertEqual(self.http_login(valid,"new-forwarded-value"),429)
        self.restart();self.error(429,lambda:self.service.access(valid,"new-peer"))

    def test_four_hour_expiry_new_login_starts_fresh_match_and_keeps_old_archive(self):
        code=self.grant("four-hour",expires_at=self.now+86400)
        token,csrf=self.service.access(code,"one-proxy")
        self.command(token,csrf,"pattern");self.command(token,csrf,"correct")
        self.now+=14401
        self.error(401,lambda:self.service.state(token))
        new_token,new_csrf=self.service.access(code,"one-proxy")
        self.assertNotEqual(token,new_token);fresh=self.service.state(new_token)
        self.assertEqual(fresh["position"],0)
        self.assertEqual(self.command(new_token,new_csrf,"pattern")["envelope"]["provenance"]["event_revisions"]["e010"],1)
        self.assertEqual(len(list((self.config.data_dir/"sessions").rglob("match-0.sqlite3"))),2)


if __name__=="__main__":unittest.main()
