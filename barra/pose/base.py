"""Pose backend interface.

The measurement core never calls a pose model directly. It calls a backend,
which is responsible for returning frames of COCO-17 keypoints in *pixel*
coordinates with a per-keypoint confidence in [0, 1].

No backend is installed by default: the spec pins the dependency list and a
pose estimator is not on it. Install exactly one extra (see pyproject.toml) and
select it with --backend.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass
class PoseResult:
    keypoints: np.ndarray   # (T, 17, 3) -> x_px, y_px, confidence
    fps: float
    width: int
    height: int


class PoseBackend(Protocol):
    name: str

    def available(self) -> bool: ...
    def estimate(self, video: Path) -> PoseResult: ...


def remap(src: np.ndarray, mapping: dict[int, int], n_dst: int = 17) -> np.ndarray:
    """Remap a backend's native topology onto COCO-17.

    Destination slots with no source keypoint are emitted with confidence 0 so
    that every downstream confidence weight sees them as unusable rather than
    as a spurious origin-point detection.
    """
    T = src.shape[0]
    dst = np.zeros((T, n_dst, 3), dtype=np.float32)
    for d, s in mapping.items():
        dst[:, d, :] = src[:, s, :]
    return dst
