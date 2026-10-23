"""Deterministic recap of a validated current snapshot. No I/O or model calls.

Recorded inputs accept only the two preserved, hash-verified M2 accepted receipts.
They remain history, and cannot introduce facts past the current match watermark.
"""
from __future__ import annotations

import hashlib
import json

from touchline_core import _canonical, _identifier, _plain, snapshot_at, validate_selection

SCHEMA_VERSION = "touchline.recap.v1"
__all__ = ["build_recap", "normalize_recorded_receipt"]
APPROVED_RECEIPTS = {
    "m2-third-ui-call.json": "8c54aebccd6163337de8c703ab8d22c26b471db67f66a876044409469bddb5ab",
    "m2-fourth-ui-call.json": "3b9f35f008c51b2ef0fbe7d9fac5a2392c2182b8f36c4f648e6b7a1734a888aa",
}


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _snapshot(value):
    if not isinstance(value, dict):
        raise ValueError("snapshot must be an object")
    try:
        expected = snapshot_at(value["events"], value["upto_ms"], value["window_ms"])
        if _canonical(value) != _canonical(expected):
            raise ValueError("snapshot does not match its canonical event evidence")
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("invalid snapshot") from error
    return expected


def _provenance(value, snapshot):
    events = {event["id"]: event for event in snapshot["events"]}
    if value is None:
        return "synthetic_snapshot", {key: None for key in events}, []
    if not isinstance(value, dict) or set(value) - {
        "synthetic", "source_id", "evidence_ids", "evidence_records", "event_revisions", "corrections"
    }:
        raise ValueError("unsupported provenance")
    if value.get("synthetic") is not True:
        raise ValueError("recap requires declared synthetic provenance")
    source = value.get("source_id")
    _identifier(source, "source_id")
    revisions = value.get("event_revisions")
    if not isinstance(revisions, dict) or set(revisions) != set(events) or any(
        type(revision) is not int or not 1 <= revision <= 501 for revision in revisions.values()
    ):
        raise ValueError("current revisions must match the visible event set")
    if revisions[snapshot["match"]["id"]] != 1:
        raise ValueError("metadata cannot have a correction revision")
    ids, records = value.get("evidence_ids"), value.get("evidence_records")
    if ids is not None or records is not None:
        if not isinstance(ids, list) or not isinstance(records, list) or not all(isinstance(key, str) for key in ids) or len(ids) != len(set(ids)):
            raise ValueError("invalid provenance evidence")
        if not all(isinstance(key, str) and key in events for key in ids):
            raise ValueError("provenance evidence is not current")
        if [event.get("id") for event in records if isinstance(event, dict)] != ids or len(records) != len(ids):
            raise ValueError("provenance evidence IDs and records disagree")
        if any(_canonical(event) != _canonical(events[event["id"]]) for event in records):
            raise ValueError("provenance evidence was revised")
    corrections = value.get("corrections", [])
    if not isinstance(corrections, list) or len(corrections) > 500:
        raise ValueError("correction history is limited to 500 rows")
    return source, _plain(revisions), corrections


