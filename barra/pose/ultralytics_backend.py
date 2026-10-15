"""YOLO-pose (ultralytics) adapter. Optional extra: pip install -e ".[ultralytics]".

Emits COCO-17 natively. The default path predicts per frame and picks the
largest-area detection. Setting BARRA_POSE_TRACK=1 opts into Ultralytics
tracking for subject continuity; it is opt-in because the tracker can cost
memory on constrained hosts. A set containing more than one lifter should still
be trimmed before ingest; tracking only helps the common single-lifter case when
the athlete is briefly occluded.
"""
from __future__ import annotations

import os
import time
from importlib.util import find_spec
from pathlib import Path

import cv2
import numpy as np

from .base import PoseResult
from .ultralytics_parallel import dense_from_samples, infer_chunks

_ROOT = Path(__file__).resolve().parents[2]
_STRONGER_WEIGHTS = (
    "yolo11x-pose.pt",
    "yolo11l-pose.pt",
    "yolo11m-pose.pt",
    "yolo11s-pose.pt",
    "yolo11n-pose.pt",
)


def inference_options() -> tuple[int, int, int, float]:
    """Configured worker count, sample stride, image size and detector threshold."""
    defaults = [
        ("BARRA_POSE_WORKERS", 1),
        ("BARRA_YOLO_POSE_STRIDE", 1),
        ("BARRA_YOLO_POSE_IMGSZ", 640),
    ]
    values = []
    for name, default in defaults:
        try:
            value = int(os.environ.get(name, str(default)).strip())
        except ValueError:
            value = default
        values.append(max(1, value))
    try:
        confidence = float(os.environ.get("BARRA_YOLO_POSE_CONF", "0.25").strip())
    except ValueError:
        confidence = 0.25
    if not 0.0 <= confidence <= 1.0:
        confidence = 0.25
    return values[0], values[1], values[2], confidence


