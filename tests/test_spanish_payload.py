"""The catalog wired in: what leaves the server is Spanish.

  * process_job returns a localized payload, with `i18n` saying what (if
    anything) the catalog did not know, and the payload sentinel reports it;
  * the vision note no longer overwrites the report's headline - on 2026-10-11
    a real job's headline was the vision model's English paragraph about
    stills - it is kept beside it as `visionNote`;
  * a movement the pipeline cannot measure is a Spanish sentence, never the
    SystemExit text with the list of known movements;
  * worker stages carry a stable `stageCode` and Spanish `stageText` beside the
    English `stage` the installed app still matches on;
  * the report's digest speaks Spanish too, so the model does not echo "solid".
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]
for k, v in {"JOBS_TABLE": "t-jobs", "FEEDBACK_TABLE": "t-fb", "REFERRALS_TABLE": "t-ref",
             "UPLOADS_TABLE": "t-up", "VIDEO_BUCKET": "t-bucket", "AWS_DEFAULT_REGION": "eu-west-1"}.items():
    os.environ.setdefault(k, v)

import process  # noqa: E402
from barra import contracts, i18n  # noqa: E402


def measured():
    return {
        "exercise": "pull_up", "detected": {"label": "Pull-up", "reason": "hanging from a fixed bar, and the shoulders never rise above the hands (peak -0.2 torso-lengths)"},
        "n_reps": 0, "n_candidates": 0, "reps": [], "sessions": [], "fps": 30.0, "duration_s": 10.0,
        "trim": None, "session": "2026-10-11", "sessionScore": None, "sessionBand": "unmeasured",
        "measurementVersion": 2, "blockers": ["no turnaround stood out from the noise"],
    }


class ProcessJob(unittest.TestCase):
    def run_job(self, note=None):
        art = mock.Mock(clip=None, stills=["s1.jpg"])
        art.as_trace_data.return_value = {}
        with mock.patch.object(process, "analyze_clip", return_value=measured()), \
                mock.patch.object(process, "technique_artifacts", return_value=art), \
                mock.patch.object(process, "technique_note", return_value=note), \
                mock.patch.object(process, "technique_second_opinion", return_value="clean"), \
                mock.patch.object(process, "_write_trace"):
            return process.process_job({"id": "j1", "exercise": "auto"}, Path("/tmp/x.mp4"))

    def test_the_payload_leaves_in_spanish(self):
        out = self.run_job()
        self.assertEqual(out["blockers"], ["Ningún cambio de dirección destacó sobre el ruido"])
        self.assertEqual(out["detected"]["label"], "Dominada")
        self.assertEqual(out["i18n"]["locale"], "es")
        self.assertEqual(out["i18n"]["untranslated"], [])

    # "pending" is what the phone sees when a prose model is configured;
    # without a key the prose is final at once. Pin the key so the test does
    # not depend on the shell it runs in.
    @mock.patch.dict(os.environ, {"NAN_API_KEY": "test-key"})
    def test_the_vision_note_does_not_take_the_headline(self):
        note = {"headline": "The stills show a floor push-up", "narrative": "English paragraph.",
                "nextSession": "Film more.", "visionObservations": [{"rep": "r1"}]}
        out = self.run_job(note)
        # The deterministic Spanish prose stands; the note is advisory.
        self.assertEqual(out["headline"], "Ningún ejercicio que barra pueda medir")
        self.assertEqual(out["proseSource"], "fallback")
        self.assertEqual(out["proseStatus"], "pending")
        self.assertEqual(out["visionNote"]["headline"], "The stills show a floor push-up")
        self.assertEqual(out["visionObservations"], [{"rep": "r1"}])



class Defaults(unittest.TestCase):
    def test_every_literal_next_session_in_process_is_spanish(self):
        """Caught by the strict sentinel on a real clip (2026-10-11): the
        default nextSession was English, and reached the phone whenever the
        report model did not answer."""
        import ast
        tree = ast.parse((ROOT / "server" / "process.py").read_text())
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "nextSession" \
                            and isinstance(v, ast.Constant) and isinstance(v.value, str):
                        found.append(v.value)
        self.assertGreaterEqual(len(found), 2)
        for text in found:
            self.assertEqual(i18n.english_words(text), [], text)


class Unsupported(unittest.TestCase):
    def test_an_unmeasurable_movement_is_a_spanish_sentence(self):
        out = process._unsupported("deadlift", {"exercise": "deadlift", "label": "deadlift"})
        es = i18n.localize_payload({**out, "headline": "h", "narrative": "n", "nextSession": "s"})
        self.assertEqual(out["blockers"], ["movement_unsupported:deadlift"])
        self.assertIn("peso muerto", es["blockers"][0])
        self.assertNotIn("Known", es["blockers"][0])
        self.assertEqual(es["i18n"]["untranslated"], [])

    def test_an_unconfirmed_exercise_is_a_spanish_sentence(self):
        out = process._empty("auto", ["movement_unconfirmed"])
        es = i18n.localize_payload({**out, "headline": "h", "narrative": "n", "nextSession": "s"})
        self.assertIn("confirmar qué ejercicio", es["blockers"][0])
        self.assertIn("no lo hemos puntuado", es["blockers"][0])
        self.assertEqual(es["i18n"]["untranslated"], [])

    def test_the_source_no_longer_returns_the_raw_exit_text(self):
        self.assertNotIn("_empty(chosen, [str(exc)]", (ROOT / "server" / "process.py").read_text())


class Contract(unittest.TestCase):
    def test_untranslated_text_is_a_violation(self):
        p = {k: None for k in contracts.REQUIRED}
        p.update(measured(), headline="h", narrative="n", nextSession="s",
                 i18n={"locale": "es", "untranslated": ["a brand new reason"]})
        rules = {v.rule for v in contracts.check_payload(p)}
        self.assertIn("untranslated_text", rules)


class Stages(unittest.TestCase):
    def test_a_stage_update_writes_code_and_spanish_text(self):
        import handler
        table = mock.Mock()
        with mock.patch.object(handler, "table", table), mock.patch.object(handler.uploads, "record"):
            handler._set_stage("j1", "o1", "recognising the movement")
        kw = table.update_item.call_args.kwargs
        values = kw["ExpressionAttributeValues"]
        self.assertEqual(values[":st"], "recognising the movement")  # the installed app matches on it
        self.assertEqual(values[":sc"], "stage.recognising")
        self.assertEqual(values[":sx"], "Reconociendo el movimiento")

    def test_job_errors_are_stored_in_spanish(self):
        import handler
        self.assertEqual(i18n.english_words(handler._spanish_error("the clip never arrived in storage")), [])


class ReportDigest(unittest.TestCase):
    def test_band_and_movement_reach_the_model_in_spanish(self):
        import report
        d = report.digest({**measured(), "sessionBand": "solid", "sessionScore": 56})
        self.assertEqual(d["sessionBand"], "sólida")
        self.assertEqual(d["movement"], "Dominada")
        self.assertEqual(d["blockers"], ["ningún cambio de dirección destacó sobre el ruido"])


if __name__ == "__main__":
    unittest.main()
