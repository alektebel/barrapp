"""The keypoint cache must not change what the pipeline measures.

A cache exists to make a run cheaper, never different. The one thing the
keypoint table does not carry is the frame rate - it stores frames - so a cache
hit must not invent one: it reports a falsy rate and the caller falls through to
the rate it probed from the container (`pose.fps or info["fps"]`). When this
returned a default 30.0 instead, every 24 fps clip in the sample corpus was
measured a quarter too fast on its SECOND run, and only on its second run:
durations, tempo ratios and the minimum-rep-length gate all moved when nothing
but the cache had changed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from barra import posecache
from barra.config import Paths


class KeypointCacheRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self._paths = posecache.PATHS
        posecache.PATHS = Paths(root=Path(self.tmp.name))
        rng = np.random.default_rng(0)
        self.kp = rng.random((12, 17, 3)).astype(np.float32)
        self.video = Path(self.tmp.name) / "clip.mp4"

    def tearDown(self) -> None:
        posecache.PATHS = self._paths
        self.tmp.cleanup()

    def test_keypoints_survive_the_round_trip(self):
        self.assertIsNone(posecache.load(self.video))
        self.assertIsNotNone(posecache.store(self.video, self.kp))
        back = posecache.load(self.video)
        self.assertIsNotNone(back)
        np.testing.assert_allclose(back[:, :, :2], self.kp[:, :, :2], rtol=1e-5)

    def test_a_cache_hit_does_not_invent_a_frame_rate(self):
        posecache.store(self.video, self.kp)
        pose = posecache.load_or_estimate(self.video)
        self.assertEqual(pose.source, "cache")
        self.assertFalse(pose.fps, "a cache hit must not report a frame rate it "
                                   "does not have - the caller probes its own")

    def test_an_explicit_fallback_is_honoured(self):
        posecache.store(self.video, self.kp)
        pose = posecache.load_or_estimate(self.video, fallback_fps=24.0)
        self.assertEqual(pose.fps, 24.0)

    def test_fresh_skips_the_cache(self):
        posecache.store(self.video, self.kp)
        with self.assertRaises(SystemExit):
            # No backend can open a file that is not a video, so `fresh` having
            # bypassed the cache is exactly what the failure proves.
            posecache.load_or_estimate(self.video, fresh=True)


if __name__ == "__main__":
    unittest.main()
