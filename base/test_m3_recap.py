"""Deterministic recap acceptance checks. No model, SDK, browser or network."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
CORE = ROOT if (ROOT / "touchline_core.py").exists() else ROOT.parents[1] / "touchline-m2" / "repo"
sys.path[:0] = [str(ROOT), str(CORE)]
from touchline_core import load_events, snapshot_at
from overlay_state import OverlayState
from recap import APPROVED_RECEIPTS, build_recap, normalize_recorded_receipt


class RecapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_events(CORE / "synthetic_match.jsonl")
        cls.receipts = []
        for name in APPROVED_RECEIPTS:
            choices = [ROOT / "evidence" / name, ROOT / "evidence" / "recorded" / name,
                       ROOT.parents[1] / "touchline-m2" / "repo" / "evidence" / name]
            path = next((path for path in choices if path.exists()), None)
            if path is None:
                raise FileNotFoundError(f"Preserved recorded receipt required: {name}")
            cls.receipts.append({"receipt_id": name, "receipt_bytes": path.read_bytes()})

    def corrected(self, through=130_000):
        state = OverlayState(self.events, through_ms=through, clock=lambda: 1_000)
        old = copy.deepcopy(next(event for event in self.events if event["id"] == "e010"))
        new = {**old, "goal": False}
        state.correct({"correction_id": "saved_shot", "target_event_id": "e010",
                       "expected_revision": 1, "replacement": new})
        envelope = state.view()
        provenance = envelope["provenance"]
        provenance["corrections"] = [{"correction_id": "saved_shot", "target_event_id": "e010",
                                      "from_revision": 1, "to_revision": 2, "before": old,
                                      "after": new, "source_id": provenance["source_id"]}]
        return envelope["snapshot"], provenance

    def test_current_final_score_and_exact_total_rates(self):
        snapshot, provenance = self.corrected()
        recap = build_recap(snapshot, provenance)
        teams = {team["team_id"]: team for team in recap["facts"]["teams"]}
        self.assertEqual(teams["harbor"]["totals"]["goals"], 0)
        self.assertEqual(teams["meadow"]["totals"]["goals"], 1)
        self.assertEqual(teams["harbor"]["totals"]["shots"], 2)
        self.assertEqual(teams["harbor"]["totals"]["pass_accuracy"], {"numerator": 2, "denominator": 3})
        self.assertEqual(teams["meadow"]["totals"]["shot_accuracy"], {"numerator": 1, "denominator": 2})
        self.assertEqual([event["id"] for event in recap["facts"]["goals"]], ["e017"])
        goals = [moment for moment in recap["current_moments"] if moment["type"] == "verified_goal"]
        self.assertEqual([moment["evidence_ids"] for moment in goals], [["e017"]])

    def test_casual_analyst_language_views_share_one_fact_identity(self):
        snapshot, provenance = self.corrected()
        recap = build_recap(snapshot, provenance)
        self.assertEqual(set(recap["views"]), {"casual", "analyst"})
        for audience in ("casual", "analyst"):
            self.assertEqual(set(recap["views"][audience]), {"en", "es"})
            for text in recap["views"][audience].values():
                self.assertIn("Harbor Owls 0, Meadow Foxes 1", text)
                self.assertIn("2/3", text)
                self.assertNotIn("\u2014", text)
                self.assertNotIn("\u2013", text)
        self.assertIn("[70000,130000]ms", recap["views"]["analyst"]["en"])

    def test_unknown_zero_denominators_never_become_percentages(self):
        recap = build_recap(snapshot_at(self.events, 0))
        self.assertIsNone(recap["facts"]["teams"][0]["totals"]["pass_accuracy"])
        self.assertIn("unknown (0 attempts)", recap["views"]["analyst"]["en"])
        self.assertIn("no passes attempted", recap["views"]["casual"]["en"])
        self.assertNotIn("0%", json.dumps(recap))

    def test_fan_recap_has_plain_correction_without_internal_ids_or_model_jargon(self):
        snapshot, provenance = self.corrected()
        recap = build_recap(snapshot, provenance, self.receipts)
        for language in ("en", "es"):
            text = recap["views"]["casual"][language]
            self.assertLessEqual(len(text.split()), 65)
            self.assertIn("Harbor Owls 0, Meadow Foxes 1", text)
            self.assertIn("2/3", text)
            self.assertNotRegex(text, r"\be\d{3}\b|proxy|candidate|receipt|recorded selection|selección registrada")
        self.assertIn("e010", recap["views"]["analyst"]["en"])
        self.assertEqual(recap["recorded_moment_count"], 1)
        self.assertEqual(recap["withdrawn_claims"][0]["event_id"], "e010")

    def test_pressure_is_a_current_window_proxy_only(self):
        snapshot, provenance = self.corrected()
        recap = build_recap(snapshot, provenance)
        self.assertEqual([pattern["team_id"] for pattern in recap["facts"]["pressure_proxies"]], ["meadow"])
        text = recap["views"]["analyst"]["en"]
        self.assertIn("Activity proxy", text)
        self.assertIn("No tactical cause inferred", text)

    def test_verified_history_withdraws_goal_and_preserves_revised_shot(self):
        snapshot, provenance = self.corrected()
        recap = build_recap(snapshot, provenance)
        self.assertEqual(recap["withdrawn_claims"][0]["event_id"], "e010")
        self.assertEqual(recap["corrected_moments"][0]["current_revision"], 2)
        self.assertEqual(recap["corrected_moments"][0]["changed_fields"], ["goal"])
        self.assertIn("Goal claims withdrawn", recap["views"]["analyst"]["en"])
        self.assertIn("A recorded goal was removed", recap["views"]["casual"]["en"])
        self.assertEqual(recap["facts"]["event_revisions"]["e010"], 2)

    def test_revision_alone_does_not_invent_prior_goal_claim(self):
        snapshot, provenance = self.corrected()
        del provenance["corrections"]
        recap = build_recap(snapshot, provenance)
        self.assertEqual(recap["withdrawn_claims"], [])
        self.assertFalse(recap["corrected_moments"][0]["history_verified"])
        self.assertNotIn("Goal claims withdrawn", recap["views"]["casual"]["en"])

    def test_missing_provenance_reports_unknown_revisions(self):
        recap = build_recap(snapshot_at(self.events, 50_000))
        self.assertTrue(all(value is None for value in recap["facts"]["event_revisions"].values()))
        self.assertEqual(recap["corrected_moments"], [])

    def test_inconsistent_history_or_source_is_rejected(self):
        snapshot, provenance = self.corrected()
        for mutate in (lambda p: p["corrections"][0].update(source_id="other_source"),
                       lambda p: p["corrections"][0].update(to_revision=3),
                       lambda p: p["corrections"][0]["after"].update(goal=True),
                       lambda p: p["event_revisions"].update(e010=3)):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(provenance); mutate(changed)
                with self.assertRaises(ValueError): build_recap(snapshot, changed)

    def test_duplicate_corrections_do_not_duplicate_moments(self):
        snapshot, provenance = self.corrected()
        expected = build_recap(snapshot, provenance)
        provenance["corrections"] *= 2
        self.assertEqual(build_recap(snapshot, provenance), expected)

    def test_same_correction_id_different_payload_is_rejected(self):
        snapshot, provenance = self.corrected()
        changed = copy.deepcopy(provenance["corrections"][0]); changed["before"]["goal"] = False
        provenance["corrections"].append(changed)
        with self.assertRaises(ValueError): build_recap(snapshot, provenance)

    def test_tampered_snapshot_statistics_or_digest_are_rejected(self):
        original = json.loads(json.dumps(snapshot_at(self.events, 50_000)))
        for mutate in (lambda s: s["stats"]["total"]["teams"]["harbor"].update(goals=99),
                       lambda s: s.update(state_digest="0" * 64),
                       lambda s: s.update(extra="unsupported")):
            changed = copy.deepcopy(original); mutate(changed)
            with self.assertRaises(ValueError): build_recap(changed)

    def test_current_provenance_must_match_visible_evidence(self):
        snapshot, provenance = self.corrected()
        for mutate in (lambda p: p["event_revisions"].update(future=1),
                       lambda p: p["event_revisions"].update(e010=True),
                       lambda p: p["event_revisions"].update(meta=2),
                       lambda p: p["evidence_records"][1].update(success=False),
                       lambda p: p.update(evidence_ids=[{}])):
            changed = copy.deepcopy(provenance); mutate(changed)
            with self.assertRaises(ValueError): build_recap(snapshot, changed)

    def test_restored_goal_is_not_still_labelled_withdrawn(self):
        state = OverlayState(self.events, through_ms=50_000, clock=lambda: 1_000)
        original = copy.deepcopy(next(event for event in self.events if event["id"] == "e010"))
        saved = {**original, "goal": False}
        state.correct({"correction_id": "saved", "target_event_id": "e010", "expected_revision": 1, "replacement": saved})
        state.correct({"correction_id": "restored", "target_event_id": "e010", "expected_revision": 2, "replacement": original})
        envelope = state.view()
        provenance = envelope["provenance"]
        provenance["corrections"] = [
            {"correction_id": "restored", "target_event_id": "e010", "from_revision": 2, "to_revision": 3, "before": saved, "after": original},
            {"correction_id": "saved", "target_event_id": "e010", "from_revision": 1, "to_revision": 2, "before": original, "after": saved},
        ]
        recap = build_recap(envelope["snapshot"], provenance)
        self.assertEqual(recap["withdrawn_claims"], [])
        self.assertEqual(recap["facts"]["teams"][0]["totals"]["goals"], 1)
        self.assertEqual(recap["corrected_moments"][0]["current_revision"], 3)

    def test_prior_future_goal_does_not_leak_as_a_withdrawn_current_claim(self):
        baseline = copy.deepcopy(self.events)
        event = next(event for event in baseline if event["id"] == "e010")
        event["at_ms"] = 80_000
        before = copy.deepcopy(event)
        replacement = {**event, "at_ms": 50_000, "goal": False}
        state = OverlayState(baseline, through_ms=50_000, clock=lambda: 1_000)
        state.correct({"correction_id": "future_review", "target_event_id": "e010", "expected_revision": 1, "replacement": replacement})
        envelope = state.view()
        provenance = envelope["provenance"]
        provenance["corrections"] = [{"correction_id": "future_review", "target_event_id": "e010", "from_revision": 1,
                                      "to_revision": 2, "before": before, "after": replacement}]
        recap = build_recap(envelope["snapshot"], provenance)
        self.assertEqual(recap["withdrawn_claims"], [])
        self.assertNotIn("80000", json.dumps(recap))

    def test_intermediate_goal_claim_is_withdrawn_when_final_returns_to_non_goal(self):
        baseline = copy.deepcopy(self.events)
        original = next(event for event in baseline if event["id"] == "e010")
        original["goal"] = False
        saved = copy.deepcopy(original)
        goal = {**saved, "goal": True}
        state = OverlayState(baseline, through_ms=50_000, clock=lambda: 1_000)
        state.correct({"correction_id": "goal_added", "target_event_id": "e010", "expected_revision": 1, "replacement": goal})
        state.correct({"correction_id": "goal_withdrawn", "target_event_id": "e010", "expected_revision": 2, "replacement": saved})
        envelope = state.view()
        provenance = envelope["provenance"]
        provenance["corrections"] = [
            {"correction_id": "goal_added", "target_event_id": "e010", "from_revision": 1, "to_revision": 2, "before": saved, "after": goal},
            {"correction_id": "goal_withdrawn", "target_event_id": "e010", "from_revision": 2, "to_revision": 3, "before": goal, "after": saved},
        ]
        recap = build_recap(envelope["snapshot"], provenance)
        self.assertEqual(recap["withdrawn_claims"][0]["from_revision"], 2)
        self.assertEqual(recap["corrected_moments"][0]["changed_fields"], ["goal"])
        self.assertEqual(recap["corrected_moments"][0]["net_changed_fields"], [])

    def test_exact_actual_recorded_receipts_normalize_as_history_only(self):
        for item in self.receipts:
            normalized = normalize_recorded_receipt(**item)
            self.assertTrue(normalized["historical_only"])
            self.assertEqual(normalized["selection"]["evidence_ids"], ["e008", "e010"])
            self.assertEqual(normalized["snapshot"]["upto_ms"], 50_000)

    def test_recorded_hash_change_timeout_or_fake_receipt_is_rejected(self):
        item = self.receipts[0]
        for receipt_id, payload in ((item["receipt_id"], item["receipt_bytes"] + b" "),
                                    ("m2-first-real-selection.json", item["receipt_bytes"]),
                                    ("fake.json", item["receipt_bytes"]),
                                    ({}, item["receipt_bytes"])):
            with self.subTest(receipt_id=receipt_id), self.assertRaises(ValueError):
                normalize_recorded_receipt(receipt_id, payload)

    def test_two_accepted_receipts_are_one_distinct_recorded_moment(self):
        recap = build_recap(snapshot_at(self.events, 50_000), recorded_selections=self.receipts)
        self.assertEqual(recap["recorded_receipt_count"], 2)
        self.assertEqual(recap["recorded_moment_count"], 1)
        self.assertEqual(len(recap["recorded_selections"][0]["receipt_ids"]), 2)
        self.assertTrue(recap["recorded_selections"][0]["historical_only"])
        self.assertIn("historical evidence only", recap["views"]["analyst"]["en"])

    def test_duplicate_reordered_receipts_produce_identical_recap(self):
        snapshot, provenance = self.corrected()
        expected = build_recap(snapshot, provenance, self.receipts)
        actual = build_recap(snapshot, provenance, list(reversed(self.receipts)) * 2)
        self.assertEqual(actual, expected)

    def test_historical_future_receipt_does_not_leak_future_facts(self):
        recap = build_recap(snapshot_at(self.events, 0), recorded_selections=self.receipts)
        self.assertEqual(recap["recorded_selections"], [])
        self.assertEqual(recap["withheld_recorded_receipt_count"], 2)
        serialized = json.dumps(recap)
        for future_id in ("e008", "e010", "50000", "shot_volume"):
            self.assertNotIn(future_id, serialized)
        self.assertEqual(recap["evidence_ids"], ["meta"])

    def test_goal_correction_does_not_falsely_withdraw_two_shot_pattern(self):
        snapshot, provenance = self.corrected(50_000)
        recap = build_recap(snapshot, provenance, self.receipts)
        moment = recap["recorded_selections"][0]
        self.assertEqual(moment["changed_evidence_ids"], ["e010"])
        self.assertEqual(moment["state_relation"], "superseded_state")
        self.assertTrue(moment["claim_supported_after_corrections"])
        self.assertEqual(moment["window_relation"], "within_current_window")
        self.assertEqual(recap["withdrawn_recorded_claims"], [])

    def test_expired_window_is_distinct_from_contradicted_historical_claim(self):
        snapshot, provenance = self.corrected()
        moment = build_recap(snapshot, provenance, self.receipts)["recorded_selections"][0]
        self.assertEqual(moment["window_relation"], "outside_current_window")
        self.assertTrue(moment["claim_supported_after_corrections"])

    def test_replacing_a_shot_really_invalidates_original_shot_volume_claim(self):
        state = OverlayState(self.events, through_ms=50_000, clock=lambda: 1_000)
        replacement = {"id": "e008", "type": "pass", "at_ms": 40_000,
                       "team_id": "harbor", "player_id": "harbor_9", "success": True}
        state.correct({"correction_id": "not_a_shot", "target_event_id": "e008",
                       "expected_revision": 1, "replacement": replacement})
        current = state.view()
        recap = build_recap(current["snapshot"], current["provenance"], self.receipts)
        self.assertFalse(recap["recorded_selections"][0]["claim_supported_after_corrections"])
        self.assertEqual(recap["withdrawn_claims"], [])
        self.assertEqual(recap["recorded_selections"][0]["claim_status"], "withdrawn_after_correction")
        self.assertEqual(len(recap["withdrawn_recorded_claims"]), 1)
        self.assertIn("no longer supported", recap["views"]["analyst"]["en"])

    def test_inputs_and_detached_output_do_not_mutate_authoritative_state(self):
        snapshot, provenance = self.corrected()
        before = copy.deepcopy((snapshot, provenance))
        recap = build_recap(snapshot, provenance, self.receipts)
        recap["facts"]["teams"][0]["totals"]["goals"] = 99
        self.assertEqual((snapshot, provenance), before)
        self.assertEqual(build_recap(snapshot, provenance)["facts"]["teams"][0]["totals"]["goals"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
