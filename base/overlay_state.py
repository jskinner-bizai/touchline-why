"""Bounded, in-memory synthetic overlay state. Callers must serialize all calls.

Event time (through_ms), service clock TTLs, event revisions and overlay versions
are independent. No framework, model, network or real match data is used here.
"""
from __future__ import annotations

import hashlib
import time
import uuid

from touchline_core import (
    MAX_EVENTS, MAX_TIME_MS, _canonical, _identifier, _keys, _plain, _time,
    render_overlay, snapshot_at, validate_selection,
)

SCHEMA_VERSION = "touchline.overlay.v2"
MAX_CORRECTIONS = 500
MAX_REQUESTS = 256
FAILURE_REASONS = {"timeout", "model_error", "invalid_selection"}


def _positive(value, label, maximum=3_600_000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be a positive bounded integer")


def _encoded(value):
    try:
        return _canonical(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("value must be finite JSON") from error


class OverlayState:
    """Small single-process engine; the HTTP owner supplies one encompassing RLock.

    view() never mutates state. tick() materializes expiry as a versioned fallback.
    Even without tick(), an expired view projects fresh deterministic fallback and
    never returns expired selected insight. Accepted mutation methods are atomic
    under the caller's lock. At most 500 unique records and corrections are kept.
    """

    def __init__(self, events, through_ms=0, window_ms=60_000, ttl_ms=15_000,
                 selection_ttl_ms=5_000, clock=None, source_id="synthetic_match"):
        _positive(ttl_ms, "ttl_ms")
        _positive(selection_ttl_ms, "selection_ttl_ms")
        _identifier(source_id, "source_id")
        snapshot = snapshot_at(events, through_ms, window_ms)
        self._clock = clock or (lambda: time.time_ns() // 1_000_000)
        self._last_now = -1
        now = self._now()
        self._events = {e["id"]: _plain(e) for e in events}
        self._revisions = {event_id: 1 for event_id in self._events}
        self._snapshot = snapshot
        self._through_ms, self._window_ms = through_ms, window_ms
        self._ttl_ms, self._selection_ttl_ms = ttl_ms, selection_ttl_ms
        self._source_id = source_id
        self._epoch = uuid.uuid4().hex
        self._version = 0
        self._selection = None
        self._requests = {}
        self._corrections = {}
        self._retracted = []
        self._issue(None, "no_selection", now)

    def _now(self):
        now = self._clock()
        if type(now) is not int or now < 0 or now < self._last_now:
            raise ValueError("clock must return nondecreasing nonnegative integer milliseconds")
        return now

    def _issue(self, selection, reason, now):
        previous = getattr(self, "_overlay_id", None)
        self._retracted = [previous] if previous else []
        self._version += 1
        self._overlay_id = f"overlay_{self._epoch}_{self._version}"
        self._selection = _plain(selection) if selection is not None else None
        self._reason = reason
        self._issued_at_ms = now
        self._expires_at_ms = now + self._ttl_ms
        self._last_now = now

    def _tick_at(self, now):
        if now >= self._expires_at_ms:
            self._issue(None, "expired", now)

    def tick(self):
        """Materialize one expiry transition. Never renew the selected insight."""
        now = self._now()
        self._tick_at(now)
        return self._view("casual", "en", now)

    def _view(self, audience, language, now):
        expired = now >= self._expires_at_ms
        choice = None if expired else self._selection
        reason = "expired" if expired else self._reason
        card = render_overlay(self._snapshot, choice, audience, language)
        card["reason"] = reason
        evidence = set(card["evidence_ids"])
        records = [e for e in self._snapshot["events"] if e["id"] in evidence]
        result = {
            "schema_version": SCHEMA_VERSION,
            "engine_epoch": self._epoch,
            "overlay_version": self._version,
            "overlay_id": self._overlay_id + ("_expired" if expired else ""),
            "fact_id": "fact_" + self._snapshot["state_digest"],
            "state_digest": self._snapshot["state_digest"],
            "issued_at_ms": now if expired else self._issued_at_ms,
            "expires_at_ms": now + self._ttl_ms if expired else self._expires_at_ms,
            "server_time_ms": now,
            "through_ms": self._through_ms,
            "window": {"start_ms": max(0, self._through_ms - self._window_ms),
                       "end_ms": self._through_ms, "inclusive": True},
            "reason": reason,
            "status": "expired_fallback" if expired else "fallback" if card["fallback"] else "insight",
            "retracted_overlay_ids": [self._overlay_id] if expired else list(self._retracted),
            "card": card,
            "snapshot": _plain(self._snapshot),
            "visible_event_count": len(self._snapshot["event_ids"]),
            "provenance": {
                "synthetic": True, "source_id": self._source_id,
                "evidence_ids": list(card["evidence_ids"]),
                "evidence_records": _plain(records),
                "event_revisions": {e["id"]: self._revisions[e["id"]] for e in self._snapshot["events"]},
            },
        }
        if language == "es":
            companion = render_overlay(self._snapshot, choice, audience, "en")
            companion["reason"] = reason
            result["english_companion"] = companion
        return result

    def view(self, audience="casual", language="en"):
        """Return a detached projection; changing display options changes no state."""
        return self._view(audience, language, self._now())

    def event_revision(self, event_id):
        """Administrative correction revision, including staged future events."""
        _identifier(event_id, "event_id")
        if event_id not in self._revisions:
            raise ValueError("unknown event_id")
        return self._revisions[event_id]

    def ingest(self, events):
        """Validate an entire batch before committing; ingest never advances time."""
        if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
            raise ValueError("ingest requires 1 through 500 records")
        merged = _plain(self._events)
        additions = []
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            _identifier(event.get("id"), "event id")
            event_id = event["id"]
            if event_id in merged:
                if _encoded(event) != _encoded(merged[event_id]):
                    raise ValueError("conflicting duplicate event; use correct")
            else:
                merged[event_id] = _plain(event)
                additions.append(event_id)
        snapshot = snapshot_at(list(merged.values()), self._through_ms, self._window_ms)
        now = self._now()
        if additions:
            self._events = merged
            self._revisions.update({event_id: 1 for event_id in additions})
            changed = snapshot["state_digest"] != self._snapshot["state_digest"]
            self._snapshot = snapshot
            self._last_now = now
            if changed:
                self._issue(None, "late_event", now)
        return self._view("casual", "en", now)

    def advance(self, through_ms):
        _time(through_ms)
        if through_ms < self._through_ms:
            raise ValueError("watermark cannot move backwards")
        snapshot = snapshot_at(list(self._events.values()), through_ms, self._window_ms)
        now = self._now()
        if through_ms != self._through_ms:
            self._snapshot, self._through_ms = snapshot, through_ms
            self._issue(None, "watermark_advanced", now)
        return self._view("casual", "en", now)

    def correct(self, correction):
        """CAS correction. Exact correction-ID retries are idempotent before CAS.

        Event ID and metadata cannot be changed. An action may move across the
        watermark; its old contribution is removed before the replacement enters.
        """
        _keys(correction, {"correction_id", "target_event_id", "expected_revision", "replacement"}, "correction")
        _identifier(correction["correction_id"], "correction_id")
        _identifier(correction["target_event_id"], "target_event_id")
        encoded = _encoded(correction)
        correction_id, target = correction["correction_id"], correction["target_event_id"]
        if correction_id in self._corrections:
            if self._corrections[correction_id] != encoded:
                raise ValueError("conflicting correction_id")
            return self.view()
        revision = correction["expected_revision"]
        if type(revision) is not int or revision < 1 or target not in self._events:
            raise ValueError("invalid target or expected_revision")
        if self._revisions[target] != revision:
            raise ValueError("expected_revision mismatch")
        if len(self._corrections) >= MAX_CORRECTIONS:
            raise ValueError("correction history capacity reached")
        old, replacement = self._events[target], correction["replacement"]
        if old["type"] == "metadata":
            raise ValueError("metadata correction is not supported")
        if not isinstance(replacement, dict) or replacement.get("id") != target or replacement.get("type") == "metadata":
            raise ValueError("replacement must preserve the action event ID")
        merged = _plain(self._events)
        merged[target] = _plain(replacement)
        snapshot = snapshot_at(list(merged.values()), self._through_ms, self._window_ms)
        now = self._now()
        visible = old["at_ms"] <= self._through_ms or replacement["at_ms"] <= self._through_ms
        self._events, self._snapshot = merged, snapshot
        self._revisions[target] += 1
        self._corrections[correction_id] = encoded
        self._last_now = now
        if visible:
            self._issue(None, "correction", now)
        return self._view("casual", "en", now)

    def selection_request(self, audience="casual", language="en"):
        """Register a one-use request, bound to this engine, state and display view."""
        # Validate view options before any expiry/state mutation.
        render_overlay(self._snapshot, audience=audience, language=language)
        now = self._now()
        # An expired but current request may still report a timeout. Keep it
        # until consumed or its captured state becomes stale, subject to cap.
        removable = [key for key, value in self._requests.items()
                     if now >= self._expires_at_ms or value["used"] or value["overlay_version"] != self._version
                     or value["state_digest"] != self._snapshot["state_digest"]]
        if len(self._requests) >= MAX_REQUESTS and not removable:
            raise ValueError("selection request capacity reached")
        self._tick_at(now)
        for key in removable:
            del self._requests[key]
        request = {
            "token_id": uuid.uuid4().hex, "engine_epoch": self._epoch,
            "overlay_version": self._version, "state_digest": self._snapshot["state_digest"],
            "deadline_ms": min(now + self._selection_ttl_ms, self._expires_at_ms),
            "audience": audience, "language": language,
            "candidates": _plain(self._snapshot["candidates"]),
            "snapshot": _plain(self._snapshot),
        }
        self._requests[request["token_id"]] = {
            "fingerprint": hashlib.sha256(_encoded(request).encode()).hexdigest(),
            "overlay_version": self._version, "state_digest": self._snapshot["state_digest"],
            "deadline_ms": request["deadline_ms"], "used": False,
        }
        self._last_now = now
        return request

    def _request(self, request, now, allow_expired=False):
        if not isinstance(request, dict) or not isinstance(request.get("token_id"), str):
            raise ValueError("unknown selection token")
        stored = self._requests.get(request["token_id"])
        if stored is None:
            raise ValueError("unknown selection token")
        if stored["used"]:
            raise ValueError("selection token already used")
        if hashlib.sha256(_encoded(request).encode()).hexdigest() != stored["fingerprint"]:
            raise ValueError("selection token was modified")
        if stored["overlay_version"] != self._version or stored["state_digest"] != self._snapshot["state_digest"]:
            raise ValueError("stale selection token")
        if not allow_expired and now >= stored["deadline_ms"]:
            raise ValueError("selection token expired")
        return stored

    def apply_selection(self, request, selection):
        now = self._now()
        stored = self._request(request, now)
        validate_selection(selection, self._snapshot)
        # No partial mutation if either request or selection validation failed.
        stored["used"] = True
        self._issue(selection, "validated_selection", now)
        return self._view(request["audience"], request["language"], now)

    def fail_selection(self, request, reason="timeout"):
        """Consume a current request and visibly retract a prior selected insight.

        Timeout may be reported at/after its deadline, but never after a newer
        overlay version. Stale failures cannot overwrite newer facts or cards.
        """
        if not isinstance(reason, str) or reason not in FAILURE_REASONS:
            raise ValueError("unsupported failure reason")
        now = self._now()
        stored = self._request(request, now, allow_expired=(reason == "timeout"))
        stored["used"] = True
        self._issue(None, reason, now)
        return self._view(request["audience"], request["language"], now)
