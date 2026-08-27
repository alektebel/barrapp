"""BlazePose via the mediapipe Tasks API. Optional extra: pip install -e ".[mediapipe]".

mediapipe 1.x removed the legacy `mp.solutions.pose` interface, so this uses
PoseLandmarker in VIDEO running mode, which carries tracking state between
frames rather than re-detecting each frame independently. That matters here:
frame-independent detection produces keypoint jitter that inflates every null
distribution downstream for no reason.

The model file is not vendored (30 MB). It is fetched on first use to
`models/`, once, over the network. Everything after ingest is fully offline.
"""
from __future__ import annotations

import os
import urllib.request
from importlib.util import find_spec
from pathlib import Path

import cv2
import numpy as np

from .base import PoseResult, remap

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
)
DEFAULT_MODEL = Path(
    os.environ.get("BARRA_POSE_MODEL", "models/pose_landmarker_heavy.task")
)

# {coco_17_index: blazepose_33_index}
COCO_FROM_BLAZE = {
    0: 0, 1: 2, 2: 5, 3: 7, 4: 8,
    5: 11, 6: 12, 7: 13, 8: 14, 9: 15, 10: 16,
    11: 23, 12: 24, 13: 25, 14: 26, 15: 27, 16: 28,
}


def ensure_model(path: Path = DEFAULT_MODEL) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading pose model -> {path} (~30 MB, once)")
    urllib.request.urlretrieve(MODEL_URL, path)
    return path


class MediapipeBackend:
    name = "mediapipe"

    def __init__(self, model_path: Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL

    def available(self) -> bool:
        return find_spec("mediapipe") is not None

    def estimate(self, video: Path) -> PoseResult:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        model = ensure_model(self.model_path)
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_segmentation_masks=False,
        )

        frames: list[np.ndarray] = []
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            idx = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                )
                ts = int(idx * 1000.0 / max(fps, 1.0))
                res = landmarker.detect_for_video(image, ts)
                row = np.zeros((33, 3), dtype=np.float32)
                if res.pose_landmarks:
                    for i, lm in enumerate(res.pose_landmarks[0]):
                        # visibility x presence: a landmark the model placed but
                        # believes is out of frame is not a usable observation
                        row[i] = (lm.x * w, lm.y * h,
                                  float(lm.visibility) * float(lm.presence))
                frames.append(row)
                idx += 1
        cap.release()
        if not frames:
            raise RuntimeError(f"no frames decoded from {video}")
        return PoseResult(remap(np.stack(frames), COCO_FROM_BLAZE), fps, w, h)
