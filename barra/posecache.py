"""Cached pose estimation, so a debug loop is worth having.

Pose is the slow step by an order of magnitude - 78 seconds against 1.3 for
everything after it - and a debug loop you have to wait 78 seconds for is a
debug loop you stop using. So the keypoints of a clip are written once, as the
same ``out/keypoints/<stem>.parquet`` the offline ``barra ingest`` stage writes,
and reused on every later run of that clip.

Two rules, both learned the hard way:

  * **The trace says when the cache was used.** A trace that silently mixed a
    fresh run with an old pose would be worse than none: the keypoints are the
    evidence every later number rests on, and "which model produced these"
    stops being answerable the moment it is implicit.
  * **A cache is keyed by the clip, not by the run.** Re-running with different
    thresholds must reuse the same keypoints, or the diff between the two runs
    is partly a diff between two pose estimates.

This module is the one place that logic lives. It was factored out of
``barra.explain`` so ``server.process.analyze_clip`` - the path that produces
what the phone actually receives - can be handed the same cached keypoints
instead of paying for pose again.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import schema as S
from .config import PATHS
from .trace import NullTrace


@dataclass
class CachedPose:
    """What a backend would have returned, however it was obtained."""
    keypoints: np.ndarray       # (T, 17, 3) -> x_px, y_px, confidence
    fps: float
    width: int = 0
    height: int = 0
    source: str = ""            # backend name, or "cache"


def cache_path(video: Path) -> Path:
    return PATHS.o(S.P_KEYPOINTS, f"{Path(video).stem}.parquet")


def load(video: Path) -> np.ndarray | None:
    """The keypoints written by an earlier run, or None."""
    path = cache_path(video)
    if not path.exists():
        return None
    try:
        import pandas as pd

        from .ingest import frame_to_keypoints

        return frame_to_keypoints(pd.read_parquet(path))
    except Exception:  # noqa: BLE001 - a broken cache re-estimates, never fails
        return None


def store(video: Path, keypoints: np.ndarray) -> Path | None:
    """Write keypoints in the schema `barra ingest` uses, so the two agree."""
    try:
        from .ingest import keypoints_to_frame

        path = cache_path(video)
        path.parent.mkdir(parents=True, exist_ok=True)
        keypoints_to_frame(keypoints).to_parquet(path, index=False)
        return path
    except Exception:  # noqa: BLE001 - failing to cache never fails a run
        return None


def estimate(video: Path, order: list[str] | None = None, trace=None) -> CachedPose:
    """Estimate pose, trying each backend in turn.

    A backend can fail in ways this process cannot survive - a native library
    that takes the interpreter down with it, which is not an exception and
    cannot be caught here. That is why the caller that cares (the debug server)
    runs this in a subprocess. What *can* be caught is caught, and the next
    backend is tried.
    """
    from .pose import available_backends, get_backend

    tr = trace or NullTrace()
    backends = available_backends()
    if not backends:
        raise SystemExit(
            'no pose backend installed; run: pip install -e ".[mediapipe]"'
        )
    # The same environment variable server/process.py honours, for the same
    # reason: which estimator produced the keypoints is a property of the run,
    # and pinning it must not require a different entry point.
    if not order:
        pinned = os.environ.get("BARRA_POSE_BACKEND", "").strip()
        order = [pinned] if pinned else None
    if order:
        backends = [b for b in order if b in backends] + \
                   [b for b in backends if b not in order]
    tr.step("backends available", backends=backends)

    last = None
    for name in backends:
        backend = get_backend(name)
        model = getattr(backend, "model_path", None)
        tr.step("estimating", backend=backend.name,
                model=str(model) if model else None,
                model_bytes=Path(model).stat().st_size
                if model and Path(model).exists() else None)
        try:
            result = backend.estimate(video)
        except Exception as exc:  # noqa: BLE001 - the next backend may still work
            last = exc
            tr.reject("pose backend failed", "the backend raised",
                      backend=name, reason=str(exc)[:200])
            continue
        return CachedPose(result.keypoints, float(result.fps or 0.0),
                          int(getattr(result, "width", 0) or 0),
                          int(getattr(result, "height", 0) or 0), name)
    raise SystemExit(f"every pose backend failed; last error: {last}")


def load_or_estimate(video: Path, fresh: bool = False, trace=None,
                     order: list[str] | None = None,
                     write_cache: bool = False,
                     fallback_fps: float = 0.0) -> CachedPose:
    """Cached keypoints when they exist, otherwise a fresh estimate.

    `fresh` skips the cache. `write_cache` stores a fresh estimate for the next
    run - off by default so a caller cannot fill `out/` without meaning to.

    `fallback_fps` is the frame rate to report for a CACHE HIT, because the
    keypoint table stores frames and not a frame rate. It defaults to 0.0 -
    falsy - so a caller that does not supply one falls through to its own
    probed value (`pose.fps or info["fps"]`) rather than being handed a guess.
    Defaulting it to 30 instead measured every 24 fps clip in the sample corpus
    a quarter too fast on its second run, and only on its second run: every
    duration, every tempo ratio and the minimum-rep-length gate all moved when
    nothing but the cache had changed. A cached run that disagrees with the run
    that filled the cache is worse than no cache.
    """
    tr = trace or NullTrace()
    if not fresh:
        keypoints = load(video)
        if keypoints is not None:
            path = cache_path(video)
            tr.step("keypoints reused from an earlier run", path=str(path),
                    written=path.stat().st_mtime, frames=int(len(keypoints)),
                    note="pass --fresh to re-run pose estimation")
            return CachedPose(keypoints, float(fallback_fps), source="cache")

    pose = estimate(video, order=order, trace=tr)
    if write_cache:
        stored = store(video, pose.keypoints)
        if stored is not None:
            tr.step("keypoints cached", path=str(stored),
                    frames=int(len(pose.keypoints)))
    return pose
