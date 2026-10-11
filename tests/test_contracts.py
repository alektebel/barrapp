"""Stage contracts: what each step of the pipeline takes in and gives out.

Every check is a pure function from a stage's output (and the context it needs)
to a list of violations. An empty list is the claim "this output is
well-formed"; it is not a claim that the measurement is right - that is what
the corpus and its labels are for. These tests pin each invariant with one
output that keeps it and one that breaks it.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra import contracts as C  # noqa: E402


def rules(violations) -> set[str]:
    return {v.rule for v in violations}


class Probe(unittest.TestCase):
    good = {"ok": True, "fps": 30.0, "frames": 300, "duration_s": 10.0}

    def test_a_readable_clip_passes(self):
        self.assertEqual(C.check_probe(self.good), [])

    def test_zero_fps_is_a_violation(self):
        self.assertIn("fps_positive", rules(C.check_probe({**self.good, "fps": 0})))

    def test_duration_must_match_frames_over_fps(self):
        bad = {**self.good, "duration_s": 20.0}
        self.assertIn("duration_matches_frames", rules(C.check_probe(bad)))

    def test_an_unreadable_clip_is_not_checked_further(self):
        self.assertEqual(C.check_probe({"ok": False, "reason": "codec"}), [])


class Pose(unittest.TestCase):
    def kp(self, t=90, k=33):
        rng = np.random.default_rng(0)
        a = rng.uniform(0.1, 0.9, size=(t, k, 3))
        a[:, :, 2] = 0.9
        return a

    def test_well_formed_keypoints_pass(self):
        self.assertEqual(C.check_pose(self.kp(), fps=30.0), [])

    def test_wrong_rank_is_fatal(self):
        v = C.check_pose(np.zeros((90, 33)), fps=30.0)
        self.assertIn("keypoints_shape", rules(v))
        self.assertTrue(any(x.fatal for x in v))

    def test_no_frames_is_a_violation(self):
        self.assertIn("has_frames", rules(C.check_pose(np.zeros((0, 33, 3)), fps=30.0)))

    def test_implausible_fps(self):
        self.assertIn("fps_plausible", rules(C.check_pose(self.kp(), fps=0.0)))

    def test_mostly_untracked_is_a_violation(self):
        kp = self.kp()
        kp[:, :, 2] = 0.0
        self.assertIn("tracked_enough", rules(C.check_pose(kp, fps=30.0)))


class Detection(unittest.TestCase):
    good = {"exercise": "pull_up", "label": "Pull-up", "confidence": 0.8,
            "certainty": "margin", "reason": "x"}

    def test_a_named_movement_passes(self):
        self.assertEqual(C.check_detection(self.good), [])

    def test_confidence_outside_unit_interval(self):
        self.assertIn("confidence_in_unit",
                      rules(C.check_detection({**self.good, "confidence": 1.4})))

    def test_blank_exercise(self):
        self.assertIn("exercise_named",
                      rules(C.check_detection({**self.good, "exercise": ""})))


class Segments(unittest.TestCase):
    def test_ordered_disjoint_reps_pass(self):
        self.assertEqual(C.check_segments([(0, 10, 20), (20, 30, 40)], n_frames=50), [])

    def test_no_reps_is_a_valid_answer(self):
        self.assertEqual(C.check_segments([], n_frames=50), [])

    def test_turn_must_sit_between_start_and_end(self):
        self.assertIn("start_turn_end_ordered",
                      rules(C.check_segments([(0, 25, 20)], n_frames=50)))

    def test_reps_inside_the_clip(self):
        self.assertIn("inside_clip", rules(C.check_segments([(0, 10, 60)], n_frames=50)))

    def test_overlapping_reps(self):
        self.assertIn("disjoint_and_sorted",
                      rules(C.check_segments([(0, 10, 30), (20, 30, 40)], n_frames=50)))


class Payload(unittest.TestCase):
    def empty(self, **extra):
        from process import _empty
        blockers = extra.pop("blockers", ["No se ve al atleta."])
        return _empty("auto", blockers, **extra)

    def rep(self, **kw):
        base = {k: None for k in C.REP_REQUIRED}
        base.update({"label": "r1", "metrics": [], "problems": [], "plausible": True,
                     "startS": 1.0, "turnS": 1.5, "endS": 2.0, "score": 70,
                     "band": "solid", "components": [], "aside": [], "trace": []})
        base.update(kw)
        return base

    def measured(self, reps, **kw):
        p = self.empty(n_reps=len(reps), n_candidates=len(reps), reps=reps,
                       duration_s=10.0, sessionScore=70, sessionBand="solid",
                       blockers=[], headline="h", narrative="n", nextSession="s")
        p.update(kw)
        return p

    def test_the_empty_path_honours_the_contract(self):
        self.assertEqual(C.check_payload(self.empty(headline="h", narrative="n",
                                                    nextSession="s")), [])

    def test_a_measured_set_passes(self):
        self.assertEqual(C.check_payload(self.measured([self.rep()])), [])

    def test_missing_key_is_fatal(self):
        p = self.measured([self.rep()])
        del p["reps"]
        v = C.check_payload(p)
        self.assertIn("required_keys", rules(v))
        self.assertTrue(any(x.fatal for x in v))

    def test_rep_missing_key(self):
        r = self.rep()
        del r["turnS"]
        self.assertIn("rep_required_keys", rules(C.check_payload(self.measured([r]))))

    def test_measurement_version(self):
        self.assertIn("measurement_version",
                      rules(C.check_payload(self.measured([self.rep()], measurementVersion=1))))

    def test_score_and_band_agree(self):
        p = self.measured([self.rep()], sessionScore=None, sessionBand="solid")
        self.assertIn("session_band_matches_score", rules(C.check_payload(p)))

    def test_score_in_range(self):
        self.assertIn("rep_score_in_range",
                      rules(C.check_payload(self.measured([self.rep(score=130, band="strong")]))))

    def test_rep_times_ordered_and_inside_clip(self):
        r = self.rep(startS=3.0, turnS=2.0, endS=4.0)
        self.assertIn("rep_times_ordered", rules(C.check_payload(self.measured([r]))))
        r = self.rep(startS=8.0, turnS=9.0, endS=14.0)
        self.assertIn("rep_times_inside_clip", rules(C.check_payload(self.measured([r]))))

    def test_counted_reps_never_exceed_candidates(self):
        p = self.measured([self.rep()], n_reps=3, n_candidates=1)
        self.assertIn("n_reps_le_candidates", rules(C.check_payload(p)))

    def test_nothing_counted_must_say_why(self):
        p = self.empty(blockers=[], headline="h", narrative="n", nextSession="s")
        self.assertIn("zero_reps_has_blocker", rules(C.check_payload(p)))

    def test_a_developer_message_never_reaches_the_phone(self):
        # D4: the raw SystemExit of movements.resolve, seen in production.
        p = self.empty(blockers=["unknown movement 'deadlift'. Known: dip, pull_up."],
                       headline="h", narrative="n", nextSession="s")
        self.assertIn("no_developer_text", rules(C.check_payload(p)))


class Registry(unittest.TestCase):
    def test_every_stage_has_a_check(self):
        for stage in ("probe", "pose", "detection", "segments", "payload"):
            self.assertIn(stage, C.CONTRACTS)

    def test_violation_is_serialisable(self):
        v = C.Violation("payload", "required_keys", "missing reps", fatal=True)
        self.assertEqual(v.as_dict(), {"stage": "payload", "rule": "required_keys",
                                       "detail": "missing reps", "fatal": True})


if __name__ == "__main__":
    unittest.main()
