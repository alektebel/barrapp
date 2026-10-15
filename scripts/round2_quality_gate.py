#!/usr/bin/env python3
"""Compare Round 2 candidate reports with reviewed manifest assertions.

Usage:
  python scripts/round2_quality_gate.py out/round2-latency/.../report.json [...]

Only human-reviewed movement/count labels, explicit forbidden faults, and
explicit not-rep intervals are hard gates. Unreviewed labels are reported as
coverage gaps and never promoted to ground truth.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/evaluation/sample_manifest.json"
FORBIDDEN_LABEL_ALIASES = {"push_up.lift_stall": {"stall"}}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _clip_id(value: str) -> str:
    match = re.search(r"WA\d{4}", value, re.IGNORECASE)
    return match.group(0).upper() if match else Path(value).stem.upper()


def _direct_result(report: dict[str, Any]) -> dict[str, Any] | None:
    if "exercise" not in report or "n_reps" not in report:
        return None
    exercise = report.get("exercise")
    # `analyze_clip` preserves the request (`auto`) when fusion deliberately
    # abstains and returns an unmeasured payload. For a candidate gate, the
    # actual final vote is recorded separately under detected.fusion.
    detected = report.get("detected")
    fusion = detected.get("fusion") if isinstance(detected, dict) else None
    if exercise in ("", "auto", None) and isinstance(fusion, dict):
        exercise = fusion.get("exercise") or exercise
    labels: set[str] = set()
    raw_failures = report.get("failures") or {}
    if isinstance(raw_failures, dict):
        labels.update(_norm(str(k)) for k, count in raw_failures.items()
                      if not isinstance(count, (int, float)) or count > 0)
    elif isinstance(raw_failures, list):
        labels.update(_norm(str(item)) for item in raw_failures)
    intervals = []
    for rep in report.get("reps") or []:
        for assessment in rep.get("assessments") or []:
            if assessment.get("status") in {"observed", "present", "failed"}:
                error_id = str(assessment.get("errorId", ""))
                if error_id:
                    labels.add(_norm(error_id.split(".")[-1]))
                if assessment.get("name"):
                    labels.add(_norm(str(assessment["name"])))
        start, end = rep.get("startS"), rep.get("endS")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            intervals.append([start, end])
    return {"exercise": exercise, "n_reps": report.get("n_reps"),
            "countStatus": report.get("countStatus"),
            "_labels": labels, "phases": intervals}


def evaluate(report: dict[str, Any], references: dict[str, dict]) -> dict[str, Any]:
    clip_id = _clip_id(str(report.get("clip") or report.get("source") or ""))
    source_offset = report.get("sourceOffsetS", 0.0)
    if (type(source_offset) not in (int, float)
            or not math.isfinite(source_offset) or source_offset < 0):
        return {"clip": clip_id, "status": "fail",
                "failures": ["invalid sourceOffsetS"], "coverageGaps": []}
    source_window = report.get("sourceWindowS")
    if source_window is not None:
        if (not isinstance(source_window, list) or len(source_window) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in source_window)
                or source_window[0] < 0 or source_window[1] <= source_window[0]
                or abs(source_window[0] - source_offset) > 1e-6):
            return {"clip": clip_id, "status": "fail",
                    "failures": ["invalid sourceWindowS"], "coverageGaps": []}
    ref = references.get(clip_id)
    if ref is None:
        return {"clip": clip_id, "status": "unmatched", "failures": [],
                "coverageGaps": ["no reviewed manifest entry"]}

    measurements = report.get("measurements") or {}
    auto = measurements.get("auto")
    # Some focused experiment reports store the auto result at the top level.
    if auto is None and "auto_exercise" in report:
        auto = {"exercise": report.get("auto_exercise"),
                "n_reps": report.get("n_reps"),
                "countStatus": report.get("countStatus"),
                "failures": report.get("failures") or {}, "phases": []}
    if auto is None:
        auto = _direct_result(report)

    if auto is not None and source_offset:
        auto = {**auto, "phases": [
            [float(phase[0]) + source_offset, float(phase[1]) + source_offset]
            for phase in auto.get("phases", [])
        ]}

    failures: list[str] = []
    gaps: list[str] = []
    expected = ref
    matching_windows = []
    if source_window is not None:
        for window in ref.get("windows") or []:
            interval = window.get("intervalS") or []
            if (window.get("reviewMethod") in {"contact-sheet", "frame-by-frame"}
                    and len(interval) == 2
                    and float(interval[0]) <= source_window[0]
                    and source_window[1] <= float(interval[1])):
                matching_windows.append(window)
    if matching_windows:
        expected = min(matching_windows,
                       key=lambda item: float(item["intervalS"][1])
                       - float(item["intervalS"][0]))
    reviewed = expected.get("reviewMethod") in {"contact-sheet", "frame-by-frame"}
    expected_move, expected_reps = expected.get("movement"), expected.get("reps")
    if reviewed and expected_move is not None and type(expected_reps) is int:
        if auto is None:
            failures.append("missing auto measurement")
        else:
            if auto.get("exercise") != expected_move:
                failures.append(f"movement {auto.get('exercise')!r} != reviewed {expected_move!r}")
            if auto.get("n_reps") != expected_reps:
                failures.append(f"reps {auto.get('n_reps')!r} != reviewed {expected_reps}")
            if expected_move != "unknown" and auto.get("countStatus") not in {"geometry", "hold"}:
                failures.append(
                    f"count status {auto.get('countStatus')!r} is not a measured count")
    else:
        gaps.append("movement/count not fully reviewed; excluded from hard gate")

    if auto is not None:
        labels = set(auto.get("_labels") or ())
        raw_failures = auto.get("failures") or {}
        if isinstance(raw_failures, dict):
            labels.update(_norm(str(k)) for k, count in raw_failures.items()
                          if not isinstance(count, (int, float)) or count > 0)
        elif isinstance(raw_failures, list):
            labels.update(_norm(str(item)) for item in raw_failures)
        for item in ref.get("forbidden") or []:
            error_id = str(item.get("errorId", ""))
            label = error_id.split(".")[-1]
            aliases = FORBIDDEN_LABEL_ALIASES.get(error_id, set())
            if _norm(label) in labels or any(_norm(alias) in labels for alias in aliases):
                failures.append(f"forbidden fault emitted: {item.get('errorId')}")
        for item in ref.get("notReps") or []:
            interval = item.get("intervalS") or []
            if len(interval) != 2:
                continue
            for phase in auto.get("phases") or []:
                if (len(phase) == 2 and float(phase[0]) < float(interval[1])
                        and float(phase[1]) > float(interval[0])):
                    failures.append(
                        f"rep interval {phase} overlaps reviewed not-rep {interval}")

    status = "fail" if failures else "incomplete" if gaps else "pass"
    return {"clip": clip_id, "status": status,
            "failures": failures, "coverageGaps": gaps}


def run(paths: list[Path], manifest_path: Path = MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    references = {
        _clip_id(clip["file"]): clip for clip in manifest.get("clips", [])
    }
    results = []
    for path in paths:
        report = json.loads(path.read_text())
        if not report.get("clip") and not report.get("source"):
            report["clip"] = path.stem
        result = evaluate(report, references)
        result["report"] = str(path)
        results.append(result)
    return {"passed": bool(results) and all(r["status"] == "pass" for r in results),
            "reports": len(results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    try:
        result = run(args.reports, args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
