"""The rescue pass: a visible set is never reported as nothing.

The relaxed segmenter is only safe because of its gradient validation - a
candidate counts only when the movement into and out of its turnaround is
faster than the clip's own velocity noise floor, and both legs of the rep
carry real displacement. These tests pin exactly that bargain: real reps
survive relaxation; noise, drift and one-sided sways do not.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.ingest import _rescue_candidates
from barra.movements import resolve

FPS = 24.0


def _humps(t: np.ndarray, starts: list[float], height: float = 0.5,
           period: float = 1.5) -> np.ndarray:
    sig = np.full(len(t), 0.5)
    for s in starts:
        m = (t >= s) & (t <= s + period)
        sig[m] = 0.5 + height * np.sin(np.pi * (t[m] - s) / period)
    return sig


class TestRescueCandidates(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)
        self.t = np.arange(int(24 * 10)) / FPS
        self.valid = np.ones(len(self.t), dtype=bool)
        self.movement = resolve("pull_up")

    def test_three_clean_reps_survive(self):
        sig = _humps(self.t, [1.0, 4.0, 7.0]) + self.rng.normal(0, 0.01, len(self.t))
        got = _rescue_candidates(sig, self.valid, FPS, self.movement)
        self.assertEqual(len(got), 3)

    def test_pure_noise_finds_nothing(self):
        sig = 0.5 + self.rng.normal(0, 0.02, len(self.t))
        self.assertEqual(len(_rescue_candidates(sig, self.valid, FPS, self.movement)), 0)

    def test_drift_with_wiggles_finds_nothing(self):
        sig = 0.5 + 0.05 * self.t + self.rng.normal(0, 0.015, len(self.t))
        self.assertEqual(len(_rescue_candidates(sig, self.valid, FPS, self.movement)), 0)

    def test_mostly_interpolated_rep_is_rejected(self):
        # swallow most of the first hump: the pose was never seen across its
        # body, so whatever the signal shape there, it is not evidence
        sig = _humps(self.t, [1.0, 4.0, 7.0])
        hole = (self.t > 1.2) & (self.t < 2.3)
        valid = self.valid.copy()
        valid[hole] = False
        sig[hole] = np.interp(self.t[hole], self.t[~hole], sig[~hole])
        got = _rescue_candidates(sig, valid, FPS, self.movement)
        turns = [p / FPS for _, p, _ in got]
        self.assertFalse(any(1.0 < x < 3.5 for x in turns),
                         f"counted a rep inside the untracked stretch: {turns}")
        self.assertEqual(len(got), 2)

    def test_one_legged_sway_is_rejected(self):
        # rises and then just stays up: the return leg carries no displacement
        # and no velocity, so however real the climb looked, it is not a rep
        sig = np.full(len(self.t), 0.5)
        rise = (self.t > 1.0) & (self.t < 2.0)
        sig[rise] = 0.5 + 0.5 * np.sin(np.pi * (self.t[rise] - 1.0) / 2.0)  # up only
        sig[self.t >= 2.0] = 1.0                                            # stays up
        self.assertEqual(len(_rescue_candidates(sig, self.valid, FPS, self.movement)), 0)


if __name__ == "__main__":
    unittest.main()
