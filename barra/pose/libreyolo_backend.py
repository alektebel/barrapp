"""LibreYOLO pose adapter. Optional: pip install libreyolo.

LibreYOLO is MIT-licensed and ships several pose families (EdgeCrafter,
HRNet, RF-DETR with an extra). Checkpoints use COCO-17 ordering when trained
on COCO-pose; we still clamp to 17 slots so a different K cannot poison the
downstream measurement core.
"""
from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

import cv2
import numpy as np

from .base import PoseResult

_DEFAULT_WEIGHTS = (
    "LibreECs-pose.pt",
    "LibreHRNetw32-pose.pt",
)


class LibreYoloBackend:
    name = "libreyolo"

    def __init__(self, weights: str | None = None) -> None:
        self.weights = weights or self._resolve_weights()
        self.device = os.environ.get("BARRA_POSE_DEVICE", "cpu").strip() or "cpu"

    @staticmethod
    def _resolve_weights() -> str:
        env = os.environ.get("BARRA_LIBREYOLO_POSE_WEIGHTS", "").strip()
        if env:
            return env
        root = Path(__file__).resolve().parents[2]
        for base in (root, root / "models", Path.cwd(), Path.cwd() / "models"):
            for name in _DEFAULT_WEIGHTS:
                candidate = base / name
                if candidate.exists():
                    return str(candidate)
        return _DEFAULT_WEIGHTS[0]

    def available(self) -> bool:
        return find_spec("libreyolo") is not None

    def estimate(self, video: Path) -> PoseResult:
        from libreyolo import LibreYOLO

        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()

        model = LibreYOLO(self.weights)
        frames: list[np.ndarray] = []
        # LibreYOLO predict accepts a video path; fall back to per-frame if the
        # stream API differs across versions.
        try:
            results = model.predict(source=str(video), stream=True, verbose=False,
                                    device=self.device)
            for res in results:
                frames.append(self._row_from_result(res))
        except TypeError:
            results = model(str(video), stream=True, verbose=False)
            for res in results:
                frames.append(self._row_from_result(res))

        if not frames and n > 0:
            # Last resort: decode ourselves and call one frame at a time.
            cap = cv2.VideoCapture(str(video))
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                res = model(frame, verbose=False)[0]
                frames.append(self._row_from_result(res))
            cap.release()

        if not frames:
            raise RuntimeError(f"no frames decoded from {video}")
        return PoseResult(np.stack(frames), fps, w, h)

    @staticmethod
    def _row_from_result(res) -> np.ndarray:
        row = np.zeros((17, 3), dtype=np.float32)
        kp = getattr(res, "keypoints", None)
        if kp is None or getattr(kp, "xy", None) is None or len(kp.xy) == 0:
            return row
        boxes = getattr(res, "boxes", None)
        idx = 0
        if boxes is not None and len(boxes) > 0 and hasattr(boxes, "xywh"):
            try:
                areas = (boxes.xywh[:, 2] * boxes.xywh[:, 3]).cpu().numpy()
                idx = int(np.argmax(areas))
            except Exception:  # noqa: BLE001
                idx = 0
        if idx >= len(kp.xy):
            idx = 0
        xy = np.asarray(kp.xy[idx].cpu().numpy() if hasattr(kp.xy[idx], "cpu")
                        else kp.xy[idx], dtype=np.float32)
        if getattr(kp, "conf", None) is not None and len(kp.conf) > idx:
            conf = np.asarray(
                kp.conf[idx].cpu().numpy() if hasattr(kp.conf[idx], "cpu")
                else kp.conf[idx],
                dtype=np.float32,
            )
        else:
            conf = np.ones(len(xy), dtype=np.float32)
        n = min(17, len(xy), len(conf))
        row[:n, :2] = xy[:n]
        row[:n, 2] = conf[:n]
        return row
