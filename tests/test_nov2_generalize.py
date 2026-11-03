"""Classify the 2026-11-02 clips correctly, with a confidence measure.

Ground truth (athlete / production notes — no L-sit in these videos):
  * a038d832f870  weighted dips
  * a9884573d367  dips
  * 93ebbf6e4894  front-lever pull progression
  * cc61dc871b9d  inverted curls
  * 31e6fc884110  hanging leg raise on dip bars

When the pipeline is unsure the *client* names the exercise freely — there is
no server-side options list of suggested exercises.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra.classify import classify  # noqa: E402
from barra.fusion import fuse_detection  # noqa: E402
from barra.movements import normalize_free_name, resolve  # noqa: E402
from barra.uncertainty import (  # noqa: E402
    classification_confidence,
    needs_confirmation,
)
from tests.test_classify_quality import _fill, bar_clip, dip_clip  # noqa: E402


class Aliases(unittest.TestCase):
    def test_weighted_dip_measures_as_dip(self):
        self.assertEqual(resolve("weighted_dip").name, "dip")

    def test_hanging_leg_raise_measures_as_knee_raise(self):
        self.assertEqual(resolve("hanging_leg_raise").name, "knee_raise")
        self.assertEqual(resolve("leg_raise").name, "knee_raise")

    def test_inverted_curl_and_fl_pull_have_profiles(self):
        self.assertEqual(resolve("inverted_curl").name, "inverted_curl")
        self.assertEqual(resolve("front_lever_pull_up").name, "front_lever_pull_up")


class FreeText(unittest.TestCase):
    def test_spanish_and_english_names_resolve(self):
        self.assertEqual(normalize_free_name("fondos lastrados"), "weighted_dip")
        self.assertEqual(resolve("fondos lastrados").name, "dip")
        self.assertEqual(normalize_free_name("front lever pull"), "front_lever_pull_up")
        self.assertEqual(normalize_free_name("leg raise en paralelas"), "knee_raise")
        self.assertEqual(normalize_free_name("curl invertido"), "inverted_curl")

    def test_unknown_text_stays_none(self):
        self.assertIsNone(normalize_free_name("ejercicio inventado xyz"))


class HoldCannotOverrideHang(unittest.TestCase):
    def test_vision_lsit_does_not_beat_pull_up_geometry(self):
        fused = fuse_detection(
            {"exercise": "pull_up", "confidence": 0.84},
            nan_label="l_sit",
        )
        self.assertEqual(fused["exercise"], "pull_up")
        self.assertNotEqual(fused["exercise"], "l_sit")
        self.assertNotEqual(fused["status"], "vision-decides")


class ClientNamesFreely(unittest.TestCase):
    def test_confirmation_has_no_options_list(self):
        out = needs_confirmation({
            "exercise": "pull_up",
            "status": "vision-decides",
            "geometry": "bulgarian_split_squat",
            "confidence": 0.8,
        })
        self.assertTrue(out["needsConfirmation"])
        self.assertTrue(out["clientNamesExercise"])
        self.assertEqual(out["detectedLabel"], "pull_up")
        # Contract: never an options menu for the phone to pick from.
        self.assertNotIn("suggestedExercises", out)
        self.assertNotIsInstance(out.get("detectedLabel"), list)


class ConfidenceMeasure(unittest.TestCase):
    def test_majority_vote_is_high(self):
        conf = classification_confidence(
            {"exercise": "dip", "status": "majority", "confidence": 0.9},
            grounding={"needsConfirmation": False},
        )
        self.assertGreaterEqual(conf["value"], 0.7)
        self.assertFalse(conf["needsConfirmation"])

    def test_disputed_vision_asks_the_client_to_name_it(self):
        ground = needs_confirmation({
            "exercise": "pull_up",
            "status": "vision-decides",
            "geometry": "bulgarian_split_squat",
            "confidence": 0.9,
        })
        conf = classification_confidence(
            {"exercise": "pull_up", "status": "vision-decides", "confidence": 0.9},
            grounding=ground,
        )
        self.assertTrue(conf["needsConfirmation"])
        self.assertTrue(conf["clientNamesExercise"])
        # Confidence stays a real per-clip score; the gate is separate.
        self.assertGreater(conf["value"], 0.5)

    def test_per_clip_confidence_is_discriminative(self):
        high = classification_confidence(
            {"exercise": "dip", "status": "majority", "confidence": 0.9},
            grounding={"needsConfirmation": False},
        )
        low = classification_confidence(
            {"exercise": "unknown", "status": "abstain", "confidence": 0.0},
            grounding={"needsConfirmation": True},
        )
        self.assertGreater(high["value"], low["value"])


def _front_lever_pull_clip(n_reps=3, fpr=60, clearance=-0.12, seed=4):
    """Hang pull with the body held near horizontal.

    Same shoulder path as a chin-to-bar pull, but hips are carried out so
    body_line_deg sits around 70° — enough to name a front-lever pull, not a
    plain pull-up, and articulated enough not to be the isometric hold.
    """
    rng = np.random.default_rng(seed)
    torso, arm = 120.0, 140.0
    total = n_reps * fpr + 40
    kp = np.zeros((total, 17, 3), np.float32)
    rad = np.deg2rad(70.0)
    for f in range(total):
        rise = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        bx, by = 300.0, 200.0
        sh = by + arm - rise * (arm + clearance * torso)
        # Hips out along the body line (near horizontal).
        hip_x = bx + torso * np.sin(rad)
        hip_y = sh + torso * np.cos(rad)
        knee_x = hip_x + 70 * np.sin(rad)
        knee_y = hip_y + 70 * np.cos(rad)
        ankle_x = hip_x + 140 * np.sin(rad)
        ankle_y = hip_y + 140 * np.cos(rad)
        _fill(kp, f, (
            ("left_wrist", bx - 40, by), ("right_wrist", bx + 40, by),
            ("left_elbow", bx - 45, (by + sh) / 2),
            ("right_elbow", bx + 45, (by + sh) / 2),
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_hip", hip_x - 22, hip_y), ("right_hip", hip_x + 22, hip_y),
            ("left_knee", knee_x - 24, knee_y), ("right_knee", knee_x + 24, knee_y),
            ("left_ankle", ankle_x - 24, ankle_y),
            ("right_ankle", ankle_x + 24, ankle_y),
            ("nose", bx, sh - 30),
        ), rng)
    return kp


def _vertical_leg_fl_pull_clip(n_reps=3, fpr=50, seed=5):
    """Vertical-leg front-lever pull (93ebbf6e4894): legs up, body parked.

    Real clip: peak≈+0.20, p05≈-0.15, legs_lifted≈0.96, parked≈0.88.
    Shoulders cycle around hand height; hips/knees/ankles stay world-fixed
    and folded up so the body reads parked with the legs raised.
    """
    rng = np.random.default_rng(seed)
    torso = 120.0
    total = n_reps * fpr + 40
    kp = np.zeros((total, 17, 3), np.float32)
    bx, by = 300.0, 200.0
    for f in range(total):
        rise = 0.0 if f >= n_reps * fpr else np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        # p05≈-0.15 → p95≈+0.20 in torso-lengths relative to the wrists.
        above = -0.15 + rise * 0.35
        sh = by - above * torso
        # Real torso length (hips below shoulders) but knees/ankles folded
        # UP toward the bar so legs_lifted / knee_over_hip stay high. Anchors
        # are world-fixed so parked_frac stays high.
        hip_y = (by + 0.05 * torso) + torso * 0.85   # ~fixed below the hang
        knee_y = by - 0.20 * torso
        ankle_y = by - 0.50 * torso
        _fill(kp, f, (
            ("left_wrist", bx - 40, by), ("right_wrist", bx + 40, by),
            ("left_elbow", bx - 45, (by + sh) / 2),
            ("right_elbow", bx + 45, (by + sh) / 2),
            ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
            ("left_hip", bx - 22, hip_y), ("right_hip", bx + 22, hip_y),
            ("left_knee", bx - 24, knee_y), ("right_knee", bx + 24, knee_y),
            ("left_ankle", bx - 24, ankle_y), ("right_ankle", bx + 24, ankle_y),
            ("nose", bx, sh - 30),
        ), rng)
    return kp


class Naming(unittest.TestCase):
    def test_dip_clip_is_dip(self):
        c = classify(dip_clip())
        self.assertEqual(c.exercise, "dip")
        self.assertGreater(c.confidence, 0.5)

    def test_deep_hang_curl_is_inverted_curl(self):
        # cc61dc871b9d shape: peak ≈ -0.57 (bar_clip clearance is that peak).
        c = classify(bar_clip(clearance=-0.57))
        self.assertEqual(c.exercise, "inverted_curl", c.reason)
        self.assertGreater(c.confidence, 0.5)

    def test_horizontal_pull_is_front_lever_pull(self):
        c = classify(_front_lever_pull_clip())
        self.assertEqual(c.exercise, "front_lever_pull_up", c.reason)
        self.assertGreater(c.confidence, 0.5)

    def test_vertical_leg_fl_pull_is_not_a_plain_pull_up(self):
        """93ebbf6e4894 shape: legs up, body parked, elbows cycling."""
        c = classify(_vertical_leg_fl_pull_clip())
        self.assertEqual(c.exercise, "front_lever_pull_up", c.reason)
        self.assertGreater(c.confidence, 0.5)

    def test_ordinary_pull_up_still_wins(self):
        c = classify(bar_clip(clearance=-0.25))
        self.assertEqual(c.exercise, "pull_up", c.reason)


if __name__ == "__main__":
    unittest.main()
