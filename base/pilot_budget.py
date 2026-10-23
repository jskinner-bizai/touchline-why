"""File-only authorization and conservative reservation journal for the H2 pilot.

The caller, never this module, initializes the authorization file. A reservation
is charged for the full client deadline before the caller may dispatch anything.
This module neither imports an SDK nor contacts or inspects a provider.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time


POLICY = {
    "model": "gemma4:12b",
    "endpoint": "http://127.0.0.1:11434",
    "max_attempts": 4,
    "per_call_timeout_ms": 25000,
    "cumulative_reserved_ms": 100000,
    "max_output_tokens": 192,
    "max_request_bytes": 12288,
    "think": False,
}
_APPROVED_POLICY = copy.deepcopy(POLICY)
_ROOT_KEYS = {
    "schema_version", "pilot_id", "authorized_at_ms", "expires_at_ms", "policy",
    "attempts", "stopped", "stop_reason",
}
_BINDING_KEYS = {"input_sha256", "snapshot_digest", "watermark_ms", "event_revisions"}
_ATTEMPT_KEYS = _BINDING_KEYS | {
    "attempt_id", "case_id", "reserved_at_ms", "reserved_ms", "status", "outcome",
    "elapsed_ms", "finished_at_ms", "success", "uncertain",
}
_MAX_FILE_BYTES = 65536
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_EVENT = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


class BudgetError(RuntimeError):
    """Authorization, journal, lock or reservation guard failed closed."""


def _now_ms():
    return time.time_ns() // 1_000_000


def _int(value, minimum=0, maximum=2**53 - 1):
    return type(value) is int and minimum <= value <= maximum


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BudgetError("duplicate_json_key")
        result[key] = value
    return result


def _encode(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BudgetError("non_json_value") from exc


def _binding(value):
    if type(value) is not dict or set(value) != _BINDING_KEYS:
        raise BudgetError("invalid_binding_fields")
    for field in ("input_sha256", "snapshot_digest"):
        if type(value[field]) is not str or not _HEX.fullmatch(value[field]):
            raise BudgetError("invalid_binding_digest")
    if not _int(value["watermark_ms"]):
        raise BudgetError("invalid_watermark")
    revisions = value["event_revisions"]
    if type(revisions) is not dict or not 1 <= len(revisions) <= 64:
        raise BudgetError("invalid_event_revisions")
    for event_id, revision in revisions.items():
        if (type(event_id) is not str or not _EVENT.fullmatch(event_id)
                or not _int(revision, 1, 2**31 - 1)):
            raise BudgetError("invalid_event_revision")
    return copy.deepcopy(value)


def _valid_outcome(value):
    if type(value) is str:
        return bool(value) and len(value) <= 256
    if type(value) is dict:
        return len(_encode(value)) <= 4096
    return False


def _validate(state, pilot_id):
    if type(state) is not dict or set(state) != _ROOT_KEYS:
        raise BudgetError("invalid_root_fields")
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise BudgetError("unsupported_schema")
    if state["pilot_id"] != pilot_id or type(state["pilot_id"]) is not str:
        raise BudgetError("pilot_id_mismatch")
    policy = state["policy"]
    # JSON booleans compare equal to integers in Python: require identical types.
    if (type(policy) is not dict or set(policy) != set(_APPROVED_POLICY)
            or any(type(policy[k]) is not type(v) or policy[k] != v
                   for k, v in _APPROVED_POLICY.items())):
        raise BudgetError("policy_mismatch")
    authorized, expiry = state["authorized_at_ms"], state["expires_at_ms"]
    if (not _int(authorized) or not _int(expiry)
            or not authorized < expiry <= authorized + 900000):
        raise BudgetError("invalid_authorization_window")
    if type(state["stopped"]) is not bool:
        raise BudgetError("invalid_stop_state")
    reason = state["stop_reason"]
    if ((state["stopped"] and (type(reason) is not str or not reason or len(reason) > 256))
            or (not state["stopped"] and reason is not None)):
        raise BudgetError("invalid_stop_reason")
    attempts = state["attempts"]
    if type(attempts) is not list or len(attempts) > 4:
        raise BudgetError("invalid_attempt_count")
    seen = set()
    seen_cases = set()
    for index, attempt in enumerate(attempts, 1):
        if type(attempt) is not dict or set(attempt) != _ATTEMPT_KEYS:
            raise BudgetError("invalid_attempt_fields")
        binding = _binding({k: attempt[k] for k in _BINDING_KEYS})
        if (type(attempt["attempt_id"]) is not int or attempt["attempt_id"] != index
                or attempt["case_id"] != "input_" + binding["input_sha256"][:16]
                or binding["input_sha256"] in seen or attempt["case_id"] in seen_cases):
            raise BudgetError("invalid_attempt_identity")
        seen.add(binding["input_sha256"])
        seen_cases.add(attempt["case_id"])
        if (type(attempt["reserved_ms"]) is not int or attempt["reserved_ms"] != 25000
                or not _int(attempt["reserved_at_ms"], authorized, expiry - 25000)):
            raise BudgetError("invalid_reservation")
        if attempt["status"] == "reserved":
            if (index != len(attempts) or any(attempt[k] is not None for k in
                    ("outcome", "elapsed_ms", "finished_at_ms", "success"))
                    or attempt["uncertain"] is not False):
                raise BudgetError("invalid_pending_attempt")
        elif attempt["status"] in ("completed", "failed"):
            if (not _valid_outcome(attempt["outcome"])
                    or not _int(attempt["elapsed_ms"])
                    or not _int(attempt["finished_at_ms"], attempt["reserved_at_ms"])
                    or type(attempt["success"]) is not bool
                    or type(attempt["uncertain"]) is not bool):
                raise BudgetError("invalid_finished_attempt")
            successful = attempt["success"] and not attempt["uncertain"]
            if ((attempt["status"] == "completed") != successful
                    or (successful and (attempt["elapsed_ms"] > 25000
                        or attempt["finished_at_ms"] - attempt["reserved_at_ms"] > 25000))
                    or (not successful and not state["stopped"])):
                raise BudgetError("inconsistent_finished_attempt")
        else:
            raise BudgetError("invalid_attempt_status")
    if sum(a["reserved_ms"] for a in attempts) > 100000:
        raise BudgetError("reservation_budget_exceeded")


class BudgetSession:
    """Exclusive, one-case session over an existing root authorization journal.

    Each successful reserve irrevocably consumes 25,000 ms. Failures stop the
    pilot. A leftover lock is never reclaimed, even if its process appears dead.
    """

    def __init__(self, path, pilot_id):
        if type(pilot_id) is not str or not pilot_id or len(pilot_id) > 128:
            raise BudgetError("invalid_pilot_id")
        self.path = Path(path).absolute()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.pilot_id = pilot_id
        self._token = "pilot-budget-lock-v1:" + secrets.token_hex(24)
        self._held = False
        self._entered = False
        self._state = None
        self._digest = None
        self._attempt_index = None
        self._finished = False
        self._unusable = False

    def _owned(self):
        if not self._held:
            return False
        try:
            if self.lock_path.is_symlink() or not stat.S_ISREG(self.lock_path.stat().st_mode):
                return False
            return self.lock_path.read_bytes() == self._token.encode("ascii")
        except OSError:
            return False

    def _read(self):
        try:
            if self.path.is_symlink() or not stat.S_ISREG(self.path.stat().st_mode):
                raise BudgetError("authorization_not_regular_file")
            with self.path.open("rb") as handle:
                raw = handle.read(_MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise BudgetError("authorization_unavailable") from exc
        if len(raw) > _MAX_FILE_BYTES:
            raise BudgetError("authorization_too_large")
        return raw

    def _persist(self):
        if not self._owned():
            raise BudgetError("lock_ownership_uncertain")
        if hashlib.sha256(self._read()).hexdigest() != self._digest:
            raise BudgetError("journal_changed_outside_session")
        _validate(self._state, self.pilot_id)
        raw = _encode(self._state) + b"\n"
        if len(raw) > _MAX_FILE_BYTES:
            raise BudgetError("journal_too_large")
        temp_path = self.path.with_name(self.path.name + ".tmp." + self._token.rsplit(":", 1)[1])
        created = False
        try:
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if not self._owned():
                raise BudgetError("lock_ownership_uncertain")
            if hashlib.sha256(self._read()).hexdigest() != self._digest:
                raise BudgetError("journal_changed_outside_session")
            os.replace(temp_path, self.path)
            created = False
            self._digest = hashlib.sha256(raw).hexdigest()
            # Directory fsync is available on POSIX, but not generally Windows.
            if os.name != "nt":
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError as exc:
            raise BudgetError("journal_persistence_failed") from exc
        finally:
            if created:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _stop(self, reason):
        if self._state is not None and not self._state["stopped"]:
            self._state["stopped"] = True
            self._state["stop_reason"] = reason
            self._persist()

    def _release(self):
        if self._held:
            owned = self._owned()
            self._held = False
            if not owned:
                raise BudgetError("lock_ownership_uncertain")
            try:
                self.lock_path.unlink()
            except OSError as exc:
                raise BudgetError("lock_release_failed") from exc

    def __enter__(self):
        if self._entered:
            raise BudgetError("session_already_entered")
        self._entered = True
        try:
            descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise BudgetError("budget_locked_no_reclaim") from exc
        except OSError as exc:
            raise BudgetError("lock_acquisition_failed") from exc
        self._held = True
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(self._token.encode("ascii"))
                handle.flush()
                os.fsync(handle.fileno())
            raw = self._read()
            try:
                state = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                                   parse_constant=lambda _: (_ for _ in ()).throw(BudgetError("nonfinite_json")))
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise BudgetError("invalid_authorization_json") from exc
            _validate(state, self.pilot_id)
            self._state = state
            self._digest = hashlib.sha256(raw).hexdigest()
            if state["stopped"]:
                raise BudgetError("pilot_stopped:" + state["stop_reason"])
            if any(a["status"] == "reserved" for a in state["attempts"]):
                self._stop("unfinished_prior_reservation")
                raise BudgetError("unfinished_prior_reservation")
            now = _now_ms()
            if now < state["authorized_at_ms"]:
                raise BudgetError("authorization_not_started")
            if state["expires_at_ms"] - now < 25000:
                self._stop("authorization_window_exhausted")
                raise BudgetError("authorization_window_exhausted")
            return self
        except BaseException:
            self._release()
            raise

    def reserve(self, binding):
        if self._unusable:
            raise BudgetError("session_persistence_uncertain")
        if not self._owned() or self._state is None:
            raise BudgetError("session_not_active")
        if self._attempt_index is not None:
            raise BudgetError("one_reservation_per_session")
        if self._state["stopped"]:
            raise BudgetError("pilot_stopped:" + self._state["stop_reason"])
        binding = _binding(binding)
        attempts = self._state["attempts"]
        if len(attempts) >= 4 or sum(a["reserved_ms"] for a in attempts) + 25000 > 100000:
            self._stop("reservation_budget_exhausted")
            raise BudgetError("reservation_budget_exhausted")
        if any(a["case_id"] == "input_" + binding["input_sha256"][:16] for a in attempts):
            self._stop("duplicate_case_forbidden")
            raise BudgetError("duplicate_case_forbidden")
        now = _now_ms()
        if now < self._state["authorized_at_ms"]:
            self._stop("clock_before_authorization")
            raise BudgetError("clock_before_authorization")
        if self._state["expires_at_ms"] - now < 25000:
            self._stop("authorization_window_exhausted")
            raise BudgetError("authorization_window_exhausted")
        record = dict(binding, attempt_id=len(attempts) + 1,
                      case_id="input_" + binding["input_sha256"][:16],
                      reserved_at_ms=now, reserved_ms=25000, status="reserved",
                      outcome=None, elapsed_ms=None, finished_at_ms=None,
                      success=None, uncertain=False)
        attempts.append(record)
        self._attempt_index = len(attempts) - 1
        try:
            self._persist()
        except BaseException:
            self._unusable = True
            raise
        return copy.deepcopy(record)

    def finish(self, outcome, elapsed_ms, success, uncertain=False):
        if self._unusable:
            raise BudgetError("session_persistence_uncertain")
        if not self._owned() or self._attempt_index is None or self._finished:
            raise BudgetError("no_active_reservation")
        if (not _valid_outcome(outcome) or not _int(elapsed_ms)
                or type(success) is not bool or type(uncertain) is not bool):
            raise BudgetError("invalid_completion")
        now = _now_ms()
        record = self._state["attempts"][self._attempt_index]
        if now < record["reserved_at_ms"]:
            self._stop("clock_reversed_during_attempt")
            raise BudgetError("clock_reversed_during_attempt")
        exceeded = elapsed_ms > 25000 or now - record["reserved_at_ms"] > 25000
        if exceeded:
            success, uncertain = False, True
        record.update(status="completed" if success and not uncertain else "failed",
                      outcome=copy.deepcopy(outcome), elapsed_ms=elapsed_ms,
                      finished_at_ms=now, success=success, uncertain=uncertain)
        if not success or uncertain:
            self._state["stopped"] = True
            self._state["stop_reason"] = ("client_deadline_exceeded" if exceeded
                                          else "uncertain_completion" if uncertain else "attempt_failed")
        try:
            self._persist()
        except BaseException:
            self._unusable = True
            raise
        self._finished = True
        return copy.deepcopy(record)

    def snapshot(self):
        if self._unusable:
            raise BudgetError("session_persistence_uncertain")
        if not self._owned() or self._state is None:
            raise BudgetError("session_not_active")
        return copy.deepcopy(self._state)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self._attempt_index is not None and not self._finished:
                self._stop("unfinished_reservation_on_exit")
            elif exc_type is not None:
                self._stop("exception_in_session")
        finally:
            self._release()
        return False