def _corrected(corrections, snapshot, revisions, source):
    current = {event["id"]: event for event in snapshot["events"]}
    unique, groups = {}, {}
    required = {"correction_id", "target_event_id", "from_revision", "to_revision", "before", "after"}
    for row in corrections:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"source_id"}:
            raise ValueError("invalid correction history row")
        _identifier(row["correction_id"], "correction_id")
        _identifier(row["target_event_id"], "target_event_id")
        if row.get("source_id", source) != source:
            raise ValueError("correction source disagrees")
        if type(row["from_revision"]) is not int or type(row["to_revision"]) is not int or not (
            1 <= row["from_revision"] < row["to_revision"] <= 501 and row["to_revision"] == row["from_revision"] + 1
        ):
            raise ValueError("invalid correction revision transition")
        key = row["correction_id"]
        normalized = {**_plain(row), "source_id": source}
        if key in unique:
            if unique[key] != normalized:
                raise ValueError("conflicting correction_id")
            continue
        target = row["target_event_id"]
        if target not in current or current[target]["type"] == "metadata":
            raise ValueError("correction target must be a currently visible action")
        for field in ("before", "after"):
            event = row[field]
            if not isinstance(event, dict) or event.get("id") != target or event.get("type") == "metadata":
                raise ValueError("correction history must preserve action ID")
            snapshot_at([_plain(snapshot["match"]), _plain(event)], snapshot["upto_ms"], snapshot["window_ms"])
        unique[key] = normalized
        groups.setdefault(target, []).append(normalized)
    result, withdrawals = [], []
    for target in sorted(current):
        revision = revisions[target]
        if revision is None or revision == 1:
            if target in groups:
                raise ValueError("correction history exceeds current revision")
            continue
        rows = sorted(groups.get(target, []), key=lambda row: row["from_revision"])
        moment = {"event_id": target, "current_revision": revision, "source_id": source,
                  "evidence_ids": [target], "history_verified": bool(rows), "correction_ids": [],
                  "changed_fields": [], "net_changed_fields": [], "withdrawn_claims": []}
        if rows:
            if rows[0]["from_revision"] != 1 or rows[-1]["to_revision"] != revision:
                raise ValueError("correction history must cover revisions 1 through current")
            for before, after in zip(rows, rows[1:]):
                if before["to_revision"] != after["from_revision"] or before["after"] != after["before"]:
                    raise ValueError("correction history is not contiguous")
            first, final = rows[0]["before"], rows[-1]["after"]
            if _canonical(final) != _canonical(current[target]):
                raise ValueError("correction history does not end at current event")
            moment["correction_ids"] = [row["correction_id"] for row in rows]
            moment["net_changed_fields"] = sorted(key for key in set(first) | set(final) if first.get(key) != final.get(key))
            moment["changed_fields"] = sorted({key for row in rows for key in set(row["before"]) | set(row["after"])
                                               if row["before"].get(key) != row["after"].get(key)})
            superseded_goals = {}
            for row in rows:
                previous = row["before"]
                if previous["at_ms"] <= snapshot["upto_ms"] and previous.get("goal") is True and (
                    final.get("goal") is not True or previous["team_id"] != final["team_id"]
                ):
                    superseded_goals[previous["team_id"]] = row["from_revision"]
            for team_id in sorted(superseded_goals):
                claim = {"type": "goal", "event_id": target, "team_id": team_id,
                         "from_revision": superseded_goals[team_id], "current_revision": revision, "source_id": source}
                moment["withdrawn_claims"].append(claim)
                withdrawals.append(claim)
        result.append(moment)
    return result, withdrawals


