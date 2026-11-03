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

import numpy as np  # noqa: E402

from barra.fusion import fuse_detection  # noqa: E402
from barra.orientation import (  # noqa: E402
    device_rotation_degrees,
    resolve_device_rotation,
    upright_luma_score,
)
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

    def test_upright_luma_prefers_brighter_top(self):
        # Brighter band at the top → positive; flip → negative.
        upright = np.zeros((100, 40), dtype=np.uint8)
        upright[:20] = 200
        upright[-20:] = 20
        self.assertGreater(upright_luma_score(upright), 50)
        self.assertLess(upright_luma_score(np.flipud(upright)), -50)

    def test_resolve_picks_complement_when_claimed_270_is_upside_down(self):
        """a038d832f870: phone said 270; applying it inverted the athlete."""
        import cv2
        import tempfile
        from pathlib import Path

        # Synthetic clip: upright person-ish gradient (bright ceiling).
        frames = []
        for _ in range(8):
            f = np.zeros((160, 90, 3), dtype=np.uint8)
            f[:40] = (180, 180, 180)
            f[-40:] = (30, 30, 30)
            frames.append(f)
        # Store it SIDEWAYS as the phone buffer often is: rotate upright
        # content 90 CCW into the file, and claim videoRotation=270 (which
        # would restore upright only if the tag matches - here the matching
        # turn is 90 CW, the complement).
        sideways = [cv2.rotate(f, cv2.ROTATE_90_COUNTERCLOCKWISE) for f in frames]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "side.mp4"
            h, w = sideways[0].shape[:2]
            wri = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                  5, (w, h))
            for f in sideways:
                wri.write(f)
            wri.release()
            deg, ev = resolve_device_rotation(
                path, {"videoRotation": 270}, n_samples=4)
        self.assertEqual(deg, 90, ev)
        self.assertEqual(ev.get("claimed"), 270)

    def test_resolve_rejects_an_inverting_180(self):
        """Clear luma gap: claimed 180 left the top darker than the floor."""
        import cv2
        import tempfile
        from pathlib import Path

        frames = []
        for _ in range(8):
            f = np.zeros((160, 90, 3), dtype=np.uint8)
            f[:40] = (180, 180, 180)
            f[-40:] = (30, 30, 30)
            frames.append(f)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "up.mp4"
            h, w = frames[0].shape[:2]
            wri = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                  5, (w, h))
            for f in frames:
                wri.write(f)
            wri.release()
            deg, ev = resolve_device_rotation(
                path, {"videoRotation": 180}, n_samples=4)
        self.assertEqual(deg, 0, ev)
        self.assertEqual(ev.get("claimed"), 180)

    def test_portrait_reencode_ignores_stale_90_tag(self):
        """a988 / cc61: portrait file + videoRotation 270 must not quarter-turn."""
        import cv2
        import tempfile
        from pathlib import Path

        # Already-upright portrait (bright ceiling), stale 270 tag.
        frames = []
        for _ in range(8):
            f = np.zeros((160, 90, 3), dtype=np.uint8)
            f[:40] = (180, 180, 180)
            f[-40:] = (30, 30, 30)
            frames.append(f)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "portrait.mp4"
            h, w = frames[0].shape[:2]
            wri = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                  5, (w, h))
            for f in frames:
                wri.write(f)
            wri.release()
            deg, ev = resolve_device_rotation(
                path, {"videoRotation": 270}, n_samples=4)
        self.assertEqual(deg, 0, ev)
        self.assertEqual(list(ev.get("candidates") or []), [0, 180])

    def test_weak_luma_keeps_claimed_180(self):
        """Near-flat lighting must not flip a 180 claim (FL pull room)."""
        import cv2
        import tempfile
        from pathlib import Path

        frames = []
        for _ in range(8):
            # Almost uniform - margin well under _LUMA_MARGIN (20).
            f = np.full((120, 160, 3), 80, dtype=np.uint8)
            f[:20] = 84
            f[-20:] = 76
            frames.append(f)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "flat.mp4"
            h, w = frames[0].shape[:2]
            wri = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                  5, (w, h))
            for f in frames:
                wri.write(f)
            wri.release()
            deg, ev = resolve_device_rotation(
                path, {"videoRotation": 180}, n_samples=4)
        self.assertEqual(deg, 180, ev)
        self.assertIn("margin", (ev.get("reason") or ""))

    def test_inverted_claim_is_not_kept_when_luma_disagrees(self):
        """93eb flake: claimed 180 scored negative while 0 was upright."""
        import cv2
        import tempfile
        from pathlib import Path

        # File is already upright (bright top). Claiming 180 would invert it.
        frames = []
        for _ in range(8):
            f = np.zeros((120, 160, 3), dtype=np.uint8)
            f[:30] = 200
            f[-30:] = 20
            frames.append(f)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "upright.mp4"
            h, w = frames[0].shape[:2]
            wri = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                  5, (w, h))
            for f in frames:
                wri.write(f)
            wri.release()
            deg, ev = resolve_device_rotation(
                path, {"videoRotation": 180}, n_samples=4)
        self.assertEqual(deg, 0, ev)
        self.assertLess(float((ev.get("lumaScore") or {}).get("180", 0)), 0)


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
