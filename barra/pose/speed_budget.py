"""Pose wall-time budget: seconds of pose per second of video, and projections.

Production Heavy sequential measured ~3.6 s of pose CPU per 1 s of video
(docs/SPEED-PLAN.md, jobs 7135be1d598a / 31103ccedfc3 / cd6f518ec47d). Full +
chunked workers are the defaults that cut that rate; projections come from the
Round-2 local Full+chunks timing scaled by the Heavy Lambda/local ratio.
"""
from __future__ import annotations

# Measured in production (Heavy, every frame, one process).
PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S = 3.6

# Round-2 local: Full with production floor (~3 chunks) on 30 s ≈ 6.82 s
# → 0.227 s/s; Heavy local on same host ≈ 1.57 s/s; Lambda Heavy ≈ 3.6 s/s
# → scale 3.6/1.57 ≈ 2.29 → projected Lambda Full+chunks ≈ 0.52 s/s.
PROJECTED_FULL_PARALLEL_S_PER_S = 0.52


def pose_seconds(video_seconds: float, rate_s_per_s: float) -> float:
    return float(video_seconds) * float(rate_s_per_s)


def pose_seconds_for_minutes(minutes: float, rate_s_per_s: float) -> float:
    return pose_seconds(float(minutes) * 60.0, rate_s_per_s)


def speedup(before_rate: float, after_rate: float) -> float:
    if after_rate <= 0:
        raise ValueError("after_rate must be positive")
    return float(before_rate) / float(after_rate)
