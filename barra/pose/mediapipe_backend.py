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

# BlazePose is scale-robust, so a clip does not need to be posed at its native
# resolution. Resizing each frame to this width (aspect preserved) before
# inference cuts the per-frame cost by roughly the pixel ratio, which is where
# most of the "measuring the reps" wait goes. Landmarks are scaled back to the
# original resolution afterwards, so every downstream metric sees the same
# pixel coordinates it always has.
PROCESS_WIDTH = 640


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
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()

        model = ensure_model(self.model_path)
        from .parallel import pose_frames
        # In parallel chunks when the clip is long enough and there are CPUs
        # for it (barra/pose/parallel.py); the same pose_range either way.
        blaze = pose_frames(
            Path(video), n_frames, fps,
            sequential=lambda: pose_range(model, Path(video), 0, 0, -1, fps))
        if not len(blaze):
            raise RuntimeError(f"no frames decoded from {video}")
        return PoseResult(remap(blaze, COCO_FROM_BLAZE), fps, w, h)


PREFETCH = 8   # frames decoded ahead of the landmarker


def _prefetch_enabled() -> bool:
    return os.environ.get("BARRA_POSE_PREFETCH", "1").strip().lower() not in ("0", "false", "off", "no")


def _decode(cap, warm: int, end: int, w: int, h: int):
    """(index, RGB frame ready for the landmarker) for frames [warm, end) in
    decode order. Frames before `warm` are advanced with grab(), which does
    not convert them. The same pixels, in the same order, whoever consumes
    them."""
    idx = 0
    while end < 0 or idx < end:
        if idx < warm:
            if not cap.grab():
                return
            idx += 1
            continue
        ok, frame = cap.read()
        if not ok:
            return
        if w > PROCESS_WIDTH:
            scale = PROCESS_WIDTH / w
            frame = cv2.resize(frame, (PROCESS_WIDTH, max(1, int(h * scale))),
                               interpolation=cv2.INTER_AREA)
        yield idx, np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        idx += 1


class _Prefetch:
    """`_decode` on a second thread, a few frames ahead of the landmarker.

    Decoding, resizing and colour conversion (cv2 releases the GIL in all
    three) used to run between two landmarker calls; they now overlap with
    them. Nothing about WHAT is posed changes - same frames, same order, same
    pixels - so the keypoints are bit-for-bit those of the serial loop
    (tests/test_pose_prefetch.py; scripts/pose_prefetch_check.py on real
    clips). A decode error is re-raised in the consumer, where the serial loop
    would have raised it."""

    _END = object()

    def __init__(self, source, depth: int = PREFETCH) -> None:
        import queue
        import threading
        self._q: queue.Queue = queue.Queue(maxsize=max(1, depth))
        self._stop = threading.Event()
        self._source = source
        self._thread = threading.Thread(target=self._run, name="pose-decode", daemon=True)
        self._thread.start()

    def _put(self, item) -> bool:
        import queue
        while not self._stop.is_set():
            try:
                self._q.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _run(self) -> None:
        try:
            for item in self._source:
                if not self._put(item):
                    return
            self._put(self._END)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the consumer
            self._put(exc)

    def __iter__(self):
        return self

    def __next__(self):
        item = self._q.get()
        if item is self._END:
            raise StopIteration
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _prepared_frames(cap, warm: int, end: int, w: int, h: int):
    """The frames to pose: prefetched on a thread unless BARRA_POSE_PREFETCH=0."""
    source = _decode(cap, warm, end, w, h)
    if not _prefetch_enabled():
        class _Serial:
            def __iter__(self):
                return source

            def close(self) -> None:
                source.close()
        return _Serial()
    return _Prefetch(source)


def pose_range(model: Path, video: Path, warm: int, start: int, end: int,
               fps: float) -> np.ndarray:
    """BlazePose landmarks (frames, 33, 3) for frames [start, end) of the clip
    (end = -1: to the end of the file), with tracking warmed up from frame
    `warm`. Frames are reached by decoding from the start, never by seeking:
    OpenCV seeks in H.264 are not frame-accurate. The sequential path is
    pose_range(model, video, 0, 0, -1, fps); a parallel chunk is a slice of it.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
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
    prepared = _prepared_frames(cap, warm, end, w, h)
    try:
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            for idx, rgb in prepared:
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts = int(idx * 1000.0 / max(fps, 1.0))
                res = landmarker.detect_for_video(image, ts)
                row = np.zeros((33, 3), dtype=np.float32)
                if res.pose_landmarks:
                    for i, lm in enumerate(res.pose_landmarks[0]):
                        # visibility x presence: a landmark the model placed but
                        # believes is out of frame is not a usable observation.
                        # lm.x/lm.y are normalised to the processed image, so
                        # scaling back by the ORIGINAL dimensions keeps the
                        # pixel coordinates downstream has always expected.
                        row[i] = (lm.x * w, lm.y * h,
                                  float(lm.visibility) * float(lm.presence))
                if idx >= start:
                    frames.append(row)
    finally:
        prepared.close()
    cap.release()
    if not frames:
        return np.zeros((0, 33, 3), dtype=np.float32)
    return np.stack(frames)
