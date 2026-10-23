"""Crash-recoverable deterministic commands over the existing M2 controller.

SQLite commits a bounded, verified command journal before the prepared controller
is published in memory. No selection, model prose, token or insight TTL is stored.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading

import app_m2
import overlay_state
import touchline_core
from app_m2 import Controller, now_ms

SCHEMA_VERSION = 1
MAX_COMMANDS = 500
MAX_DB_BYTES = 16_000_000
OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
META_SQL = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
COMMAND_SQL = """CREATE TABLE commands (
sequence INTEGER PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
command_json TEXT NOT NULL, accepted_at_ms INTEGER NOT NULL,
previous_hash TEXT NOT NULL, state_hash TEXT NOT NULL, entry_hash TEXT NOT NULL)"""


class DurableIntegrityError(RuntimeError):
    """Refuse to serve or modify unverifiable persistent state."""


class CommittedCommandError(RuntimeError):
    """The command committed; reopen rather than retrying as an uncommitted write."""
    committed = True


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Finite JSON is required") from error


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _parse(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
        if _json(value) != text: raise ValueError("Noncanonical JSON")
        return value
    except (TypeError, ValueError) as error:
        raise DurableIntegrityError("Stored JSON is invalid or noncanonical") from error


def _command(value):
    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        raise ValueError("A deterministic action is required")
    action = value["action"]
    if action == "view":
        if set(value) != {"action", "audience", "language"} or not isinstance(value["audience"], str) or not isinstance(value["language"], str) or value["audience"] not in {"casual", "analyst"} or value["language"] not in {"en", "es"}:
            raise ValueError("Unsupported view")
    elif action not in {"reset", "next", "finish", "pattern", "duplicate", "correct"} or set(value) != {"action"}:
        raise ValueError("Only deterministic core actions can be journalled")
    return _parse(_json(value))


def _milliseconds(value):
    if type(value) is not int or not 0 <= value <= 9_223_372_036_854_775_000:
        raise ValueError("Clock must return nonnegative integer milliseconds")
    return value


class _Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value


def _sources():
    paths = {"durable_controller": Path(__file__), "app_m2": Path(app_m2.__file__),
             "overlay_state": Path(overlay_state.__file__), "touchline_core": Path(touchline_core.__file__)}
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _projection(controller):
    # Delivery IDs, wall-clock TTLs, job histories and selected cards are transient.
    envelope = controller.engine.view(controller.audience, controller.language)
    return {"snapshot": envelope["snapshot"], "position": controller.position,
            "times": list(controller.times), "audience": controller.audience,
            "language": controller.language,
            "event_revisions": {e["id"]: controller.engine.event_revision(e["id"]) for e in controller.events},
            "corrections": _correction_audit(controller)}


def _correction_audit(controller):
    """Verify contiguous revision lineage against current engine payloads."""
    current = {event["id"]: copy.deepcopy(event) for event in controller.events}
    revisions = {event_id: 1 for event_id in current}
    parsed = [_parse(value) for value in controller.engine._corrections.values()]
    parsed.sort(key=lambda row: (row["target_event_id"], row["expected_revision"], row["correction_id"]))
    audit = []
    for row in parsed:
        target, expected = row["target_event_id"], row["expected_revision"]
        if target not in current or revisions[target] != expected or row["replacement"]["id"] != target:
            raise DurableIntegrityError("Correction revision lineage is not contiguous")
        audit.append({"correction_id": row["correction_id"], "target_event_id": target,
                      "from_revision": expected, "to_revision": expected + 1,
                      "before": copy.deepcopy(current[target]), "after": copy.deepcopy(row["replacement"]),
                      "source_id": controller.engine._source_id})
        current[target] = copy.deepcopy(row["replacement"])
        revisions[target] += 1
    for target in current:
        if controller.engine.event_revision(target) != revisions[target] or controller.engine._events[target] != current[target]:
            raise DurableIntegrityError("Current event payload does not match revision lineage")
    return audit


class DurableController:
    """One live owner with thread-safe commands and fail-closed recovery.

    The public .lock is the same RLock used by .controller. Transient recorded
    selection may use .controller under that lock, but is deliberately not durable.
    A second live owner must reopen after another owner commits; stale writes fail.
    """

    def __init__(self, events, db_path, *, clock=now_ms, max_commands=MAX_COMMANDS, fault_hook=None):
        if type(max_commands) is not int or not 1 <= max_commands <= MAX_COMMANDS:
            raise ValueError("max_commands must be from 1 through 500")
        if not callable(clock) or fault_hook is not None and not callable(fault_hook):
            raise ValueError("Clock and fault hook must be callable")
        touchline_core.snapshot_at(events, 0)
        self.events = copy.deepcopy(events)
        self.lock = threading.RLock()
        self.clock, self.fault_hook, self.max_commands = clock, fault_hook, max_commands
        self.db_path = Path(db_path).resolve()
        if not self.db_path.parent.is_dir(): raise ValueError("Database parent must exist")
        existed = self.db_path.exists()
        if existed and (not self.db_path.is_file() or not 0 < self.db_path.stat().st_size <= MAX_DB_BYTES):
            raise DurableIntegrityError("Existing database is empty, oversized or not a file")
        self._source_hashes = _sources()
        self._fixture_hash = _hash(self.events)
        self._closed, self._poisoned = False, False
        self._count, self._head, self._last_commit_ms = 0, None, None
        self._connection = None
        try:
            self._connection = sqlite3.connect(str(self.db_path), timeout=5,
                                               isolation_level=None, check_same_thread=False)
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA busy_timeout=5000")
            if existed:
                self._connection.execute("BEGIN")
                header, rows = self._verified()
                controller = self._replay(header, rows)
                self._connection.execute("COMMIT")
            else:
                created = _milliseconds(self.clock())
                controller = Controller(self.events, clock=_Clock(created))
                header = {"schema_version": SCHEMA_VERSION, "fixture_sha256": self._fixture_hash,
                          "source_sha256": self._source_hashes, "created_at_ms": created,
                          "max_commands": max_commands, "initial_state_sha256": _hash(_projection(controller))}
                header["header_sha256"] = _hash(header)
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(META_SQL)
                self._connection.execute(COMMAND_SQL)
                self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                self._connection.execute("INSERT INTO meta(key,value) VALUES('header',?)", (_json(header),))
                checkpoint = self._checkpoint(0, header["header_sha256"], created, header["initial_state_sha256"])
                self._connection.execute("INSERT INTO meta(key,value) VALUES('checkpoint',?)", (_json(checkpoint),))
                self._connection.execute("COMMIT")
                rows = []
            self._header = header
            self._count = len(rows)
            self._head = rows[-1]["entry_hash"] if rows else header["header_sha256"]
            self._last_commit_ms = rows[-1]["accepted_at_ms"] if rows else header["created_at_ms"]
            now = _milliseconds(self.clock())
            if now < self._last_commit_ms: raise DurableIntegrityError("Service clock precedes the journal")
            self.controller = controller
            self._bind(controller, self.clock)
            if existed:
                # Never restore a selected card, token, previous stream identity or
                # previous insight with a fresh TTL. Recovery emits facts only.
                controller.engine._issue(None, "recovered", now)
                controller.fingerprint = controller.publication = None
                controller.sequence = 0
                controller.job = {"status": "recovered_fallback", "note": "Deterministic replay; no live or recorded insight restored"}
                controller.history.append({"at_ms": now, "action": "recovery"})
            self._recovery_info = {"recovered": existed, "replayed_commands": len(rows),
                                   "recovery_mode": "deterministic_fallback" if existed else "new_store",
                                   "new_stream_id": controller.stream_id,
                                   "insight_restored": False}
        except Exception as error:
            if self._connection is not None:
                if self._connection.in_transaction: self._connection.execute("ROLLBACK")
                self._connection.close()
            self._closed = True
            if isinstance(error, (DurableIntegrityError, ValueError)): raise
            raise DurableIntegrityError("Database could not be verified") from error

    def _bind(self, controller, clock):
        controller.lock = self.lock
        controller.clock = clock
        controller.engine._clock = clock

    def _verified(self):
        try:
            return self._verified_inner()
        except sqlite3.Error as error:
            raise DurableIntegrityError("SQLite state could not be verified") from error

    def _verified_inner(self):
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise DurableIntegrityError("Unsupported database schema version")
        integrity = self._connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]: raise DurableIntegrityError("SQLite integrity check failed")
        objects = self._connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        expected = {"meta": META_SQL, "commands": COMMAND_SQL}
        tables = {name: sql for kind, name, sql in objects if kind == "table"}
        normalize = lambda text: " ".join(text.lower().split())
        if set(tables) != set(expected) or any(normalize(tables[name]) != normalize(expected[name]) for name in expected):
            raise DurableIntegrityError("Database table schema changed")
        if any(kind != "table" and not (kind == "index" and sql is None and name in {"sqlite_autoindex_meta_1", "sqlite_autoindex_commands_1"}) for kind, name, sql in objects):
            raise DurableIntegrityError("Unexpected database object")
        meta = dict(self._connection.execute("SELECT key,value FROM meta").fetchall())
        if set(meta) != {"header", "checkpoint"}: raise DurableIntegrityError("Invalid metadata rows")
        header = _parse(meta["header"])
        keys = {"schema_version", "fixture_sha256", "source_sha256", "created_at_ms", "max_commands", "initial_state_sha256", "header_sha256"}
        if not isinstance(header, dict) or set(header) != keys: raise DurableIntegrityError("Invalid metadata fields")
        bare = {key: value for key, value in header.items() if key != "header_sha256"}
        if header["header_sha256"] != _hash(bare): raise DurableIntegrityError("Metadata hash mismatch")
        if type(header["schema_version"]) is not int or header["schema_version"] != SCHEMA_VERSION or header["fixture_sha256"] != self._fixture_hash or header["source_sha256"] != self._source_hashes or type(header["max_commands"]) is not int or header["max_commands"] != self.max_commands:
            raise DurableIntegrityError("Fixture, source or schema fingerprint mismatch")
        try: previous_time = _milliseconds(header["created_at_ms"])
        except ValueError as error: raise DurableIntegrityError("Invalid initial clock") from error
        raw = self._connection.execute("SELECT sequence,operation_id,command_json,accepted_at_ms,previous_hash,state_hash,entry_hash FROM commands ORDER BY sequence LIMIT ?", (self.max_commands + 1,)).fetchall()
        if len(raw) > self.max_commands: raise DurableIntegrityError("Journal capacity exceeded")
        rows, previous_hash = [], header["header_sha256"]
        for index, item in enumerate(raw, 1):
            sequence, operation_id, command_json, accepted, predecessor, state_hash, entry_hash = item
            if type(sequence) is not int or sequence != index or not isinstance(operation_id, str) or not OPERATION_ID.fullmatch(operation_id):
                raise DurableIntegrityError("Invalid journal sequence or operation ID")
            try:
                command = _command(_parse(command_json))
                _milliseconds(accepted)
            except (ValueError, TypeError) as error: raise DurableIntegrityError("Invalid journal command or clock") from error
            body = {"sequence": sequence, "operation_id": operation_id, "command": command,
                    "accepted_at_ms": accepted, "previous_hash": predecessor, "state_hash": state_hash}
            if accepted < previous_time or predecessor != previous_hash or entry_hash != _hash(body):
                raise DurableIntegrityError("Journal hash chain or clock mismatch")
            if not isinstance(state_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", state_hash):
                raise DurableIntegrityError("Invalid state hash")
            rows.append({**body, "entry_hash": entry_hash})
            previous_time, previous_hash = accepted, entry_hash
        checkpoint = _parse(meta["checkpoint"])
        expected_checkpoint = self._checkpoint(len(rows), previous_hash, previous_time,
                                               rows[-1]["state_hash"] if rows else header["initial_state_sha256"])
        if checkpoint != expected_checkpoint:
            raise DurableIntegrityError("Journal checkpoint or tail differs")
        return header, rows

    @staticmethod
    def _checkpoint(count, head, committed_at, state_hash):
        value = {"count": count, "head_sha256": head, "last_commit_ms": committed_at,
                 "state_sha256": state_hash}
        return {**value, "checkpoint_sha256": _hash(value)}

    def _replay(self, header, rows):
        replay_clock = _Clock(header["created_at_ms"])
        controller = Controller(self.events, clock=replay_clock)
        if _hash(_projection(controller)) != header["initial_state_sha256"]:
            raise DurableIntegrityError("Initial fixture state differs")
        for row in rows:
            replay_clock.value = row["accepted_at_ms"]
            try: controller.control(copy.deepcopy(row["command"]))
            except Exception as error: raise DurableIntegrityError("Committed command cannot be replayed") from error
            if _hash(_projection(controller)) != row["state_hash"]:
                raise DurableIntegrityError("Replayed fact state differs")
        return controller

    def _healthy(self):
        if self._closed: raise RuntimeError("Durable controller is closed")
        if self._poisoned: raise CommittedCommandError("Committed state not applied; close and reopen")
        try: sources = _sources()
        except OSError as error: raise DurableIntegrityError("Source files are unavailable") from error
        if sources != self._source_hashes: raise DurableIntegrityError("Source files changed while running")

    def _check_head(self):
        header, rows = self._verified()
        head = rows[-1]["entry_hash"] if rows else header["header_sha256"]
        if head != self._head or len(rows) != self._count:
            raise DurableIntegrityError("Another owner changed the journal; close and reopen")
        expected_state = rows[-1]["state_hash"] if rows else header["initial_state_sha256"]
        if _hash(_projection(self.controller)) != expected_state:
            raise DurableIntegrityError("Live facts or view changed outside the durable journal")
        return rows

    def _clone(self, now):
        # Controller contains an RLock and possibly a transient recorded result.
        # Clone its data only, never a lock, worker, selector or model callback.
        if self.controller.worker and self.controller.worker.is_alive():
            raise RuntimeError("An active worker cannot enter deterministic persistence")
        result = object.__new__(Controller)
        for key, value in self.controller.__dict__.items():
            if key not in {"lock", "worker", "clock", "selector", "model_budget"}:
                setattr(result, key, copy.deepcopy(value))
        result.worker = result.selector = result.model_budget = None
        self._bind(result, _Clock(now))
        return result

    def _decorate(self, state, operation=None):
        audit = _correction_audit(self.controller)
        through_ms = state["envelope"]["through_ms"]
        visible = [row for row in audit if row["after"]["at_ms"] <= through_ms]
        state["envelope"]["provenance"]["corrections"] = copy.deepcopy(visible)
        state["publication"]["provenance"]["corrections"] = copy.deepcopy(visible)
        state["recovery_audit"] = {"corrections": copy.deepcopy(visible), "insight_persisted": False}
        state["durability"] = {"schema_version": SCHEMA_VERSION, "journal_count": self._count,
                               "journal_limit": self.max_commands, "journal_head_sha256": self._head,
                               "fixture_sha256": self._fixture_hash, "last_commit_ms": self._last_commit_ms,
                               "insight_persisted": False, "recovery": copy.deepcopy(self._recovery_info)}
        if operation is not None: state["durability"]["operation"] = operation
        return state

    @property
    def recovery_info(self):
        with self.lock: return copy.deepcopy(self._recovery_info)

    def state(self):
        with self.lock:
            self._healthy()
            self._check_head()
            return self._decorate(self.controller.state())

    def operation_command(self, operation_id):
        """Read the verified command occupying this durable operation ID.

        Transient UI actions use this guard so they cannot reuse a committed
        deterministic ID after the process-local retry cache has been lost.
        """
        if not isinstance(operation_id, str) or not OPERATION_ID.fullmatch(operation_id):
            raise ValueError("A bounded operation_id is required")
        with self.lock:
            self._healthy()
            rows = self._check_head()
            prior = next((row for row in rows if row["operation_id"] == operation_id), None)
            return copy.deepcopy(prior["command"]) if prior else None

    def control(self, value, operation_id):
        command = _command(value)
        if not isinstance(operation_id, str) or not OPERATION_ID.fullmatch(operation_id):
            raise ValueError("A bounded operation_id is required")
        with self.lock:
            self._healthy()
            self._connection.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                rows = self._check_head()
                prior = next((row for row in rows if row["operation_id"] == operation_id), None)
                if prior:
                    if prior["command"] != command: raise ValueError("Conflicting operation_id")
                    self._connection.execute("ROLLBACK")
                    # Return present state, never an old snapshot that could rewind
                    # a consumer after a delayed duplicate operation receipt.
                    return self._decorate(self.controller.state(), {"operation_id": operation_id, "duplicate": True, "sequence": prior["sequence"]})
                if self._count >= self.max_commands: raise ValueError("Journal capacity reached")
                now = _milliseconds(self.clock())
                if now < self._last_commit_ms: raise ValueError("Clock precedes the last command")
                prepared = self._clone(now)
                prepared.control(copy.deepcopy(command))
                state_hash = _hash(_projection(prepared))
                body = {"sequence": self._count + 1, "operation_id": operation_id,
                        "command": command, "accepted_at_ms": now,
                        "previous_hash": self._head, "state_hash": state_hash}
                entry_hash = _hash(body)
                self._connection.execute("INSERT INTO commands(sequence,operation_id,command_json,accepted_at_ms,previous_hash,state_hash,entry_hash) VALUES(?,?,?,?,?,?,?)",
                                         (body["sequence"], operation_id, _json(command), now, self._head, state_hash, entry_hash))
                checkpoint = self._checkpoint(body["sequence"], entry_hash, now, state_hash)
                self._connection.execute("UPDATE meta SET value=? WHERE key='checkpoint'", (_json(checkpoint),))
                if self.fault_hook: self.fault_hook("before_commit")
                self._connection.execute("COMMIT")
                committed = True
                if self.fault_hook: self.fault_hook("after_commit_before_apply")
                self._bind(prepared, self.clock)
                self.controller = prepared
                self._count, self._head, self._last_commit_ms = body["sequence"], entry_hash, now
                return self._decorate(self.controller.state(), {"operation_id": operation_id, "duplicate": False, "sequence": body["sequence"]})
            except Exception as error:
                if self._connection.in_transaction: self._connection.execute("ROLLBACK")
                if committed:
                    self._poisoned = True
                    raise CommittedCommandError("Command committed before application; close and reopen") from error
                raise

    def close(self):
        with self.lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
