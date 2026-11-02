"""Regressions for naming + counting the 2026-11-02 production clips.

Evidence-backed (local upright replays of the S3 clips):
  * a038d832f870 weighted dips: named dip, but 1 bottom rejected because
    anchor_travel ran over a 6.7 s walk-window (pose drift). Cap travel near
    the peak.
  * a9884573d367 dips: hands_below + body hanging, but squat won because the
    dip branch sat after squat and required articulation.
  * Muscle-up must have started from a hang (p05 < 0); support work that
    briefly clears the hands is not a muscle-up.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra.classify import OVER_BAR, classify  # noqa: E402
from barra.ingest import candidate_checks, segment_reps  # noqa: E402
from barra.movements import DIP, MAX_BAR_TRAVEL, MUSCLE_UP, anchor_travel  # noqa: E402
from barra import schema as S  # noqa: E402
from tests.test_classify_quality import bar_clip, dip_clip, squat_clip  # noqa: E402


def _torso_bar_clip_with_lockout_drift(n_reps=1, fpr=50, drift_per_frame=0.015):
    """One dip bottom, then a long support hold whose wrists slowly drift.

    Mimics a038d832f870: travel over the full walked window exceeds
    MAX_BAR_TRAVEL, travel near the peak does not.
    """
    rng = np.random.default_rng(1)
    torso, total = 120.0, n_reps * fpr + 120  # long lockout after the set
    kp = np.zeros((total, 17, 3), np.float32)
    bx, by = 300.0, 420.0
    for f in range(total):
        if f < n_reps * fpr:
            drop = np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        else:
            drop = 0.0
            bx = 300.0 + drift_per_frame * (f - n_reps * fpr) * torso
        sh = by - 0.62 * torso + drop * 0.45 * torso
        hip = sh + torso
        for name, x, y in (
            ("left_wrist", bx - 42, by), ("right_wrist", bx + 42, by),
            ("left_elbow", bx - 44, (by + sh) / 2), ("right_elbow", bx + 44, (by + sh) / 2),
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_hip", bx - 22, hip), ("right_hip", bx + 22, hip),
            ("left_knee", bx - 24, hip + 80), ("right_knee", bx + 24, hip + 80),
            ("left_ankle", bx - 24, hip + 150), ("right_ankle", bx + 24, hip + 150),
            ("nose", bx, sh - 30),
        ):
            kp[f, S.KP_INDEX[name]] = (x + rng.normal(0, 0.4),
                                       y + rng.normal(0, 0.4), 0.95)
        for n in ("left_eye", "right_eye", "left_ear", "right_ear"):
            kp[f, S.KP_INDEX[n]] = kp[f, S.KP_INDEX["nose"]]
    return kp


class TravelNearPeak(unittest.TestCase):
    def test_long_lockout_drift_still_counts_the_dip(self):
        kp = _torso_bar_clip_with_lockout_drift()
        fps = 25.0
        # Full-window travel is the false reject a038 hit.
        self.assertGreater(anchor_travel(kp, 0, len(kp) - 1), MAX_BAR_TRAVEL)
        reps = segment_reps(kp, fps, DIP)
        self.assertGreaterEqual(len(reps), 1, "lockout drift must not zero a real dip")

    def test_walking_away_is_still_rejected(self):
        from tests.test_movements import synth_bar_clip
        kp = synth_bar_clip(n_reps=3, bar_drift=3.5)
        self.assertEqual(segment_reps(kp, 30.0, MUSCLE_UP), [])


class DipBeforeSquat(unittest.TestCase):
    def test_hands_below_beats_a_planted_looking_squat(self):
        self.assertEqual(classify(dip_clip()).exercise, "dip")
        self.assertEqual(classify(squat_clip()).exercise, "squat")

    def test_support_without_a_prior_hang_is_not_a_muscle_up(self):
        """L-sit / dip-station support can clear the hands without hanging."""
        kp = dip_clip()
        c = classify(kp)
        self.assertEqual(c.exercise, "dip")
        self.assertNotEqual(c.exercise, "muscle_up")

    def test_real_muscle_up_still_needs_a_hang(self):
        c = classify(bar_clip(clearance=0.5))
        self.assertEqual(c.exercise, "muscle_up")
        self.assertLess(c.features["shoulder_above_hands_p05"], -0.05)

    def test_pull_up_when_clearance_stays_below_the_bar(self):
        c = classify(bar_clip(clearance=-0.25))
        self.assertEqual(c.exercise, "pull_up")

    def test_support_dominant_clearance_is_a_pull_up_not_a_muscle_up(self):
        """FL-pull style: hands mostly below the shoulders, peak clears bar."""
        kp = bar_clip(clearance=0.5)
        from barra import schema as S
        # Wrists stay fixed (anchor). Lift the shoulders above the wrists on
        # most frames so hands_below > hands_overhead - dip-station FL-pull
        # geometry (93ebbf6e4894) - without breaking wrist travel.
        n = len(kp)
        # ~65% support frames (bel < 0.80 so dip does not fire) + hang start.
        for f in range(n):
            if f < int(0.35 * n):
                continue
            for side in ("left", "right"):
                wr = float(kp[f, S.KP_INDEX[f"{side}_wrist"], 1])
                kp[f, S.KP_INDEX[f"{side}_shoulder"], 1] = wr - 30
        c = classify(kp)
        self.assertGreater(c.features["hands_below_frac"],
                           c.features["hands_overhead_frac"])
        self.assertLess(c.features["hands_below_frac"], 0.80)
        self.assertEqual(c.exercise, "pull_up")


class PeakTravelHelper(unittest.TestCase):
    def test_candidate_checks_uses_a_capped_travel_window(self):
        kp = _torso_bar_clip_with_lockout_drift()
        fps = 25.0
        pk = int(0.5 * 50)  # mid-rep bottom in the synthetic clip
        a, b = 0, len(kp) - 1
        valid = np.ones(len(kp), dtype=bool)
        # Physical sign unused when signal is not shoulder_above_bar check path
        why = candidate_checks(kp, None, valid, a, pk, b, DIP, fps,
                               min_frames=3, min_observed=0.0)
        self.assertIsNone(why, why)


class HoldIsometric(unittest.TestCase):
    def test_moving_horizontal_body_is_not_a_front_lever(self):
        """L-sit / moving pike must not win the isometric front-lever gate."""
        from tests.test_classify_quality import bar_clip
        from barra import schema as S
        kp = bar_clip(clearance=-0.25)
        # Tilt the body nearly horizontal while keeping hips moving (not parked).
        for f in range(len(kp)):
            mid = 0.5 * (kp[f, S.KP_INDEX["left_hip"], 1]
                         + kp[f, S.KP_INDEX["right_hip"], 1])
            # Push ankles out to the side so the hip→ankle line is flat.
            for side in ("left", "right"):
                kp[f, S.KP_INDEX[f"{side}_ankle"], 0] = (
                    kp[f, S.KP_INDEX[f"{side}_hip"], 0] + 200)
                kp[f, S.KP_INDEX[f"{side}_ankle"], 1] = mid
                kp[f, S.KP_INDEX[f"{side}_knee"], 0] = (
                    kp[f, S.KP_INDEX[f"{side}_hip"], 0] + 100)
                kp[f, S.KP_INDEX[f"{side}_knee"], 1] = mid
        c = classify(kp)
        self.assertNotEqual(c.exercise, "front_lever")


if __name__ == "__main__":
    unittest.main()
