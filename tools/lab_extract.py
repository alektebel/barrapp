#!/usr/bin/env python3
"""Extract + cache pose keypoints for the sample clips, then classify.

Usage:
  python tools/lab_extract.py VID-20260827-WA0018   # one clip
  python tools/lab_classify.py                      # classify all cached
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE = Path("/tmp/opencode/kp")
CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault(
    "BARRA_POSE_MODEL", str(ROOT / "models" / "pose_landmarker_heavy.task"))


def clip_path(stem: str) -> Path:
    for d in (ROOT / "data" / "videos", ROOT):
        p = d / f"{stem}.mp4"
        if p.exists():
            return p
    raise SystemExit(f"no clip {stem}")


def extract(stem: str):
    import numpy as np
    from barra.pose import available_backends, get_backend

    out = CACHE / f"{stem}.npz"
    if out.exists():
        return
    pose = get_backend(available_backends()[0]).estimate(clip_path(stem))
    np.savez_compressed(out, keypoints=pose.keypoints, fps=pose.fps,
                        width=pose.width, height=pose.height)
    print(f"cached {out}")


if __name__ == "__main__":
    for stem in sys.argv[1:]:
        extract(stem)
