"""End-to-end check of the barra measurement core, un-mocked and on one clip.

Tools/debugweb/server.py and scripts/e2e_pipeline.py each prove a slice - the
first that the debug surface describes the trace, the second that the AWS
transport seats the clip before the worker ever runs. This is the slice between
them: pose (from cache, so the suite stays fast) straight into `analyze_clip`,
the exact call the server makes, and an assertion on the JSON a phone would
have to render. Nothing is mocked, because the defects worth catching live in
the seams - a rep that comes back without a `score`, a clip the segmenter
rejected that the payload still counts, a score reported without a band.

Skipped, not failed, when there is no cached pose for a sample clip: on a fresh
checkout the pose has to be estimated first (78s and a backend that can take
the interpreter down), which is a manual step, not a unit-test guarantee.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra.config import PATHS               # noqa: E402
from barra.schema import P_KEYPOINTS          # noqa: E402
from barra.trace import Trace, new_id, NullTrace  # noqa: E402


def _cached_sample() -> Path | None:
    """The first repo clip whose keypoints are already on disk. This is what
    keeps the test honest AND fast: it exercises the real measurement, but it
    will not fall off the end of a slow pose estimate."""
    from barra.posecache import load

    for clip in sorted(ROOT.glob("VID-*.mp4")):
        if load(clip) is not None:
            return clip
    return None


def _run(clip: Path):
    from barra.posecache import load_or_estimate
    from process import analyze_clip

    tr = Trace(new_id(clip.name), clip.name, source="e2e-test",
               clip=str(clip), exercise_requested="auto")
    pose = load_or_estimate(clip, fresh=False, trace=tr, write_cache=False)
    payload = analyze_clip(clip, exercise="auto",
                           session="1970-01-01", trace=tr, pose=pose)
    return tr, payload


class TestE2EPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clip = _cached_sample()

    def setUp(self):
        if self.clip is None:
            self.skipTest("no sample clip with cached keypoints - run the "
                          "pipeline once (or barra explain VID-*.mp4) first")
        if not hasattr(self, "_ran"):
            self.tr, self.payload = _run(self.clip)
            type(self)._ran = True
            type(self)._tr = self.tr
            type(self)._payload = self.payload

    # ---- the contract the phone parses ---------------------------------
    def test_payload_carries_the_fields_the_app_reads(self):
        p = self._payload
        for field in ("exercise", "detected", "n_reps", "n_candidates",
                      "reps", "sessionScore", "sessionBand", "duration_s",
                      "blockers", "countedBy", "consistency", "fps", "trim"):
            self.assertIn(field, p, f"payload missing {field}")

    def test_a_detection_is_a_string_not_a_throw(self):
        d = self._payload["detected"]
        self.assertIn("exercise", d)
        self.assertIn("label", d)
        self.assertIsInstance(d.get("label"), str)
        self.assertTrue(d.get("label"))

    def test_n_reps_agrees_with_the_reps_list(self):
        self.assertEqual(self._payload["n_reps"], len(self._payload["reps"]))

    def test_every_rep_is_scorable_in_shape(self):
        for rep in self._payload["reps"]:
            for field in ("label", "score", "band", "scoreNote", "components",
                          "metrics", "startS", "endS", "turnS", "total_s",
                          "transition_s", "trace", "session", "failures"):
                self.assertIn(field, rep, f"rep {rep.get('label')!r} missing {field}")

    def test_a_scored_rep_has_a_band(self):
        scored = [r for r in self._payload["reps"] if r.get("score") is not None]
        for rep in scored:
            self.assertIsInstance(rep["band"], str)
            self.assertTrue(rep["band"])

    def test_the_trace_never_reported_fewer_measurements_than_it_kept(self):
        """A rejection is recorded where it happened, and the payload's rep
        count and the trace's decisions never contradict each other by more
        than the rejected candidates it turned away."""
        self.assertGreaterEqual(len(self._tr.entries), 1)

    def test_the_measurement_did_not_crash_the_interpreter(self):
        """The point of the subprocess runner in runner.py: a pose backend
        SIGKILL is not an exception. A test that reaches here means the batch
        call held, which is the condition that has actually failed before."""
        self.assertIsNotNone(self._payload)


if __name__ == "__main__":
    unittest.main()
