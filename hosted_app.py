"""Isolated controlled playtest wrapper. No model import, network client or signup.

Preparation only: grants, hosting and deployment need explicit owner approval.
The original recorded engine in base/ is unchanged. State is private per browser
session, not a global producer singleton. This stdlib server requires a qualified
TLS/reverse-proxy host before Internet use; local tests are not host evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import io
import json
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'base'))
from app_advisory import AdvisoryDesk
from touchline_core import load_events
from verify_package import verify as verify_base

TOKEN = re.compile(r'^[A-Za-z0-9_-]{32,128}$')
OPERATION = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
COOKIE = '__Host-touchline_session'
FEEDBACK_DELETE_AT = int(datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp())
MAX_BODY = 16384
READ_SESSION = object()
ALLOWED_ACTIONS = {'pattern', 'replay3', 'correct', 'timeout', 'recover', 'finish', 'reset', 'view', 'new_match',
                   'review_copy', 'approve_copy', 'clear_copy'}


class HttpError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Config:
    data_dir: Path
    origin: str
    allow_local_http: bool = False
    max_sessions: int = 100
    max_desks: int = 8
    max_matches: int = 3
    session_seconds: int = 14400
    read_per_minute: int = 90
    control_per_minute: int = 20
    feedback_per_day: int = 5
    max_feedback: int = 1000
    max_grants: int = 200
    max_data_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'} or not parsed.netloc:
            raise ValueError('Configure one exact origin without path, credentials or query')
        local = parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
        if self.allow_local_http and not (parsed.scheme == 'http' and local):
            raise ValueError('Local HTTP test mode requires one exact loopback HTTP origin')
        if parsed.scheme != 'https' and not (self.allow_local_http and parsed.scheme == 'http' and local):
            raise ValueError('HTTPS is required outside explicit loopback tests')
        if not all(type(x) is int and x > 0 for x in (self.max_sessions, self.max_desks, self.max_matches, self.session_seconds,
                self.read_per_minute, self.control_per_minute, self.feedback_per_day, self.max_feedback, self.max_grants, self.max_data_bytes)):
            raise ValueError('Limits must be positive integers')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class HostedService:
    def __init__(self, config: Config, clock=time.time):
        self.config, self.clock = config, clock
        verify_base(ROOT / 'base')
        self.lock = threading.RLock()
        self.closed = False
        self.desks = OrderedDict()
        self.events = load_events(ROOT / 'base' / 'synthetic_match.jsonl')
        self.data_dir = Path(config.data_dir).resolve()
        if self.data_dir == ROOT or ROOT in self.data_dir.parents:
            raise ValueError('Keep private runtime data outside the application/package folder')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'sessions').mkdir(exist_ok=True)
        self.db_path = self.data_dir / 'playtest.sqlite3'
        if (self.data_dir / 'sessions').is_symlink() or self.db_path.is_symlink():
            raise ValueError('Private runtime paths cannot be symbolic links')
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS grants(
              id TEXT PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, role TEXT NOT NULL,
              expires_at INTEGER NOT NULL, max_sessions INTEGER NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(
              id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, csrf TEXT NOT NULL,
              grant_id TEXT NOT NULL REFERENCES grants(id), created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL, generation INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS sessions_admission ON sessions(expires_at,grant_id);
            CREATE TABLE IF NOT EXISTS feedback(
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
              created_at INTEGER NOT NULL, consent INTEGER NOT NULL,
              clarity INTEGER NOT NULL, usefulness INTEGER NOT NULL, trust INTEGER NOT NULL,
              role TEXT NOT NULL, comment TEXT NOT NULL, viewport TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'new');
            CREATE TABLE IF NOT EXISTS buckets(
              key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS host_operations(
              session_id TEXT NOT NULL REFERENCES sessions(id), operation_id TEXT NOT NULL,
              command_hash TEXT NOT NULL, PRIMARY KEY(session_id,operation_id));
            CREATE TABLE IF NOT EXISTS feedback_requests(
              session_id TEXT NOT NULL REFERENCES sessions(id), feedback_id TEXT NOT NULL,
              payload_hash TEXT, receipt_id TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL,
              deleted INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY(session_id,feedback_id));
            ''')
        self.purge_feedback()

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def now(self):
        return int(self.clock())

    def _healthy(self):
        if self.closed:
            raise HttpError(503, 'Playtest is stopping. Please try again later.')

    def _storage_budget(self):
        if sum(p.stat().st_size for p in self.data_dir.rglob('*') if p.is_file()) > self.config.max_data_bytes:
            raise HttpError(503, 'Playtest storage limit reached. The owner must review capacity.')

    def _limit_in_db(self, db, category, subject, maximum, seconds=60):
        now = self.now()
        key = f'{category}:{subject}:{now // seconds}'
        db.execute('DELETE FROM buckets WHERE expires_at <= ?', (now,))
        row = db.execute('SELECT count FROM buckets WHERE key=?', (key,)).fetchone()
        if row and row['count'] >= maximum:
            raise HttpError(429, 'Please pause before trying again. Your match has been kept.')
        if not row and db.execute('SELECT COUNT(*) FROM buckets').fetchone()[0] >= 2048:
            raise HttpError(503, 'Playtest is busy. Please try again later.')
        db.execute('INSERT INTO buckets VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
                   (key, 1, (now // seconds + 1) * seconds))

    def _limit(self, category, subject, maximum, seconds=60):
        with self.db() as db:
            self._limit_in_db(db, category, subject, maximum, seconds)

    def add_grant(self, code, role='friend', expires_at=None, max_sessions=10):
        """Owner CLI / synthetic tests only. Never exposed as an HTTP route."""
        if not isinstance(code, str) or not TOKEN.fullmatch(code) or role not in {'friend', 'judge'}:
            raise ValueError('Use a high-entropy 32+ character access code and an allowed role')
        if type(max_sessions) is not int or not 1 <= max_sessions <= self.config.max_sessions:
            raise ValueError('Grant sessions exceed configured capacity')
        if type(expires_at) is not int or expires_at <= self.now():
            raise ValueError('Set an explicit future grant expiry')
        with self.lock, self.db() as db:
            if db.execute('SELECT COUNT(*) FROM grants').fetchone()[0] >= self.config.max_grants:
                raise HttpError(503, 'Grant capacity reached')
            grant_id = secrets.token_hex(16)
            db.execute('INSERT INTO grants(id,code_hash,role,expires_at,max_sessions) VALUES(?,?,?,?,?)',
                       (grant_id, digest(code), role, expires_at, max_sessions))
            return grant_id

    def revoke_grant(self, grant_id):
        with self.lock:
            with self.db() as db:
                db.execute('UPDATE grants SET disabled=1 WHERE id=?', (grant_id,))
            self._reap_inactive_desks()

    def _login_limit(self, category, subject, maximum, seconds, db=None):
        try:
            if db is None:
                self._limit(category, subject, maximum, seconds)
            else:
                self._limit_in_db(db, category, subject, maximum, seconds)
        except HttpError as error:
            if error.status == 429:
                raise HttpError(429, 'Too many sign-in attempts. Wait before trying your access code again.') from None
            raise

    def _failed_login(self, code_hash=None):
        # Unknown guesses share a global failure ceiling. A validated-format
        # guess also has a bounded hashed-code bucket; raw code/IP is not stored.
        self._login_limit('login-failed-global', 'all', 60, 600)
        self._login_limit('login-invalid-code', code_hash or 'invalid-shape', 5, 600)
        raise HttpError(401, 'That access code is unavailable. Check the code from the owner.')

    def access(self, code, client_key):
        with self.lock:
            self._healthy()
            # The compatibility client_key and all forwarding headers have no
            # authority over login limits. A reverse proxy can put every tester
            # behind one TCP peer. Valid grants therefore have independent
            # hashed-code buckets. Failed guesses cannot spend the separate
            # global budget for recognized active grants.
            if not isinstance(code, str) or not TOKEN.fullmatch(code):
                self._failed_login()
            code_hash=digest(code)
            now = self.now()
            with self.db() as db:
                grant = db.execute('SELECT * FROM grants WHERE code_hash=?', (code_hash,)).fetchone()
            if not grant or grant['disabled'] or grant['expires_at'] <= now:
                self._failed_login(code_hash)
            self._reap_inactive_desks(now)
            self._storage_budget()
            try:
                with self.db() as db:
                    # One SQLite write transaction owns the active-count check,
                    # role reservation, rate charging and insertion. Keep this
                    # atomic even if another service instance opens the DB.
                    db.execute('BEGIN IMMEDIATE')
                    now = self.now()
                    grant = db.execute('SELECT * FROM grants WHERE code_hash=?', (code_hash,)).fetchone()
                    if not grant or grant['disabled'] or grant['expires_at'] <= now:
                        raise HttpError(401, 'That access code is unavailable. Check the code from the owner.')
                    self._admission_capacity(db, grant, now)
                    judge = grant['role'] == 'judge'
                    self._login_limit('login-grant', grant['code_hash'], 30 if judge else 15, 600, db)
                    self._login_limit('login-grant-hour', grant['code_hash'], 90 if judge else 30, 3600, db)
                    self._login_limit('login-valid-role', grant['role'], 300 if judge else 150, 3600, db)
                    token, csrf, sid = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_hex(16)
                    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,0)',
                               (sid, digest(token), csrf, grant['id'], now, min(now + self.config.session_seconds, grant['expires_at'])))
            except HttpError as error:
                if error.status == 401:
                    # Grant expiry/revocation racing admission is rejected and
                    # charged as a failed guess only after releasing the DB.
                    self._failed_login(code_hash)
                raise
            return token, csrf

    def _admission_capacity(self, db, grant, now):
        counts = db.execute('''SELECT COUNT(*) AS total,
          COALESCE(SUM(grants.role='friend'),0) AS friends,
          COALESCE(SUM(sessions.grant_id=?),0) AS per_grant
          FROM sessions JOIN grants ON grants.id=sessions.grant_id
          WHERE sessions.expires_at>? AND grants.expires_at>? AND grants.disabled=0''',
          (grant['id'], now, now)).fetchone()
        if counts['total'] >= self.config.max_sessions:
            raise HttpError(503, 'Playtest active-session capacity reached. Try again after a session ends or use the downloadable build.')
        if counts['per_grant'] >= grant['max_sessions']:
            raise HttpError(429, 'This code has reached its active-session allowance. Try again after a session ends.')
        # Friends cannot fill the final fifth of active capacity. Judges may
        # use shared free slots too; no current session is evicted or deleted.
        friend_capacity = self.config.max_sessions - self.config.max_sessions // 5
        if grant['role'] == 'friend' and counts['friends'] >= friend_capacity:
            raise HttpError(503, 'Friend playtest capacity reached. Remaining session slots are reserved for judges.')

    def _session(self, token, csrf=READ_SESSION):
        self._healthy()
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise HttpError(401, 'Enter your playtest access code to continue.')
        with self.db() as db:
            row = db.execute('''SELECT sessions.*, grants.role, grants.disabled, grants.expires_at AS grant_expiry
              FROM sessions JOIN grants ON grants.id=sessions.grant_id WHERE token_hash=?''', (digest(token),)).fetchone()
        if not row or row['disabled'] or min(row['expires_at'], row['grant_expiry']) <= self.now():
            if row:
                self._close_desk(row['id'])
            raise HttpError(401, 'Your playtest session has ended. Enter an active access code to continue.')
        if csrf is not READ_SESSION and (not isinstance(csrf, str) or not hmac.compare_digest(csrf, row['csrf'])):
            raise HttpError(403, 'This action needs a fresh playtest page. Reload, then try again.')
        return dict(row)

    def session(self, token):
        with self.lock:
            row = self._session(token)
            return {'authenticated': True, 'csrf': row['csrf'], 'participant_role': row['role'],
                    'expires_at': row['expires_at'], 'matches_used': row['generation'] + 1,
                    'max_matches': self.config.max_matches,
                    'feedback_retention_planned_until': '2026-11-18', 'live_model_calls': 0}

    def logout(self, token, csrf):
        with self.lock:
            row = self._session(token, csrf)
            with self.db() as db:
                db.execute('UPDATE sessions SET expires_at=? WHERE id=?', (self.now(), row['id']))
            self._close_desk(row['id'])

    def _close_desk(self, sid):
        entry = self.desks.pop(sid, None)
        if entry:
            entry[1].close()

    def _reap_inactive_desks(self, now=None):
        """Release only inactive cached handles; preserve every journal/row."""
        if not self.desks:
            return
        now = self.now() if now is None else now
        cached = tuple(self.desks)
        placeholders = ','.join('?' for _ in cached)
        with self.db() as db:
            active = {row['id'] for row in db.execute(f'''SELECT sessions.id
              FROM sessions JOIN grants ON grants.id=sessions.grant_id
              WHERE sessions.id IN ({placeholders}) AND sessions.expires_at>?
                AND grants.expires_at>? AND grants.disabled=0''', (*cached, now, now))}
        for sid in cached:
            if sid not in active:
                self._close_desk(sid)

    def _desk(self, row):
        sid, generation = row['id'], row['generation']
        if sid in self.desks:
            old_generation, desk = self.desks.pop(sid)
            if old_generation == generation:
                self.desks[sid] = (generation, desk)
                return desk
            desk.close()
        self._storage_budget()
        while len(self.desks) >= self.config.max_desks:
            _, (_, desk) = self.desks.popitem(last=False)
            desk.close()
        path = self.data_dir / 'sessions' / sid / f'match-{generation}.sqlite3'
        path.parent.mkdir(exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self.data_dir):
            raise HttpError(503, 'Private replay path failed verification')
        # Each authenticated tester owns one transient advisory service over
        # their existing durable match. This constructor enables no provider.
        desk = AdvisoryDesk(self.events, path)
        self.desks[sid] = (generation, desk)
        return desk

    @staticmethod
    def public_copy_review(value):
        """Project recorded advisory content without internal binding or wire data."""
        def fields(row,names):
            if not isinstance(row,dict):return {}
            return {key:copy.deepcopy(row[key]) for key in names if key in row}
        def clauses(rows):
            return [fields(row,('id','text','disposition','evidence_ids'))
                    for row in rows if isinstance(row,dict)] if isinstance(rows,list) else []
        if not isinstance(value,dict):value={}
        result=fields(value,('label','qualification','status','evidence_error','approval_persisted'))
        # Hosted playtests expose recorded reviews only. There is no opt-in or
        # live action, and raw adapter publishable flags confer no approval.
        result.update(mode='recorded',live_available=False,new_provider_requests=0)
        result['evaluation']=fields(value.get('evaluation'),('strict_passes','total','status','qualification'))
        result['cases']=[fields(row,('case_id','available','unavailable_reason','label'))
                         for row in value.get('cases',[]) if isinstance(row,dict)]
        advice=value.get('advice')
        result['advice']=None
        if isinstance(advice,dict):
            public=fields(advice,('advice_id','case_id','decision','keep','drop','raw_reason',
                'receipt_sha256','evidence_mode','test_mode','historical_only','can_approve','fact_reference_qualification'))
            public['clauses']=clauses(advice.get('clauses'))
            public['facts']=[fields(row,('fact_id','text','evidence_ids','event_revisions'))
                             for row in advice.get('facts',[]) if isinstance(row,dict)]
            public['deterministic_classification']=fields(advice.get('deterministic_classification'),
                ('reason','source','explanation','evidence_ids','from_revision','to_revision'))
            public['recorded_trace']=[fields(row,('source','event','agent_id','agent_class','client_class','stream',
                'response_class','request_sha256','response_sha256','bytes'))
                for row in advice.get('recorded_trace',[]) if isinstance(row,dict)]
            public['sdk_versions']=fields(advice.get('sdk_versions'),
                ('agent-framework-core','agent-framework-ollama','ollama'))
            result['advice']=public
        draft=value.get('producer_copy_draft')
        result['producer_copy_draft']=None
        if isinstance(draft,dict):
            public=fields(draft,('advice_id','case_id','text','label','on_air'))
            public['clauses']=clauses(draft.get('clauses'))
            result['producer_copy_draft']=public
        return result

    @staticmethod
    def public_state(state):
        """Only fictional facts/receipts; no runtime DB/header, filesystem or admin metadata."""
        result = {key: state[key] for key in ('publication', 'audience', 'language', 'recorded_replay',
                  'recap', 'position', 'positions', 'recorded_framework_trace')}
        result['envelope'] = {'through_ms': state['envelope']['through_ms'],
                              'provenance': state['envelope']['provenance']}
        result['live_model_calls'] = 0
        result['copy_review'] = HostedService.public_copy_review(state.get('copy_review'))
        return result

    def state(self, token):
        with self.lock:
            row = self._session(token)
            self._limit('read', row['id'], self.config.read_per_minute)
            return self.public_state(self._desk(row).state())

    def control(self, token, csrf, command):
        with self.lock:
            row = self._session(token, csrf)
            if not isinstance(command, dict) or not isinstance(command.get('action'),str) or command['action'] not in ALLOWED_ACTIONS or not isinstance(command.get('operation_id'), str) or not OPERATION.fullmatch(command['operation_id']):
                raise HttpError(400, 'Choose an available playtest action.')
            command_hash = digest(json.dumps(command, sort_keys=True, separators=(',', ':'), allow_nan=False))
            with self.db() as db:
                previous = db.execute('SELECT command_hash FROM host_operations WHERE session_id=? AND operation_id=?',
                                      (row['id'], command['operation_id'])).fetchone()
                if previous:
                    if previous['command_hash'] != command_hash:
                        raise HttpError(409, 'This action identifier was already used for a different change.')
                    self._limit('read', row['id'], self.config.read_per_minute)
                    return self.public_state(self._desk(row).state())
                if db.execute('SELECT COUNT(*) FROM host_operations WHERE session_id=?', (row['id'],)).fetchone()[0] >= 1000:
                    raise HttpError(409, 'This session has reached its saved-action allowance. Contact the owner.')
            self._limit('control', row['id'], 60 if row['role'] == 'judge' else self.config.control_per_minute)
            self._limit('control-day', row['grant_id'], 10000 if row['role'] == 'judge' else 600, 86400)
            self._storage_budget()
            if command['action'] == 'new_match':
                if set(command) != {'action', 'operation_id'}:
                    raise HttpError(400, 'Unexpected action fields')
                if row['generation'] + 1 >= self.config.max_matches:
                    raise HttpError(409, 'Fresh-match allowance reached. Rewind keeps your approved corrections.')
                self._close_desk(row['id'])
                with self.db() as db:
                    db.execute('UPDATE sessions SET generation=generation+1 WHERE id=?', (row['id'],))
                    db.execute('INSERT INTO host_operations VALUES(?,?,?)', (row['id'], command['operation_id'], command_hash))
                row['generation'] += 1
                return self.public_state(self._desk(row).state())
            try:
                state = self.public_state(self._desk(row).control(command))
                with self.db() as db:
                    db.execute('INSERT INTO host_operations VALUES(?,?,?)', (row['id'], command['operation_id'], command_hash))
                return state
            except ValueError as error:
                # Known engine validation text has no runtime paths. Do not serialize exception traces.
                raise HttpError(409, str(error)) from None
            except RuntimeError:
                raise HttpError(503, 'Saved match is unavailable. Stop repeating actions and contact the owner.') from None

    def feedback(self, token, csrf, payload):
        with self.lock:
            row = self._session(token, csrf)
            if not isinstance(payload, dict) or set(payload) != {'feedback_id', 'consent', 'ratings', 'role', 'comment', 'viewport'} or payload['consent'] is not True:
                raise HttpError(400, 'Feedback is optional and requires your consent.')
            if not isinstance(payload['feedback_id'], str) or not OPERATION.fullmatch(payload['feedback_id']):
                raise HttpError(400, 'A bounded feedback identifier is required for safe retries.')
            ratings = payload['ratings']
            if not isinstance(ratings, dict) or set(ratings) != {'clarity', 'usefulness', 'trust'} or not all(type(value) is int and 1 <= value <= 5 for value in ratings.values()):
                raise HttpError(400, 'Choose a rating from one to five for each question.')
            if (not isinstance(payload['role'],str) or payload['role'] not in {'football_fan', 'microsoft_user', 'both', 'prefer_not'}
                    or not isinstance(payload['viewport'],str) or payload['viewport'] not in {'phone', 'tablet', 'desktop'}):
                raise HttpError(400, 'Choose an available feedback option.')
            comment = payload['comment']
            if not isinstance(comment, str) or len(comment) > 2000 or any(ord(c) < 32 and c not in '\n\r\t' for c in comment):
                raise HttpError(400, 'Keep your comment under 2,000 characters without control characters.')
            self.purge_feedback()
            if self.now() >= FEEDBACK_DELETE_AT:
                raise HttpError(410, 'Feedback collection has ended.')
            payload_hash=digest(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False))
            with self.db() as db:
                previous=db.execute('SELECT payload_hash,receipt_id,deleted FROM feedback_requests WHERE session_id=? AND feedback_id=?',
                                    (row['id'],payload['feedback_id'])).fetchone()
                if previous:
                    if previous['deleted']:
                        raise HttpError(410, 'That feedback was deleted. A new feedback form needs a new identifier.')
                    if previous['payload_hash']!=payload_hash:
                        raise HttpError(409, 'That feedback identifier belongs to different content. Use a new feedback form.')
                    return {'saved':True,'receipt_id':previous['receipt_id'],'duplicate':True,
                            'message':'Your earlier feedback was already saved privately.'}
            self._limit('feedback', row['id'], self.config.feedback_per_day, 86400)
            self._storage_budget()
            with self.db() as db:
                if db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] >= self.config.max_feedback:
                    raise HttpError(503, 'Feedback capacity reached. Your match is unaffected.')
                if db.execute('SELECT COUNT(*) FROM feedback_requests').fetchone()[0] >= self.config.max_feedback:
                    raise HttpError(503, 'Feedback receipt capacity reached. Your match is unaffected.')
                fid = secrets.token_hex(16)
                db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (fid, row['id'], self.now(), 1, ratings['clarity'], ratings['usefulness'], ratings['trust'],
                            payload['role'], comment, payload['viewport'], 'new'))
                # The feedback and retry receipt commit atomically. Existing
                # feedback rows/status and private export columns are unchanged.
                db.execute('INSERT INTO feedback_requests VALUES(?,?,?,?,?,0)',
                           (row['id'],payload['feedback_id'],payload_hash,fid,self.now()))
            return {'saved': True, 'receipt_id':fid, 'duplicate':False,
                    'message': 'Thank you. Your feedback is private to the owner and review team.'}

    def delete_feedback(self, token, csrf):
        with self.lock:
            row = self._session(token, csrf)
            with self.db() as db:
                db.execute('DELETE FROM feedback WHERE session_id=?', (row['id'],))
                # Keep a bounded content-free tombstone so a lost-response retry
                # cannot resurrect explicitly deleted private feedback.
                db.execute('UPDATE feedback_requests SET deleted=1,payload_hash=NULL WHERE session_id=?', (row['id'],))
            return {'deleted': True}

    def purge_feedback(self):
        with self.lock, self.db() as db:
            # Owner CLI/legacy deletion may precede this process. Never claim
            # orphaned feedback is saved, and scrub its content-derived hash.
            db.execute('''UPDATE feedback_requests SET deleted=1,payload_hash=NULL
                          WHERE deleted=0 AND NOT EXISTS
                          (SELECT 1 FROM feedback WHERE feedback.id=feedback_requests.receipt_id)''')
            if self.now() >= FEEDBACK_DELETE_AT:
                db.execute('DELETE FROM feedback')
                db.execute('DELETE FROM feedback_requests')
            # Operational volume deletion after the playtest is a separate deployment gate.

    def close(self):
        with self.lock:
            for _, desk in self.desks.values():
                desk.close()
            self.desks.clear()
            self.closed = True


class DeadlineReader(io.RawIOBase):
    """Absolute deadline bounds request-line, headers and body, even with slow bytes."""
    def __init__(self, connection, deadline):
        self.connection, self.deadline = connection, deadline
    def readable(self):
        return True
    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Request deadline')
        self.connection.settimeout(min(remaining, 2.0))
        return self.connection.recv_into(buffer)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'Touchline'
    sys_version = ''

    def setup(self):
        super().setup()
        self.rfile.close()
        self.rfile = io.BufferedReader(DeadlineReader(self.connection, time.monotonic() + 8.0))
        self.connection.settimeout(2.0)

    def log_message(self, *args):
        # Never log peer IP, code, cookie, query strings, request bodies or feedback.
        pass

    @property
    def service(self):
        return self.server.service

    def _reply(self, status, value, kind='application/json; charset=utf-8', extra=()):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        headers = {
            'Content-Type': kind, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
            'Connection': 'close', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY', 'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
        }
        if not self.service.config.allow_local_http:
            headers['Strict-Transport-Security'] = 'max-age=31536000'
        if status == 429:
            headers['Retry-After'] = '60'
        for key, value in [*headers.items(), *extra]:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _validate(self, mutation=False):
        parsed = urlsplit(self.service.config.origin)
        if len(self.headers.get_all('Host') or []) != 1 or self.headers.get('Host', '').lower() != parsed.netloc.lower():
            raise HttpError(403, 'Unrecognized host')
        if len(self.path) > 2048 or urlsplit(self.path).query or sum(len(k) + len(v) for k, v in self.headers.items()) > 8192:
            raise HttpError(400, 'Unexpected request target or oversized headers')
        if mutation and (len(self.headers.get_all('Origin') or []) != 1 or self.headers.get('Origin') != self.service.config.origin.rstrip('/')):
            raise HttpError(403, 'Use the approved playtest page for this action.')

    def _token(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get('Cookie', ''))
            name = 'touchline_test_session' if self.service.config.allow_local_http else COOKIE
            return cookie[name].value if name in cookie else ''
        except Exception:
            return ''

    def _csrf(self):
        value = self.headers.get('X-CSRF-Token')
        if not value:
            raise HttpError(403, 'This action needs a fresh playtest page.')
        return value

    def _body(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json' or self.headers.get('Transfer-Encoding'):
            raise HttpError(415, 'Use JSON with a bounded content length')
        lengths = self.headers.get_all('Content-Length') or []
        if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
            raise HttpError(413, 'Request is too large or has no valid content length')
        raw = self.rfile.read(int(lengths[0]))
        if len(raw) != int(lengths[0]):
            raise HttpError(400, 'Incomplete request')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate fields')
                result[key] = value
            return result
        try:
            value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise HttpError(400, 'Invalid JSON request') from None

    def _safe(self, operation):
        try:
            return operation()
        except HttpError as error:
            return self._reply(error.status, {'error': str(error)})
        except (TimeoutError, socket.timeout):
            return self._reply(408, {'error': 'Request timed out. Refresh state before repeating a change.'})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            return self._reply(503, {'error': 'Playtest is temporarily unavailable. Your saved match is kept.'})

    def do_GET(self):
        return self._safe(self._get)

    def _get(self):
        self._validate()
        path = urlsplit(self.path).path
        if path == '/healthz':
            with self.service.db() as db:
                db.execute('SELECT 1').fetchone()
            return self._reply(200, {'status': 'ready', 'mode': 'synthetic-recorded', 'model_calls': 0})
        public = {'/': ('landing.html', 'text/html; charset=utf-8'),
                  '/static/site.css': ('site.css', 'text/css; charset=utf-8'),
                  '/static/landing.js': ('landing.js', 'text/javascript; charset=utf-8'),
                  '/static/playtest.js': ('playtest.js', 'text/javascript; charset=utf-8')}
        if path in public:
            name, kind = public[path]
            return self._reply(200, (ROOT / 'web' / name).read_bytes(), kind)
        if path == '/api/session':
            return self._reply(200, self.service.session(self._token()))
        if path == '/playtest':
            self.service.session(self._token())
            return self._reply(200, (ROOT / 'web' / 'playtest.html').read_bytes(), 'text/html; charset=utf-8')
        if path in {'/api/state', '/api/overlay'}:
            state = self.service.state(self._token())
            return self._reply(200, state if path == '/api/state' else state['publication'])
        raise HttpError(404, 'Page not found')

    def do_POST(self):
        return self._safe(self._post)

    def _post(self):
        self._validate(mutation=True)
        path = urlsplit(self.path).path
        allowed = {'/api/access', '/api/logout', '/api/control', '/api/feedback'}
        if path not in allowed:
            raise HttpError(404, 'Page not found')
        if path != '/api/access':
            self.service.session(self._token())
            self.service._session(self._token(), self._csrf())
        value = self._body()
        if path == '/api/access':
            if set(value) != {'code'}:
                raise HttpError(400, 'Unexpected access fields')
            peer = hmac.new(self.server.peer_key, self.client_address[0].encode(), hashlib.sha256).hexdigest()
            token, csrf = self.service.access(value['code'], peer)
            local = self.service.config.allow_local_http
            name = 'touchline_test_session' if local else COOKIE
            flags = f'{name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={self.service.config.session_seconds}' + ('' if local else '; Secure')
            return self._reply(200, {'authenticated': True, 'csrf': csrf}, extra=[('Set-Cookie', flags)])
        if path == '/api/control':
            return self._reply(200, self.service.control(self._token(), self._csrf(), value))
        if path == '/api/feedback':
            return self._reply(201, self.service.feedback(self._token(), self._csrf(), value))
        if value:
            raise HttpError(400, 'Unexpected logout fields')
        self.service.logout(self._token(), self._csrf())
        name = 'touchline_test_session' if self.service.config.allow_local_http else COOKIE
        flags = f'{name}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0' + ('' if self.service.config.allow_local_http else '; Secure')
        return self._reply(200, {'logged_out': True}, extra=[('Set-Cookie', flags)])

    def do_DELETE(self):
        def operation():
            self._validate(mutation=True)
            if self.path != '/api/feedback':
                raise HttpError(404, 'Page not found')
            return self._reply(200, self.service.delete_feedback(self._token(), self._csrf()))
        return self._safe(operation)


class BoundedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = 16
    def __init__(self, address, service, handler=Handler):
        self.service = service
        self.peer_key = secrets.token_bytes(32)  # Ephemeral anti-abuse salt; never persisted/logged.
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, handler)
    def process_request(self, request, address):
        if not self.slots.acquire(False):
            try:
                request.settimeout(0.2)
                request.sendall(b'HTTP/1.0 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
    def handle_error(self, request, address):
        # The socketserver default includes the remote address and a traceback.
        # Keep the app's unexpected-error log constant and free of client data.
        print('Playtest request failed; inspect private operational health.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8896)
    parser.add_argument('--allow-local-http', action='store_true')
    args = parser.parse_args()
    if args.allow_local_http and args.bind != '127.0.0.1':
        parser.error('Local HTTP tests must bind only to loopback')
    if not 1024 <= args.port <= 65535:
        parser.error('Unprivileged port required')
    service = HostedService(Config(args.data_dir, args.origin, args.allow_local_http))
    try:
        server = BoundedServer((args.bind, args.port), service)
    except BaseException:
        service.close()
        raise
    print('Touchline controlled synthetic playtest; zero model calls; no grants created automatically.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == '__main__':
    main()
