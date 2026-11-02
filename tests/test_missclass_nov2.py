"""Regression for the 2026-11-02 miss-classifications.

Two production clips (jobs 93ebbf6e4894, cc61dc871b9d):
  * front-lever pull progression with vertical legs → scored as kipping pull_up
  * inverted curls → freeform leg_raise_(lying/…) unsupported

Root causes covered here: IMU rotation must be applied before pose; locate
free-text must not be a fusion vote; freeform prose is not a movement name;
vision-decides that disagrees with geometry must ask before scoring.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra.fusion import fuse_detection  # noqa: E402
from barra.orientation import device_rotation_degrees  # noqa: E402
from barra.uncertainty import needs_confirmation  # noqa: E402


class DeviceRotation(unittest.TestCase):
    def test_phone_video_rotation_is_read(self):
        self.assertEqual(device_rotation_degrees({"videoRotation": 180}), 180)
        self.assertEqual(device_rotation_degrees({"videoRotation": 270}), 270)
        self.assertEqual(device_rotation_degrees({"videoRotation": 90}), 90)

    def test_upright_or_missing_is_zero(self):
        self.assertEqual(device_rotation_degrees({"videoRotation": 0}), 0)
        self.assertEqual(device_rotation_degrees({"upright": True}), 0)
        self.assertEqual(device_rotation_degrees(None), 0)
        self.assertEqual(device_rotation_degrees({}), 0)

    def test_odd_values_are_snapped_to_quarter_turns(self):
        self.assertEqual(device_rotation_degrees({"videoRotation": 175}), 180)
        self.assertEqual(device_rotation_degrees({"videoRotation": 95}), 90)
        self.assertEqual(device_rotation_degrees({"videoRotation": 12}), 0)


class FreeformVision(unittest.TestCase):
    def test_locate_prose_is_not_a_fusion_vote(self):
        """cc61dc871b9d: vision said 'leg raise (lying/hanging…)' and won."""
        fused = fuse_detection(
            {"exercise": "muscle_up", "confidence": 0.98},
            nan_label="leg raise (lying/hanging leg raise on dip station)",
        )
        self.assertEqual(fused["exercise"], "muscle_up")
        self.assertEqual(fused["status"], "geometry-only")
        # Raw locate prose may still be echoed on `nan`; it must not win.
        self.assertNotIn("leg_raise", fused["exercise"])

    def test_known_skill_without_profile_is_still_named(self):
        fused = fuse_detection(
            {"exercise": "squat", "confidence": 0.4},
            nan_label="front_lever_pull_up",
        )
        self.assertEqual(fused["exercise"], "front_lever_pull_up")
        self.assertEqual(fused["status"], "vision-decides")

    def test_model_deadlift_still_counts(self):
        fused = fuse_detection(
            {"exercise": "squat", "confidence": 0.9},
            {"exercise": "deadlift", "confidence": 0.8, "marginToRunnerUp": 0.3},
            {"exercise": "deadlift"},
        )
        self.assertEqual(fused["exercise"], "deadlift")
        self.assertEqual(fused["status"], "majority")


class ConfirmationGate(unittest.TestCase):
    def test_vision_decides_against_geometry_asks(self):
        """93ebbf6e4894: vision pull_up vs geometry bulgarian_split_squat."""
        fused = {
            "exercise": "pull_up",
            "status": "vision-decides",
            "geometry": "bulgarian_split_squat",
            "nan": "pull_up",
            "confidence": 0.8,
        }
        out = needs_confirmation(fused)
        self.assertTrue(out["needsConfirmation"])
        self.assertTrue(any("disagree" in r for r in out["reasons"]))

    def test_vision_majority_with_geometry_does_not(self):
        fused = {
            "exercise": "pull_up",
            "status": "majority",
            "geometry": "pull_up",
            "nan": "pull_up",
            "confidence": 0.9,
        }
        out = needs_confirmation(fused)
        self.assertFalse(out["needsConfirmation"])


class VisionVoteHelper(unittest.TestCase):
    def test_locate_prose_is_refused_as_a_skill_id(self):
        from vision import skill_from_locate_label
        self.assertIsNone(skill_from_locate_label(
            "leg raise (lying/hanging leg raise on dip station)"))
        self.assertIsNone(skill_from_locate_label(
            "A man doing something on a dip station"))
        # Clean aliases still resolve; the vote path prefers the tree walk.
        self.assertEqual(skill_from_locate_label("pull-up"), "pull_up")
        self.assertEqual(skill_from_locate_label("front_lever_pull_up"),
                         "front_lever_pull_up")
        self.assertEqual(skill_from_locate_label("Pull Up"), "pull_up")


if __name__ == "__main__":
    unittest.main()
