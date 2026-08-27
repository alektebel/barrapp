"""Invariants for the movement profiles, segmenter and metrics.

Several of these encode failures observed on real footage. They are here so
those failures cannot come back quietly.
"""
from __future__ import annotations

import unittest

import numpy as np

from barra import schema as S
from barra.ingest import segment_reps
from barra.metrics import arm_reach, implausibilities, rep_metrics
from barra.movements import (DIP, MAX_BAR_TRAVEL, MUSCLE_UP, SQUAT,
                             anchor_travel, resolve, robust_torso,
                             tracking_signal)


def synth_bar_clip(n_reps: int = 3, frames_per: int = 60, fps: float = 30.0,
                   bar_drift: float = 0.0, seed: int = 0) -> np.ndarray:
    """A subject hanging from a fixed bar doing `n_reps` pull-to-above-bar reps.

    Built directly rather than via barra.synthetic, which models a squat.
    """
    rng = np.random.default_rng(seed)
    torso_px, arm_px = 120.0, 140.0
    total = n_reps * frames_per + 40
    kp = np.zeros((total, 17, 3), dtype=np.float32)
    bar_x, bar_y = 300.0, 200.0

    for f in range(total):
        phase = (f % frames_per) / frames_per
        rise = 0.0 if f >= n_reps * frames_per else np.sin(np.pi * phase) ** 2
        bx = bar_x + bar_drift * f
        # wrists stay on the bar; shoulders climb from an arm below it to above
        sh_y = bar_y + arm_px - rise * (arm_px + 0.5 * torso_px)
        hip_y = sh_y + torso_px
        for name, x, y in (
            ("left_wrist", bx - 40, bar_y), ("right_wrist", bx + 40, bar_y),
            ("left_elbow", bx - 45, (bar_y + sh_y) / 2),
            ("right_elbow", bx + 45, (bar_y + sh_y) / 2),
            ("left_shoulder", bx - 38, sh_y), ("right_shoulder", bx + 38, sh_y),
            ("left_hip", bx - 22, hip_y), ("right_hip", bx + 22, hip_y),
            ("left_knee", bx - 24, hip_y + 90), ("right_knee", bx + 24, hip_y + 90),
            ("left_ankle", bx - 24, hip_y + 175), ("right_ankle", bx + 24, hip_y + 175),
            ("nose", bx, sh_y - 30),
        ):
            i = S.KP_INDEX[name]
            kp[f, i] = (x + rng.normal(0, 0.6), y + rng.normal(0, 0.6), 0.95)
        for name in ("left_eye", "right_eye", "left_ear", "right_ear"):
            kp[f, S.KP_INDEX[name]] = kp[f, S.KP_INDEX["nose"]]
    return kp


class TestMovementProfiles(unittest.TestCase):
    def test_aliases_resolve(self):
        for alias in ("muscle_up", "muscleup", "muscle-up", "MU", "Muscle Up"):
            self.assertEqual(resolve(alias).name, "muscle_up")
        self.assertEqual(resolve(None).name, "squat")

    def test_unknown_movement_is_an_error_not_a_default(self):
        """Silently analysing a muscle-up with squat geometry would produce
        numbers that look fine and mean nothing."""
        with self.assertRaises(SystemExit):
            resolve("deadlift")

    def test_turnaround_is_a_maximum_for_both_directions(self):
        """The segmenter only works because every movement's signal is oriented
        so the turnaround is a peak. Two movements sharing one signal but
        travelling opposite ways must come out as exact negations."""
        kp = synth_bar_clip(n_reps=2)
        up, _ = tracking_signal(kp, MUSCLE_UP)     # ascending
        down, _ = tracking_signal(kp, DIP)         # same signal, descending
        self.assertEqual(MUSCLE_UP.signal, DIP.signal)
        self.assertGreater(np.nanmax(up), np.nanmedian(up))
        np.testing.assert_allclose(up, -down, rtol=0, atol=1e-9)

    def test_squat_signal_tracks_the_hips_not_the_bar(self):
        kp = synth_bar_clip(n_reps=2)
        squat, _ = tracking_signal(kp, SQUAT)
        bar, _ = tracking_signal(kp, MUSCLE_UP)
        self.assertEqual(SQUAT.signal, "hip_height")
        self.assertFalse(np.allclose(squat, bar))
        self.assertFalse(np.allclose(squat, -bar))

    def test_robust_torso_survives_a_collapsed_frame(self):
        kp = synth_bar_clip(n_reps=1)
        good = robust_torso(kp)
        kp[10, S.KP_INDEX["left_hip"], :2] = kp[10, S.KP_INDEX["left_shoulder"], :2]
        kp[10, S.KP_INDEX["right_hip"], :2] = kp[10, S.KP_INDEX["right_shoulder"], :2]
        self.assertAlmostEqual(robust_torso(kp), good, delta=0.05 * good)


