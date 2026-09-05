"""The technique artifacts: the cut and the rep stills.

These land on disk beside the trace, so a vision pass (or a human) can study
what was measured. They are best-effort by design - every assertion here is
about what MUST exist when the inputs are good, and that bad inputs produce
empty artifacts rather than an error.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from barra.frames import cut_technique, grab_stills, technique_artifacts

# The smallest clip in the repo; a second of it is enough for both decoders.
CLIP = ROOT / "VID-20260827-WA0011.mp4"


def _report(start: float, end: float, turns: list[float]) -> dict:
    return {
        "trim": {"startS": start, "endS": end},
        "reps": [
            {"label": f"r{i + 1}", "startS": t - 0.5, "turnS": t, "endS": t + 0.5}
            for i, t in enumerate(turns)
        ],
    }


@unittest.skipUnless(CLIP.exists(), "sample clip not in the repo")
class TestFrames(unittest.TestCase):
    def test_cut_produces_a_playable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = cut_technique(CLIP, 0.5, 2.5, Path(tmp) / "technique.mp4")
            self.assertIsNotNone(out)
            self.assertGreater(out.stat().st_size, 0)

    def test_cut_rejects_an_inverted_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(cut_technique(CLIP, 3.0, 1.0, Path(tmp) / "x.mp4"))

    def test_stills_land_one_per_moment(self):
        with tempfile.TemporaryDirectory() as tmp:
            stills = grab_stills(CLIP, [0.5, 1.0, 1.5], Path(tmp))
            self.assertEqual(len(stills), 3)
            for p in stills:
                self.assertGreater(p.stat().st_size, 0)
                self.assertTrue(p.name.endswith(".jpg"))

    def test_artifacts_carry_window_and_turning_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = technique_artifacts(
                CLIP, _report(1.0, 4.0, [1.5, 2.5, 3.5]), Path(tmp), "trace-x")
            self.assertIsNotNone(art.clip)
            # the window's first frame, then one still per rep
            self.assertEqual(len(art.stills), 4)
            self.assertEqual(art.labels[0], "start of the technique")
            self.assertEqual(art.labels[1:], ["r1 turning point",
                                              "r2 turning point",
                                              "r3 turning point"])
            self.assertTrue(all(s.exists() for s in art.stills))

    def test_artifacts_empty_without_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = technique_artifacts(CLIP, {"trim": None, "reps": []},
                                      Path(tmp), "trace-y")
            self.assertIsNone(art.clip)
            self.assertEqual(art.stills, [])


if __name__ == "__main__":
    unittest.main()
