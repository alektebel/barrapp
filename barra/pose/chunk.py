"""One parallel pose chunk, run as a subprocess by barra/pose/parallel.py.

    python -m barra.pose.chunk <video> <warm> <start> <end> <fps> <out.npy> [stride]

Writes the BlazePose landmarks for frames [start, end) (end = -1: to the end
of the file) to out.npy, keeping every `stride`-th frame (absolute index
divisible by stride; default 1). A separate process because Lambda has no /dev/shm,
and `multiprocessing` needs it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from .mediapipe_backend import ensure_model, DEFAULT_MODEL, pose_range


def main(argv: list[str]) -> int:
    video, warm, start, end, fps, out, *rest = argv
    stride = int(rest[0]) if rest else 1
    rows = pose_range(ensure_model(DEFAULT_MODEL), Path(video), int(warm), int(start),
                      int(end), float(fps), stride)
    np.save(out, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
