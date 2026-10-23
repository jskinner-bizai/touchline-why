"""Deterministic synthetic-football replay and evidence-bound display cards.

No model, network, framework, credentials or external data is used here. A turnover
names the losing actor and the player/team gaining possession. Statistics use
integer counts; rates retain exact numerator/denominator pairs. Replay sorts the
validated event set by (at_ms, id) and emits a detached immutable JSON snapshot at
each distinct timestamp. This is event-time replay, not a claim of live watermark
handling or tactical causation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

__all__ = ["load_events", "replay", "snapshot_at", "validate_selection", "render_overlay"]

ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9 '\-]{0,39}\Z")
KINDS = {"pass", "shot", "tackle", "turnover", "pressure"}
BASE = {"id", "type", "at_ms", "team_id", "player_id"}
COUNT_KEYS = ("pass_attempts", "passes_completed", "shots", "on_target", "goals",
              "tackles", "turnovers", "regains", "pressure")
# This milestone retains full evidence history per timestamp. Keep the accepted
# replay bounded until a streaming/shared-history implementation is reviewed.
MAX_EVENTS = 500
MAX_TIME_MS = 7_200_000


class FrozenDict(dict):
    """JSON-serializable value container, immutable through its public methods."""
    __slots__ = ("_initialized",)
    def __init__(self, *args, **kwargs):
        if hasattr(self, "_initialized"):
            raise TypeError("Snapshot is immutable")
        dict.__init__(self, *args, **kwargs)
        object.__setattr__(self, "_initialized", True)
    def _blocked(self, *args, **kwargs):
        raise TypeError("Snapshot is immutable")
    __setattr__ = __delattr__ = _blocked
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _blocked
    def __deepcopy__(self, memo):
        return self


class FrozenList(list):
    __slots__ = ("_initialized",)
    def __init__(self, *args, **kwargs):
        if hasattr(self, "_initialized"):
            raise TypeError("Snapshot is immutable")
        list.__init__(self, *args, **kwargs)
        object.__setattr__(self, "_initialized", True)
    def _blocked(self, *args, **kwargs):
        raise TypeError("Snapshot is immutable")
    __setattr__ = __delattr__ = _blocked
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _blocked
    def __deepcopy__(self, memo):
        return self


def _freeze(value):
    if isinstance(value, dict):
        return FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return FrozenList(_freeze(v) for v in value)
    return value


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _keys(value: Any, expected: set[str], label: str):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label}: expected exact keys {sorted(expected)}")


def _identifier(value: Any, label: str):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{label}: invalid identifier")


def _name(value: Any, label: str):
    if not isinstance(value, str) or not NAME.fullmatch(value) or len(value.split()) > 5:
        raise ValueError(f"{label}: invalid display name")


def _time(value: Any):
    if type(value) is not int or not 0 <= value <= MAX_TIME_MS:
        raise ValueError("at_ms must be an integer from 0 through 7200000")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _validated(events):
    if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
        raise ValueError("events must be a nonempty list of at most 500 records")
    unique = {}
    for item in events:
        if not isinstance(item, dict):
            raise ValueError("event must be an object")
        _identifier(item.get("id"), "event id")
        if item["id"] in unique:
            if _canonical(item) != _canonical(unique[item["id"]]):
                raise ValueError(f"conflicting duplicate event: {item['id']}")
            continue
        unique[item["id"]] = _plain(item)
    metadata = [item for item in unique.values() if item.get("type") == "metadata"]
    if len(metadata) != 1:
        raise ValueError("exactly one metadata event required")
    meta = metadata[0]
    _keys(meta, {"id", "type", "at_ms", "match_id", "teams", "players"}, "metadata")
    if type(meta["at_ms"]) is not int or meta["at_ms"] != 0:
        raise ValueError("metadata at_ms must be zero")
    _identifier(meta["match_id"], "match id")
    if not isinstance(meta["teams"], list) or len(meta["teams"]) != 2:
        raise ValueError("metadata must define two teams")
    teams = {}
    for team in meta["teams"]:
        _keys(team, {"id", "name"}, "team")
        _identifier(team["id"], "team id"); _name(team["name"], "team name")
        if team["id"] in teams:
            raise ValueError("duplicate team id")
        teams[team["id"]] = team
    if not isinstance(meta["players"], list) or not 2 <= len(meta["players"]) <= 50:
        raise ValueError("metadata must define 2 to 50 players")
    players = {}
    for player in meta["players"]:
        _keys(player, {"id", "name", "team_id"}, "player")
        _identifier(player["id"], "player id"); _name(player["name"], "player name")
        _identifier(player["team_id"], "player team id")
        if player["team_id"] not in teams or player["id"] in players:
            raise ValueError("invalid player team or duplicate player")
        players[player["id"]] = player
    if set(p["team_id"] for p in players.values()) != set(teams):
        raise ValueError("each team needs a declared player")
    # Metadata is not an on-pitch action. Actions at time zero are valid.
    actions = []
    for item in unique.values():
        if item is meta:
            continue
        kind = item.get("type")
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("unsupported event type")
        extras = {"success"} if kind == "pass" else {"on_target", "goal"} if kind == "shot" else {"gained_by_team_id", "gained_by_player_id"} if kind == "turnover" else set()
        _keys(item, BASE | extras, kind)
        _time(item["at_ms"])
        _identifier(item["team_id"], "event team id")
        _identifier(item["player_id"], "event player id")
        if item["team_id"] not in teams or item["player_id"] not in players or players[item["player_id"]]["team_id"] != item["team_id"]:
            raise ValueError("actor does not match declared team/player")
        if kind == "pass" and type(item["success"]) is not bool:
            raise ValueError("pass success must be bool")
        if kind == "shot":
            if type(item["on_target"]) is not bool or type(item["goal"]) is not bool or (item["goal"] and not item["on_target"]):
                raise ValueError("shot flags invalid; a goal must be on target")
        if kind == "turnover":
            gained_team, gained_player = item["gained_by_team_id"], item["gained_by_player_id"]
            _identifier(gained_team, "turnover beneficiary team")
            _identifier(gained_player, "turnover beneficiary player")
            if gained_team not in teams or gained_team == item["team_id"] or gained_player not in players or players[gained_player]["team_id"] != gained_team:
                raise ValueError("turnover beneficiary must belong to the other team")
        actions.append(item)
    # Canonical metadata ordering avoids semantic differences from roster order.
    meta["teams"] = sorted(meta["teams"], key=lambda x: x["id"])
    meta["players"] = sorted(meta["players"], key=lambda x: x["id"])
    return meta, sorted(actions, key=lambda x: (x["at_ms"], x["id"]))


def load_events(path) -> list[dict]:
    """Load a bounded JSONL fixture; reject blank records, invalid JSON and schema."""
    with Path(path).open("rb") as source:
        content_bytes = source.read(5_000_001)
    if len(content_bytes) > 5_000_000:
        raise ValueError("fixture is too large")
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("fixture must be UTF-8") from error
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result
    events = []
    for index, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            raise ValueError(f"blank JSONL record at line {index}")
        try:
            event = json.loads(line, object_pairs_hook=no_duplicate_keys,
                               parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid JSON at line {index}") from error
        events.append(event)
    _validated(events)
    return events


def _counts():
    return {key: 0 for key in COUNT_KEYS}


def _stats(events, meta):
    teams = {x["id"]: _counts() for x in meta["teams"]}
    players = {x["id"]: _counts() for x in meta["players"]}
    for event in events:
        containers = (teams[event["team_id"]], players[event["player_id"]])
        for count in containers:
            kind = event["type"]
            if kind == "pass":
                count["pass_attempts"] += 1
                count["passes_completed"] += int(event["success"])
            elif kind == "shot":
                count["shots"] += 1
                count["on_target"] += int(event["on_target"])
                count["goals"] += int(event["goal"])
            elif kind == "tackle":
                count["tackles"] += 1
            elif kind == "pressure":
                count["pressure"] += 1
            elif kind == "turnover":
                count["turnovers"] += 1
        if event["type"] == "turnover":
            teams[event["gained_by_team_id"]]["regains"] += 1
            players[event["gained_by_player_id"]]["regains"] += 1
    for count in [*teams.values(), *players.values()]:
        count["pass_accuracy"] = ({"numerator": count["passes_completed"], "denominator": count["pass_attempts"]} if count["pass_attempts"] else None)
        count["shot_accuracy"] = ({"numerator": count["on_target"], "denominator": count["shots"]} if count["shots"] else None)
    return {"teams": teams, "players": players}


def _candidates(window, statistics, upto_ms, window_ms):
    candidates = []
    for team_id, count in statistics["teams"].items():
        pressure = [e for e in window if e["type"] == "pressure" and e["team_id"] == team_id]
        regains = [e for e in window if e["type"] == "turnover" and e["gained_by_team_id"] == team_id]
        shots = [e for e in window if e["type"] == "shot" and e["team_id"] == team_id]
        patterns = []
        if len(pressure) >= 3 and regains:
            patterns.append(("pressure_activity", pressure + regains, {"pressure_events": len(pressure), "regains": len(regains)}))
        if len(shots) >= 2:
            patterns.append(("shot_volume", shots, {"shots": len(shots), "on_target": count["on_target"]}))
        for explanation, evidence, metrics in patterns:
            evidence = sorted(evidence, key=lambda e: (e["at_ms"], e["id"]))
            metrics = {**metrics, "window_start_ms": max(0, upto_ms - window_ms), "window_end_ms": upto_ms}
            candidate_body = {"explanation_type": explanation, "team_id": team_id, "evidence_ids": [e["id"] for e in evidence], "metrics": metrics}
            candidate_id = "candidate_" + hashlib.sha256(_canonical(candidate_body).encode()).hexdigest()[:20]
            candidates.append({"candidate_id": candidate_id, **candidate_body})
    return sorted(candidates, key=lambda x: (x["explanation_type"], x["team_id"], x["candidate_id"]))


def replay(events: list[dict], window_ms=60_000) -> list[dict]:
    """Replay a validated set, deduplicated by ID, in deterministic event-time order."""
    if type(window_ms) is not int or not 1 <= window_ms <= MAX_TIME_MS:
        raise ValueError("window_ms must be an integer from 1 through 7200000")
    meta, actions = _validated(events)
    snapshots = []
    for timestamp in sorted({0, *(e["at_ms"] for e in actions)}):
        seen = [e for e in actions if e["at_ms"] <= timestamp]
        window = [e for e in seen if timestamp - window_ms <= e["at_ms"] <= timestamp]
        statistics = {"total": _stats(seen, meta), "window": _stats(window, meta)}
        body = {
            "match": meta,
            "upto_ms": timestamp,
            "window_ms": window_ms,
            "event_ids": [meta["id"], *(e["id"] for e in seen)],
            "window_event_ids": [e["id"] for e in window],
            "events": [meta, *seen],
            "stats": statistics,
            "candidates": _candidates(window, statistics["window"], timestamp, window_ms),
        }
        body["state_digest"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
        snapshots.append(_freeze(body))
    return snapshots


def snapshot_at(events: list[dict], through_ms, window_ms=60_000) -> dict:
    """Compute one immutable snapshot at an explicit event-time watermark.

    Future records are validated but never enter the visible snapshot or digest.
    Unlike replay's event timestamps, gaps still advance the rolling window.
    """
    _time(through_ms)
    if type(window_ms) is not int or not 1 <= window_ms <= MAX_TIME_MS:
        raise ValueError("window_ms must be an integer from 1 through 7200000")
    meta, actions = _validated(events)
    seen = [e for e in actions if e["at_ms"] <= through_ms]
    window = [e for e in seen if through_ms - window_ms <= e["at_ms"] <= through_ms]
    statistics = {"total": _stats(seen, meta), "window": _stats(window, meta)}
    body = {
        "match": meta, "upto_ms": through_ms, "window_ms": window_ms,
        "event_ids": [meta["id"], *(e["id"] for e in seen)],
        "window_event_ids": [e["id"] for e in window],
        "events": [meta, *seen], "stats": statistics,
        "candidates": _candidates(window, statistics["window"], through_ms, window_ms),
    }
    body["state_digest"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
    return _freeze(body)


def validate_selection(selection, snapshot) -> dict:
    """Accept IDs from one existing candidate only; never accept generated prose."""
    _keys(selection, {"candidate_id", "explanation_type", "evidence_ids"}, "selection")
    if not isinstance(selection["candidate_id"], str) or not isinstance(selection["explanation_type"], str):
        raise ValueError("selection IDs and type must be strings")
    if not isinstance(selection["evidence_ids"], list) or not selection["evidence_ids"] or not all(isinstance(x, str) for x in selection["evidence_ids"]):
        raise ValueError("evidence_ids must be a nonempty list of strings")
    if len(selection["evidence_ids"]) != len(set(selection["evidence_ids"])):
        raise ValueError("duplicate selection evidence")
    candidate = next((x for x in snapshot["candidates"] if x["candidate_id"] == selection["candidate_id"]), None)
    if candidate is None:
        raise ValueError("unsupported candidate")
    if selection["explanation_type"] != candidate["explanation_type"]:
        raise ValueError("unsupported explanation type")
    if selection["evidence_ids"] != candidate["evidence_ids"]:
        raise ValueError("evidence does not exactly match candidate")
    if not set(candidate["evidence_ids"]) <= set(snapshot["window_event_ids"]):
        raise ValueError("candidate evidence is not current")
    return _plain(candidate)


def render_overlay(snapshot, selection=None, audience="casual", language="en") -> dict:
    """Render trusted templates. Invalid/missing selection selects labelled fallback."""
    if audience not in {"casual", "analyst"} or language not in {"en", "es"}:
        raise ValueError("unsupported audience or language")
    candidate = None
    reason = "no_selection"
    if selection is not None:
        try:
            candidate = validate_selection(selection, snapshot)
            reason = "validated_selection"
        except (ValueError, TypeError):
            reason = "unsupported_selection"
    teams = snapshot["match"]["teams"]
    fallback = candidate is None
    if fallback:
        # Fallback has no pattern/causal claims and remains useful without a model.
        metrics = {x["id"]: _plain(snapshot["stats"]["total"]["teams"][x["id"]]) for x in teams}
        goals = [metrics[x["id"]]["goals"] for x in teams]
        if language == "en":
            text = f"Verified fact card: {teams[0]['name']} {goals[0]}, {teams[1]['name']} {goals[1]}. Synthetic replay; no model explanation accepted."
        else:
            text = f"Ficha verificada: {teams[0]['name']} {goals[0]}, {teams[1]['name']} {goals[1]}. Partido sintetico; sin explicacion de modelo aceptada."
        if audience == "analyst":
            start = max(0, snapshot["upto_ms"] - snapshot["window_ms"])
            if language == "en":
                text += f" Window [{start},{snapshot['upto_ms']}]ms, inclusive."
            else:
                text += f" Ventana [{start},{snapshot['upto_ms']}]ms, inclusiva."
            for team in teams:
                count = snapshot["stats"]["window"]["teams"][team["id"]]
                passes = f"{count['passes_completed']}/{count['pass_attempts']}" if count["pass_attempts"] else ("unknown (0 attempts)" if language == "en" else "desconocido (0 intentos)")
                shots = f"{count['on_target']}/{count['shots']}" if count["shots"] else ("unknown (0 shots)" if language == "en" else "desconocido (0 tiros)")
                if language == "en":
                    text += f" {team['name']}: passes {passes}; shots on target {shots}; pressure events {count['pressure']}."
                else:
                    text += f" {team['name']}: pases {passes}; tiros a puerta {shots}; eventos de presion {count['pressure']}."
        # The fallback carries complete total metrics, so expose their complete
        # event lineage as well as the scoreboard's scoring events.
        evidence_ids = list(snapshot["event_ids"])
        explanation = "verified_score"
        candidate_id = None
    else:
        metrics = candidate["metrics"]
        team = next(x["name"] for x in teams if x["id"] == candidate["team_id"])
        explanation = candidate["explanation_type"]
        candidate_id = candidate["candidate_id"]
        evidence_ids = candidate["evidence_ids"]
        # Early match windows are clipped at match start. Describe the observed
        # span, rather than claiming a full nominal window has elapsed.
        seconds, milliseconds = divmod(metrics["window_end_ms"] - metrics["window_start_ms"], 1000)
        duration = str(seconds) + ("." + f"{milliseconds:03d}".rstrip("0") if milliseconds else "")
        if explanation == "pressure_activity":
            if language == "en":
                text = f"{team}: {metrics['pressure_events']} pressure events and {metrics['regains']} possession regains in {duration}s. Activity proxy, not proof of tactical cause."
            else:
                text = f"{team}: {metrics['pressure_events']} eventos de presion y {metrics['regains']} recuperaciones en {duration}s. Indicador de actividad, no prueba de causa tactica."
        else:
            if language == "en":
                text = f"{team}: {metrics['shots']} shots, {metrics['on_target']} on target in {duration}s. Attempts counted in this window; no xG or causal claim."
            else:
                text = f"{team}: {metrics['shots']} tiros, {metrics['on_target']} a puerta en {duration}s. Intentos contados en esta ventana; sin xG ni afirmacion causal."
        if audience == "analyst":
            if language == "en":
                text += f" Window [{metrics['window_start_ms']},{metrics['window_end_ms']}]ms, inclusive."
            else:
                text += f" Ventana [{metrics['window_start_ms']},{metrics['window_end_ms']}]ms, inclusiva."
    return {
        "text": text, "audience": audience, "language": language,
        "fallback": fallback, "reason": reason,
        "candidate_id": candidate_id, "explanation_type": explanation,
        "evidence_ids": list(evidence_ids), "metrics": _plain(metrics),
        "window_metrics": _plain(snapshot["stats"]["window"]["teams"]),
        "window_start_ms": max(0, snapshot["upto_ms"] - snapshot["window_ms"]),
        "window_end_ms": snapshot["upto_ms"],
        "upto_ms": snapshot["upto_ms"], "state_digest": snapshot["state_digest"],
        "window_ms": snapshot["window_ms"],
        "qualification": "Synthetic data; deterministic templates. Spanish wording needs final language review.",
    }
