"""G1: active admission, preserved history and scratch-only concurrency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hosted_app import Config, HostedService, HttpError, digest


class SessionCapacityRevision5Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='touchline-g1-test-')
        self.addCleanup(self.temp.cleanup)
        self.now = int(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())
        self.services = []
        self.service = self.make_service(max_sessions=10, session_seconds=10)
        self.addCleanup(self.close_all)

    def close_all(self):
        for service in self.services:
            service.close()

    def make_service(self, **changes):
        config = Config(Path(self.temp.name), 'https://synthetic.invalid', **changes)
        service = HostedService(config, clock=lambda: self.now)
        self.services.append(service)
        return service

    def grant(self, name, role='judge', capacity=10, duration=86400):
        code = 'synthetic-g1-' + name + '-never-deploy-000000000000'
        gid = self.service.add_grant(code, role, self.now + duration, capacity)
        return code, gid

    def rows(self):
        with self.service.db() as db:
            return db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]

    def active(self):
        with self.service.db() as db:
            return db.execute('''SELECT COUNT(*) FROM sessions JOIN grants ON grants.id=sessions.grant_id
              WHERE sessions.expires_at>? AND grants.expires_at>? AND grants.disabled=0''',
              (self.now, self.now)).fetchone()[0]

    def role_count(self):
        with self.service.db() as db:
            return db.execute("SELECT COALESCE(SUM(count),0) FROM buckets WHERE key LIKE 'login-valid-role:%'").fetchone()[0]

    def assert_error(self, status, call):
        with self.assertRaises(HttpError) as caught:
            call()
        self.assertEqual(caught.exception.status, status)
        return caught.exception

    def command(self, token, csrf, action):
        return self.service.control(token, csrf, {'action': action, 'operation_id': uuid4().hex})

    def session_id(self, token):
        with self.service.db() as db:
            return db.execute('SELECT id FROM sessions WHERE token_hash=?', (digest(token),)).fetchone()[0]

    def test_exact_session_expiry_frees_global_capacity_without_deleting_rows(self):
        self.service.close()
        self.service = self.make_service(max_sessions=2, session_seconds=10)
        code, _ = self.grant('two', capacity=2)
        old = [self.service.access(code, 'same-peer')[0] for _ in range(2)]
        self.assert_error(503, lambda: self.service.access(code, 'same-peer'))
        self.now += 9
        self.assert_error(503, lambda: self.service.access(code, 'same-peer'))
        self.now += 1
        new = [self.service.access(code, 'same-peer')[0] for _ in range(2)]
        self.assertEqual(self.rows(), 4)
        self.assertEqual(self.active(), 2)
        for token in old:
            self.assert_error(401, lambda token=token: self.service.session(token))
        for token in new:
            self.assertTrue(self.service.session(token)['authenticated'])

    def test_expired_rows_beyond_global_and_grant_limits_do_not_charge_active_capacity(self):
        code, gid = self.grant('seeded', capacity=1)
        with self.service.db() as db:
            for _ in range(25):
                db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,0)',
                    (uuid4().hex, uuid4().hex, 'synthetic-csrf', gid, self.now - 20, self.now))
        token, _ = self.service.access(code, 'same-peer')
        self.assertTrue(self.service.session(token)['authenticated'])
        self.assertEqual(self.rows(), 26)
        self.assertEqual(self.active(), 1)
        self.assert_error(429, lambda: self.service.access(code, 'same-peer'))

    def test_per_grant_active_limit_reclaims_at_expiry_and_after_logout(self):
        code, _ = self.grant('one', capacity=1)
        token, csrf = self.service.access(code, 'same-peer')
        self.assert_error(429, lambda: self.service.access(code, 'same-peer'))
        self.service.logout(token, csrf)
        replacement, _ = self.service.access(code, 'same-peer')
        self.assert_error(401, lambda: self.service.session(token))
        self.now += 10
        next_token, _ = self.service.access(code, 'same-peer')
        self.assert_error(401, lambda: self.service.session(replacement))
        self.assertTrue(self.service.session(next_token)['authenticated'])
        self.assertEqual(self.rows(), 3)

    def test_expired_grant_rows_stop_counting_before_session_timestamp(self):
        self.service.close()
        self.service = self.make_service(max_sessions=1, session_seconds=100)
        old, _ = self.grant('grant-expiry', capacity=1, duration=5)
        token, _ = self.service.access(old, 'same-peer')
        # Exercise the grant-side filter independently of the normal min()
        # expiry clamp, as could exist in an older retained metadata row.
        with self.service.db() as db:
            db.execute('UPDATE sessions SET expires_at=?', (self.now + 100,))
        self.now += 5
        replacement, _ = self.grant('fresh-grant', capacity=1)
        new_token, _ = self.service.access(replacement, 'same-peer')
        self.assert_error(401, lambda: self.service.session(token))
        self.assertTrue(self.service.session(new_token)['authenticated'])
        self.assertEqual(self.rows(), 2)

    def test_revoked_grant_frees_capacity_and_cannot_authenticate(self):
        self.service.close()
        self.service = self.make_service(max_sessions=1, session_seconds=100)
        code, gid = self.grant('revoke', capacity=1)
        token, _ = self.service.access(code, 'same-peer')
        self.service.revoke_grant(gid)
        other, _ = self.grant('after-revoke', capacity=1)
        self.service.access(other, 'same-peer')
        self.assert_error(401, lambda: self.service.session(token))
        self.assert_error(401, lambda: self.service.access(code, 'same-peer'))
        self.assertEqual(self.rows(), 2)

    def test_friends_cannot_fill_judge_reservation_and_no_current_session_is_deleted(self):
        friend, _ = self.grant('friend-load', 'friend', 10)
        tokens = [self.service.access(friend, 'same-peer')[0] for _ in range(8)]
        self.assert_error(503, lambda: self.service.access(friend, 'same-peer'))
        before_rate = self.role_count()
        judge, _ = self.grant('reserved-judge', capacity=10)
        judges = [self.service.access(judge, 'same-peer')[0] for _ in range(2)]
        self.assert_error(503, lambda: self.service.access(judge, 'same-peer'))
        self.assertEqual(self.role_count(), before_rate + 2)
        self.assertEqual(self.active(), 10)
        for token in tokens + judges:
            self.assertTrue(self.service.session(token)['authenticated'])

    def test_reservation_limits_friends_not_total_when_judges_use_shared_slots(self):
        judge, _ = self.grant('shared-judge', capacity=10)
        friend, _ = self.grant('shared-friend', 'friend', 10)
        for _ in range(6):
            self.service.access(judge, 'same-peer')
        for _ in range(4):
            self.service.access(friend, 'same-peer')
        self.assertEqual(self.active(), 10)
        self.assert_error(503, lambda: self.service.access(friend, 'same-peer'))

    def test_expired_cache_is_closed_but_active_judge_handle_and_journals_survive(self):
        code, _ = self.grant('cache', capacity=3)
        old_token, old_csrf = self.service.access(code, 'same-peer')
        self.command(old_token, old_csrf, 'pattern')
        self.command(old_token, old_csrf, 'correct')
        old_id = self.session_id(old_token)
        old_path = self.service.data_dir / 'sessions' / old_id / 'match-0.sqlite3'
        self.assertTrue(old_path.exists())
        self.now += 5
        active_token, active_csrf = self.service.access(code, 'same-peer')
        self.command(active_token, active_csrf, 'pattern')
        active_id = self.session_id(active_token)
        active_handle = self.service.desks[active_id][1]
        self.now += 5
        self.service.access(code, 'same-peer')
        self.assertNotIn(old_id, self.service.desks)
        self.assertIs(self.service.desks[active_id][1], active_handle)
        self.assertTrue(old_path.exists())
        self.assertEqual(self.rows(), 3)
        self.assert_error(401, lambda: self.service.state(old_token))
        self.assertEqual(self.service.state(active_token)['envelope']['provenance']['event_revisions']['e010'], 1)

    def test_revoke_releases_only_its_cached_handles_and_keeps_journals(self):
        first, gid = self.grant('cached-revoke', capacity=1)
        second, _ = self.grant('cached-active', capacity=1)
        old, old_csrf = self.service.access(first, 'same-peer')
        active, active_csrf = self.service.access(second, 'same-peer')
        self.command(old, old_csrf, 'pattern')
        self.command(active, active_csrf, 'pattern')
        old_id, active_id = self.session_id(old), self.session_id(active)
        active_handle = self.service.desks[active_id][1]
        self.service.revoke_grant(gid)
        self.assertNotIn(old_id, self.service.desks)
        self.assertIs(self.service.desks[active_id][1], active_handle)
        self.assertTrue((self.service.data_dir / 'sessions' / old_id / 'match-0.sqlite3').exists())
        self.assertEqual(self.rows(), 2)

    def test_expired_token_request_releases_cached_handle(self):
        code, _ = self.grant('expired-read', capacity=1)
        token, csrf = self.service.access(code, 'same-peer')
        self.command(token, csrf, 'pattern')
        sid = self.session_id(token)
        self.now += 10
        self.assert_error(401, lambda: self.service.session(token))
        self.assertNotIn(sid, self.service.desks)
        self.assertTrue((self.service.data_dir / 'sessions' / sid / 'match-0.sqlite3').exists())

    def test_reclaimed_session_cannot_inherit_another_tenants_match_or_feedback(self):
        code, _ = self.grant('tenant', capacity=1)
        old, csrf = self.service.access(code, 'same-peer')
        self.command(old, csrf, 'pattern')
        self.command(old, csrf, 'correct')
        payload = {'feedback_id': uuid4().hex, 'consent': True,
            'ratings': {'clarity': 4, 'usefulness': 4, 'trust': 4}, 'role': 'football_fan',
            'comment': 'Synthetic retained feedback', 'viewport': 'phone'}
        self.service.feedback(old, csrf, payload)
        old_id = self.session_id(old)
        self.service.logout(old, csrf)
        new, new_csrf = self.service.access(code, 'same-peer')
        new_id = self.session_id(new)
        self.assertNotEqual(old_id, new_id)
        fresh = self.service.state(new)
        self.assertEqual(fresh['publication']['event_time']['through_ms'], 0)
        self.assertEqual(fresh['envelope']['provenance']['corrections'], [])
        self.service.delete_feedback(new, new_csrf)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback WHERE session_id=?', (old_id,)).fetchone()[0], 1)
        self.assertTrue((self.service.data_dir / 'sessions' / old_id / 'match-0.sqlite3').exists())

    def test_active_capacity_and_ended_credentials_survive_service_restart(self):
        code, _ = self.grant('restart', capacity=1)
        old, _ = self.service.access(code, 'same-peer')
        self.now += 10
        self.service.close()
        self.service = self.make_service(max_sessions=10, session_seconds=10)
        new, _ = self.service.access(code, 'same-peer')
        self.assert_error(401, lambda: self.service.session(old))
        self.assertTrue(self.service.session(new)['authenticated'])
        self.assertEqual(self.rows(), 2)

    def test_parallel_service_instances_cannot_oversubscribe_global_capacity(self):
        self.service.close()
        self.service = self.make_service(max_sessions=5, session_seconds=10)
        second = self.make_service(max_sessions=5, session_seconds=10)
        code, _ = self.grant('parallel', capacity=5)
        def login(index):
            try:
                (self.service if index % 2 else second).access(code, 'same-peer')
                return 200
            except HttpError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=10) as pool:
            statuses = list(pool.map(login, range(10)))
        self.assertEqual(statuses.count(200), 5)
        self.assertEqual(statuses.count(503), 5)
        self.assertEqual(self.active(), 5)
        self.assertEqual(self.role_count(), 5)

    def test_parallel_friend_admission_preserves_reserved_judge_slots(self):
        second = self.make_service(max_sessions=10, session_seconds=10)
        code, _ = self.grant('parallel-friend', 'friend', 10)
        def login(index):
            try:
                (self.service if index % 2 else second).access(code, 'same-peer')
                return 200
            except HttpError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(login, range(12)))
        self.assertEqual(statuses.count(200), 8)
        self.assertEqual(statuses.count(503), 4)
        judge, _ = self.grant('parallel-reserved', capacity=2)
        for _ in range(2):
            self.service.access(judge, 'same-peer')
        self.assertEqual(self.active(), 10)
        self.assertEqual(self.role_count(), 10)

    def test_valid_rate_bucket_updates_roll_back_if_later_role_limit_rejects(self):
        code, _ = self.grant('rate-rollback', capacity=1)
        with self.service.db() as db:
            db.execute('INSERT INTO buckets VALUES(?,?,?)',
                (f'login-valid-role:judge:{self.now // 3600}', 300, (self.now // 3600 + 1) * 3600))
        self.assert_error(429, lambda: self.service.access(code, 'same-peer'))
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM buckets WHERE key LIKE 'login-grant:%' OR key LIKE 'login-grant-hour:%'").fetchone()[0], 0)
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.role_count(), 300)

    def test_storage_budget_is_checked_before_allocating_another_session(self):
        self.service.close()
        self.service = self.make_service(max_sessions=10, session_seconds=10, max_data_bytes=1)
        code, _ = self.grant('storage', capacity=1)
        error = self.assert_error(503, lambda: self.service.access(code, 'same-peer'))
        self.assertIn('storage', str(error))
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.role_count(), 0)


if __name__ == '__main__':
    unittest.main()
