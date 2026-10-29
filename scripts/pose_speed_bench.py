"""Measure pose seconds per video second: Heavy sequential vs Full (+workers).

    python scripts/pose_speed_bench.py [--seconds 10] [--workers 2] [--out PATH]

Creates a short synthetic clip (or uses --video), times each configuration, and
prints the rate plus the projection for X minutes of footage. Writes JSON so
the before/after cut is evidence in the repo (or out/).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.pose.speed_budget import (  # noqa: E402
    PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S,
    PROJECTED_FULL_PARALLEL_S_PER_S,
    pose_seconds_for_minutes,
    speedup,
)


def _synthetic(path: Path, seconds: float, fps: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"testsrc=size=720x1280:rate={fps}",
        "-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an", str(path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def _time_pose(model: Path, video: Path, workers: int, min_chunk: int) -> dict:
    os.environ["BARRA_POSE_MODEL"] = str(model)
    os.environ["BARRA_POSE_WORKERS"] = str(workers)
    os.environ["BARRA_POSE_MIN_CHUNK"] = str(min_chunk)
    # Re-import path uses env at call time for workers/min_chunk; model via ensure.
    from barra.pose.mediapipe_backend import ensure_model, pose_range
    from barra.pose.parallel import pose_frames, plan_chunks, workers as n_workers, min_chunk as floor
    import cv2

    model = ensure_model(model)
    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    video_s = n / max(fps, 1.0)
    chunks = plan_chunks(n, n_workers(), min_chunk=floor())

    t0 = time.perf_counter()
    rows = pose_frames(
        video, n, fps,
        sequential=lambda: pose_range(model, video, 0, 0, -1, fps),
    )
    wall = time.perf_counter() - t0
    rate = wall / video_s if video_s else 0.0
    return {
        "model": model.name,
        "workers": n_workers(),
        "minChunk": floor(),
        "chunks": len(chunks),
        "frames": len(rows),
        "videoSeconds": round(video_s, 3),
        "wallSeconds": round(wall, 3),
        "posePerVideoSecond": round(rate, 3),
        "minutes1": round(pose_seconds_for_minutes(1.0, rate), 1),
        "minutes3": round(pose_seconds_for_minutes(3.0, rate), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--min-chunk", type=int, default=120)
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "tests" / "fixtures" / "pose_speed_bench.json")
    args = ap.parse_args()

    video = args.video or _synthetic(Path("/tmp/barra-speed/bench.mp4"), args.seconds)
    heavy = ROOT / "models" / "pose_landmarker_heavy.task"
    full = ROOT / "models" / "pose_landmarker_full.task"
    for p in (heavy, full):
        if not p.exists():
            print(f"missing {p}", file=sys.stderr)
            return 1

    before = _time_pose(heavy, video, workers=1, min_chunk=args.min_chunk)
    after = _time_pose(full, video, workers=args.workers, min_chunk=args.min_chunk)
    report = {
        "hostNote": "local wall times; Lambda is slower — use production rates for X-min budget",
        "clip": {
            "path": str(video),
            "stem": video.stem,
            "frames": before["frames"],
            "videoSeconds": before["videoSeconds"],
        },
        "productionBaseline": {
            "config": "Heavy sequential",
            "posePerVideoSecond": PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S,
            "minutes1": round(pose_seconds_for_minutes(1, PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S), 1),
            "minutes3": round(pose_seconds_for_minutes(3, PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S), 1),
        },
        "productionProjectionAfter": {
            "config": "Full + parallel chunks",
            "posePerVideoSecond": PROJECTED_FULL_PARALLEL_S_PER_S,
            "minutes1": round(pose_seconds_for_minutes(1, PROJECTED_FULL_PARALLEL_S_PER_S), 1),
            "minutes3": round(pose_seconds_for_minutes(3, PROJECTED_FULL_PARALLEL_S_PER_S), 1),
            "speedupVsBaseline": round(
                speedup(PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S, PROJECTED_FULL_PARALLEL_S_PER_S), 2),
        },
        "localMeasured": {"before": before, "after": after,
                          "speedup": round(speedup(before["posePerVideoSecond"],
                                                   after["posePerVideoSecond"]), 2)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
