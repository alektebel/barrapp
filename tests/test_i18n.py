"""Spanish at the edge (barra/i18n.py).

barra writes its reasons in English, and they stay English in the trace - that
is the developer's record. What the phone shows is translated once, when the
payload is built, through a catalog of templates: each English template has a
stable `code`, numbered holes ({n} a number, {x*} a fragment translated in
turn) and a Spanish template. What the catalog does not know is left as it is
and listed, so the sentinel can say "untranslated" and the catalog can grow
from what production actually says.

The fixture tests/fixtures/visible_text_prod.json is every distinct visible
string the production stack returned up to 2026-10-11; every one of them must
come out Spanish.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra import i18n  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "visible_text_prod.json").read_text())


class Translate(unittest.TestCase):
    def test_an_exact_message(self):
        t = i18n.translate("no turnaround stood out from the noise")
        self.assertEqual(t.code, "segment.no_turnaround")
        self.assertEqual(t.text, "ningún cambio de dirección destacó sobre el ruido")

    def test_numbers_are_carried_with_a_decimal_comma(self):
        t = i18n.translate("descent 1.45x the ascent - controlled")
        self.assertEqual(t.text, "bajada 1,45x la subida: controlada")
        self.assertEqual(t.params, {"r": "1.45"})

    def test_percent_and_negative_numbers(self):
        self.assertIn("66 %", i18n.translate(
            "hanging from something fixed, but 66% of the clip is spent within a fifth "
            "of a torso-length of one position - a hold, or resting between attempts, "
            "rather than a set of repetitions").text)
        self.assertIn("-0,3", i18n.translate(
            "hanging from a fixed bar, and the shoulders never rise above the hands "
            "(peak -0.3 torso-lengths)").text)

    def test_fragments_are_translated_in_turn(self):
        t = i18n.translate("the standard pass found nothing (no turnaround stood out from "
                           "the noise) — the relaxed pass validated by the movement's own "
                           "gradients counted 3 rep(s) the standard pass missed")
        self.assertNotIn("turnaround", t.text)
        self.assertIn("ningún cambio de dirección", t.text)
        self.assertIn("3", t.text)

    def test_a_trailing_full_stop_is_kept(self):
        self.assertTrue(i18n.translate("no turnaround stood out from the noise.").text.endswith("."))

    def test_the_session_note(self):
        self.assertEqual(i18n.translate("4 segmented, 2 usable — need 3 for a session median").text,
                         "4 detectadas, 2 útiles: hacen falta 3 para la mediana de una sesión")
        self.assertEqual(i18n.translate("5 segmented, 5 usable").text, "5 detectadas, 5 útiles")

    def test_unknown_text_is_not_guessed(self):
        self.assertIsNone(i18n.translate("something nobody wrote a template for"))

    def test_spanish_input_is_left_alone(self):
        self.assertIsNone(i18n.translate("ningún cambio de dirección destacó sobre el ruido"))


class Catalog(unittest.TestCase):
    def test_codes_are_unique(self):
        codes = [m.code for m in i18n.CATALOG]
        self.assertEqual(len(codes), len(set(codes)))

    def test_holes_match_between_languages(self):
        hole = re.compile(r"\{(\w+)\*?\}")
        for m in i18n.CATALOG:
            self.assertEqual(sorted(hole.findall(m.en)), sorted(hole.findall(m.es)), m.code)

    def test_no_spanish_template_reads_as_english(self):
        for m in i18n.CATALOG:
            plain = re.sub(r"\{\w+\*?\}", "", m.es)
            self.assertEqual(i18n.english_words(plain), [], m.code)


class ProductionText(unittest.TestCase):
    """Every visible string production returned must come out Spanish."""

    def test_every_field_of_the_fixture(self):
        untranslated = []
        for field, samples in FIXTURE.items():
            if field == "metric.value":
                continue
            for s in samples:
                out = i18n.localize_text(s)
                if i18n.english_words(out):
                    untranslated.append(f"{field}: {s!r} -> {out!r}")
        self.assertEqual(untranslated, [], "\n".join(untranslated))

    def test_metric_values_get_spanish_numbers_and_units(self):
        self.assertEqual(i18n.localize_value("0.33 s"), "0,33 s")
        self.assertEqual(i18n.localize_value("1.2 torso"), "1,2 torsos")
        self.assertEqual(i18n.localize_value("1.0 torso"), "1,0 torsos")
        self.assertEqual(i18n.localize_value("1.45 x"), "1,45 x")


class Payload(unittest.TestCase):
    def payload(self):
        return {
            "headline": "3 dominadas", "narrative": "Bien.", "nextSession": "Graba otra.",
            "blockers": ["no turnaround stood out from the noise"],
            "detected": {"label": "Pull-up", "reason": "hanging from a fixed bar, and the shoulders finish 0.4 torso-lengths above the hands"},
            "reps": [{
                "problems": ["rep starts 0.2 torso ABOVE the bar, so the detected start is not a hang"],
                "scoreNote": "This rep could not be measured - the pose estimate is not physically possible.",
                "metrics": [{"key": "total_s", "name": "Rep duration", "value": "2.50 s", "class": "INVARIANT"}],
                "transition_s": "0.33 s", "total_s": "2.50 s",
                "components": [{"name": "range", "why": "hang 95% of full, lockout 90% of full"}],
                "aside": [{"name": "swing", "why": "body travel relative to the bar - needs a consistent camera side, so it is not part of the score"}],
                "penalties": [{"name": "control", "why": "descent 0.8x the ascent, under the 1.2x that counts as controlled"}],
                "faults": [{"name": "dead_hang"}],
            }],
            "sessions": [{"note": "trimmed to the active spans"}],
        }

    def test_visible_fields_are_spanish_and_keys_are_not_touched(self):
        out = i18n.localize_payload(self.payload())
        rep = out["reps"][0]
        self.assertEqual(out["blockers"], ["Ningún cambio de dirección destacó sobre el ruido"])
        self.assertEqual(out["detected"]["label"], "Dominada")
        self.assertNotIn("hanging", out["detected"]["reason"])
        self.assertEqual(rep["metrics"][0]["name"], "Duración de la rep")
        self.assertEqual(rep["metrics"][0]["key"], "total_s")
        self.assertEqual(rep["metrics"][0]["value"], "2,50 s")
        self.assertEqual(rep["total_s"], "2,50 s")
        # Component names are keys the app matches on (Cues.kt): kept, labelled.
        self.assertEqual(rep["components"][0]["name"], "range")
        self.assertEqual(rep["components"][0]["label"], "recorrido")
        self.assertEqual(rep["aside"][0]["name"], "swing")
        self.assertEqual(rep["penalties"][0]["name"], "control")
        self.assertEqual(rep["faults"][0]["name"], "dead_hang")
        self.assertNotIn("hang", rep["components"][0]["why"])
        self.assertEqual(out["i18n"], {"locale": "es", "untranslated": []})

    def test_unknown_text_is_listed_not_dropped(self):
        p = self.payload()
        p["blockers"].append("a brand new reason")
        out = i18n.localize_payload(p)
        self.assertIn("a brand new reason", out["blockers"])
        self.assertEqual(out["i18n"]["untranslated"], ["a brand new reason"])

    def test_it_does_not_mutate_its_input(self):
        p = self.payload()
        i18n.localize_payload(p)
        self.assertEqual(p["blockers"], ["no turnaround stood out from the noise"])

    def test_running_twice_changes_nothing(self):
        once = i18n.localize_payload(self.payload())
        self.assertEqual(i18n.localize_payload(once), once)


class StagesAndErrors(unittest.TestCase):
    def test_every_worker_stage_has_a_code_and_spanish_text(self):
        for stage in ("receiving the clip", "locating the exercise", "opening the clip",
                      "estimating the pose", "recognising the movement", "finding the reps",
                      "trying the relaxed pass", "counting from the frames", "scoring the reps",
                      "measuring the hold"):
            code, text = i18n.stage(stage)
            self.assertTrue(code.startswith("stage."), stage)
            self.assertEqual(i18n.english_words(text), [], stage)

    def test_job_errors_are_spanish(self):
        for err in ("the clip was never finished uploading. Retry. (stuck for 44 min)",
                    "the worker never picked this up. Retry. (stuck for 151 min)",
                    "the clip never arrived in storage"):
            self.assertEqual(i18n.english_words(i18n.localize_text(err)), [], err)


if __name__ == "__main__":
    unittest.main()
