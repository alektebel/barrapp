"""Label-free invariants for the two stages upstream of the fault layer.

None of these tests needs a labelled clip. Each one states a property the
answer must have whatever the answer is - add frames that contain no reps and
the count cannot change; film the same set twice as loudly and the quiet copy
is still counted; hand the pipeline noise and it must invent nothing. A
property is falsifiable on synthetic footage in a way an accuracy number on
eight clips is not.

Covers findings C4 (segmentation constants), C5 (clip-wide amplitude poisons
the standard pass), C6 (whole-clip percentiles include the walk-in) and C8
(the "confidence" number is a margin) from feedback.md.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra import schema as S
from barra.classify import CERTAINTY_KIND, classify, features
from barra.config import THRESHOLDS
from barra.ingest import segment_reps_verbose
from barra.movements import resolve

FPS = 30.0
TORSO, ARM = 120.0, 140.0


def _fill(kp, f, points, rng):
    for name, x, y in points:
        kp[f, S.KP_INDEX[name]] = (x + rng.normal(0, 0.6), y + rng.normal(0, 0.6), 0.95)
    for n in ("left_eye", "right_eye", "left_ear", "right_ear"):
        kp[f, S.KP_INDEX[n]] = kp[f, S.KP_INDEX["nose"]]


def _hanging(kp, f, bx, by, rise, clearance, rng):
    """One frame of a bar movement: hands on the bar at (bx, by), the body
    lifted `rise` of the way from a dead hang to `clearance` above the bar."""
    sh = by + ARM - rise * (ARM + clearance * TORSO)
    hip = sh + TORSO
    _fill(kp, f, (
        ("left_wrist", bx - 40, by), ("right_wrist", bx + 40, by),
        ("left_elbow", bx - 45, (by + sh) / 2), ("right_elbow", bx + 45, (by + sh) / 2),
        ("left_shoulder", bx - 38, sh), ("right_shoulder", bx + 38, sh),
        ("left_hip", bx - 22, hip), ("right_hip", bx + 22, hip),
        ("left_knee", bx - 24, hip + 90), ("right_knee", bx + 24, hip + 90),
        ("left_ankle", bx - 24, hip + 175), ("right_ankle", bx + 24, hip + 175),
        ("nose", bx, sh - 30),
    ), rng)


def _standing(kp, f, x, rng):
    """One frame of somebody stood on the ground with their arms at their
    sides - the walk to the bar, and the walk away from it.

    This is the frame that broke the percentiles. The wrists sit at the hips,
    a whole torso-length BELOW the shoulders, so `shoulder_above_hands` reads
    +1.0 here - further above the hands than the top of any muscle-up.
    """
    sh = 300.0
    hip = sh + TORSO
    _fill(kp, f, (
        ("left_wrist", x - 26, hip), ("right_wrist", x + 26, hip),
        ("left_elbow", x - 30, (sh + hip) / 2), ("right_elbow", x + 30, (sh + hip) / 2),
        ("left_shoulder", x - 38, sh), ("right_shoulder", x + 38, sh),
        ("left_hip", x - 22, hip), ("right_hip", x + 22, hip),
        ("left_knee", x - 24, hip + 90), ("right_knee", x + 24, hip + 90),
        ("left_ankle", x - 24, hip + 175), ("right_ankle", x + 24, hip + 175),
        ("nose", x, sh - 30),
    ), rng)


def bar_set(n_reps=3, fpr=60, clearance=0.5, rise_frac=1.0, bx=300.0, seed=0):
    """A set of `n_reps` on a bar, and nothing else."""
    rng = np.random.default_rng(seed)
    kp = np.zeros((n_reps * fpr, 17, 3), np.float32)
    for f in range(len(kp)):
        rise = rise_frac * np.sin(np.pi * ((f % fpr) / fpr)) ** 2
        _hanging(kp, f, bx, 200.0, rise, clearance, rng)
    return kp


def walk(n=40, x0=300.0, x1=900.0, seed=1):
    """Somebody walking across the frame, doing nothing."""
    rng = np.random.default_rng(seed)
    kp = np.zeros((n, 17, 3), np.float32)
    for f in range(n):
        _standing(kp, f, x0 + (x1 - x0) * (f / max(1, n - 1)), rng)
    return kp


class TestPrefixInvariance(unittest.TestCase):
    """C6 - adding frames that contain no movement cannot change the label."""

    def test_a_pull_up_stays_a_pull_up_behind_a_walk_in(self):
        """The failure this pins: the walk-in puts the hands at the hips, a
        whole torso-length below the shoulders, and a whole-clip p95 read that
        as the shoulders finishing far above the bar - a muscle-up."""
        bare = bar_set(clearance=-0.30)
        padded = np.concatenate([walk(x0=900.0, x1=300.0), bare,
                                 walk(x0=300.0, x1=900.0)])
        self.assertEqual(classify(bare, fps=FPS).exercise, "pull_up")
        self.assertEqual(classify(padded, fps=FPS).exercise, "pull_up")

    def test_a_muscle_up_stays_a_muscle_up(self):
        bare = bar_set(clearance=0.50)
        padded = np.concatenate([walk(x0=900.0, x1=300.0), bare,
                                 walk(x0=300.0, x1=900.0)])
        self.assertEqual(classify(bare, fps=FPS).exercise, "muscle_up")
        self.assertEqual(classify(padded, fps=FPS).exercise, "muscle_up")

    def test_the_deciding_percentile_barely_moves(self):
        """Not just the label: the number the label is decided on."""
        bare = features(bar_set(clearance=0.50), FPS)
        padded = features(np.concatenate([walk(x0=900.0, x1=300.0),
                                          bar_set(clearance=0.50),
                                          walk(x0=300.0, x1=900.0)]), FPS)
        self.assertAlmostEqual(bare["shoulder_above_hands_p95"],
                               padded["shoulder_above_hands_p95"], delta=0.10)
        # ...while the whole-clip number, kept for the trace, moves a lot -
        # which is the evidence that the scoping is what did the work.
        self.assertGreater(padded["shoulder_above_hands_p95_clip"],
                           bare["shoulder_above_hands_p95"] + 0.30)

    def test_a_clip_with_no_anchored_window_still_reports_something(self):
        """Nothing anchored means the whole clip is used, not an empty set:
        an unmeasurable clip must reach the gates and be refused there, with a
        reason, rather than arriving as NaN."""
        f = features(walk(n=90, x0=0.0, x1=1800.0), FPS)
        self.assertEqual(f["on_bar_frac"], 1.0)
        self.assertTrue(np.isfinite(f["shoulder_above_hands_p95"]))
        self.assertEqual(classify(walk(n=90, x0=0.0, x1=1800.0),
                                  fps=FPS).exercise, "unknown")


class TestPerSpanAmplitude(unittest.TestCase):
    """C5 - one span's amplitude must not set the bar for another."""

    def setUp(self):
        self.movement = resolve("pull_up")

    def two_sets(self):
        """A loud set, a walk to another bar, then a quiet one. Both are real;
        the second is shallow, as a set gets when the athlete is tired."""
        return np.concatenate([
            bar_set(n_reps=3, clearance=0.50, bx=300.0, seed=0),
            walk(n=40, x0=300.0, x1=900.0),
            bar_set(n_reps=3, clearance=0.50, rise_frac=0.15, bx=900.0, seed=2),
        ])

    def test_both_sets_are_counted(self):
        reps, reasons = segment_reps_verbose(self.two_sets(), FPS, self.movement)
        self.assertEqual(len(reps), 6, f"missed a set: {reasons}")

    def spans(self, kp):
        """(amplitude) per active span, measured the way the segmenter does."""
        from barra.ingest import _clean_signal, _runs, _smooth_window, active_mask
        from barra.movements import tracking_signal
        sig, valid = _clean_signal(*tracking_signal(kp, self.movement))
        active = active_mask(kp, FPS, self.movement)
        measured = valid & active
        half = _smooth_window(len(sig)) // 2
        out = []
        for lo, hi in _runs(active):
            i, j = (lo + half, hi - half) if hi - lo > 4 * half else (lo, hi)
            s = sig[i:j + 1][measured[i:j + 1]]
            out.append(float(np.percentile(s, 97) - np.percentile(s, 15)))
        clip = float(np.percentile(sig[measured], 97)
                     - np.percentile(sig[measured], 15))
        return out, clip

    def test_the_quiet_set_would_not_survive_the_clip_wide_threshold(self):
        """The mechanism, stated as numbers rather than as a claim: the quiet
        set's whole amplitude is smaller than the prominence a clip-wide
        amplitude would have demanded of a single turnaround inside it. That
        is the shape of the bug - not a rep judged and rejected, but a rep no
        threshold could ever have proposed."""
        amps, clip = self.spans(self.two_sets())
        self.assertEqual(len(amps), 2)
        loud, quiet = max(amps), min(amps)
        self.assertLess(quiet, THRESHOLDS.peak_prominence * clip)
        self.assertGreater(loud, THRESHOLDS.peak_prominence * clip)
        # And the quiet set is still well clear of the stillness floor, so it
        # is being counted because it moved, not because the bar was lowered.
        self.assertGreater(quiet, 1.5 * THRESHOLDS.min_span_amplitude)

    def test_a_span_that_never_moved_is_not_given_its_own_low_threshold(self):
        """The risk a per-span threshold introduces, pinned: 0.35 of nothing
        is nothing, and pose jitter clears nothing."""
        rng = np.random.default_rng(3)
        hang = bar_set(n_reps=1, fpr=180, clearance=0.5, rise_frac=0.0)
        hang[:, :, :2] += rng.normal(0, 1.5, size=(len(hang), 17, 2))
        amps, _ = self.spans(hang)
        self.assertLess(max(amps), THRESHOLDS.min_span_amplitude)
        reps, reasons = segment_reps_verbose(hang, FPS, self.movement)
        self.assertEqual(reps, [])
        self.assertTrue(reasons, "a refusal must come with a reason")

    def test_a_walk_on_its_own_produces_no_reps(self):
        reps, _ = segment_reps_verbose(walk(n=120, x0=0.0, x1=2400.0), FPS,
                                       self.movement)
        self.assertEqual(reps, [])

    def test_noise_produces_no_reps(self):
        """A per-span threshold is a lower bar, so the null has to be re-run:
        relaxing a threshold is only safe if it still refuses nothing."""
        rng = np.random.default_rng(11)
        kp = bar_set(n_reps=1, fpr=180, clearance=0.5, rise_frac=0.0)
        kp[:, :, :2] += rng.normal(0, 1.5, size=(len(kp), 17, 2))
        reps, _ = segment_reps_verbose(kp, FPS, self.movement)
        self.assertEqual(reps, [])


