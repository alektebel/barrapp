"""YOLO-pose (ultralytics) adapter. Optional extra: pip install -e ".[ultralytics]".

Emits COCO-17 natively. When several people are in frame the largest-area
detection is taken as the subject; a set containing more than one lifter should
be trimmed before ingest rather than relying on that heuristic.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import cv2
import numpy as np

from .base import PoseResult


class UltralyticsBackend:
    name = "ultralytics"

    def __init__(self, weights: str = "yolo11n-pose.pt") -> None:
        self.weights = weights

    def available(self) -> bool:
        return find_spec("ultralytics") is not None

    def estimate(self, video: Path) -> PoseResult:
        from ultralytics import YOLO

        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        model = YOLO(self.weights)
        frames: list[np.ndarray] = []
        for res in model.predict(str(video), stream=True, verbose=False, device="cpu"):
            row = np.zeros((17, 3), dtype=np.float32)
            kp = res.keypoints
            if kp is not None and kp.xy is not None and len(kp.xy) > 0:
                boxes = res.boxes
                idx = 0
                if boxes is not None and len(boxes) > 1:
                    areas = (boxes.xywh[:, 2] * boxes.xywh[:, 3]).cpu().numpy()
                    idx = int(np.argmax(areas))
                xy = kp.xy[idx].cpu().numpy()
                conf = (
                    kp.conf[idx].cpu().numpy()
                    if kp.conf is not None
                    else np.ones(len(xy), dtype=np.float32)
                )
                row[:, :2] = xy
                row[:, 2] = conf
            frames.append(row)
        if not frames:
            raise RuntimeError(f"no frames decoded from {video}")
        return PoseResult(np.stack(frames), fps, w, h)
