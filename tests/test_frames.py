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

    def test_artifacts_walk_each_selected_rep_through_its_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = technique_artifacts(
                CLIP, _report(1.0, 4.0, [1.5, 2.5, 3.5]), Path(tmp), "trace-x")
            self.assertIsNotNone(art.clip)
            # the window's first frame, then five moments per rep
            self.assertEqual(len(art.stills), 1 + 3 * 5)
            self.assertEqual(len(art.labels), len(art.stills))
            self.assertEqual(art.frames[0].rep, "")
            self.assertEqual([f.moment for f in art.frames[1:6]],
                             ["start", "mid-first", "turn", "mid-second", "end"])
            self.assertEqual({f.rep for f in art.frames[1:]}, {"r1", "r2", "r3"})
            # every still names its rep, phase and source timestamp
            for f in art.frames[1:]:
                self.assertIn(f.rep, f.label)
                self.assertIn(f"{f.t_s:.2f}s", f.label)
            self.assertTrue(all(s.exists() for s in art.stills))
            self.assertEqual(art.selected_reps, ["r1", "r2", "r3"])

    def test_selection_is_early_middle_late_under_the_budget(self):
        from barra.frames import MAX_STILLS, select_reps
        reps = [{"label": f"r{i}"} for i in range(1, 20)]
        self.assertEqual([r["label"] for r in select_reps(reps)], ["r1", "r10", "r19"])
        with tempfile.TemporaryDirectory() as tmp:
            art = technique_artifacts(
                CLIP, _report(0.5, 5.0, [0.6 + 0.2 * i for i in range(19)]),
                Path(tmp), "trace-z")
            self.assertLessEqual(len(art.stills), MAX_STILLS)
            self.assertEqual(art.selected_reps, ["r1", "r10", "r19"])

    def test_labels_stay_aligned_when_a_frame_fails(self):
        """A still that failed to decode drops out of both lists together."""
        from unittest import mock

        import barra.frames as frames

        real = frames.grab_frames

        def flaky(video, moments, out_dir, prefix="frame"):
            return [(i, p) for i, p in real(video, moments, out_dir, prefix) if i != 2]

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(frames, "grab_frames", flaky):
            art = technique_artifacts(
                CLIP, _report(1.0, 3.0, [1.5]), Path(tmp), "trace-f")
            self.assertEqual(len(art.stills), 5)
            self.assertEqual([f.moment for f in art.frames],
                             ["start", "start", "turn", "mid-second", "end"])
            self.assertNotIn("mid-first", [f.moment for f in art.frames])

    def test_hold_attempts_sample_onset_sustained_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = {"trim": {"startS": 0.5, "endS": 3.0},
                      "reps": [{"label": "h1", "startS": 1.0, "endS": 2.5}]}
            art = technique_artifacts(CLIP, report, Path(tmp), "trace-h")
            self.assertEqual([f.moment for f in art.frames[1:]],
                             ["onset", "sustained", "exit"])

    def test_artifacts_empty_without_a_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = technique_artifacts(CLIP, {"trim": None, "reps": []},
                                      Path(tmp), "trace-y")
            self.assertIsNone(art.clip)
            self.assertEqual(art.stills, [])


if __name__ == "__main__":
    unittest.main()
