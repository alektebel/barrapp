#!/usr/bin/env python3
"""Run the opt-in YOLO candidate and production measurement in a worker image.

Run inside a worker-compatible container with the repo's current `barra/pose`
and a SHA-pinned checkpoint mounted in. This records process import, pose and
measurement time separately. It does not include container image pull or AWS
Lambda initialization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Worker images may have a stale /opt/barra earlier on sys.path than the
# mounted repository. Keep this experiment tied to the exact source being
# measured, as the harness documentation promises.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clips", nargs="+", type=Path)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--save-keypoints-dir", type=Path,
                        help="optional directory for raw candidate PoseResult arrays")
    parser.add_argument("--source-offset-s", type=float,
                        help="source-video timestamp at this clip's first frame")
    parser.add_argument("--source-window-s", nargs=2, type=float,
                        metavar=("START", "END"),
                        help="reviewed source-time window represented by each input clip")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--worker-mode", choices=("subprocess", "fork"), default="fork")
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--imgsz", type=int, default=480)
    parser.add_argument("--min-span-amplitude", type=float,
                        help="screen a segmentation noise-floor change (experimental)")
    parser.add_argument("--min-turn-peak-fraction", type=float,
                        help="screen the turnaround-height threshold (experimental)")
    parser.add_argument("--fusion-policy", default="default",
                        choices=("default", "ultralytics-screen-v1",
                                 "ultralytics-supported-only-v2",
                                 "ultralytics-geometry-supported-v3"))
    args = parser.parse_args()
    if args.workers < 1 or args.stride < 1 or args.imgsz < 1:
        parser.error("workers, stride and imgsz must be positive")
    if args.source_offset_s is not None and args.source_offset_s < 0:
        parser.error("source-offset-s cannot be negative")
    source_offset = args.source_offset_s
    if args.source_window_s is not None:
        source_start, source_end = args.source_window_s
        if source_start < 0 or source_end <= source_start:
            parser.error("source-window-s must be a non-empty non-negative interval")
        if source_offset is not None and abs(source_start - source_offset) > 1e-6:
            parser.error("source-offset-s must match source-window-s START")
        source_offset = source_start
    source_offset = source_offset or 0.0
    if not args.weights.is_file():
        parser.error(f"weights file does not exist: {args.weights}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.save_keypoints_dir is not None:
        args.save_keypoints_dir.mkdir(parents=True, exist_ok=True)

    # Make this screen deterministic and offline with respect to remote vision.
    for name in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY"):
        os.environ.pop(name, None)
    os.environ["NAN_BASE_URL"] = ""
    os.environ["BARRA_SENTINEL"] = "record"
    os.environ["BARRA_POSE_BACKEND"] = "ultralytics"
    os.environ["BARRA_POSE_WORKERS"] = str(args.workers)
    os.environ["BARRA_YOLO_POSE_STRIDE"] = str(args.stride)
    os.environ["BARRA_YOLO_POSE_IMGSZ"] = str(args.imgsz)
    os.environ["BARRA_POSE_CPU_THREADS"] = "1"
    os.environ["BARRA_POSE_WORKER_MODE"] = args.worker_mode
    os.environ["BARRA_YOLO_POSE_WEIGHTS"] = str(args.weights)
    os.environ["BARRA_ULTRALYTICS_FUSION_POLICY"] = args.fusion_policy

    process_start = time.perf_counter()
    from barra.pose.ultralytics_backend import UltralyticsBackend
    from process import measure_job
    import barra.ingest as ingest
    if (args.min_span_amplitude is not None or
            args.min_turn_peak_fraction is not None):
        changes = {}
        if args.min_span_amplitude is not None:
            if args.min_span_amplitude < 0:
                parser.error("min-span-amplitude cannot be negative")
            changes["min_span_amplitude"] = args.min_span_amplitude
        if args.min_turn_peak_fraction is not None:
            if not 0 < args.min_turn_peak_fraction <= 1:
                parser.error("min-turn-peak-fraction must be in (0, 1]")
            changes["min_turn_peak_fraction"] = args.min_turn_peak_fraction
        ingest.THRESHOLDS = replace(ingest.THRESHOLDS, **changes)
    imports_done = time.perf_counter()
    process_import_seconds = imports_done - process_start

    candidate = UltralyticsBackend(str(args.weights))
    for clip in args.clips:
        started = time.perf_counter()
        pose_start = time.perf_counter()
        pose = candidate.estimate(clip)
        pose_end = time.perf_counter()
        if args.save_keypoints_dir is not None:
            import numpy as np
            np.save(args.save_keypoints_dir / f"{clip.stem}.npy", pose.keypoints)
        payload = measure_job({"id": clip.stem, "exercise": "auto"}, clip,
                              pose=pose, pose_backend_override="ultralytics")
        measured = time.perf_counter()
        result = {
            **payload,
            "clip": clip.stem,
            "sourceOffsetS": source_offset,
            "sourceWindowS": args.source_window_s,
            "poseKeypointsSha256": hashlib.sha256(
                pose.keypoints.tobytes(order="C")
            ).hexdigest(),
            "poseKeypointsShape": list(pose.keypoints.shape),
            "candidateTiming": {
                "poseSeconds": round(pose_end - pose_start, 3),
                "poseSubstagesSeconds": {
                    key: round(value, 3) for key, value in candidate.last_timing.items()
                },
                "poseWorkerSubstagesSeconds": [
                    {key: round(value, 3) for key, value in worker.items()}
                    for worker in candidate.last_worker_timing
                ],
                "measurementSeconds": round(measured - pose_end, 3),
                "clipElapsedSeconds": round(measured - started, 3),
                "processImportSeconds": round(process_import_seconds, 3),
            },
            "candidateConfig": {
                "backend": "ultralytics",
                "workers": args.workers,
                "workerMode": candidate.last_worker_mode,
                "stride": args.stride,
                "imgsz": args.imgsz,
                "cpuThreadsPerWorker": 1,
                "minSpanAmplitude": args.min_span_amplitude,
                "minTurnPeakFraction": ingest.THRESHOLDS.min_turn_peak_fraction,
                "fusionPolicy": args.fusion_policy,
                "weightsSha256": sha256(args.weights),
            },
            "clipSha256": sha256(clip),
        }
        path = args.output_dir / f"{clip.stem}.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"report": str(path),
                          "exercise": result.get("exercise"),
                          "n_reps": result.get("n_reps"),
                          **result["candidateTiming"]}, ensure_ascii=False),
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
