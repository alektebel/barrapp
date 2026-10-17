"""Pose frame budget (barra/pose/budget.py): long clips are posed on every
k-th frame with fps / k, so every `frame / fps` time stays in source seconds;
clips that would need an effective rate under MIN_POSE_FPS are refused."""
from __future__ import annotations

import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra import config  # noqa: E402
from barra.i18n import localize_payload  # noqa: E402
from barra.pose import budget, parallel  # noqa: E402


class StrideMath(unittest.TestCase):
    def test_default_budget(self):
        self.assertEqual(config.MAX_POSE_FRAMES, 4000)
        self.assertEqual(config.MIN_POSE_FPS, 10.0)

    def test_stride_is_ceil_of_frames_over_budget(self):
        self.assertEqual(budget.pose_stride(316), 1)
        self.assertEqual(budget.pose_stride(4000), 1)
        self.assertEqual(budget.pose_stride(4001), 2)
        self.assertEqual(budget.pose_stride(9000), 3)
        self.assertEqual(budget.pose_stride(12000), 3)
        self.assertEqual(budget.pose_stride(0), 1)

    def test_budget_is_always_met(self):
        for n in (1, 3999, 4000, 4001, 8000, 8001, 9100, 23456):
            k = budget.pose_stride(n)
            self.assertLessEqual(budget.sampled_count(n, k), config.MAX_POSE_FRAMES)

    def test_env_overrides_the_budget(self):
        with mock.patch.object(config, "MAX_POSE_FRAMES", 1000):
            self.assertEqual(budget.pose_stride(2500), 3)

    def test_sampled_count(self):
        for n in (1, 10, 11, 100):
            for k in (1, 2, 3, 7):
                self.assertEqual(budget.sampled_count(n, k), len(range(0, n, k)))


class FailFast(unittest.TestCase):
    def test_the_two_production_clips(self):
        # 150 s @ 60 fps -> stride 3 -> 20 fps: analysable.
        self.assertFalse(budget.too_long(9000, 60.0))
        # 364 s @ 25 fps -> stride 3 -> 8.3 fps: refused.
        self.assertTrue(budget.too_long(9100, 25.0))

    def test_threshold_is_exactly_min_fps(self):
        # 30 fps: stride 3 -> 10 fps is fine, stride 4 -> 7.5 is not.
        self.assertFalse(budget.too_long(12000, 30.0))
        self.assertTrue(budget.too_long(12001, 30.0))

    def test_max_seconds_is_consistent_with_too_long(self):
        for fps in (24.0, 25.0, 30.0, 60.0):
            s = budget.max_clip_seconds(fps)
            self.assertFalse(budget.too_long(int(s * fps), fps), fps)
            self.assertTrue(budget.too_long(int((s + 2) * fps) + 1, fps), fps)

    def test_unknown_probe_is_not_refused(self):
        self.assertFalse(budget.too_long(0, 30.0))
        self.assertFalse(budget.too_long(99999, 0.0))

    def test_message_is_spanish(self):
        out = localize_payload({"blockers": ["video_too_long:320"], "i18n": {}})
        text = out["blockers"][0]
        self.assertIn("demasiado largo", text)
        self.assertIn("320 segundos", text)
        self.assertEqual(out["i18n"]["untranslated"], [])


def _install_fake_mediapipe(seen: list[int]):
    """A mediapipe whose landmarker records each timestamp and returns a pose
    whose x is that timestamp, so a row says which frame it came from."""
    class Landmarker:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def detect_for_video(self, image, ts):
            seen.append(ts)
            lm = types.SimpleNamespace(x=ts / 1e6, y=0.5, visibility=1.0, presence=1.0)
            return types.SimpleNamespace(pose_landmarks=[[lm] * 33])

    vision = types.SimpleNamespace(
        PoseLandmarkerOptions=lambda **k: k,
        RunningMode=types.SimpleNamespace(VIDEO=1),
        PoseLandmarker=types.SimpleNamespace(create_from_options=lambda o: Landmarker()))
    mp = types.ModuleType("mediapipe")
    mp.Image = lambda image_format, data: data
    mp.ImageFormat = types.SimpleNamespace(SRGB=1)
    tasks = types.ModuleType("mediapipe.tasks")
    py = types.ModuleType("mediapipe.tasks.python")
    py.BaseOptions = lambda **k: k
    py.vision = vision
    tasks.python = py
    mp.tasks = tasks
    return {"mediapipe": mp, "mediapipe.tasks": tasks,
            "mediapipe.tasks.python": py, "mediapipe.tasks.python.vision": vision}


