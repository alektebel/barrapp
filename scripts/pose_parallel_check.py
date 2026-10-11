"""Does parallel pose give the sequential answer? (docs/SPEED-PLAN.md step 2)

    python scripts/pose_parallel_check.py CLIP [CLIP...] [--workers 4] [--min-chunk 60]

For each clip: pose it sequentially and in forced parallel chunks, compare the
keypoints, then run the production measurement (process.measure_job, remote
models off) on each and compare every number the phone shows. Prints timings.
Exit status 1 if any measured number differs.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
for k in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY"):
    os.environ.pop(k, None)
os.environ["NAN_BASE_URL"] = ""
os.environ.setdefault("BARRA_SENTINEL", "strict")


class Pose:
    def __init__(self, keypoints, fps, source):
        self.keypoints, self.fps, self.source = keypoints, fps, source


def numbers(payload: dict) -> dict:
    reps = [{k: r.get(k) for k in ("startS", "turnS", "endS", "score", "band", "transition_s", "total_s")}
            | {"metrics": [(m.get("key"), m.get("value")) for m in r.get("metrics") or []]}
            for r in payload.get("reps") or []]
    return {"exercise": payload.get("exercise"), "n_reps": payload.get("n_reps"),
            "n_candidates": payload.get("n_candidates"), "sessionScore": payload.get("sessionScore"),
            "blockers": payload.get("blockers"), "reps": reps}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-chunk", type=int, default=60)
    a = ap.parse_args()

    import cv2
    from barra.pose import parallel
    from barra.pose.base import remap
    from barra.pose.mediapipe_backend import COCO_FROM_BLAZE, DEFAULT_MODEL, ensure_model, pose_range
    from process import measure_job

    model = ensure_model(DEFAULT_MODEL)
    bad = 0
    for clip in a.clips:
        cap = cv2.VideoCapture(str(clip))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        t = time.time()
        seq = pose_range(model, clip, 0, 0, -1, fps)
        t_seq = time.time() - t
        chunks = parallel.plan_chunks(n, a.workers, min_chunk=a.min_chunk)
        t = time.time()
        par = parallel.stitch(chunks, parallel._run_chunks(clip, chunks, fps))
        t_par = time.time() - t

        same_shape = seq.shape == par.shape
        diff = float(np.abs(seq - par).max()) if same_shape else float("inf")
        outs = []
        for name, kp in (("sequential", seq), ("parallel", par)):
            pose = Pose(remap(kp, COCO_FROM_BLAZE), fps, f"check-{name}")
            outs.append(numbers(measure_job({"id": f"{clip.stem}-{name}", "exercise": "auto"},
                                            clip, pose=pose)))
        equal = outs[0] == outs[1]
        bad += 0 if equal else 1
        print(f"{clip.name}: {n} frames, {len(chunks)} chunks | sequential {t_seq:.1f}s, "
              f"parallel {t_par:.1f}s | keypoints max|diff| {diff:.4g} px | "
              f"measurement {'IDENTICAL' if equal else 'DIFFERS'} "
              f"({outs[0]['exercise']}, {outs[0]['n_reps']} reps, score {outs[0]['sessionScore']})")
        if not equal:
            for k in outs[0]:
                if outs[0][k] != outs[1][k]:
                    print(f"   {k}: {str(outs[0][k])[:120]}  !=  {str(outs[1][k])[:120]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
