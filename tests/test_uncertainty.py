"""Uncertainty signals and the confirmation gate."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.uncertainty import (  # noqa: E402
    auroc,
    needs_confirmation,
    signals_from_detectors,
    vote_entropy,
)


class Signals(unittest.TestCase):
    def test_higher_when_detectors_disagree(self):
        agree = signals_from_detectors(
            model="pull_up", model_confidence=0.9, model_margin=0.5,
            geometry="pull_up", geometry_confidence=0.8,
            vision="pull_up",
            fusion={"exercise": "pull_up", "status": "majority", "confidence": 0.86},
        )
        fight = signals_from_detectors(
            model="dip", model_confidence=0.9, model_margin=0.5,
            geometry="push_up", geometry_confidence=0.8,
            vision="pull_up",
            fusion={"exercise": "dip", "status": "model-decides", "confidence": 0.9},
        )
        self.assertGreater(fight["vote_entropy"], agree["vote_entropy"])
        self.assertEqual(fight["risky_fusion_status"], 1.0)
        self.assertEqual(agree["risky_fusion_status"], 0.0)

    def test_vote_entropy_is_zero_on_unanimous(self):
        self.assertEqual(vote_entropy(["pull_up", "pull_up", "pull_up"]), 0.0)
        self.assertGreater(vote_entropy(["pull_up", "dip", "push_up"]), 0.9)


class Gate(unittest.TestCase):
    def test_risky_status_asks(self):
        out = needs_confirmation({"exercise": "dip", "status": "model-decides"},
                                 model_margin=0.9)
        self.assertTrue(out["needsConfirmation"])
        self.assertIn("fusion_status:model-decides", out["reasons"])

    def test_majority_with_clear_margin_does_not(self):
        out = needs_confirmation({"exercise": "push_up", "status": "majority"},
                                 model_margin=0.5)
        self.assertFalse(out["needsConfirmation"])

    def test_thin_model_margin_asks_only_when_enabled(self):
        quiet = needs_confirmation({"exercise": "push_up", "status": "majority"},
                                   model_margin=0.1)
        self.assertFalse(quiet["needsConfirmation"])
        loud = needs_confirmation({"exercise": "push_up", "status": "majority"},
                                  model_margin=0.1, use_margin=True)
        self.assertTrue(loud["needsConfirmation"])


class Ranking(unittest.TestCase):
    def test_auroc_perfect_separator(self):
        scores = [0.9, 0.8, 0.1, 0.0]
        labels = [1, 1, 0, 0]
        self.assertAlmostEqual(auroc(scores, labels), 1.0)


if __name__ == "__main__":
    unittest.main()