class TestSegmenter(unittest.TestCase):
    def test_ascending_movement_is_segmented(self):
        kp = synth_bar_clip(n_reps=3)
        reps = segment_reps(kp, 30.0, MUSCLE_UP)
        self.assertEqual(len(reps), 3)
        for a, turn, b in reps:
            self.assertLess(a, turn)
            self.assertLess(turn, b)

    def test_moving_anchor_is_rejected(self):
        """A subject walking away from the bar produced textbook muscle-ups on
        real footage, at 0.9 keypoint confidence. The anchor must stay put."""
        kp = synth_bar_clip(n_reps=3, bar_drift=3.5)
        self.assertGreater(anchor_travel(kp, 0, 59), MAX_BAR_TRAVEL)
        self.assertEqual(segment_reps(kp, 30.0, MUSCLE_UP), [])

    def test_fixed_bar_travel_is_small(self):
        kp = synth_bar_clip(n_reps=2)
        self.assertLess(anchor_travel(kp, 0, 59), MAX_BAR_TRAVEL)

    def test_rep_boundaries_reach_the_hang_not_the_gate(self):
        """Boundaries stopping at the detection gate would bias every amplitude
        and duration metric the same way on every rep."""
        kp = synth_bar_clip(n_reps=2, frames_per=60)
        sig, _ = tracking_signal(kp, MUSCLE_UP)
        reps = segment_reps(kp, 30.0, MUSCLE_UP)
        self.assertTrue(reps)
        a, turn, b = reps[0]
        amplitude = np.nanmax(sig) - np.nanpercentile(sig, 15)
        self.assertLess(sig[a] - np.nanpercentile(sig, 15), 0.25 * amplitude)


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.kp = synth_bar_clip(n_reps=2)
        self.reps = segment_reps(self.kp, 30.0, MUSCLE_UP)

    def test_arm_reach_is_measured_per_clip(self):
        reach = arm_reach(self.kp)
        self.assertTrue(np.isfinite(reach))
        self.assertGreater(reach, 0.5)

    def test_timing_metrics_are_scale_free(self):
        """Doubling every pixel coordinate is a camera moving closer. Timing
        must not notice."""
        a, turn, b = self.reps[0]
        m1 = rep_metrics(self.kp, a, turn, b, 30.0, MUSCLE_UP)
        big = self.kp.copy()
        big[:, :, :2] *= 2.0
        m2 = rep_metrics(big, a, turn, b, 30.0, MUSCLE_UP)
        for k in ("concentric_s", "eccentric_s", "total_s", "tempo_ratio"):
            self.assertAlmostEqual(m1.values[k], m2.values[k], places=9)
        self.assertAlmostEqual(m1.values["rom"], m2.values["rom"], places=6)

    def test_impossible_lockout_is_caught(self):
        vals = {"peak_height": 1.9, "start_depth": 0.7, "rom": 2.6}
        self.assertTrue(implausibilities(vals, MUSCLE_UP, arm=0.9))

    def test_sane_rep_is_not_flagged(self):
        vals = {"peak_height": 0.6, "start_depth": 0.8, "rom": 1.4}
        self.assertEqual(implausibilities(vals, MUSCLE_UP, arm=0.9), [])

    def test_start_above_the_bar_is_caught(self):
        vals = {"peak_height": 0.5, "start_depth": -0.8, "rom": 1.3}
        self.assertTrue(any("ABOVE" in p for p in
                            implausibilities(vals, MUSCLE_UP, arm=0.9)))


class TestProgressGating(unittest.TestCase):
    def test_scaled_metric_blocked_when_the_ruler_drifts(self):
        import pandas as pd

        from barra.progress import _comparable

        a = pd.Series({"bins": "FRONTAL", "side": "anterior", "arm_reach": 1.09})
        b = pd.Series({"bins": "FRONTAL", "side": "anterior", "arm_reach": 0.78})
        self.assertTrue(_comparable(a, b, "INVARIANT")[0])
        ok, why = _comparable(a, b, "SCALED")
        self.assertFalse(ok)
        self.assertIn("ruler", why)

    def test_planar_metric_blocked_across_camera_sides(self):
        import pandas as pd

        from barra.progress import _comparable

        a = pd.Series({"bins": "FRONTAL", "side": "anterior", "arm_reach": 1.0})
        b = pd.Series({"bins": "FRONTAL", "side": "posterior", "arm_reach": 1.0})
        self.assertTrue(_comparable(a, b, "INVARIANT")[0])
        self.assertFalse(_comparable(a, b, "PLANAR")[0])

    def test_timing_survives_every_gate(self):
        import pandas as pd

        from barra.progress import _comparable

        a = pd.Series({"bins": "SAGITTAL", "side": "left", "arm_reach": 1.4})
        b = pd.Series({"bins": "FRONTAL", "side": "posterior", "arm_reach": 0.6})
        self.assertTrue(_comparable(a, b, "INVARIANT")[0])


if __name__ == "__main__":
    unittest.main()
