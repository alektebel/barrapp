from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

import barra.pose.ultralytics_backend as ub
import barra.pose.ultralytics_chunk as chunk
import barra.pose.ultralytics_parallel as parallel
from barra.pose.ultralytics_parallel import dense_from_samples, split_ranges


def test_split_ranges_covers_all_samples_in_balanced_contiguous_chunks():
    chunks = split_ranges(11, 4)

    assert chunks == [(0, 3), (3, 6), (6, 9), (9, 11)]
    assert [i for start, end in chunks for i in range(start, end)] == list(range(11))


def test_split_ranges_limits_worker_count_to_available_samples():
    assert split_ranges(2, 6) == [(0, 1), (1, 2)]
    assert split_ranges(1, 6) == [(0, 1)]


def test_split_ranges_rejects_empty_input_and_nonpositive_workers():
    assert split_ranges(0, 6) == []
    assert split_ranges(4, 0) == [(0, 4)]


def test_fork_worker_launch_failure_falls_back_to_serialized_subprocess(
    monkeypatch,
):
    monkeypatch.setattr(
        parallel, "_run_fork_workers",
        lambda *_args: (_ for _ in ()).throw(OSError("process limit")),
    )

    def fake_run(command, **_kwargs):
        source, _weights, _size, _device, _confidence, output, report = command[-7:]
        frames = np.load(source)
        np.save(output, np.zeros((len(frames), 17, 3), dtype=np.float32))
        Path(report).write_text('{"fallback_worker": true}')

    from pathlib import Path
    monkeypatch.setattr(parallel.subprocess, "run", fake_run)
    timing, workers = {}, []
    result = parallel.infer_chunks(
        [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(4)],
        "weights.pt", 480, "cpu", 2, worker_mode="fork",
        timing=timing, worker_timing=workers,
    )

    assert result.shape == (4, 17, 3)
    assert timing["fork_fallback"] == 1.0
    assert len(workers) == 2
    assert all(worker["fallback_worker"] for worker in workers)


def test_dense_from_samples_interpolates_coordinates_and_confidence_by_frame():
    samples = np.array([
        [[0.0, 10.0, 0.2]],
        [[20.0, 30.0, 0.8]],
    ], dtype=np.float32)

    dense = dense_from_samples(samples, sample_frames=[0, 2], n_frames=4)

    np.testing.assert_allclose(
        dense[:, 0, :],
        [[0, 10, .2], [10, 20, .5], [20, 30, .8], [20, 30, .8]],
    )


def test_dense_from_samples_requires_matching_nonempty_sample_index():
    samples = np.zeros((2, 17, 3), dtype=np.float32)

    try:
        dense_from_samples(samples, sample_frames=[0], n_frames=4)
    except ValueError as exc:
        assert "sample" in str(exc)
    else:
        raise AssertionError("mismatched frame indices must fail")


def test_yolo_inference_options_keep_default_path_unchanged(monkeypatch):
    from barra.pose.ultralytics_backend import inference_options

    monkeypatch.delenv("BARRA_POSE_WORKERS", raising=False)
    monkeypatch.delenv("BARRA_YOLO_POSE_STRIDE", raising=False)
    monkeypatch.delenv("BARRA_YOLO_POSE_IMGSZ", raising=False)
    monkeypatch.delenv("BARRA_YOLO_POSE_CONF", raising=False)

    assert inference_options() == (1, 1, 640, 0.25)


def test_yolo_inference_options_accept_explicit_round2_settings(monkeypatch):
    from barra.pose.ultralytics_backend import inference_options

    monkeypatch.setenv("BARRA_POSE_WORKERS", "6")
    monkeypatch.setenv("BARRA_YOLO_POSE_STRIDE", "2")
    monkeypatch.setenv("BARRA_YOLO_POSE_IMGSZ", "480")
    monkeypatch.setenv("BARRA_YOLO_POSE_CONF", "0.1")

    assert inference_options() == (6, 2, 480, 0.1)


