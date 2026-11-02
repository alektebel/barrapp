"""Ops signals: pose rate and missed-set suspicion."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.ops_signals import (  # noqa: E402
    latency_block,
    pose_per_video_second,
    suspect_missed_reps,
)


class PoseRate(unittest.TestCase):
    def test_rate_is_wall_over_video(self):
        self.assertAlmostEqual(pose_per_video_second(10.0, 20.0), 0.5)
        self.assertIsNone(pose_per_video_second(10.0, 0.0))

    def test_latency_block(self):
        b = latency_block(4.8, 19.94, backend="mediapipe")
        self.assertEqual(b["poseBackend"], "mediapipe")
        self.assertAlmostEqual(b["posePerVideoSecond"], 0.2407, places=3)


class MissedSet(unittest.TestCase):
    def test_holds_never_suspect(self):
        out = suspect_missed_reps(
            n_reps=0, exercise="planche", active_frac=0.9, signal_span=0.5)
        self.assertFalse(out["suspectMissedReps"])

    def test_scored_set_never_suspect(self):
        out = suspect_missed_reps(
            n_reps=5, exercise="pull_up", active_frac=0.9, signal_span=0.5)
        self.assertFalse(out["suspectMissedReps"])

    def test_active_zero_rep_set_is_suspect(self):
        out = suspect_missed_reps(
            n_reps=0, exercise="pull_up", active_frac=0.4, signal_span=0.35)
        self.assertTrue(out["suspectMissedReps"])
        self.assertTrue(any(r.startswith("active_frac") for r in out["reasons"]))

    def test_vision_estimate_alone_can_flag(self):
        out = suspect_missed_reps(
            n_reps=0, exercise="push_up", vision_reps_estimate=8)
        self.assertTrue(out["suspectMissedReps"])


if __name__ == "__main__":
    unittest.main()
