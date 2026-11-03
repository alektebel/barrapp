"""Compare pose backends via per-joint periodicity fingerprints.

    python scripts/pose_periodicity_compare.py \\
        --clips-dir /tmp/barra-nov2 \\
        --backends mediapipe [ultralytics libreyolo] \\
        --out out/pose_periodicity.json

For each clip × backend: estimate pose (or load posecache), print the
periodicity matrix, identity hint, wall time, and mean keypoint confidence.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.joint_periodicity import (  # noqa: E402
    fingerprint_dict,
    identity_hint,
    joint_periodicity,
)
from barra.pose import available_backends, get_backend  # noqa: E402
from barra import posecache  # noqa: E402


def _clips(dir_path: Path) -> list[Path]:
    return sorted(dir_path.glob("*.mp4"))


def _probe_fps(video: Path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
    cap.release()
    return fps


def _run_one(video: Path, backend: str, use_cache: bool) -> dict:
    tag = backend
    if use_cache:
        cached = posecache.load(video, tag=tag)
        if cached is not None:
            return _summarize(
                video, backend, cached, _probe_fps(video), wall_s=0.0, cached=True,
            )

    be = get_backend(backend)
    t0 = time.perf_counter()
    pose = be.estimate(video)
    wall = time.perf_counter() - t0
    if use_cache:
        posecache.store(video, pose.keypoints, tag=tag)
    return _summarize(video, backend, pose.keypoints, pose.fps, wall, cached=False)


def _summarize(video: Path, backend: str, kp, fps: float, wall_s: float,
               cached: bool) -> dict:
    periods = joint_periodicity(kp, fps)
    fp = fingerprint_dict(periods)
    conf = float(kp[:, :, 2].mean()) if kp.size else 0.0
    video_s = len(kp) / max(float(fps), 1.0)
    return {
        "job": video.stem,
        "backend": backend,
        "cached": cached,
        "frames": int(len(kp)),
        "fps": float(fps),
        "videoSeconds": round(video_s, 3),
        "wallSeconds": round(wall_s, 3),
        "posePerVideoSecond": round(wall_s / video_s, 3) if video_s and wall_s else None,
        "meanKeypointConf": round(conf, 3),
        "identityHint": identity_hint(periods),
        "fingerprint": fp,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=Path("/tmp/barra-nov2"))
    ap.add_argument("--backends", nargs="+", default=None,
                    help="default: every available backend")
    ap.add_argument("--out", type=Path, default=Path("out/pose_periodicity.json"))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    have = available_backends()
    backends = args.backends or have
    missing = [b for b in backends if b not in have]
    if missing:
        print(f"skipping unavailable backends: {', '.join(missing)}", file=sys.stderr)
        backends = [b for b in backends if b in have]
    if not backends:
        print(f"no backends available; installed extras give: {have}", file=sys.stderr)
        return 2

    clips = _clips(args.clips_dir)
    if not clips:
        print(f"no mp4 in {args.clips_dir}", file=sys.stderr)
        return 2

    rows = []
    for video in clips:
        for backend in backends:
            print(f"→ {video.stem} / {backend}", flush=True)
            try:
                rows.append(_run_one(video, backend, use_cache=not args.no_cache))
            except Exception as exc:  # noqa: BLE001
                rows.append({
                    "job": video.stem,
                    "backend": backend,
                    "error": str(exc)[:300],
                })
                print(f"  ERROR: {exc}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"rows": rows, "backends": backends}, indent=2))
    print(f"\nwrote {args.out}")
    _print_table(rows)
    return 0


def _print_table(rows: list[dict]) -> None:
    print("\njob            backend       hint                     top_driver                 conf  s/s")
    for r in rows:
        if "error" in r:
            print(f"{r['job']:<14} {r['backend']:<12} ERROR {r['error'][:50]}")
            continue
        top = (r.get("fingerprint") or {}).get("top") or "-"
        drivers = (r.get("fingerprint") or {}).get("drivers") or []
        print(
            f"{r['job']:<14} {r['backend']:<12} {r['identityHint']:<24} "
            f"{top:<24} {r['meanKeypointConf']:<5} {r.get('posePerVideoSecond')}"
        )
        if drivers[1:]:
            print(f"{'':14} {'':12} drivers: {', '.join(drivers[:4])}")


if __name__ == "__main__":
    raise SystemExit(main())
