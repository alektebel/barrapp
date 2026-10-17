"""Pose frame budget: how many source frames one keypoint row stands for.

Pose cost is linear in frames (~11 frames/s end to end), the worker's Lambda
has a hard 600 s, and an athlete's phone happily records 2.5 minutes at 60 fps.
Above `MAX_POSE_FRAMES` the pose is estimated on every k-th frame, k =
ceil(n_frames / MAX_POSE_FRAMES), and the PoseResult carries fps / k, so every
downstream `frame / fps` stays in the SOURCE video's seconds (the phone seeks
its local copy with those times). Row j is source frame j * k.

When even that leaves fewer than `MIN_POSE_FPS` samples per second the clip is
not posed at all (`too_long`): the job should say so at once, not time out.
"""
from __future__ import annotations

import math

from barra import config


def pose_stride(n_frames: int, max_frames: int | None = None) -> int:
    """Source frames per pose sample: 1 while the clip fits the budget."""
    cap = max(1, config.MAX_POSE_FRAMES if max_frames is None else max_frames)
    return max(1, math.ceil(max(0, n_frames) / cap))


def sampled_count(n_frames: int, stride: int) -> int:
    """Rows a stride-k pass over n frames yields (frames 0, k, 2k, ...)."""
    return math.ceil(max(0, n_frames) / max(1, stride))


def max_stride(fps: float, min_fps: float | None = None) -> int:
    floor = config.MIN_POSE_FPS if min_fps is None else min_fps
    return max(1, int(fps // floor)) if fps > 0 else 1


def max_clip_seconds(fps: float, max_frames: int | None = None,
                     min_fps: float | None = None) -> int:
    """Longest clip (whole seconds) that is still analysable at this fps."""
    cap = config.MAX_POSE_FRAMES if max_frames is None else max_frames
    return int(max_stride(fps, min_fps) * cap // max(fps, 1.0))


def too_long(n_frames: int, fps: float, max_frames: int | None = None,
             min_fps: float | None = None) -> bool:
    """True when the needed stride would drop the effective rate below the
    minimum. An unknown fps or frame count is never refused here."""
    if n_frames <= 0 or fps <= 0:
        return False
    return pose_stride(n_frames, max_frames) > max_stride(fps, min_fps)