class StubbedPose(unittest.TestCase):
    N, FPS = 101, 50.0

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.tmp.name) / "clip.avi"
        w = cv2.VideoWriter(str(cls.video), cv2.VideoWriter_fourcc(*"MJPG"), cls.FPS, (64, 48))
        for _ in range(cls.N):
            w.write(np.zeros((48, 64, 3), np.uint8))
        w.release()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _range(self, stride, warm=0, start=0, end=-1):
        from barra.pose import mediapipe_backend as mb
        seen: list[int] = []
        with mock.patch.dict(sys.modules, _install_fake_mediapipe(seen)):
            rows = mb.pose_range(Path("m.task"), self.video, warm, start, end, self.FPS, stride)
        return rows, seen

    def test_rows_are_ceil_n_over_k_and_timestamps_stay_in_source_time(self):
        for k in (1, 2, 3, 4):
            rows, seen = self._range(k)
            n = len(rows)
            self.assertEqual(n, math.ceil(self.N / k), k)
            self.assertEqual(seen, sorted(set(seen)))                    # strictly increasing
            self.assertEqual(seen, [int(i * k * 1000 / self.FPS) for i in range(n)])

    def test_chunks_cover_the_same_frames_as_the_sequential_pass(self):
        k = 3
        whole, _ = self._range(k)
        sampled = budget.sampled_count(self.N, k)
        chunks = parallel.plan_chunks(sampled, 3, overlap=4, min_chunk=1)
        parts = []
        for i, c in enumerate(chunks):
            end = -1 if i == len(chunks) - 1 else c.end * k
            part, _ = self._range(k, c.warm * k, c.start * k, end)
            parts.append(part)
        stitched = parallel.stitch(chunks, parts)
        self.assertEqual(stitched.shape, whole.shape)
        # Same frames; x encodes the frame's timestamp.
        np.testing.assert_allclose(stitched[:, 0, 0], whole[:, 0, 0])

    def test_backend_reports_effective_fps_and_stride(self):
        from barra.pose import mediapipe_backend as mb
        seen: list[int] = []
        with mock.patch.dict(sys.modules, _install_fake_mediapipe(seen)), \
                mock.patch.object(config, "MAX_POSE_FRAMES", 40), \
                mock.patch.object(mb, "ensure_model", return_value=Path("m.task")):
            res = mb.MediapipeBackend().estimate(self.video)
        k = math.ceil(self.N / 40)
        self.assertEqual(res.stride, k)
        self.assertEqual(len(res.keypoints), math.ceil(self.N / k))
        self.assertAlmostEqual(res.fps, self.FPS / k)
        self.assertLessEqual(len(res.keypoints), 40)


class ProcessFailsFast(unittest.TestCase):
    def test_too_long_clip_ends_with_a_spanish_blocker_and_never_poses(self):
        sys.path.insert(0, str(ROOT / "server"))
        # A private copy: other tests leave a stubbed analyze_clip on the
        # shared `process` module.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "process_budget_copy", ROOT / "server" / "process.py")
        process = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(process)
        import barra.ingest as ingest
        import barra.pose as pose_pkg
        info = {"ok": True, "fps": 25.0, "frames": 9100, "width": 1280,
                "height": 720, "duration_s": 364.0}
        with tempfile.TemporaryDirectory() as d:
            clip = Path(d) / "c.mp4"
            clip.write_bytes(b"x")
            with mock.patch.object(ingest, "probe_video", return_value=info), \
                    mock.patch.object(pose_pkg, "available_backends", return_value=["mediapipe"]), \
                    mock.patch.object(pose_pkg, "get_backend",
                                      side_effect=AssertionError("pose must not run")):
                out = process.analyze_clip(clip, "auto")
        self.assertEqual(out["blockers"], ["video_too_long:320"])
        self.assertEqual(out["n_reps"], 0)
        text = localize_payload(dict(out))["blockers"][0]
        self.assertIn("demasiado largo", text)


class RepTimesUnchanged(unittest.TestCase):
    def test_peak_times_in_seconds_match_stride_one(self):
        from scipy.signal import find_peaks
        fps, n = 60.0, 900
        t = np.arange(n) / fps
        y = np.sin(2 * np.pi * 0.5 * t)             # a rep every 2 s
        full, _ = find_peaks(y, prominence=0.5)
        k = 3
        sub, _ = find_peaks(y[::k], prominence=0.5)
        t_full = full / fps
        t_sub = sub / (fps / k)
        self.assertEqual(len(t_full), len(t_sub))
        np.testing.assert_allclose(t_sub, t_full, atol=k / fps)


if __name__ == "__main__":
    unittest.main()
