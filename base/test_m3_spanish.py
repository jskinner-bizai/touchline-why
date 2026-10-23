"""Bounded English/Spanish templates retain exact facts across audiences."""
import copy
import importlib.util
from pathlib import Path
import unittest

from touchline_core import load_events, replay, render_overlay

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("core_before_spanish_review", ROOT / "touchline_core.before.py")
before = importlib.util.module_from_spec(spec)
spec.loader.exec_module(before)


def choice(candidate):
    return {key: copy.deepcopy(candidate[key]) for key in ("candidate_id", "explanation_type", "evidence_ids")}


class SpanishTemplateReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = load_events(ROOT / "synthetic_match.jsonl")
        cls.snapshots = replay(cls.events)
        cls.pattern = next(snapshot for snapshot in cls.snapshots if snapshot["upto_ms"] == 50000)

    def test_entire_fixture_state_and_english_card_facts_are_identical(self):
        self.assertEqual(self.snapshots, before.replay(self.events))
        for snapshot in self.snapshots:
            for selected in [None] + [choice(candidate) for candidate in snapshot["candidates"]]:
                for audience in ("casual", "analyst"):
                    current = render_overlay(snapshot, selected, audience, "en")
                    old = before.render_overlay(snapshot, selected, audience, "en")
                    self.assertEqual({k: v for k, v in current.items() if k != "text"}, {k: v for k, v in old.items() if k != "text"})

    def test_spanish_only_changes_display_text_preserving_all_facts_and_ids(self):
        for snapshot in self.snapshots:
            for selected in [None] + [choice(candidate) for candidate in snapshot["candidates"]]:
                for audience in ("casual", "analyst"):
                    current = render_overlay(snapshot, selected, audience, "es")
                    old = before.render_overlay(snapshot, selected, audience, "es")
                    self.assertEqual({k: v for k, v in current.items() if k != "text"}, {k: v for k, v in old.items() if k != "text"})
                    if audience == "casual":
                        self.assertLessEqual(len(current["text"].split()), 35)

    def test_pressure_singular_and_causal_qualification(self):
        candidate = next(c for c in self.pattern["candidates"] if c["explanation_type"] == "pressure_activity")
        text = render_overlay(self.pattern, choice(candidate), audience="analyst", language="es")["text"]
        self.assertIn("3 acciones de presión", text)
        self.assertIn("1 recuperación del balón", text)
        self.assertIn("no demuestra que la presión causara las recuperaciones", text)
        self.assertIn("50s", text)
        self.assertNotIn("60s", text)

    def test_shot_template_keeps_xg_and_causal_exclusion(self):
        candidate = next(c for c in self.pattern["candidates"] if c["explanation_type"] == "shot_volume")
        card = render_overlay(self.pattern, choice(candidate), audience="analyst", language="es")
        self.assertIn("2 tiros, 2 a puerta", card["text"])
        self.assertIn("sin xG ni afirmación causal", card["text"])

    def test_fallback_and_zero_denominators_have_clear_spanish_meaning(self):
        card = render_overlay(self.snapshots[0], audience="analyst", language="es")
        self.assertIn("Partido sintético; sin selección válida del modelo", card["text"])
        self.assertIn("no disponible (0 intentos)", card["text"])
        self.assertIn("no disponible (0 tiros)", card["text"])
        self.assertNotIn("0/0", card["text"])

    def test_fan_cards_are_brief_without_debugging_or_causal_qualifiers(self):
        for language in ("en", "es"):
            for selected in [None] + [choice(c) for c in self.pattern["candidates"]]:
                card = render_overlay(self.pattern, selected, "casual", language)
                self.assertLessEqual(len(card["text"].split()), 25)
                self.assertNotRegex(card["text"], r"\be\d{3}\b|proxy|xG|causal|candidate|Window|Ventana")

    def test_audience_changes_only_display_not_numeric_or_evidence_payload(self):
        for snapshot in self.snapshots:
            for language in ("en", "es"):
                for selected in [None] + [choice(c) for c in snapshot["candidates"]]:
                    casual = render_overlay(snapshot, selected, "casual", language)
                    analyst = render_overlay(snapshot, selected, "analyst", language)
                    self.assertEqual({k: v for k, v in casual.items() if k not in {"text", "audience"}},
                                     {k: v for k, v in analyst.items() if k not in {"text", "audience"}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
