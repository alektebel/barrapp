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

Since the prose moved off the result's critical path (docs/SPEED-PLAN.md B),
`write_prose` is the deferred half of the same judgement: it returns the
judged prose for `process.finish_prose` to apply, or why it was not used.
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


def fired(*names_ids):
    return {"faults": [{"name": n, "errorId": i, "value": 1.0} for n, i in names_ids]}


class OnlyMeasuredFaults(unittest.TestCase):
    """Audit finding 1: a text with no numbers used to pass whatever errors it
    attributed to the athlete."""

    INVENTED = answer(headline="Tienes valgo de rodilla",
                      narrative="Se te hunde la cadera y pierdes el control escapular.")

    def setUp(self):
        p = mock.patch.object(llm, "config", return_value=("https://nan.test/v1", "k"))
        p.start()
        self.addCleanup(p.stop)

    def test_every_rule_name_has_a_claim_vocabulary(self):
        from barra.rules import RULES
        names = {r.name for rules in RULES.values() for r in rules}
        self.assertEqual(sorted(names - set(report.FAULT_CLAIMS)), [])

    def test_faults_with_no_reps_are_rejected(self):
        facts = report.digest(payload(reps=[], n_reps=0, n_candidates=0))
        self.assertEqual(facts["faults"], [])
        prose, why = report._judge(self.INVENTED, facts)
        self.assertIsNone(prose)
        self.assertIn("unsupported_fault", why)
        self.assertIn("Rodillas hacia dentro", why)
        self.assertIn("Cadera hundida", why)
        self.assertIn("Retracción escapular", why)

    def test_unmeasured_faults_fall_back_to_the_deterministic_text(self):
        with mock.patch.object(llm, "complete", return_value=self.INVENTED):
            out = report.write_report(payload())
        self.assertEqual(out["proseSource"], "fallback")
        self.assertIn("unsupported_fault", out["proseRejected"])
        text = out["headline"] + " " + out["narrative"]
        self.assertEqual(report.unsupported_faults(text, report.digest(payload())), [])

    def test_a_clean_set_may_not_name_a_fault_even_by_negation_or_synonym(self):
        facts = report.digest(payload())
        for text in ("Notamos balanceo en la subida.", "Las rodillas se van hacia dentro.",
                     "Levantas los talones al bajar.", "Bloqueo incompleto arriba."):
            self.assertTrue(report.unsupported_faults(text, facts), text)

    def test_a_text_naming_only_measured_faults_passes(self):
        reps = payload()["reps"]
        reps[0].update(fired(("momentum", "pull_up.body_swing")))
        p = payload(reps=reps)
        facts = report.digest(p)
        self.assertEqual(facts["faults"], [{"id": "pull_up.body_swing", "name": "Balanceo"}])
        reply = answer(narrative="Hiciste 3 repeticiones; en la primera hay balanceo del cuerpo.")
        prose, why = report._judge(reply, facts)
        self.assertEqual(why, "")
        self.assertIn("balanceo", prose["narrative"])
        # ... but a second, unmeasured fault in the same text still sinks it.
        worse = answer(narrative="Hay balanceo y además rodillas hacia dentro.")
        self.assertIn("Rodillas hacia dentro", report._judge(worse, facts)[1])

    def test_neutral_words_are_not_fault_claims(self):
        facts = report.digest(payload())
        text = "Lo más flojo fue el recorrido, al 80 %; la mejor puntuó 61 y el control fue bueno."
        self.assertEqual(report.unsupported_faults(text, facts), [])

    def test_the_digest_lists_faults_by_rule_id_beyond_the_rep_cap(self):
        reps = [{"label": f"r{i}", "score": 50, "band": "solid", "metrics": []} for i in range(40)]
        reps[35].update(fired(("knee valgus", "squat.knee_medial_drift")))
        facts = report.digest(payload(reps=reps, n_reps=40, n_candidates=40))
        self.assertEqual(facts["faults"], [{"id": "squat.knee_medial_drift", "name": "Rodillas hacia dentro"}])


