"""Exercise detection and the baseline quality proxy.

Fixtures are parametric rather than recorded, so a movement can be dialled in
by the one geometric property that defines it - how far above the bar the
shoulders finish, whether the hands stay put - and the classifier tested on
that property alone.
"""
from __future__ import annotations

import unittest

import numpy as np

from barra import schema as S
from barra.classify import ANCHOR_FIXED, OVER_BAR, classify, features
from barra.quality import WEIGHTS, band, score_rep, smoothness_component


def _fill(kp, f, points, rng):
    for name, x, y in points:
        kp[f, S.KP_INDEX[name]] = (x + rng.normal(0, 0.6), y + rng.normal(0, 0.6), 0.95)
    for n in ("left_eye", "right_eye", "left_ear", "right_ear"):
        kp[f, S.KP_INDEX[n]] = kp[f, S.KP_INDEX["nose"]]


def bar_clip(n_reps=3, fpr=60, clearance=0.5, drift=0.0, seed=0):
    """Hanging bar movement. `clearance` is how far above the bar the shoulders
    finish, in torso-lengths; negative is a chin-to-bar pull-up."""
    rng = np.random.default_rng(seed)
    torso, arm = 120.0, 140.0
    total = n_reps * fpr + 40
    kp = np.zeros((total, 17, 3), np.float32)
    for f in range(total):
        rise = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        bx, by = 300.0 + drift * f, 200.0
        sh = by + arm - rise * (arm + clearance * torso)
        hip = sh + torso
        _fill(kp, f, (
            ("left_wrist", bx - 40, by), ("right_wrist", bx + 40, by),
            ("left_elbow", bx - 45, (by + sh) / 2), ("right_elbow", bx + 45, (by + sh) / 2),
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_hip", bx - 22, hip), ("right_hip", bx + 22, hip),
            ("left_knee", bx - 24, hip + 90), ("right_knee", bx + 24, hip + 90),
            ("left_ankle", bx - 24, hip + 175), ("right_ankle", bx + 24, hip + 175),
            ("nose", bx, sh - 30),
        ), rng)
    return kp


def dip_clip(n_reps=3, fpr=60, seed=0):
    """Hands fixed at hip height; the body rises and falls above them."""
    rng = np.random.default_rng(seed)
    torso, total = 120.0, n_reps * 60 + 40
    kp = np.zeros((total, 17, 3), np.float32)
    bx, by = 300.0, 420.0
    for f in range(total):
        drop = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        sh = by - 0.62 * torso + drop * 0.45 * torso
        hip = sh + torso
        _fill(kp, f, (
            ("left_wrist", bx - 42, by), ("right_wrist", bx + 42, by),
            ("left_elbow", bx - 44, (by + sh) / 2), ("right_elbow", bx + 44, (by + sh) / 2),
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_hip", bx - 22, hip), ("right_hip", bx + 22, hip),
            ("left_knee", bx - 24, hip + 80), ("right_knee", bx + 24, hip + 80),
            ("left_ankle", bx - 24, hip + 150), ("right_ankle", bx + 24, hip + 150),
            ("nose", bx, sh - 30),
        ), rng)
    return kp


def squat_clip(n_reps=3, fpr=60, seed=0):
    """Feet planted, hands free at the sides, hips travelling vertically."""
    rng = np.random.default_rng(seed)
    torso, total = 120.0, n_reps * 60 + 40
    kp = np.zeros((total, 17, 3), np.float32)
    bx, ground = 300.0, 700.0
    for f in range(total):
        d = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        hip = ground - 1.75 * torso + d * 0.75 * torso
        sh = hip - torso
        _fill(kp, f, (
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_elbow", bx - 44, sh + 0.45 * torso), ("right_elbow", bx + 44, sh + 0.45 * torso),
            ("left_wrist", bx - 46, sh + 0.9 * torso), ("right_wrist", bx + 46, sh + 0.9 * torso),
            ("left_hip", bx - 22, hip), ("right_hip", bx + 22, hip),
            ("left_knee", bx - 26, (hip + ground) / 2 + d * 22), ("right_knee", bx + 26, (hip + ground) / 2 + d * 22),
            ("left_ankle", bx - 24, ground), ("right_ankle", bx + 24, ground),
            ("nose", bx, sh - 30),
        ), rng)
    return kp