def normalize_recorded_receipt(receipt_id, receipt_bytes):
    """Verify original receipt bytes and return historical selection data only.

    This reads no files and makes no requests. Replaying this selection is not a
    model invocation; the consumer must retain historical/recorded attribution.
    """
    if not isinstance(receipt_id, str) or receipt_id not in APPROVED_RECEIPTS or not isinstance(receipt_bytes, bytes) or len(receipt_bytes) > 100_000:
        raise ValueError("unapproved recorded receipt")
    digest = hashlib.sha256(receipt_bytes).hexdigest()
    if digest != APPROVED_RECEIPTS[receipt_id]:
        raise ValueError("recorded receipt hash mismatch")
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        job = receipt["model_job"]
        if job["status"] != "accepted" or job["injected"] is not False or job["result"]["status"] != "selected":
            raise ValueError("receipt is not an actual accepted selection")
        original = _snapshot(receipt["envelope"]["snapshot"])
        selection = job["result"]["selection"]
        candidate = validate_selection(selection, original)
        source = receipt["envelope"]["provenance"]["source_id"]
        _identifier(source, "recorded source_id")
    except (KeyError, UnicodeError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid recorded receipt") from error
    return {"receipt_id": receipt_id, "receipt_sha256": digest, "historical_only": True,
            "source_id": source, "snapshot": _plain(original), "selection": _plain(selection),
            "candidate": _plain(candidate)}


def _recorded(inputs, snapshot):
    if inputs is None:
        return [], [], 0
    if not isinstance(inputs, list) or len(inputs) > 20:
        raise ValueError("recorded selections require a bounded list")
    receipts, moments, withheld = {}, {}, 0
    current_events = {event["id"]: event for event in snapshot["events"]}
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {"receipt_id", "receipt_bytes"}:
            raise ValueError("recorded input requires receipt_id and original receipt_bytes")
        normalized = normalize_recorded_receipt(item["receipt_id"], item["receipt_bytes"])
        receipt_id, digest = normalized["receipt_id"], normalized["receipt_sha256"]
        if receipt_id in receipts:
            continue
        original, selection, candidate = normalized["snapshot"], normalized["selection"], normalized["candidate"]
        receipts[receipt_id] = {"receipt_id": receipt_id, "receipt_sha256": digest}
        if original["match"] != snapshot["match"]:
            raise ValueError("recorded selection belongs to a different match")
        if original["upto_ms"] > snapshot["upto_ms"]:
            withheld += 1
            continue
        source = normalized["source_id"]
        key = _digest({"source_id": source, "state_digest": original["state_digest"], "selection": selection})
        if key not in moments:
            historical_events = {event["id"]: event for event in original["events"]}
            changed = [event_id for event_id in selection["evidence_ids"] if event_id not in current_events
                       or current_events[event_id] != historical_events[event_id]]
            revised_past = snapshot_at(snapshot["events"], original["upto_ms"], original["window_ms"])
            try:
                validate_selection(selection, revised_past)
                supported = True
            except ValueError:
                supported = False
            moments[key] = {
                "recorded_moment_id": "recorded_" + key, "historical_only": True,
                "original_state_digest": original["state_digest"], "original_through_ms": original["upto_ms"],
                "source_id": source, "selection": _plain(selection), "original_metrics": candidate["metrics"],
                "receipt_ids": [], "changed_evidence_ids": changed,
                "state_relation": "same_snapshot" if original["state_digest"] == snapshot["state_digest"] else "superseded_state",
                "window_relation": "within_current_window" if set(selection["evidence_ids"]) <= set(snapshot["window_event_ids"]) else "outside_current_window",
                "claim_supported_after_corrections": supported,
                "claim_status": "supported_historical" if supported else "withdrawn_after_correction",
            }
        moments[key]["receipt_ids"].append(receipt_id)
    for moment in moments.values():
        moment["receipt_ids"].sort()
    return [receipts[key] for key in sorted(receipts)], [moments[key] for key in sorted(moments)], withheld


def _seconds(value):
    seconds, remainder = divmod(value, 1000)
    return str(seconds) + ("." + f"{remainder:03d}".rstrip("0") if remainder else "")


def _rate(value, language):
    if value is None:
        return "unknown (0 attempts)" if language == "en" else "no disponible (0 intentos)"
    return f"{value['numerator']}/{value['denominator']}"


def _text(facts, corrected, withdrawals, recorded, audience, language):
    teams = facts["teams"]
    score = ", ".join(f"{team['name']} {team['totals']['goals']}" for team in teams)
    if audience == "casual":
        text = (f"Score at {_seconds(facts['through_ms'])}s: {score}." if language == "en"
                else f"Marcador a los {_seconds(facts['through_ms'])}s: {score}.")
        for team in teams:
            stats = team["totals"]
            shot_term = ("shot" if stats["shots"] == 1 else "shots") if language == "en" else ("tiro" if stats["shots"] == 1 else "tiros")
            passes = (f"{stats['passes_completed']}/{stats['pass_attempts']}" if stats["pass_attempts"]
                      else ("no passes attempted" if language == "en" else "sin intentos de pase"))
            text += (f" {team['name']}: {stats['shots']} {shot_term}, {stats['on_target']} on target; passes completed {passes}."
                     if language == "en" else
                     f" {team['name']}: {stats['shots']} {shot_term}, {stats['on_target']} a puerta; pases completados {passes}.")
        if withdrawals:
            text += (" A recorded goal was removed after a verified correction." if language == "en"
                     else " Se retiró un gol registrado tras una corrección verificada.")
        return text
    text = (f"Verified score at {_seconds(facts['through_ms'])}s: {score}." if language == "en"
            else f"Marcador verificado a los {_seconds(facts['through_ms'])}s: {score}.")
    for team in teams:
        stats = team["totals"]
        if language == "en":
            text += f" {team['name']}: {stats['shots']} shots, on-target rate {_rate(stats['shot_accuracy'], language)}, passes {_rate(stats['pass_accuracy'], language)}."
        else:
            text += f" {team['name']}: {stats['shots']} tiros, tiros a puerta {_rate(stats['shot_accuracy'], language)}, pases completados {_rate(stats['pass_accuracy'], language)}."
    for pattern in facts["pressure_proxies"]:
        team = next(team["name"] for team in teams if team["team_id"] == pattern["team_id"])
        metrics = pattern["metrics"]
        regain = "regain" if metrics["regains"] == 1 else "regains"
        recuperacion = "recuperación" if metrics["regains"] == 1 else "recuperaciones"
        text += (f" Activity proxy: {team}, {metrics['pressure_events']} pressure events and {metrics['regains']} {regain} in the current window. No tactical cause inferred."
                 if language == "en" else f" Indicador de actividad: {team}, {metrics['pressure_events']} acciones de presión y {metrics['regains']} {recuperacion} del balón en la ventana actual. Solo describe actividad; no demuestra que la presión causara las recuperaciones.")
    if not facts["pressure_proxies"]:
        text += " No verified pressure-pattern proxy in the current window." if language == "en" else " Sin indicador verificado de actividad de presión en la ventana actual."
    if withdrawals:
        ids = ", ".join(claim["event_id"] for claim in withdrawals[:10])
        text += f" Goal claims withdrawn after verified corrections: {ids}." if language == "en" else f" Goles previamente registrados y retirados tras correcciones verificadas: {ids}."
    elif corrected:
        text += " Revised records are identified; no unverified prior claim is inferred." if language == "en" else " Hay registros revisados; no se presupone ninguna afirmación previa sin verificar."
    if recorded:
        term = "momento distinto" if len(recorded) == 1 else "momentos distintos"
        text += f" {len(recorded)} distinct recorded selection moment; historical evidence only, not a live or newly inferred result." if language == "en" else f" {len(recorded)} {term} de selección registrada; solo evidencia histórica, no un resultado en directo ni una nueva inferencia."
        if any(not moment["claim_supported_after_corrections"] for moment in recorded):
            text += (" A previously recorded pattern is no longer supported by corrected events and is withdrawn as a current claim."
                     if language == "en" else " Un patrón registrado previamente ya no está respaldado por los eventos corregidos y se retira como afirmación actual.")
    if audience == "analyst":
        window = facts["window"]
        text += (f" Inclusive event-time window [{window['start_ms']},{window['end_ms']}]ms."
                 if language == "en" else f" Ventana temporal [{window['start_ms']},{window['end_ms']}]ms, con ambos extremos incluidos.")
        for team in teams:
            stats = team["window"]
            text += (f" Window {team['name']}: shots {stats['shots']}, on target {_rate(stats['shot_accuracy'], language)}, passes {_rate(stats['pass_accuracy'], language)}."
                     if language == "en" else f" En la ventana actual, {team['name']}: tiros {stats['shots']}, tiros a puerta {_rate(stats['shot_accuracy'], language)}, pases completados {_rate(stats['pass_accuracy'], language)}.")
        revised = [f"{item['event_id']}={item['current_revision']}" for item in corrected[:10]]
        if revised:
            text += (" Current revisions: " if language == "en" else " Revisiones actuales: ") + ", ".join(revised) + "."
    return text


def build_recap(snapshot, provenance=None, recorded_selections=None):
    """Return JSON facts and casual/analyst English/Spanish text, all deterministic.

    Provenance accepts the M2 current shape plus optional verified correction rows:
    correction_id,target_event_id,from_revision,to_revision,before,after,source_id?.
    Without before/after history a revision is reported without invented withdrawals.
    The caller supplies authoritative committed history; this module checks its
    consistency, not journal authentication or persistence.
    Recorded inputs are {receipt_id,receipt_bytes}; exact original bytes are required.
    """
    snapshot = _snapshot(snapshot)
    source, revisions, corrections = _provenance(provenance, snapshot)
    corrected, withdrawn = _corrected(corrections, snapshot, revisions, source)
    receipts, recorded, withheld = _recorded(recorded_selections, snapshot)
    teams = [{"team_id": team["id"], "name": team["name"],
              "totals": _plain(snapshot["stats"]["total"]["teams"][team["id"]]),
              "window": _plain(snapshot["stats"]["window"]["teams"][team["id"]])}
             for team in snapshot["match"]["teams"]]
    facts = {
        "through_ms": snapshot["upto_ms"], "teams": teams,
        "window": {"start_ms": max(0, snapshot["upto_ms"] - snapshot["window_ms"]),
                   "end_ms": snapshot["upto_ms"], "inclusive": True},
        "pressure_proxies": [_plain(candidate) for candidate in snapshot["candidates"] if candidate["explanation_type"] == "pressure_activity"],
        "goals": [_plain(event) for event in snapshot["events"] if event.get("goal") is True],
        "source_id": source, "event_revisions": revisions,
    }
    current_moments = [{"moment_id": "goal_" + _digest({"source_id": source, "event": event,
                                                       "revision": revisions[event["id"]]}),
                        "type": "verified_goal", "at_ms": event["at_ms"],
                        "team_id": event["team_id"], "player_id": event["player_id"],
                        "source_id": source, "evidence_ids": [event["id"]],
                        "current_revision": revisions[event["id"]]} for event in facts["goals"]]
    current_moments += [{"moment_id": "proxy_" + _digest({"source_id": source, "candidate": candidate}),
                         "type": "pressure_activity_proxy", "team_id": candidate["team_id"],
                         "source_id": source, "evidence_ids": candidate["evidence_ids"],
                         "metrics": candidate["metrics"]} for candidate in facts["pressure_proxies"]]
    body = {"schema_version": SCHEMA_VERSION, "state_digest": snapshot["state_digest"],
            "fact_id": "fact_" + snapshot["state_digest"],
            "through_ms": snapshot["upto_ms"], "facts": facts, "evidence_ids": list(snapshot["event_ids"]),
            "current_moments": current_moments,
            "corrected_moments": corrected, "withdrawn_claims": withdrawn,
            "recorded_receipts": receipts, "recorded_selections": recorded,
            "withdrawn_recorded_claims": [{"recorded_moment_id": moment["recorded_moment_id"],
                                           "type": moment["selection"]["explanation_type"],
                                           "receipt_ids": list(moment["receipt_ids"])}
                                          for moment in recorded if not moment["claim_supported_after_corrections"]],
            "recorded_receipt_count": len(receipts), "recorded_moment_count": len(recorded),
            "withheld_recorded_receipt_count": withheld,
            "qualification": "Synthetic current snapshot; deterministic recap. Recorded selections are historical only. Spanish wording needs language review."}
    body["recap_id"] = "recap_" + _digest(body)
    body["views"] = {audience: {language: _text(facts, corrected, withdrawn, recorded, audience, language)
                                for language in ("en", "es")} for audience in ("casual", "analyst")}
    return body