class FinishProse(unittest.TestCase):
    """The deferred pass: the model path taken off the result's critical path
    (docs/SPEED-PLAN.md B), with the same judgement as `write_report`."""

    def test_a_faithful_reply_is_the_prose(self):
        with mock.patch.object(llm, "config", return_value=("https://nan.test/v1", "k")), \
                mock.patch.object(llm, "complete", return_value=answer()) as c:
            out = report.write_prose(payload())
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["prose"]["headline"], "3 dominadas verificadas, sólidas")
        self.assertEqual(out["prose"]["nextSession"],
                         "Graba cinco o seis repeticiones con la cámara fija.")
        self.assertEqual(c.call_args.args[0], report.REPORT_MODEL)

    def test_an_invented_number_is_not_the_prose(self):
        with mock.patch.object(llm, "config", return_value=("https://nan.test/v1", "k")), \
                mock.patch.object(llm, "complete",
                                  return_value=answer(narrative="Hiciste 12 repeticiones perfectas.")):
            out = report.write_prose(payload())
        self.assertEqual(out["status"], "fallback")
        self.assertIn("invented_number", out["reason"])
        self.assertNotIn("prose", out)

    def test_a_failed_call_is_failed(self):
        reply = llm.ChatResult(model=report.REPORT_MODEL, error="401 no access", status=401)
        with mock.patch.object(llm, "config", return_value=("https://nan.test/v1", "k")), \
                mock.patch.object(llm, "complete", side_effect=[reply, reply]) as c:
            out = report.write_prose(payload())
        self.assertEqual(out["status"], "failed")
        self.assertIn("401", out["reason"])
        self.assertEqual([call.args[0] for call in c.call_args_list],
                         [report.REPORT_MODEL, report.BACKUP_MODEL])

    def test_unconfigured_is_never_pending(self):
        with mock.patch.object(llm, "config", return_value=None):
            out = report.write_prose(payload())
        self.assertEqual(out["status"], "fallback")
        self.assertEqual(out["reason"], "not_configured")
        self.assertNotIn("prose", out)


class FallsBack(unittest.TestCase):
    def test_unconfigured_uses_the_deterministic_text(self):
        with mock.patch.object(llm, "config", return_value=None):
            out = report.write_report(payload())
        self.assertEqual(out["proseSource"], "fallback")
        self.assertEqual(out["proseRejected"], "not_configured")
        from barra.i18n import english_words
        for k in ("headline", "narrative", "nextSession"):
            self.assertTrue(out[k])
            self.assertEqual(english_words(out[k]), [], out[k])

    def test_the_old_writer_is_gone(self):
        self.assertFalse((ROOT / "server" / "deepseek.py").exists())
        self.assertNotIn("DEEPSEEK", (ROOT / "server" / "template.yaml").read_text())
        self.assertIn("from report import fallback_report", (ROOT / "server" / "process.py").read_text())


if __name__ == "__main__":
    unittest.main()


class QuotingMeasuredMetrics(unittest.TestCase):
    """A measured swing metric may be quoted with its number; it may not be
    claimed as a fault without one (2026-10-18: every model's prose was thrown
    away for "poco balanceo (0,19 torsos)")."""

    def facts(self):
        reps = payload()["reps"]
        reps[0]["metrics"].append({"key": "swing", "name": "Body swing relative to the bar",
                                   "value": "0.19 torso", "class": "PLANAR"})
        return report.digest(payload(reps=reps))

    def test_quoting_the_metric_with_its_number_passes(self):
        text = "La primera tuvo poco balanceo (0,19 torsos) y buena subida."
        self.assertEqual(report.unsupported_faults(text, self.facts()), [])

    def test_naming_it_without_a_number_is_still_a_claim(self):
        self.assertIn("Balanceo",
                      report.unsupported_faults("Notamos balanceo en la subida.", self.facts()))

    def test_an_unmeasured_fault_still_fails_next_to_a_quoted_metric(self):
        text = "Poco balanceo (0,19 torsos). Las rodillas se van hacia dentro."
        self.assertIn("Rodillas hacia dentro", report.unsupported_faults(text, self.facts()))