class TestSegmentationConstants(unittest.TestCase):
    """C4 - the numbers segmentation decides on live in config.py too."""

    MIRRORED = ("peak_prominence", "rescue_prominence", "max_half_rep_s")

    def test_ingest_holds_no_private_copy(self):
        src = (ROOT / "barra" / "ingest.py").read_text()
        body = src[src.index("def segment_reps("):]
        # The literals these thresholds replaced, as they appeared inline.
        for literal, field in (("0.35 * amplitude", "peak_prominence"),
                               ("0.15 * amplitude", "rescue_prominence"),
                               ("max_half_rep_s: float = 4.0", "max_half_rep_s")):
            self.assertNotIn(literal, body,
                             f"segmentation pins {field} locally again")

    def test_the_thresholds_exist_and_are_frozen(self):
        for name in self.MIRRORED:
            self.assertIsInstance(getattr(THRESHOLDS, name), float)
        with self.assertRaises(Exception):
            THRESHOLDS.peak_prominence = 0.5    # type: ignore[misc]


class TestCertaintyIsNamed(unittest.TestCase):
    """C8 - the number beside a detection is a margin, and says so."""

    def test_every_detection_names_the_kind(self):
        for kp in (bar_set(clearance=0.50), bar_set(clearance=-0.30)):
            self.assertEqual(classify(kp, fps=FPS).certainty, CERTAINTY_KIND)

    def test_the_margin_is_the_same_number_under_its_real_name(self):
        c = classify(bar_set(clearance=0.50), fps=FPS)
        self.assertEqual(c.margin, c.confidence)

    def test_no_branch_claims_a_probability(self):
        """A margin capped at 0.98 is not a 98% chance, and nothing in the
        module may describe it as one."""
        src = (ROOT / "barra" / "classify.py").read_text().lower()
        self.assertNotIn("probability that", src)
        self.assertIn("not a probability", src)


if __name__ == "__main__":
    unittest.main()
