"""The contract between the server and the phone.

Every field the app reads must be present on every path, including the paths
where nothing could be measured. A client that has to ask whether a field exists
ends up guessing what its absence means, and a clip that produced no reps is a
complete answer rather than a partial one.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

# Keys the Kotlin client reads. Kept in one list so adding a field to the app
# without adding it to the server fails here rather than at a user's phone.
REQUIRED = [
    "headline", "narrative", "nextSession",
    "exercise", "detected", "trim", "session",
    "sessionScore", "sessionBand",
    "n_reps", "n_candidates", "fps", "duration_s",
    "reps", "sessions", "blockers",
]

REP_REQUIRED = [
    "session", "label", "transition_s", "total_s", "class", "metrics",
    "plausible", "problems", "startS", "endS", "turnS",
    "score", "band", "scoreNote", "components", "aside", "trace",
]


class TestPayloadShape(unittest.TestCase):
    def setUp(self):
        from process import _empty
        self._empty = _empty

    def test_every_key_present_when_nothing_could_be_measured(self):
        payload = self._empty("auto", ["no video arrived"])
        missing = [k for k in REQUIRED if k not in payload and k not in
                   ("headline", "narrative", "nextSession")]
        self.assertEqual(missing, [], f"missing on the empty path: {missing}")

    def test_empty_payload_says_unmeasured_not_zero(self):
        """A score of 0 and no score are different facts. The app draws the
        first as a broken rep and the second as an em dash."""
        payload = self._empty("auto", ["nothing"])
        self.assertIsNone(payload["sessionScore"])
        self.assertEqual(payload["sessionBand"], "unmeasured")
        self.assertEqual(payload["n_reps"], 0)

    def test_extra_fields_override_defaults(self):
        payload = self._empty("auto", ["x"], detected={"label": "Pull-up"})
        self.assertEqual(payload["detected"]["label"], "Pull-up")

    def test_prose_keys_are_the_only_ones_the_model_owns(self):
        """process_job carries every measurement key through untouched. If that
        ever becomes an allow-list again, a new field silently stops reaching
        the phone."""
        source = (ROOT / "server" / "process.py").read_text()
        self.assertIn('prose = {"headline", "narrative", "nextSession"}', source)
        self.assertIn("if key not in prose:", source)


class TestTrace(unittest.TestCase):
    def test_trace_is_downsampled_to_a_fixed_length(self):
        import numpy as np

        from process import _trace
        signal = np.sin(np.linspace(0, 3.14, 400))
        self.assertEqual(len(_trace(signal, 0, 399)), 48)
        self.assertEqual(len(_trace(signal, 0, 5, n=12)), 12)

    def test_a_too_short_rep_yields_no_trace(self):
        import numpy as np

        from process import _trace
        self.assertEqual(_trace(np.zeros(10), 0, 2), [])

    def test_downsampling_preserves_a_stall(self):
        """The shape is the point. A steady ascent and one that stops halfway
        must still be distinguishable after being cut to 48 points, or the
        phone draws two identical lines for two different reps.

        Measured the same way the quality proxy measures it: the fraction of
        the ascent making no real progress.
        """
        import numpy as np

        from process import _trace

        def stall_fraction(points):
            step = np.diff(points)
            rate = (points[-1] - points[0]) / len(step)
            return float(np.mean(step < 0.2 * rate))

        steady = np.linspace(0.0, 1.0, 200)
        stalled = np.concatenate([
            np.linspace(0.0, 0.5, 60), np.full(80, 0.5), np.linspace(0.5, 1.0, 60)
        ])
        self.assertLess(stall_fraction(_trace(steady, 0, 199)), 0.1)
        self.assertGreater(stall_fraction(_trace(stalled, 0, 199)), 0.3)


if __name__ == "__main__":
    unittest.main()
