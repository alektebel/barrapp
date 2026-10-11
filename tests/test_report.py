"""The written report (server/report.py): prose from a model, held to the
measurement by a sentinel.

In production the report never used a model - DEEPSEEK_API_KEY was empty - and
every phone got the same English fallback. Now the report goes through
nan.builders (deepseek-v4-flash, then qwen3.8-flash), in Spanish, and a reply
is only used if it keeps the rules the old prompt only asked for:
  * it is the JSON object with headline / narrative / nextSession;
  * every number in the headline and narrative exists in the measurement - a
    model that writes "12 reps" for a set of 3 is not used, whatever its prose.
Anything else falls back to the deterministic text, and says why.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]

import llm  # noqa: E402
import report  # noqa: E402


def payload(**kw):
    p = {
        "exercise": "pull_up", "n_reps": 3, "n_candidates": 3,
        "sessionScore": 56, "sessionBand": "solid", "duration_s": 13.4, "fps": 30.0,
        "blockers": [], "sessions": [],
        "reps": [{"label": f"r{i}", "score": s, "band": "solid", "plausible": True,
                  "startS": 1.0 + 3 * i, "turnS": 2.0 + 3 * i, "endS": 3.5 + 3 * i,
                  "metrics": [{"key": "total_s", "name": "Total", "value": "2.5 s", "class": "INVARIANT"}],
                  "trace": [0.1] * 48}
                 for i, s in ((1, 52), (2, 56), (3, 61))],
    }
    p.update(kw)
    return p


def answer(**kw):
    body = {"headline": "3 dominadas verificadas, sólidas",
            "narrative": "Hiciste 3 repeticiones en 13.4 s; la mejor puntuó 61.",
            "nextSession": "Graba cinco o seis repeticiones con la cámara fija."}
    body.update(kw)
    return llm.ChatResult(model="deepseek-v4-flash", text=json.dumps(body, ensure_ascii=False))


class UsesTheModel(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(llm, "config", return_value=("https://nan.test/v1", "k"))
        p.start()
        self.addCleanup(p.stop)

    def test_a_faithful_reply_is_used(self):
        with mock.patch.object(llm, "complete", return_value=answer()) as c:
            out = report.write_report(payload())
        self.assertEqual(out["headline"], "3 dominadas verificadas, sólidas")
        self.assertEqual(out["proseSource"], "llm:deepseek-v4-flash")
        self.assertEqual(c.call_args.args[0], report.REPORT_MODEL)

    def test_an_invented_number_is_rejected(self):
        bad = answer(narrative="Hiciste 12 repeticiones perfectas.")
        with mock.patch.object(llm, "complete", return_value=bad):
            out = report.write_report(payload())
        self.assertEqual(out["proseSource"], "fallback")
        self.assertIn("invented_number: 12", out["proseRejected"])

    def test_numbers_are_matched_at_their_written_precision(self):
        # 13.4 s written as "13 s" or "13,4 s" is the same measurement.
        for text in ("Duró 13 s.", "Duró 13,4 s.", "Puntuación media 56."):
            with mock.patch.object(llm, "complete", return_value=answer(narrative=text)):
                self.assertEqual(report.write_report(payload())["proseSource"],
                                 "llm:deepseek-v4-flash", text)

    def test_next_session_advice_may_carry_its_own_numbers(self):
        reply = answer(nextSession="Haz 5 o 6 repeticiones en 2 series.")
        with mock.patch.object(llm, "complete", return_value=reply):
            self.assertEqual(report.write_report(payload())["proseSource"], "llm:deepseek-v4-flash")

    def test_the_backup_model_answers_when_the_first_fails(self):
        failed = llm.ChatResult(model=report.REPORT_MODEL, error="401 no access", status=401)
        backup = answer()
        backup = llm.ChatResult(model=report.BACKUP_MODEL, text=backup.text)
        with mock.patch.object(llm, "complete", side_effect=[failed, backup]) as c:
            out = report.write_report(payload())
        self.assertEqual([call.args[0] for call in c.call_args_list],
                         [report.REPORT_MODEL, report.BACKUP_MODEL])
        self.assertEqual(out["proseSource"], f"llm:{report.BACKUP_MODEL}")

    def test_malformed_or_incomplete_replies_fall_back(self):
        for text in ("not json", json.dumps({"headline": "x"})):
            reply = llm.ChatResult(model="m", text=text)
            with mock.patch.object(llm, "complete", return_value=reply):
                out = report.write_report(payload())
            self.assertEqual(out["proseSource"], "fallback", text)

    def test_the_model_sees_a_digest_not_the_raw_series(self):
        with mock.patch.object(llm, "complete", return_value=answer()) as c:
            report.write_report(payload())
        sent = c.call_args.args[1][-1]["content"]
        self.assertNotIn('"trace"', sent)
        self.assertIn('"n_reps": 3', sent)
        self.assertLess(len(sent), 4000)

    def test_the_prompt_is_spanish_and_keeps_the_rules(self):
        self.assertIn("español", report.SYSTEM)
        self.assertIn("Nunca inventes", report.SYSTEM)


class FallsBack(unittest.TestCase):
    def test_unconfigured_uses_the_deterministic_text(self):
        with mock.patch.object(llm, "config", return_value=None):
            out = report.write_report(payload())
        self.assertEqual(out["proseSource"], "fallback")
        self.assertEqual(out["proseRejected"], "not_configured")
        for k in ("headline", "narrative", "nextSession"):
            self.assertTrue(out[k])

    def test_the_old_writer_is_gone(self):
        self.assertFalse((ROOT / "server" / "deepseek.py").exists())
        self.assertNotIn("DEEPSEEK", (ROOT / "server" / "template.yaml").read_text())
        self.assertIn("from report import write_report", (ROOT / "server" / "process.py").read_text())


if __name__ == "__main__":
    unittest.main()
