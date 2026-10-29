"""Pose in parallel chunks (barra/pose/parallel.py) - docs/SPEED-PLAN.md step 2.

Pose was 134 s of a production job: ~1,100 frames through MediaPipe heavy on
~2 vCPU. Contiguous frame ranges are posed in separate subprocesses (Lambda
has no /dev/shm, so no multiprocessing) and stitched back in order.

What must not change is the output. MediaPipe's VIDEO mode carries tracking
state from frame to frame, so each chunk starts OVERLAP frames early and drops
them; frames are reached by decoding from the start, never by seeking (OpenCV
seeks in H.264 are not frame-accurate). Any failure falls back to the
sequential path.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.pose import parallel  # noqa: E402


class Planning(unittest.TestCase):
    def test_chunks_cover_every_frame_exactly_once(self):
        for n, w in ((1100, 6), (1000, 4), (301, 3), (7, 2)):
            chunks = parallel.plan_chunks(n, w, overlap=45)
            covered = [i for c in chunks for i in range(c.start, c.end)]
            self.assertEqual(covered, list(range(n)), (n, w))

    def test_warm_up_starts_early_but_never_before_frame_zero(self):
        chunks = parallel.plan_chunks(1100, 6, overlap=45)
        self.assertEqual(chunks[0].warm, 0)
        for c in chunks[1:]:
            self.assertEqual(c.warm, max(0, c.start - 45))

    def test_one_worker_is_the_sequential_path(self):
        self.assertEqual(parallel.plan_chunks(1100, 1, overlap=45),
                         [parallel.Chunk(warm=0, start=0, end=1100)])

    def test_short_clips_are_not_split(self):
        # Splitting below MIN_CHUNK frames costs more warm-up than it saves.
        self.assertEqual(len(parallel.plan_chunks(parallel.MIN_CHUNK, 6, overlap=45)), 1)

    def test_eight_second_clip_splits_with_six_workers(self):
        # 240 frames @ 30 fps ≈ 8 s: floor 120 → two chunks (was sequential at 240).
        chunks = parallel.plan_chunks(240, 6, overlap=45, min_chunk=120)
        self.assertEqual(len(chunks), 2)

    def test_sequential_unless_asked(self):
        """Unset BARRA_POSE_WORKERS keeps local/rollback sequential; production
        pins workers in the worker template."""
        import os
        with mock.patch.dict("os.environ", {}, clear=False), \
                mock.patch("os.cpu_count", return_value=6):
            os.environ.pop("BARRA_POSE_WORKERS", None)
            self.assertEqual(parallel.workers(), 1)
        with mock.patch.dict("os.environ", {"BARRA_POSE_WORKERS": "4"}):
            self.assertEqual(parallel.workers(), 4)

    def test_min_chunk_env_override(self):
        import os
        with mock.patch.dict("os.environ", {"BARRA_POSE_MIN_CHUNK": "60"}):
            self.assertEqual(parallel.min_chunk(), 60)
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("BARRA_POSE_MIN_CHUNK", None)
            self.assertEqual(parallel.min_chunk(), parallel.MIN_CHUNK)


class Stitching(unittest.TestCase):
    def test_chunks_are_stitched_in_frame_order(self):
        chunks = parallel.plan_chunks(10, 3, overlap=2, min_chunk=1)
        parts = [np.full((c.end - c.start, 33, 3), c.start, dtype=np.float32) for c in chunks]
        out = parallel.stitch(chunks, parts)
        self.assertEqual(out.shape, (10, 33, 3))
        self.assertEqual([int(out[i, 0, 0]) for i in range(10)],
                         [c.start for c in chunks for _ in range(c.end - c.start)])

    def test_a_short_middle_part_is_an_error_not_a_silent_gap(self):
        chunks = parallel.plan_chunks(12, 3, overlap=2, min_chunk=1)
        parts = [np.zeros((c.end - c.start, 33, 3)) for c in chunks]
        parts[1] = parts[1][:-1]
        with self.assertRaises(ValueError):
            parallel.stitch(chunks, parts)

    def test_the_last_part_runs_to_the_end_of_the_file(self):
        # CAP_PROP_FRAME_COUNT is an estimate; the last worker reads to EOF,
        # so the clip keeps every decoded frame, as the sequential path does.
        chunks = parallel.plan_chunks(12, 3, overlap=2, min_chunk=1)
        parts = [np.zeros((c.end - c.start, 33, 3)) for c in chunks]
        parts[-1] = np.zeros((len(parts[-1]) + 2, 33, 3))
        self.assertEqual(len(parallel.stitch(chunks, parts)), 14)


class Estimate(unittest.TestCase):
    def test_parallel_runs_each_chunk_and_stitches(self):
        seen = []

        def run(video, chunks, fps):
            seen.extend(chunks)
            return [np.full((c.end - c.start, 33, 3), i, dtype=np.float32) for i, c in enumerate(chunks)]

        with mock.patch.object(parallel, "_run_chunks", side_effect=run):
            kp = parallel.pose_frames(Path("clip.mp4"), n_frames=1100, fps=30.0,
                                      sequential=lambda: self.fail("should not fall back"),
                                      n_workers=4)
        self.assertEqual(kp.shape[0], 1100)
        self.assertEqual(len(seen), 4)

    def test_any_failure_falls_back_to_sequential(self):
        with mock.patch.object(parallel, "_run_chunks", side_effect=RuntimeError("worker 3 died")):
            kp = parallel.pose_frames(Path("clip.mp4"), n_frames=1100, fps=30.0,
                                      sequential=lambda: np.ones((1100, 33, 3)), n_workers=4)
        self.assertEqual(float(kp.sum()), 1100 * 33 * 3)

    def test_one_worker_never_spawns(self):
        with mock.patch.object(parallel, "_run_chunks") as run:
            parallel.pose_frames(Path("clip.mp4"), n_frames=1100, fps=30.0,
                                 sequential=lambda: np.zeros((1100, 33, 3)), n_workers=1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
