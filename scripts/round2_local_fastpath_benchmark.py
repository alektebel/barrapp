#!/usr/bin/env python3
"""Time one reviewed clip through the local server worker's first-result path.

Example:
  NAN_API_KEY= BARRA_POSE_BACKEND=ultralytics BARRA_POSE_WORKERS=6 \
  BARRA_YOLO_POSE_STRIDE=2 BARRA_YOLO_POSE_IMGSZ=480 \
  uv run python scripts/round2_local_fastpath_benchmark.py clip.mp4 \
    --min-span-amplitude 0.25 --output out/round2-latency/local.json

The output distinguishes first measured-result availability from post-result
localization, advisory vision and prose work performed by the local worker.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--exercise", default="auto")
    parser.add_argument("--min-span-amplitude", type=float)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-output", type=Path,
                        help="also save the full result payload for the quality gate")
    parser.add_argument("--label-clip", default=None,
                        help="review-manifest filename to attach to the result payload")
    parser.add_argument("--source-window", nargs=2, type=float, metavar=("START", "END"),
                        help="reviewed source window represented by the input clip")
    args = parser.parse_args()

    import barra.ingest
    import local_server

    if args.min_span_amplitude is not None:
        object.__setattr__(barra.ingest.THRESHOLDS, "min_span_amplitude",
                           args.min_span_amplitude)
    clip = args.clip.resolve()
    job_id = f"round2-{time.time_ns():x}"[-24:]
    with tempfile.TemporaryDirectory(prefix="barrapp-round2-fastpath-") as tmp:
        local_server.DATA = Path(tmp)
        shutil.copyfile(clip, local_server.DATA / f"{job_id}.mp4")
        local_server.JOBS = {
            job_id: {
                "id": job_id,
                "owner": "round2-benchmark",
                "exercise": args.exercise,
                "status": "processing",
                "createdAt": "round2-benchmark",
            }
        }
        started = time.perf_counter_ns()
        local_server._run(job_id)
        worker_total_ms = round((time.perf_counter_ns() - started) / 1_000_000)
        job = local_server.JOBS[job_id]
        result = job.get("result") or {}
        full_report = {**result, "clip": args.label_clip or clip.name}
        if args.source_window:
            start_s, end_s = args.source_window
            full_report["sourceWindowS"] = [start_s, end_s]
            full_report["sourceOffsetS"] = start_s
        output = {
            "jobId": job_id,
            "clip": str(clip),
            "clipBytes": clip.stat().st_size,
            "status": job.get("status"),
            "exercise": result.get("exercise"),
            "repCount": result.get("n_reps"),
            "countStatus": result.get("countStatus"),
            "traceId": result.get("traceId"),
            "resultReadyAtEpochMs": job.get("resultReadyAtEpochMs"),
            "serverMeasurementMs": job.get("serverMeasurementMs"),
            "workerTotalMs": worker_total_ms,
            "postResultMs": max(
                0, worker_total_ms - int(job.get("serverMeasurementMs") or 0)),
            "visionStatus": result.get("visionStatus"),
            "proseStatus": result.get("proseStatus"),
        }
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(json.dumps(full_report, indent=2) + "\n")
    print(rendered, end="")
    return 0 if output["status"] == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