def test_backend_uses_explicit_chunked_sampling_and_preserves_video_length(
    monkeypatch, tmp_path
):
    class Capture:
        def __init__(self, frames):
            self.frames = iter(frames)

        def isOpened(self):
            return True

        def get(self, prop):
            values = {
                ub.cv2.CAP_PROP_FPS: 30.0,
                ub.cv2.CAP_PROP_FRAME_WIDTH: 4,
                ub.cv2.CAP_PROP_FRAME_HEIGHT: 2,
            }
            return values.get(prop, 0)

        def read(self):
            try:
                return True, next(self.frames)
            except StopIteration:
                return False, None

        def release(self):
            pass

    video_frames = [np.full((2, 4, 3), i, np.uint8) for i in range(5)]
    captures = iter([Capture([]), Capture(video_frames)])
    monkeypatch.setattr(ub.cv2, "VideoCapture", lambda _path: next(captures))
    monkeypatch.setenv("BARRA_POSE_WORKERS", "6")
    monkeypatch.setenv("BARRA_YOLO_POSE_STRIDE", "2")
    monkeypatch.setenv("BARRA_YOLO_POSE_IMGSZ", "480")
    monkeypatch.setenv("BARRA_YOLO_POSE_CONF", "0.12")
    monkeypatch.setenv("BARRA_POSE_WORKER_MODE", "subprocess")

    ultralytics = ModuleType("ultralytics")
    ultralytics.YOLO = lambda _weights: (_ for _ in ()).throw(
        AssertionError("chunked mode must initialize models in child workers")
    )
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics)
    captured = {}

    def infer(frames, weights, imgsz, device, workers, conf, timing=None,
              worker_timing=None, worker_mode="subprocess"):
        captured["frames"] = frames
        captured["config"] = (weights, imgsz, device, workers, conf, worker_mode)
        if timing is not None:
            timing.update(chunk_write_seconds=0.01, workers_wall_seconds=0.02,
                          load_merge_seconds=0.003)
        if worker_timing is not None:
            worker_timing.append({"model_load_seconds": 0.4})
        result = np.zeros((3, 17, 3), np.float32)
        result[:, 0, 0] = [0, 20, 40]
        result[:, 0, 2] = 1
        return result

    monkeypatch.setattr(ub, "infer_chunks", infer)
    backend = ub.UltralyticsBackend(weights=str(tmp_path / "model.pt"))
    result = backend.estimate(
        tmp_path / "clip.mp4"
    )

    assert result.keypoints.shape == (5, 17, 3)
    assert result.fps == 30.0
    assert (result.width, result.height) == (4, 2)
    np.testing.assert_allclose(result.keypoints[:, 0, 0], [0, 10, 20, 30, 40])
    np.testing.assert_allclose(result.keypoints[:, 0, 2], 1)
    assert [int(frame[0, 0, 0]) for frame in captured["frames"]] == [0, 2, 4]
    assert captured["config"] == (str(tmp_path / "model.pt"), 480, "cpu", 6, 0.12, "subprocess")
    assert backend.last_timing["decode_seconds"] >= 0
    assert backend.last_timing["workers_wall_seconds"] == 0.02
    assert backend.last_timing["densify_seconds"] >= 0
    assert backend.last_worker_timing == [{"model_load_seconds": 0.4}]


def test_chunk_worker_caps_cpu_threads_and_writes_coco_rows(monkeypatch, tmp_path):
    class Tensor:
        def __init__(self, value):
            self.value = np.asarray(value)

        def __getitem__(self, index):
            return Tensor(self.value[index])

        def __len__(self):
            return len(self.value)

        def cpu(self):
            return self

        def numpy(self):
            return self.value

    frames = np.zeros((2, 4, 4, 3), dtype=np.uint8)
    source, output = tmp_path / "frames.npy", tmp_path / "pose.npy"
    np.save(source, frames)
    points = np.arange(34, dtype=np.float32).reshape(1, 17, 2)
    confidences = np.full((1, 17), 0.75, dtype=np.float32)
    result = SimpleNamespace(
        keypoints=SimpleNamespace(xy=Tensor(points), conf=Tensor(confidences)),
        boxes=None,
    )
    predict_calls = []

    class Model:
        def predict(self, **kwargs):
            predict_calls.append(kwargs)
            return iter([result, result])

    ultralytics = ModuleType("ultralytics")
    ultralytics.__path__ = []
    ultralytics.YOLO = lambda _weights: Model()
    utils = ModuleType("ultralytics.utils")
    utils.__path__ = []
    utils.NUM_THREADS = 8
    torch_utils = ModuleType("ultralytics.utils.torch_utils")
    torch_utils.NUM_THREADS = 8
    ultralytics.utils = utils
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics)
    monkeypatch.setitem(sys.modules, "ultralytics.utils", utils)
    monkeypatch.setitem(sys.modules, "ultralytics.utils.torch_utils", torch_utils)
    thread_calls = []
    monkeypatch.setitem(
        sys.modules, "torch",
        SimpleNamespace(set_num_threads=thread_calls.append),
    )
    monkeypatch.setenv("BARRA_POSE_CPU_THREADS", "1")

    assert chunk.main([str(source), "weights.pt", "480", "cpu", "0.1", str(output)]) == 0

    saved = np.load(output)
    assert saved.shape == (2, 17, 3)
    np.testing.assert_array_equal(saved[0, :, :2], points[0])
    np.testing.assert_allclose(saved[:, :, 2], 0.75)
    assert predict_calls[0]["imgsz"] == 480
    assert predict_calls[0]["device"] == "cpu"
    assert predict_calls[0]["conf"] == 0.1
    assert thread_calls == [1]
    assert utils.NUM_THREADS == torch_utils.NUM_THREADS == 1