class UltralyticsBackend:
    name = "ultralytics"

    def __init__(self, weights: str | None = None) -> None:
        self.weights = weights or self._resolve_weights()
        self.model_path = self._display_model_path(self.weights)
        self.device = os.environ.get("BARRA_POSE_DEVICE", "cpu").strip() or "cpu"
        self.last_timing: dict[str, float] = {}
        self.last_worker_timing: list[dict[str, float]] = []
        self.last_worker_mode = "subprocess"

    @staticmethod
    def _resolve_weights() -> str:
        env = os.environ.get("BARRA_YOLO_POSE_WEIGHTS", "").strip()
        if env:
            return env
        for root in (_ROOT, _ROOT / "models", Path.cwd(), Path.cwd() / "models"):
            for name in _STRONGER_WEIGHTS:
                candidate = root / name
                if candidate.exists():
                    return str(candidate)
        return "yolo11n-pose.pt"

    @staticmethod
    def _display_model_path(weights: str) -> str:
        p = Path(weights)
        return str(p if p.exists() else Path.cwd() / p)

    @staticmethod
    def _select_subject(areas: np.ndarray, ids: list[int] | None,
                        selected: int | None,
                        missed: int = 0) -> tuple[int, int | None, int]:
        """Pick the dominant tracked subject.

        Prefer the current track. If it is absent this frame, keep the prior
        subject for a short gap and output the largest box; only when the gap is
        long enough do we switch identity to the largest tracked id.
        """
        max_missed_frames = int(os.environ.get("BARRA_POSE_TRACK_GAP", "6") or 6)
        if areas.size == 0:
            return 0, selected, missed
        fallback = int(np.argmax(areas))
        if ids is None:
            return fallback, selected, missed
        if selected in ids:
            return ids.index(selected), selected, 0
        if selected is not None and missed < max_missed_frames:
            return fallback, selected, missed + 1
        return fallback, ids[min(fallback, len(ids) - 1)], 0

    @staticmethod
    def _iter_results(model, video: Path, device: str, confidence: float):
        source = str(video)
        track = os.environ.get("BARRA_POSE_TRACK", "").lower() in {"1", "true", "yes"}
        if track:
            try:
                yield from model.track(source, stream=True, verbose=False,
                                       persist=True, device=device, conf=confidence)
                return
            except Exception:  # noqa: BLE001 - predict is the safe single-frame path
                pass
        yield from model.predict(source, stream=True, verbose=False, device=device,
                                 conf=confidence)

    def available(self) -> bool:
        return find_spec("ultralytics") is not None

    def estimate(self, video: Path) -> PoseResult:
        total_started = time.perf_counter()
        import_started = time.perf_counter()
        from ultralytics import YOLO
        model_import_seconds = time.perf_counter() - import_started

        probe_started = time.perf_counter()
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        self.last_timing = {
            "model_import_seconds": model_import_seconds,
            "probe_seconds": time.perf_counter() - probe_started,
        }

        workers, stride, imgsz, confidence = inference_options()
        track = os.environ.get("BARRA_POSE_TRACK", "").lower() in {"1", "true", "yes"}
        if not track and (workers > 1 or stride > 1 or imgsz != 640):
            decode_started = time.perf_counter()
            cap = cv2.VideoCapture(str(video))
            frames: list[np.ndarray] = []
            sample_frames: list[int] = []
            frame_index = 0
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                if frame_index % stride == 0:
                    frames.append(image)
                    sample_frames.append(frame_index)
                frame_index += 1
            cap.release()
            self.last_timing["decode_seconds"] = time.perf_counter() - decode_started
            chunk_timing: dict[str, float] = {}
            self.last_worker_timing = []
            default_worker_mode = (
                "fork" if os.name == "posix" and self.device.lower() == "cpu" and workers > 1
                else "subprocess"
            )
            self.last_worker_mode = os.environ.get(
                "BARRA_POSE_WORKER_MODE", default_worker_mode
            ).strip().lower()
            inference_started = time.perf_counter()
            sparse = infer_chunks(frames, self.weights, imgsz, self.device,
                                  workers, confidence, timing=chunk_timing,
                                  worker_timing=self.last_worker_timing,
                                  worker_mode=self.last_worker_mode)
            if chunk_timing.get("fork_fallback"):
                self.last_worker_mode = "subprocess-fallback"
            self.last_timing.update(chunk_timing)
            self.last_timing["chunk_pipeline_seconds"] = time.perf_counter() - inference_started
            merge_started = time.perf_counter()
            dense = dense_from_samples(sparse, sample_frames, frame_index)
            self.last_timing["densify_seconds"] = time.perf_counter() - merge_started
            self.last_timing["total_seconds"] = time.perf_counter() - total_started
            return PoseResult(dense, fps, w, h)

        model = YOLO(self.weights)
        self.last_timing["model_init_seconds"] = time.perf_counter() - total_started
        frames: list[np.ndarray] = []
        selected: int | None = None
        missed = 0
        for res in self._iter_results(model, video, self.device, confidence):
            row = np.zeros((17, 3), dtype=np.float32)
            kp = res.keypoints
            if kp is not None and kp.xy is not None and len(kp.xy) > 0:
                boxes = res.boxes
                areas = np.asarray(
                    (boxes.xywh[:, 2] * boxes.xywh[:, 3]).cpu().numpy(),
                    dtype=float,
                ) if boxes is not None and len(boxes) else np.empty(0)
                ids = ([int(v) for v in boxes.id.cpu().numpy().tolist()]
                       if boxes is not None and getattr(boxes, "id", None) is not None
                       else None)
                idx, selected, missed = self._select_subject(areas, ids, selected, missed)
                if idx >= len(kp.xy):
                    idx = 0
                    selected = None
                xy = np.asarray(kp.xy[idx].cpu().numpy(), dtype=np.float32)
                if kp.conf is not None and len(kp.conf) > idx:
                    conf = np.asarray(kp.conf[idx].cpu().numpy(), dtype=np.float32)
                else:
                    conf = np.ones(len(xy), dtype=np.float32)
                n = min(17, len(xy), len(conf))
                row[:n, :2] = xy[:n]
                row[:n, 2] = conf[:n]
            frames.append(row)
        if not frames:
            raise RuntimeError(f"no frames decoded from {video}")
        self.last_timing["total_seconds"] = time.perf_counter() - total_started
        return PoseResult(np.stack(frames), fps, w, h)
