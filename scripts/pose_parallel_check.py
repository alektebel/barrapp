"""Does parallel pose give the sequential answer? (docs/SPEED-PLAN.md step 2)

    python scripts/pose_parallel_check.py CLIP [CLIP...] [--workers 4] [--min-chunk 60]
    python scripts/pose_parallel_check.py --replay out/parallel-check/*.json

For each clip: pose it sequentially and in forced parallel chunks with the REAL
production landmarker (MediaPipe heavy, the same model the Lambda runs), compare
the keypoints, then run the production measurement (process.measure_job, remote
models off) on each and compare EVERY number the phone shows: exercise, reps,
sessionScore/band, per-rep start/turn/end, scores, faults, problems, metrics,
topFixes - the full payload minus its run-metadata keys (traceId, provenance,
the prose the local run cannot produce, session/date and shape counts that say
nothing about the measurement).

Both keypoints and both payloads are written to out/parallel-check/ so a later
--replay can re-derive the verdict without posing again. The payload contract
runs with the sentinel in record mode: a clip that legitimately measures zero
reps (no vision fallback locally) must not take the gate down, and each saved
result records its payload-contract verdict for the report.
Exit status 1 if any measured number differs or a payload trips its contract.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]
for k in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY"):
    os.environ.pop(k, None)
os.environ["NAN_BASE_URL"] = ""
os.environ["BARRA_SENTINEL"] = "record"

# Keys of the measured payload that are about THIS run, not the measurement:
# the prose source, the local trace identity and its environment stamp, the
# session row, and two counts that repeat what the compared numbers say.
RUN_KEYS = {"headline", "narrative", "nextSession", "proseSource",
            "proseRejected", "traceId", "provenance", "session",
            "measurementVersion", "n_reps", "n_candidates", "sessions"}

OUT_DIR = ROOT / "out" / "parallel-check"


def pose_object(keypoints, fps, width, height):
    from barra.pose.base import PoseResult
    return PoseResult(keypoints, fps, width, height)


def payload_for(clip: Path, name: str, pose) -> dict:
    """The production measurement (measure_job). With no NAN_API_KEY the prose
    is the deterministic Spanish fallback and the vision passes are skipped,
    so nothing here touches the network."""
    from process import measure_job
    return measure_job({"id": f"{clip.stem}-{name}", "exercise": "auto"},
                       clip, pose=pose)


def strip(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in RUN_KEYS}


def deep_diff(a, b, path="$") -> list[str]:
    """Every leaf where two payload trees disagree, with both values."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(a.keys() | b.keys())
                for d in deep_diff(a.get(k), b.get(k), f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b))
                for d in deep_diff(x, y, f"{path}[{i}]")]
    if a != b:
        sa, sb = json.dumps(a, ensure_ascii=False, default=str), \
                 json.dumps(b, ensure_ascii=False, default=str)
        return [f"{path}: {sa[:160]}  !=  {sb[:160]}"]
    return []


def contract_violations(payload: dict) -> list[str]:
    from barra.contracts import check_payload
    return [f"{v.rule} ({v.detail})" for v in check_payload(payload)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", type=Path)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--min-chunk", type=int, default=60,
                    help="chunk floor small enough to split the test clips "
                         "(production splits at MIN_CHUNK=%d frames)"
                         % __import__("barra.pose.parallel", fromlist=["MIN_CHUNK"]).MIN_CHUNK)
    ap.add_argument("--force", action="store_true",
                    help="pose again even if a saved result exists")
    ap.add_argument("--replay", nargs="?", const=str(OUT_DIR), default=None,
                    metavar="DIR",
                    help="no posing: re-derive the verdict from saved JSON "
                         "(default: out/parallel-check)")
    a = ap.parse_args()

    if a.replay:
        records = [json.loads(p.read_text())
                   for p in sorted(Path(a.replay).glob("*.json"))]
        if not records:
            print(f"no saved results under {a.replay}")
            return 1
        bad = 0
        for rec in records:
            bad += _report(rec, None, None)
        return 1 if bad else 0

    import cv2
    from barra.pose import parallel
    from barra.pose.base import remap
    from barra.pose.mediapipe_backend import COCO_FROM_BLAZE, DEFAULT_MODEL, ensure_model, pose_range

    model = ensure_model(DEFAULT_MODEL)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bad = 0
    for clip in a.clips:
        if not a.force and (OUT_DIR / f"{clip.stem}.json").exists():
            print(f"{clip.name}: already gated ({OUT_DIR / (clip.stem + '.json')}); "
                  f"--force to pose again")
            continue
        cap = cv2.VideoCapture(str(clip))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
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

        payloads: dict[str, dict] = {}
        for name, kp in (("sequential", seq), ("parallel", par)):
            payloads[name] = payload_for(clip, name, pose_object(remap(kp, COCO_FROM_BLAZE), fps, w, h))

        out = OUT_DIR / f"{clip.stem}.json"
        out.write_text(json.dumps({
            "clip": clip.name, "frames": n, "fps": round(fps, 3), "width": w, "height": h,
            "chunks": [c.__dict__ for c in chunks],
            "sequential_s": round(t_seq, 1), "parallel_s": round(t_par, 1),
            "keypoints_max_abs_diff": None if not same_shape else diff,
            "shape_equal": same_shape,
            "payloads": {k: strip(v) for k, v in payloads.items()},
            "contracts": {k: contract_violations(v) for k, v in payloads.items()},
        }, ensure_ascii=False, indent=1, default=str))

        bad += _report(json.loads(out.read_text()), diff, (t_seq, t_par, len(chunks), n))
    return 1 if bad else 0


def _report(rec: dict, diff: float, timing) -> int:
    """Print one clip's verdict; 1 if any measured number moved."""
    a, b = rec["payloads"]["sequential"], rec["payloads"]["parallel"]
    drift = rec.get("keypoints_max_abs_diff")
    diffs = deep_diff(a, b)
    contract_bad = {k: v for k, v in rec["contracts"].items() if v}
    clean = not diffs and not contract_bad
    head = (f"{rec['clip']}: {rec['frames']} frames")
    if timing:
        t_seq, t_par, n_chunks, _ = timing
        head += f" | sequential {t_seq:.1f}s, parallel {t_par:.1f}s, {n_chunks} chunks"
    print(head + f" | keypoints max|diff| {'SHAPE' if drift is None else f'{drift:.4g} px'} | "
                 f"measurement {'IDENTICAL' if not diffs else 'DIFFERS'}"
                 + ("" if not contract_bad else f" | contract: {contract_bad}"))
    for line in diffs:
        print(f"   {line}")
    for name, vs in contract_bad.items():
        for v in vs:
            print(f"   contract[{name}]: {v}")
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
