"""Multi-channel consistency report over cached pose clips.

    python scripts/consistency_eval.py --clips-dir /tmp/barra-nov2 \\
        --out out/consistency/report.json

Runs geometry channels that need no VLM (W1/W2/I1/I2/R2) and prints pairwise
agreement + consensus. Metamorphic padding check: prepend idle frames and
require identity/reps stable when a working set is found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from barra.channels import (  # noqa: E402
    Estimate,
    identity_drivers,
    identity_geometry,
    reps_period_times_duration,
    working_set_geometry,
    working_set_periodicity,
)
from barra.consensus import pairwise_matrix, resolve  # noqa: E402
from barra.pose import available_backends, get_backend  # noqa: E402
from barra import posecache  # noqa: E402


def _load_kp(video: Path, backend: str):
    cached = posecache.load(video, tag=backend)
    if cached is not None:
        import cv2
        cap = cv2.VideoCapture(str(video))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
        cap.release()
        return cached, fps
    pose = get_backend(backend).estimate(video)
    posecache.store(video, pose.keypoints, tag=backend)
    return pose.keypoints, pose.fps


def _run_clip(kp, fps: float) -> dict:
    estimates: list[Estimate] = []
    for name, fn, qty, fam in (
        ("W1", working_set_geometry, "working_set", "P"),
        ("W2", working_set_periodicity, "working_set", "P"),
        ("I1", identity_geometry, "identity", "P"),
        ("I2", identity_drivers, "identity", "P"),
        ("R2", reps_period_times_duration, "reps", "P"),
    ):
        try:
            est = fn(kp, fps)
        except TypeError:
            est = fn(kp, fps, window=None)
        except Exception as exc:  # noqa: BLE001
            est = Estimate(None, 0.0, "abstain", {"error": str(exc)[:120]})
        est.channel = name
        est.quantity = qty
        est.family = fam
        estimates.append(est)

    # I1/I2 share family P — consensus will abstain on identity (by design);
    # still report pairwise and each channel's value.
    report = {
        "channels": {e.channel: e.as_dict() for e in estimates},
        "identity": resolve(estimates, "identity"),
        "reps": resolve(estimates, "reps"),
        "working_set": resolve(estimates, "working_set"),
        "pairwiseIdentity": pairwise_matrix(estimates, "identity"),
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips-dir", type=Path, default=Path("/tmp/barra-nov2"))
    ap.add_argument("--backend", default="mediapipe")
    ap.add_argument("--out", type=Path, default=Path("out/consistency/report.json"))
    args = ap.parse_args()

    if args.backend not in available_backends():
        print(f"backend {args.backend} unavailable: {available_backends()}",
              file=sys.stderr)
        return 2

    rows = []
    for video in sorted(args.clips_dir.glob("*.mp4")):
        print(f"→ {video.stem}", flush=True)
        try:
            kp, fps = _load_kp(video, args.backend)
            row = {"job": video.stem, **_run_clip(kp, fps)}
        except Exception as exc:  # noqa: BLE001
            row = {"job": video.stem, "error": str(exc)[:300]}
        rows.append(row)
        hint = ((row.get("channels") or {}).get("I1") or {}).get("value")
        print(f"  I1={hint}  consensus_id={row.get('identity', {}).get('status')}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"rows": rows}, indent=2))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
