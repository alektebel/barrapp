#!/usr/bin/env python3
"""Summarize Android Round 2 attempts without hiding unfinished attempts.

Usage after pulling the app-private JSON from a quiescent phone:
  python scripts/round2_phone_report.py round2-timings.json \
    --current-boot-id "$(adb shell cat /proc/sys/kernel/random/boot_id)"

The <15 s fraction uses every recorded attempt as its denominator. A row with
missing endpoints, a partial origin, or a different boot ID is not a pass.
Percentiles describe only complete, comparable timings and are labelled as
such. Run after the phone is quiescent so pending attempts are not mistaken
for terminal failures. Geometry/hold plus a non-negative count is only a
count-status proxy; it does not establish correctness. The quality-approved
gate requires an explicit `qualityApproved: true` review annotation as well.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

TARGET_MS = 15_000
MEASURED_COUNT_STATUSES = {"geometry", "hold"}


def percentile(values: list[int | float], p: float) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * p
    lo = math.floor(at)
    hi = math.ceil(at)
    value = ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo)
    return round(value) if all(isinstance(item, int) for item in values) else round(value, 2)


def summarize(path: Path, current_boot_id: str) -> dict[str, Any]:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError("timing file must contain a JSON array")

    durations: dict[str, list[int]] = {
        "total": [], "upload_submit": [], "submit_to_result": [], "result_render": [],
    }
    under = 0
    count_status_proxy_completed = 0
    under_count_status_proxy = 0
    quality_approved_completed = 0
    under_quality_approved = 0
    unmeasured_completed = 0
    complete = 0
    source_bytes: list[int] = []
    prepared_bytes: list[int] = []
    poll_counts: list[int] = []
    prepared_larger_than_source = 0
    phase_durations: dict[str, list[int]] = {}
    observed_phase_durations: dict[str, list[int]] = {}
    observed_result_ms: list[int] = []
    observed_submit_to_result_ms: list[int] = []
    effective_transfer_mbps: list[float] = []
    incomplete_ids = []
    for row in rows:
        if not isinstance(row, dict):
            incomplete_ids.append("<invalid-row>")
            continue
        attempt_id = str(row.get("attemptId") or "<missing-id>")
        start = row.get("startedNs")
        submit = row.get("submittedNs")
        result = row.get("resultNs")
        render = row.get("renderedNs")
        comparable_origin = (
            row.get("completeOrigin") is True
            and row.get("bootId") == current_boot_id
            and isinstance(start, int) and start > 0
        )
        if comparable_origin:
            if isinstance(result, int) and result >= start:
                observed_result_ms.append((result - start) // 1_000_000)
                if isinstance(submit, int) and start <= submit <= result:
                    observed_submit_to_result_ms.append((result - submit) // 1_000_000)
            phases = row.get("phaseMs")
            if isinstance(phases, dict):
                for name, elapsed in phases.items():
                    if isinstance(elapsed, int) and elapsed >= 0:
                        observed_phase_durations.setdefault(str(name), []).append(elapsed)
        valid = (
            comparable_origin
            and all(isinstance(v, int) and v > 0 for v in (start, submit, result, render))
            and start <= submit <= result <= render
        )
        if not valid:
            incomplete_ids.append(attempt_id)
            continue
        complete += 1
        polls = row.get("pollCount")
        if type(polls) is int and polls >= 0:
            poll_counts.append(polls)
        original_size = row.get("sourceBytes")
        upload_size = row.get("preparedBytes")
        if (type(original_size) is int and original_size > 0
                and type(upload_size) is int and upload_size > 0):
            source_bytes.append(original_size)
            prepared_bytes.append(upload_size)
            prepared_larger_than_source += upload_size > original_size
        stage_ns = {
            "total": render - start,
            "upload_submit": submit - start,
            "submit_to_result": result - submit,
            "result_render": render - result,
        }
        for name, elapsed in stage_ns.items():
            durations[name].append(elapsed // 1_000_000)
        phases = row.get("phaseMs")
        if isinstance(phases, dict):
            for name, elapsed in phases.items():
                if isinstance(elapsed, int) and elapsed >= 0:
                    phase_durations.setdefault(str(name), []).append(elapsed)
            transfer_ms = phases.get("singlePut") or phases.get("partTransfer")
            if (type(upload_size) is int and upload_size > 0
                    and type(transfer_ms) is int and transfer_ms > 0):
                effective_transfer_mbps.append(upload_size * 8 / (transfer_ms * 1000))
        has_count_status_proxy = (
            row.get("countStatus") in MEASURED_COUNT_STATUSES
            and type(row.get("repCount")) is int
            and row["repCount"] >= 0
        )
        quality_approved = has_count_status_proxy and row.get("qualityApproved") is True
        if has_count_status_proxy:
            count_status_proxy_completed += 1
        else:
            unmeasured_completed += 1
        if quality_approved:
            quality_approved_completed += 1
        if stage_ns["total"] < TARGET_MS * 1_000_000:
            under += 1
            if has_count_status_proxy:
                under_count_status_proxy += 1
            if quality_approved:
                under_quality_approved += 1

    n = len(rows)
    total_ms = durations["total"]
    return {
        "file": str(path),
        "currentBootId": current_boot_id,
        "targetMs": TARGET_MS,
        "attempts": n,
        "completed": complete,
        "incomplete": n - complete,
        "incompleteAttemptIds": incomplete_ids,
        "under_target": under,
        "under_target_fraction": under / n if n else 0.0,
        "count_status_proxy_completed": count_status_proxy_completed,
        "no_count_status_proxy_completed": unmeasured_completed,
        "under_target_count_status_proxy": under_count_status_proxy,
        "under_target_count_status_proxy_fraction": under_count_status_proxy / n if n else 0.0,
        "quality_approved_completed": quality_approved_completed,
        "under_target_quality_approved": under_quality_approved,
        "under_target_quality_approved_fraction": under_quality_approved / n if n else 0.0,
        "clip_bytes": {
            "comparable_attempts": len(source_bytes),
            "source_p50": percentile(source_bytes, 0.50),
            "prepared_p50": percentile(prepared_bytes, 0.50),
            "prepared_larger_than_source": prepared_larger_than_source,
        },
        "completed_total_ms": {
            "p50": percentile(total_ms, 0.50),
            "p95": percentile(total_ms, 0.95),
            "mean": round(statistics.mean(total_ms)) if total_ms else None,
        },
        "completed_poll_count": {
            "comparable_attempts": len(poll_counts),
            "p50": percentile(poll_counts, 0.50),
            "p95": percentile(poll_counts, 0.95),
        },
        "completed_stage_ms": {
            name: {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}
            for name, values in durations.items() if name != "total"
        },
        "completed_phase_ms": {
            name: {"p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}
            for name, values in sorted(phase_durations.items())
        },
        "observed_result_ms": {
            "comparable_attempts": len(observed_result_ms),
            "p50": percentile(observed_result_ms, 0.50),
            "p95": percentile(observed_result_ms, 0.95),
        },
        "observed_submit_to_result_ms": {
            "comparable_attempts": len(observed_submit_to_result_ms),
            "p50": percentile(observed_submit_to_result_ms, 0.50),
            "p95": percentile(observed_submit_to_result_ms, 0.95),
        },
        "observed_phase_ms": {
            name: {"comparable_attempts": len(values),
                   "p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}
            for name, values in sorted(observed_phase_durations.items())
        },
        "effective_transfer_mbps": {
            "comparable_attempts": len(effective_transfer_mbps),
            "p50": percentile(effective_transfer_mbps, 0.50),
            "p95": percentile(effective_transfer_mbps, 0.95),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timings", type=Path)
    parser.add_argument("--current-boot-id", required=True,
                        help="boot ID read from the same device when collecting timings")
    args = parser.parse_args()
    try:
        report = summarize(args.timings, args.current_boot_id.strip())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
