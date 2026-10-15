#!/usr/bin/env python3
"""Offline replay of count segmenters over cached pose estimates.

This script never estimates pose or makes network calls. Scraped ``reps_estimate``
values are weak silver metadata; only the reviewed sample manifest is treated as
count evidence.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

import barra.ingest as ingest
from barra.ingest import probe_video, rescue_reps, segment_reps_verbose
from dataclasses import replace
from barra.movements import resolve
from barra.posecache import load

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data/calisthenics/labels/videos"
MANIFEST = ROOT / "data/evaluation/sample_manifest.json"


def percentile(values: list[float], p: float) -> float | None:
    return round(float(np.percentile(values, p)), 3) if values else None


def intervals(reps, fps: float, offset: float = 0.0):
    return [[round(offset + a / fps, 3), round(offset + c / fps, 3)] for a, _, c in reps]


def replay(kp: np.ndarray, fps: float, movement: str, offset: float = 0.0):
    t0 = time.perf_counter()
    standard, standard_reasons = segment_reps_verbose(kp, fps, resolve(movement))
    standard_ms = (time.perf_counter() - t0) * 1000
    rescue_ms = 0.0
    rescue_note = None
    found = standard
    source = "standard"
    if not found:
        t0 = time.perf_counter()
        found, rescue_note = rescue_reps(kp, fps, resolve(movement))
        rescue_ms = (time.perf_counter() - t0) * 1000
        source = "rescue" if found else "none"
    return {"count": len(found), "source": source, "intervals_s": intervals(found, fps, offset),
            "standard_ms": round(standard_ms, 3), "rescue_ms": round(rescue_ms, 3),
            "standard_reasons": standard_reasons, "rescue_note": rescue_note}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="limit corpus labels (smoke test)")
    ap.add_argument("--min-turn-peak-fraction", type=float,
                    help="experimental turnaround-height threshold override")
    ap.add_argument("--output", type=Path, default=ROOT / "out/round2-count-shadow/report.json")
    args = ap.parse_args()
    if args.min_turn_peak_fraction is not None:
        if not 0 < args.min_turn_peak_fraction <= 1:
            ap.error("min-turn-peak-fraction must be in (0, 1]")
        ingest.THRESHOLDS = replace(
            ingest.THRESHOLDS,
            min_turn_peak_fraction=args.min_turn_peak_fraction,
        )

    label_files = sorted(LABELS.rglob("*.json"))
    if args.limit:
        label_files = label_files[:args.limit]
    rows, times = [], []
    counts = {"labels": len(label_files), "cache_hits": 0, "cache_misses": 0,
              "unsupported": 0, "errors": 0}
    for label_path in label_files:
        label = json.loads(label_path.read_text())
        rel = Path(label.get("file", ""))
        video = ROOT / "data/calisthenics" / rel
        stem = Path(label.get("file", label_path.stem)).stem
        cache_path = ROOT / "out/keypoints" / f"{stem}.parquet"
        kp = load(video) if cache_path.exists() else None
        row = {"label": str(label_path.relative_to(ROOT)), "video": str(video.relative_to(ROOT)),
               "movement": label.get("claimed_trick"), "reps_estimate_weak_silver": label.get("reps_estimate"),
               "cache": "hit" if kp is not None else "miss"}
        if kp is None:
            counts["cache_misses"] += 1
            rows.append(row)
            continue
        counts["cache_hits"] += 1
        movement = label.get("claimed_trick")
        try:
            profile = resolve(movement)
        except (SystemExit, Exception) as e:
            row["skip"] = f"unsupported movement: {movement!r} ({e})"
            counts["unsupported"] += 1
            rows.append(row)
            continue
        info = probe_video(video)
        fps = float(info.get("fps") or 0)
        if fps <= 0:
            row["skip"] = "could not read source fps"
            counts["errors"] += 1
            rows.append(row)
            continue
        start = max(0.0, float(label.get("technique_start") or 0))
        end = float(label.get("technique_end") or len(kp) / fps)
        # The labeling pipeline physically trims agreeing clips to the labeled
        # technique interval but preserves the original timestamps in JSON.
        # ``duration_after_cut`` marks those clips; their cached timeline starts
        # at zero, so replay the whole trimmed clip and report local intervals.
        trimmed = bool(label.get("duration_after_cut"))
        offset = 0.0 if trimmed else start
        if trimmed:
            start, end = 0.0, len(kp) / fps
        lo, hi = max(0, round(start * fps)), min(len(kp), round(end * fps))
        if hi <= lo:
            row["skip"] = "empty technique interval"
            counts["errors"] += 1
            rows.append(row)
            continue
        result = replay(kp[lo:hi], fps, profile.name, offset)
        row.update(result)
        row["technique_interval_s"] = [start, end]
        row["trimmed_source_clip"] = trimmed
        row["silver_match"] = (result["count"] == label["reps_estimate"]
                               if isinstance(label.get("reps_estimate"), int) else None)
        times.append(result["standard_ms"] + result["rescue_ms"])
        rows.append(row)

    manifest = json.loads(MANIFEST.read_text())
    reviewed = []
    for item in manifest["clips"]:
        video = ROOT / "data/calisthenics/videos/own" / item["file"]
        kp = load(video)
        rec = {"file": item["file"], "movement": item.get("movement"), "reviewed_reps": item.get("reps"),
               "review_method": item.get("reviewMethod"), "role": item.get("role")}
        if kp is None:
            rec["status"] = "cache-miss"
        elif item.get("movement") in (None, "unknown"):
            rec["status"] = "abstention-constraint; geometric count not attempted"
        else:
            info = probe_video(video)
            fps = float(info.get("fps") or 0)
            result = replay(kp, fps, item["movement"]) if fps > 0 else None
            if result is None:
                rec["status"] = "fps-unavailable"
            else:
                rec.update(result)
                rec["count_match"] = result["count"] == item["reps"] if isinstance(item.get("reps"), int) else None
                forbidden = [x["intervalS"] for x in item.get("notReps", [])]
                rec["not_rep_overlaps"] = any(max(a, x[0]) < min(b, x[1])
                                               for a, b in result["intervals_s"] for x in forbidden)
                rec["status"] = "reviewed-count-constraint" if item.get("reps") is not None else "interval-constraint"
        reviewed.append(rec)

    silver = [r for r in rows if isinstance(r.get("reps_estimate_weak_silver"), int) and "count" in r]
    errors = [abs(r["count"] - r["reps_estimate_weak_silver"]) for r in silver]
    report = {"title": "Round 2 offline count shadow replay",
              "experimental_config": {"min_turn_peak_fraction": args.min_turn_peak_fraction},
              "safety": "Cached keypoints only; no pose inference or network. Scraped reps_estimate is weak silver metadata, not ground truth.",
              "corpus": {"counts": counts, "rows_with_silver_estimate": len(silver),
                         "exact_match_vs_weak_silver": sum(e == 0 for e in errors),
                         "mae_vs_weak_silver": round(statistics.mean(errors), 3) if errors else None,
                         "segment_runtime_ms_p50": percentile(times, 50), "segment_runtime_ms_p95": percentile(times, 95)},
              "reviewed_manifest_constraints": reviewed, "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "corpus": report["corpus"],
                      "reviewed_manifest_constraints": reviewed}, indent=2))


if __name__ == "__main__":
    main()
