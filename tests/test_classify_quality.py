"""Exercise detection and the baseline quality proxy.

Fixtures are parametric rather than recorded, so a movement can be dialled in
by the one geometric property that defines it - how far above the bar the
shoulders finish, whether the hands stay put - and the classifier tested on
that property alone.
"""
from __future__ import annotations

import pathlib
import unittest

import numpy as np

from barra import schema as S
from barra.classify import ANCHOR_FIXED, OVER_BAR, classify, features
from barra.metrics import implausibilities
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


def pushup_clip(n_reps=3, fpr=60, seed=0):
    """Hands fixed on the floor, torso laid out flat, body descending onto them.

    Geometrically the same shape as a dip apart from the one thing that
    separates them: where the torso points.
    """
    rng = np.random.default_rng(seed)
    torso, total = 120.0, n_reps * 60 + 40
    kp = np.zeros((total, 17, 3), np.float32)
    hx, floor = 260.0, 620.0
    for f in range(total):
        drop = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        sh_y = floor - 78.0 + drop * 46.0          # shoulders stay above the hands
        _fill(kp, f, (
            ("left_wrist", hx - 34, floor), ("right_wrist", hx + 34, floor),
            ("left_elbow", hx - 40, sh_y + 34), ("right_elbow", hx + 40, sh_y + 34),
            ("left_shoulder", hx - 30, sh_y), ("right_shoulder", hx + 30, sh_y),
            # torso runs backwards along the floor, not downwards
            ("left_hip", hx + torso - 18, sh_y + 26), ("right_hip", hx + torso + 18, sh_y + 26),
            ("left_knee", hx + 1.9 * torso - 18, sh_y + 40),
            ("right_knee", hx + 1.9 * torso + 18, sh_y + 40),
            ("left_ankle", hx + 2.7 * torso - 18, sh_y + 52),
            ("right_ankle", hx + 2.7 * torso + 18, sh_y + 52),
            ("nose", hx - 6, sh_y - 22),
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

    def test_push_up_is_a_dip_lying_down(self):
        """Same hands-fixed, shoulders-above shape. What separates them is that
        a dip has your legs below your hands and a push-up has nothing below
        them - a comparison of heights, which projection does not distort."""
        push = classify(pushup_clip())
        dip = classify(dip_clip())
        self.assertEqual(push.exercise, "push_up")
        self.assertEqual(dip.exercise, "dip")
        self.assertEqual(push.runner_up, "dip")
        self.assertLess(push.features["body_below_hands"], 0.25)
        self.assertGreater(dip.features["body_below_hands"], 0.25)

    def test_torso_angle_is_not_used_to_decide(self):
        """Filmed head-on, a real push-up's torso projects to 5 degrees from
        vertical - indistinguishable from a dip. The angle is reported as a
        diagnostic and must not drive the decision."""
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "barra" / "classify.py").read_text()
        decision = source[source.index("def classify("):]
        self.assertNotIn("torso_tilt", decision)

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

    def test_the_score_is_fully_accounted_for(self):
        """The graded components plus the worst fault penalty must account for
        the whole scale, so no part of the number is unexplained."""
        from barra.quality import CONTROL_PENALTY
        self.assertAlmostEqual(sum(WEIGHTS.values()) + CONTROL_PENALTY, 1.0,
                               places=9)

    def test_control_is_not_a_term_in_the_mean(self):
        """It is a fault detector: it reads the same for every rep without the
        fault, and a constant inside a weighted mean is a floor under every
        score rather than a measurement."""
        self.assertNotIn("control", WEIGHTS)

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

    def test_dropping_off_the_bar_is_penalised(self):
        from barra.quality import CONTROL_PENALTY

        smooth = np.linspace(-1, 1, 80)
        clean = score_rep(self.base(), 0.9, smooth, 0, 79)
        v = self.base(); v["tempo_ratio"] = 0.0          # straight off the bar
        dropped = score_rep(v, 0.9, smooth, 0, 79)
        self.assertLess(dropped.score, clean.score)
        self.assertAlmostEqual(dropped.penalties["control"]["value"],
                               CONTROL_PENALTY, places=3)

    def test_a_controlled_descent_costs_nothing_at_all(self):
        """The point of moving control out of the mean: no fault, no charge -
        and no constant either."""
        smooth = np.linspace(-1, 1, 80)
        for tempo in (0.70, 0.90, 1.50, 3.00):
            v = self.base(); v["tempo_ratio"] = tempo
            q = score_rep(v, 0.9, smooth, 0, 79)
            self.assertEqual(q.penalties["control"]["value"], 0.0, f"tempo {tempo}")

    def test_smoothness_is_graded_not_counted(self):
        """Counting stalled frames makes the frame count the denominator, so a
        short rep can only take a handful of values. Grading how far below the
        floor each frame fell is continuous."""
        def ascent(depth, n=40):
            """A rate profile that dips in the middle, integrated into a
            monotone signal. Built this way on purpose: splicing a slow section
            into a linear ramp leaves a step discontinuity at the join, and
            that single large frame then defines the rep's "fast" rate and
            swamps the thing under test."""
            t = np.linspace(0, 1, n)
            rate = 1.0 - depth * np.exp(-((t - 0.5) ** 2) / (2 * 0.12 ** 2))
            sig = np.concatenate([[0.0], np.cumsum(rate)])[:n]
            return 2 * sig / sig[-1] - 1

        seen = [smoothness_component(ascent(d), 0, 39)[0]
                for d in np.linspace(0.0, 0.95, 25)]
        self.assertEqual(len(set(round(v, 4) for v in seen)), 25,
                         "the component is quantised")
        self.assertTrue(all(a >= b - 1e-9 for a, b in zip(seen, seen[1:])),
                        "a deeper stall must never score higher")

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

    def test_a_descending_rep_starting_above_the_hands_is_fine(self):
        """A dip and a push-up start above the hands by construction. Applying
        the hanging check to them rejected all 19 reps of a correctly segmented
        push-up clip."""
        from barra.movements import MUSCLE_UP, PUSH_UP

        started_high = {"peak_height": 0.6, "start_depth": -0.6, "rom": 0.5}
        self.assertEqual(implausibilities(started_high, PUSH_UP, arm=1.2), [])
        self.assertTrue(implausibilities(started_high, MUSCLE_UP, arm=1.2))

    def test_an_unusable_ruler_refuses_the_score_rather_than_faking_it(self):
        """Filmed head-on, a push-up's torso projects to almost nothing and the
        arm:torso ratio came out at 2.7, so range is unmeasurable for the whole
        clip. Scored on what survived, 19 such reps read 94 - a number saying
        the movement was continuous and nothing about whether it happened."""
        from barra.metrics import usable_reference

        self.assertFalse(usable_reference(2.70))
        self.assertTrue(usable_reference(1.20))
        q = score_rep(self.base(), arm=2.70, signal=np.linspace(-1, 1, 80),
                      start=0, turn=79)
        self.assertIsNone(q.score)
        self.assertFalse(q.complete)
        self.assertIsNone(q.components["range"]["value"])
        self.assertIn("from the side", q.note)

    def test_a_missing_smoothness_still_scores_on_range(self):
        """The refusal is specific to range, not to any missing component: a
        rep whose depth is known is still partly measured."""
        q = score_rep(self.base(), arm=0.9, signal=None)
        self.assertIsNotNone(q.score)
        self.assertFalse(q.complete)
        self.assertIn("partial", q.context)

    def test_score_is_bounded(self):
        wild = {"start_depth": 9.0, "peak_height": 9.0, "tempo_ratio": 9.0}
        q = score_rep(wild, 0.9, np.linspace(-1, 1, 80), 0, 79)
        self.assertLessEqual(q.score, 100)
        self.assertGreaterEqual(q.score, 0)


if __name__ == "__main__":
    unittest.main()


class TestOcclusionAndHolds(unittest.TestCase):
    """The three failures found by watching the sample clips instead of
    trusting the classifier's own confidence."""

    def test_a_pair_seen_only_on_one_side_is_still_measurable(self):
        """Side-on is the angle these movements are supposed to be filmed from,
        and it hides the far arm and leg completely."""
        import numpy as np

        from barra.movements import midpoint, pair_confidence
        from barra.schema import KP_INDEX

        kp = bar_clip()
        kp[:, KP_INDEX["right_wrist"], 2] = 0.05      # far arm behind the near one
        pts = midpoint(kp, "left_wrist", "right_wrist")
        conf = pair_confidence(kp, "left_wrist", "right_wrist")
        self.assertGreater(float((conf >= 0.5).mean()), 0.5,
                           "an occluded far side must not blind the near one")
        self.assertTrue(np.allclose(pts, kp[:, KP_INDEX["left_wrist"], :2]),
                        "the visible side should be used as-is")

    def test_the_reference_point_does_not_jump_mid_clip(self):
        """Switching between the midpoint and one side partway through moves
        the reference by half the pair's separation, and every switch reads
        downstream as motion that never happened."""
        import numpy as np

        from barra.movements import midpoint
        from barra.schema import KP_INDEX

        kp = bar_clip()
        kp[:, KP_INDEX["right_wrist"], 0] += 60.0     # a wide, asymmetric grip
        baseline = np.abs(np.diff(
            midpoint(kp, "left_wrist", "right_wrist")[:, 0])).max()

        occluded = kp.copy()
        half = len(kp) // 2
        occluded[half:, KP_INDEX["right_wrist"], 2] = 0.05   # far side lost halfway
        step = np.abs(np.diff(
            midpoint(occluded, "left_wrist", "right_wrist")[:, 0])).max()

        # Losing the far side must not add a discontinuity of its own. Half the
        # grip width is 30px here; the frame-to-frame jitter of the clip is a
        # couple of px, so a mode switch would be unmissable.
        self.assertLess(float(step), float(baseline) + 5.0,
                        "the reference point jumped when the far side was lost")

    def test_a_missing_measurement_never_satisfies_a_branch(self):
        """`not articulated` must not be satisfiable by a NaN. This is how a
        muscle-up filmed side-on came out as a squat."""
        from barra.classify import classify
        from barra.schema import KP_INDEX

        kp = bar_clip()
        for side in ("left", "right"):
            kp[:, KP_INDEX[f"{side}_wrist"], 2] = 0.0
            kp[:, KP_INDEX[f"{side}_elbow"], 2] = 0.0
        self.assertEqual(classify(kp).exercise, "unknown",
                         "with the arms unseen, no arm-based verdict is available")

    def test_a_hold_is_not_a_set(self):
        """A static hang has hands as fixed as any bar movement and drifts
        just enough to look articulated."""
        import numpy as np

        from barra.classify import classify

        kp = bar_clip(n_reps=1)
        held = np.repeat(kp[len(kp) // 2:len(kp) // 2 + 1], 300, axis=0)
        held[:, :, :2] += np.random.default_rng(0).normal(0, 0.004, held[:, :, :2].shape)
        c = classify(held)
        # A hold is named as a hold - never as a movement with reps in it.
        self.assertEqual(c.kind, "hold")
        self.assertNotIn(c.exercise, ("muscle_up", "pull_up", "dip", "push_up",
                                      "squat", "knee_raise"))
        self.assertIn("hold", c.reason)
        self.assertGreater(c.hold.seconds, 5.0)

    def test_hanging_knee_raise_is_not_a_pull_up(self):
        """Every condition of the pull-up branch holds except the one that
        defines it: the shoulders never rise to the hands, the knees do."""
        import numpy as np

        from barra.classify import classify
        from barra.schema import KP_INDEX

        from barra.movements import robust_torso

        kp = bar_clip(clearance=-0.9, n_reps=3)
        torso = robust_torso(kp)                      # the clip is in pixels
        hip_y = kp[:, KP_INDEX["left_hip"], 1].copy()
        t = np.linspace(0, 3 * 2 * np.pi, len(kp))
        lift = 0.9 * torso * (0.5 + 0.5 * np.sin(t))  # knees curl up and back down
        for side in ("left", "right"):
            kp[:, KP_INDEX[f"{side}_knee"], 1] = hip_y - lift
            kp[:, KP_INDEX[f"{side}_knee"], 2] = 0.95
        self.assertEqual(classify(kp).exercise, "knee_raise")
