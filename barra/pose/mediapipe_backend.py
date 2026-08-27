"""BlazePose (mediapipe) adapter. Optional extra: pip install -e ".[mediapipe]"."""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import cv2
import numpy as np

from .base import PoseResult, remap

# {coco_17_index: blazepose_33_index}
COCO_FROM_BLAZE = {
    0: 0, 1: 2, 2: 5, 3: 7, 4: 8,
    5: 11, 6: 12, 7: 13, 8: 14, 9: 15, 10: 16,
    11: 23, 12: 24, 13: 25, 14: 26, 15: 27, 16: 28,
}


class MediapipeBackend:
    name = "mediapipe"

    def available(self) -> bool:
        return find_spec("mediapipe") is not None

    def estimate(self, video: Path) -> PoseResult:
        import mediapipe as mp

        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        frames: list[np.ndarray] = []
        with mp.solutions.pose.Pose(
            model_complexity=2, smooth_landmarks=True,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        ) as pose:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                res = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                row = np.zeros((33, 3), dtype=np.float32)
                if res.pose_landmarks:
                    for i, lm in enumerate(res.pose_landmarks.landmark):
                        row[i] = (lm.x * w, lm.y * h, lm.visibility)
                frames.append(row)
        cap.release()
        if not frames:
            raise RuntimeError(f"no frames decoded from {video}")
        return PoseResult(remap(np.stack(frames), COCO_FROM_BLAZE), fps, w, h)
