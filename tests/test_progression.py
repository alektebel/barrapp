"""The progression referee.

The rules under test are the ones that make a verdict trustworthy: a rep only
counts if it was measured, the standard is never quietly moved, and "ready"
never comes from a single session.
"""
import unittest

from barra.progression import SOLID as SOLID_PY
from barra.progression import STRONG as STRONG_PY
from barra.progression import (LADDER, Day, Verdict, assess, from_sessions,
                               verified_reps)


def rep(score=75, plausible=True):
    return {"score": score, "plausible": plausible}


class TestWhatCounts(unittest.TestCase):
    def test_only_scored_plausible_reps_count(self):
        reps = [rep(80), rep(None), rep(70, plausible=False), rep(65)]
        self.assertEqual(len(verified_reps(reps)), 2)

    def test_a_rejected_rep_is_not_a_bad_rep(self):
        """It is a rep barra did not measure. Counting it as a poor rep would
        punish the athlete for the camera."""
        self.assertEqual(verified_reps([rep(70, plausible=False)]), [])


class TestTheStandardIsNotMoved(unittest.TestCase):
    def test_one_big_session_is_not_enough(self):
        step = LADDER["pull_up"]
        v = assess("pull_up", [Day("2026-08-10", step.reps + 5, 90)])
        self.assertFalse(v.ready, v.evidence)
        self.assertIn("qualifying day", v.missing)

    def test_two_qualifying_days_earn_it(self):
        step = LADDER["pull_up"]
        v = assess("pull_up", [Day("2026-08-10", step.reps, step.quality),
                               Day("2026-08-14", step.reps, step.quality)])
        self.assertTrue(v.ready, v.missing)
        self.assertEqual(v.missing, "")
        self.assertIn("Ready to work", v.headline)

    def test_volume_without_quality_does_not_qualify(self):
        step = LADDER["pull_up"]
        low = step.quality - 15
        v = assess("pull_up", [Day("2026-08-10", step.reps + 10, low),
                               Day("2026-08-14", step.reps + 10, low)])
        self.assertFalse(v.ready)
        self.assertIn(str(step.quality), v.missing)

    def test_quality_without_volume_does_not_qualify(self):
        step = LADDER["pull_up"]
        v = assess("pull_up", [Day("2026-08-10", step.reps - 3, 95),
                               Day("2026-08-14", step.reps - 3, 95)])
        self.assertFalse(v.ready)
        self.assertIn("more verified rep", v.missing)

    def test_the_standard_is_always_stated(self):
        """An unstated bar is one the athlete cannot argue with."""
        v = assess("pull_up", [])
        self.assertIn(str(LADDER["pull_up"].reps), v.standard)
        self.assertIn(str(LADDER["pull_up"].days), v.standard)


class TestHonesty(unittest.TestCase):
    def test_it_says_where_the_ladder_stops(self):
        """Barra cannot verify added load or a single-leg squat from video, and
        a ladder that quietly stops refereeing is worse than one that says so."""
        for movement in ("muscle_up", "squat", "knee_raise"):
            self.assertFalse(LADDER[movement].target_measurable, movement)
            self.assertTrue(LADDER[movement].note, movement)

    def test_an_untracked_movement_says_so_rather_than_guessing(self):
        v = assess("handstand", [Day("2026-08-10", 20, 90)])
        self.assertFalse(v.ready)
        self.assertIsNone(v.step)
        self.assertIn("no progression ladder", v.evidence.lower())

    def test_no_reps_is_a_clear_starting_point_not_an_error(self):
        v = assess("pull_up", [])
        self.assertIn("No verified reps", v.evidence)
        self.assertIn("Film a set", v.missing)

    def test_the_verdict_survives_serialisation(self):
        v = assess("pull_up", [Day("2026-08-10", 8, 70)])
        d = v.as_dict()
        for key in ("movement", "towards", "ready", "standard", "evidence",
                    "missing", "qualifyingDays", "targetMeasurable"):
            self.assertIn(key, d)
        self.assertIsInstance(d["ready"], bool)


class TestFromSessions(unittest.TestCase):
    def test_a_day_is_scored_on_its_median_not_its_best(self):
        """One exceptional rep must not carry a session over the line."""
        sessions = [{"date": "2026-08-10",
                     "reps": [rep(100), rep(40), rep(40), rep(40), rep(40),
                              rep(40), rep(40), rep(40)]}]
        v = from_sessions("pull_up", sessions)
        self.assertEqual(v.best_quality, 40)
        self.assertFalse(v.ready)

    def test_unverified_reps_do_not_inflate_the_count(self):
        sessions = [{"date": "2026-08-10",
                     "reps": [rep(80)] * 3 + [rep(None)] * 10}]
        v = from_sessions("pull_up", sessions)
        self.assertEqual(v.best_reps, 3)

    def test_a_session_with_nothing_verified_is_skipped_not_zeroed(self):
        """A blank session should not drag an average down - it is absence of
        evidence, not evidence of a bad day."""
        sessions = [{"date": "2026-08-10", "reps": [rep(90)] * 8},
                    {"date": "2026-08-12", "reps": [rep(None)] * 4},
                    {"date": "2026-08-14", "reps": [rep(90)] * 8}]
        v = from_sessions("pull_up", sessions)
        self.assertEqual(v.qualifying_days, ["2026-08-10", "2026-08-14"])
        self.assertTrue(v.ready)



class TestTheLaddersDoNotDrift(unittest.TestCase):
    """The standard exists twice - Python for the server and CLI, Kotlin so the
    phone can referee offline. Two copies of a published standard that disagree
    would have the phone and the server judge the same athlete differently, and
    the athlete would have no way to tell which was right."""

    def test_kotlin_and_python_publish_the_same_numbers(self):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "app" / "src" / "main" /
               "java" / "com" / "barrapp" / "Progression.kt")
        if not src.exists():
            self.skipTest("Kotlin source not present")
        text = src.read_text()

        # "push_up" to Step("dip", "Dip", reps = 15, quality = SOLID, days = 2,
        pattern = re.compile(
            r'"(\w+)"\s+to\s+Step\(\s*"(\w+)",\s*"[^"]*",\s*'
            r'reps\s*=\s*(\d+),\s*quality\s*=\s*(\w+),\s*days\s*=\s*(\d+)',
            re.S)
        # Read the constants out of the Kotlin too, rather than restating
        # them here - otherwise this test needs editing every time the scale
        # changes, which is exactly when it most needs to be untouched.
        names = {}
        for const in ("SOLID", "STRONG"):
            m = re.search(rf"const val {const}\s*=\s*(\d+)", text)
            self.assertIsNotNone(m, f"could not find {const} in Progression.kt")
            names[const] = int(m.group(1))
        self.assertEqual(names["SOLID"], SOLID_PY, "SOLID differs")
        self.assertEqual(names["STRONG"], STRONG_PY, "STRONG differs")
        found = {m.group(1): (m.group(2), int(m.group(3)),
                              names[m.group(4)], int(m.group(5)))
                 for m in pattern.finditer(text)}

        self.assertTrue(found, "could not parse the Kotlin ladder")
        self.assertEqual(set(found), set(LADDER),
                         "the two ladders cover different movements")
        for movement, step in LADDER.items():
            self.assertEqual(
                found[movement],
                (step.towards, step.reps, step.quality, step.days),
                f"{movement} differs between Python and Kotlin")

if __name__ == "__main__":
    unittest.main()
