"""Does decoding ahead of the landmarker change a single keypoint?

    python scripts/pose_prefetch_check.py CLIP [CLIP...] [--frames N]

For each clip: pose it with the serial loop (BARRA_POSE_PREFETCH=0) and with the
prefetch thread (the default), with the REAL production landmarker (MediaPipe
heavy), and compare the keypoint arrays bit for bit (np.array_equal on the
float32 arrays - not a tolerance). Prints wall time for both. Exit status 1 if
any clip's keypoints differ. docs/SPEED-ROUND3.md has the numbers.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]


def pose(clip: Path, prefetch: bool, frames: int | None) -> tuple[np.ndarray, float]:
    import cv2
    from barra.pose.mediapipe_backend import DEFAULT_MODEL, ensure_model, pose_range

    os.environ["BARRA_POSE_PREFETCH"] = "1" if prefetch else "0"
    cap = cv2.VideoCapture(str(clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    t0 = time.perf_counter()
    rows = pose_range(ensure_model(DEFAULT_MODEL), clip, 0, 0, frames if frames else -1, fps)
    return rows, time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--frames", type=int, default=0, help="pose only the first N frames")
    a = ap.parse_args()
    bad = 0
    for clip in a.clips:
        serial, t_serial = pose(clip, False, a.frames)
        ahead, t_ahead = pose(clip, True, a.frames)
        same = serial.shape == ahead.shape and np.array_equal(serial, ahead)
        bad += 0 if same else 1
        print(f"{clip.name}: {len(serial)} frames  serial {t_serial:.1f} s  "
              f"prefetch {t_ahead:.1f} s  ({(1 - t_ahead / t_serial) * 100:+.1f}% time)  "
              f"keypoints {'IDENTICAL' if same else 'DIFFER'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
