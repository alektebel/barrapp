"""Pose estimation in parallel chunks of frames.

Pose was 134 s of a 339 s production job (2026-10-11): ~1,100 frames through
MediaPipe heavy, one frame at a time, on a Lambda with ~2 vCPU. MediaPipe uses
about one core per process, so contiguous frame ranges are posed in separate
SUBPROCESSES - Lambda has no /dev/shm, which `multiprocessing` needs - and
stitched back in frame order.

The output must be the one the sequential path gives:

* MediaPipe's VIDEO mode carries tracking state between frames. Each chunk
  starts `overlap` frames early and drops them (warm-up). This brings a chunk
  CLOSE to the sequential result, not equal to it - see `workers()`.
* Frames are reached by decoding from the start of the file, never by seeking:
  OpenCV seeks in H.264 are not frame-accurate, and a chunk that started one
  frame off would shift every timestamp after it.
* Any failure - a worker that dies, a part of the wrong length - falls back to
  the sequential path. Parallelism is an optimisation, never a new way to fail.

`BARRA_POSE_WORKERS` sets the number of workers; unset means 1 (sequential).
See `workers()` for why this is not on by default.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

OVERLAP = 45      # frames of warm-up before each chunk (1.5 s at 30 fps)
# Floor for a chunk that is worth the subprocess + warm-up cost. 240 left
# typical phone clips (<16 s @ 30 fps) sequential even with six workers;
# 120 lets an ~8 s clip split in two. Override with BARRA_POSE_MIN_CHUNK.
MIN_CHUNK = 120


@dataclass(frozen=True)
class Chunk:
    warm: int   # first frame posed (tracking warm-up starts here)
    start: int  # first frame kept
    end: int    # one past the last frame kept


def workers() -> int:
    """1 (sequential) unless BARRA_POSE_WORKERS says otherwise.

    Chunked pose is close to sequential MediaPipe, not equal to it - VIDEO
    mode carries tracking state, and a cold chunk stays 1-10 px away for its
    length (docs/SPEED-PLAN.md). Production pins workers via the worker
    template when the latency budget needs the cores; unset stays sequential
    so local runs and rollback stay one process."""
    pinned = os.environ.get("BARRA_POSE_WORKERS", "").strip()
    if pinned.isdigit() and int(pinned) > 0:
        return int(pinned)
    return 1


def min_chunk() -> int:
    pinned = os.environ.get("BARRA_POSE_MIN_CHUNK", "").strip()
    if pinned.isdigit() and int(pinned) > 0:
        return int(pinned)
    return MIN_CHUNK


def plan_chunks(n_frames: int, n_workers: int, overlap: int = OVERLAP,
                min_chunk: int = MIN_CHUNK) -> list[Chunk]:
    """Contiguous ranges covering [0, n_frames) exactly once."""
    n = max(1, min(n_workers, n_frames // max(1, min_chunk)))
    if n <= 1:
        return [Chunk(0, 0, n_frames)]
    bounds = [round(i * n_frames / n) for i in range(n + 1)]
    return [Chunk(max(0, a - overlap) if i else 0, a, b)
            for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]


def stitch(chunks: list[Chunk], parts: list[np.ndarray]) -> np.ndarray:
    """Concatenate in frame order. Every chunk but the last must be exactly
    its planned length; the last reads to the end of the file, because the
    container's frame count is only an estimate."""
    if len(parts) != len(chunks):
        raise ValueError(f"{len(parts)} parts for {len(chunks)} chunks")
    for c, p in list(zip(chunks, parts))[:-1]:
        if len(p) != c.end - c.start:
            raise ValueError(f"chunk {c} returned {len(p)} frames, expected {c.end - c.start}")
    if len(parts[-1]) == 0:
        raise ValueError("the last chunk returned no frames")
    return np.concatenate(parts, axis=0)


def _run_chunks(video: Path, chunks: list[Chunk], fps: float) -> list[np.ndarray]:
    """Pose each chunk in its own subprocess (`python -m barra.pose.chunk`)."""
    with tempfile.TemporaryDirectory(prefix="barra-pose-") as tmp:
        procs = []
        for i, c in enumerate(chunks):
            out = Path(tmp) / f"chunk{i}.npy"
            end = -1 if i == len(chunks) - 1 else c.end  # last: to end of file
            cmd = [sys.executable, "-m", "barra.pose.chunk", str(video),
                   str(c.warm), str(c.start), str(end), str(fps), str(out)]
            procs.append((subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE), out))
        parts, errors = [], []
        for proc, out in procs:
            _, err = proc.communicate()
            if proc.returncode != 0 or not out.exists():
                errors.append(err.decode(errors="replace")[-300:])
                continue
            parts.append(np.load(out))
        if errors:
            raise RuntimeError("pose worker failed: " + " | ".join(errors))
        return parts


def pose_frames(video: Path, n_frames: int, fps: float,
                sequential: Callable[[], np.ndarray],
                n_workers: int | None = None) -> np.ndarray:
    """Keypoints (n_frames, 33, 3) for the clip: in parallel when it pays,
    otherwise - or on any failure - from `sequential()`."""
    chunks = plan_chunks(
        n_frames,
        workers() if n_workers is None else n_workers,
        min_chunk=min_chunk(),
    )
    if len(chunks) == 1:
        return sequential()
    try:
        return stitch(chunks, _run_chunks(video, chunks, fps))
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        print(f"[barra] parallel pose fell back to sequential: {exc}", flush=True)
        return sequential()