class TestClassifier(unittest.TestCase):
    def test_muscle_up_when_the_shoulders_clear_the_bar(self):
        c = classify(bar_clip(clearance=0.5))
        self.assertEqual(c.exercise, "muscle_up")
        self.assertTrue(c.certain)

    def test_pull_up_when_they_do_not(self):
        """The one distinction that matters, and it is a sign change rather
        than a judgement call."""
        for clearance in (-0.05, -0.25, -0.5):
            c = classify(bar_clip(clearance=clearance))
            self.assertEqual(c.exercise, "pull_up", f"clearance {clearance}")
            self.assertEqual(c.runner_up, "muscle_up")

    def test_the_split_sits_where_it_is_documented(self):
        below = classify(bar_clip(clearance=(OVER_BAR - 0.12) / 1.0))
        above = classify(bar_clip(clearance=OVER_BAR + 0.30))
        self.assertEqual(below.exercise, "pull_up")
        self.assertEqual(above.exercise, "muscle_up")

    def test_dip_and_squat(self):
        self.assertEqual(classify(dip_clip()).exercise, "dip")
        self.assertEqual(classify(squat_clip()).exercise, "squat")

    def test_walking_is_not_a_movement(self):
        """The failure that produced textbook muscle-ups from real footage of
        someone strolling around the rig."""
        c = classify(bar_clip(drift=3.5))
        self.assertEqual(c.exercise, "unknown")
        self.assertEqual(c.confidence, 0.0)

    def test_features_are_scale_free(self):
        a = features(bar_clip(seed=1))
        big = bar_clip(seed=1)
        big[:, :, :2] *= 2.0
        b = features(big)
        for k in ("wrist_travel", "shoulder_above_hands_p95", "hands_overhead_frac"):
            self.assertAlmostEqual(a[k], b[k], places=5, msg=k)


class TestQualityProxy(unittest.TestCase):
    def base(self):
        return {"start_depth": 0.9, "peak_height": 0.9, "tempo_ratio": 0.8,
                "swing": 0.2, "shoulder_asymmetry": 0.05}

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_a_full_clean_rep_scores_high(self):
        smooth = np.linspace(-1, 1, 80)
        q = score_rep(self.base(), arm=0.9, signal=smooth, start=0, turn=79)
        self.assertGreaterEqual(q.score, 90)

    def test_half_range_costs_the_range_component(self):
        v = self.base(); v["peak_height"] = 0.45
        smooth = np.linspace(-1, 1, 80)
        full = score_rep(self.base(), 0.9, smooth, 0, 79).score
        half = score_rep(v, 0.9, smooth, 0, 79).score
        self.assertLess(half, full)

    def test_dropping_off_the_bar_costs_control(self):
        v = self.base(); v["tempo_ratio"] = 0.15
        q = score_rep(v, 0.9, np.linspace(-1, 1, 80), 0, 79)
        self.assertLess(q.components["control"]["value"], 0.3)

    def test_a_stall_is_detected(self):
        stalled = np.concatenate([np.linspace(-1, 0, 20), np.zeros(40), np.linspace(0, 1, 20)])
        clean = np.linspace(-1, 1, 80)
        self.assertLess(smoothness_component(stalled, 0, 79)[0],
                        smoothness_component(clean, 0, 79)[0])

    def test_an_unmeasurable_rep_gets_no_score_not_a_bad_one(self):
        """A pose failure is not bad technique. Showing it as a low mark would
        be the most misleading thing the app could do."""
        self.assertIsNone(score_rep(self.base(), 0.9, plausible=False).score)
        self.assertIsNone(score_rep(self.base(), 0.9, rep_quality=0.2).score)
        self.assertEqual(band(None), "unmeasured")

    def test_viewpoint_dependent_terms_are_reported_but_never_scored(self):
        q = score_rep(self.base(), 0.9, np.linspace(-1, 1, 80), 0, 79)
        self.assertIn("swing", q.context)
        self.assertNotIn("swing", q.components)
        self.assertEqual(set(q.components), set(WEIGHTS))

    def test_score_is_bounded(self):
        wild = {"start_depth": 9.0, "peak_height": 9.0, "tempo_ratio": 9.0}
        q = score_rep(wild, 0.9, np.linspace(-1, 1, 80), 0, 79)
        self.assertLessEqual(q.score, 100)
        self.assertGreaterEqual(q.score, 0)


if __name__ == "__main__":
    unittest.main()
