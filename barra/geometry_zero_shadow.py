"""Fail-closed shadow eligibility check for a possible geometric zero.

This module never changes a count status. It evaluates evidence captured by
the segmentation trace and can only suggest a shadow candidate; callers must
keep the actual result unmeasured until a broader reviewed gate authorizes a
production status.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .movements import resolve


MIN_ACTIVE_SPAN_OBSERVED_FRAC = 0.90
_CANDIDATE_TIME = re.compile(r"candidate at ([0-9]+(?:\.[0-9]+)?)s")
_PHYSICAL_REJECTION_MARKERS = (
    "the rest position is not a hang",
    "the rest position is not a support",
    "the hands were not on anything fixed",
)


def _finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _disposition(name: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "clip": row.get("clip"),
        "disposition": name,
        "reason": reason,
        "count": 0,
        "countStatus": "unmeasured",
        "measured": False,
    }


def evaluate_zero_candidate(
    row: dict[str, Any], *,
    min_observed_frac: float = MIN_ACTIVE_SPAN_OBSERVED_FRAC,
) -> dict[str, Any]:
    """Classify shadow evidence without ever asserting a measured zero.

    A candidate needs a known movement, an existing unmeasured zero, no
    accepted reps, at least one fully evidenced active span, and a physical
    rejection for every detected turnaround. A missing or malformed field
    fails closed.
    """
    if (not _finite_number(min_observed_frac)
            or not 0 < float(min_observed_frac) <= 1):
        raise ValueError("min_observed_frac must be in (0, 1]")

    movement = row.get("movement")
    if not isinstance(movement, str) or movement in {"", "unknown", "auto"}:
        return _disposition("abstain_unknown_movement", row,
                            "movement is unknown or automatic")
    try:
        resolve(movement)
    except SystemExit:
        return _disposition("abstain_unknown_movement", row,
                            "movement is not a supported movement")

    accepted = row.get("accepted_geometry_reps")
    if not isinstance(accepted, int) or isinstance(accepted, bool) or accepted < 0:
        return _disposition("abstain_invalid_evidence", row,
                            "accepted geometry rep count is missing or invalid")
    if accepted > 0:
        return _disposition("abstain_accepted_reps", row,
                            "at least one geometry rep was accepted")
    if row.get("reported_count_status") != "unmeasured" or row.get("reported_count") != 0:
        return _disposition("abstain_invalid_evidence", row,
                            "source result is not the explicit unmeasured zero case")

    coverage = row.get("active_span_coverage")
    amplitudes = row.get("span_amplitudes")
    if not isinstance(coverage, list) or not isinstance(amplitudes, list):
        return _disposition("abstain_invalid_evidence", row,
                            "active span evidence is missing")
    if not coverage:
        return _disposition("abstain_no_active_spans", row,
                            "no qualifying active spans were observed")
    if len(coverage) != len(amplitudes):
        return _disposition("abstain_invalid_evidence", row,
                            "active span coverage and amplitude evidence differ")
    for span, amplitude in zip(coverage, amplitudes):
        if not isinstance(span, dict) or not isinstance(amplitude, dict):
            return _disposition("abstain_invalid_evidence", row,
                                "active span evidence has an invalid shape")
        span_interval = span.get("at_seconds")
        amplitude_interval = amplitude.get("at_seconds")
        if (not isinstance(span_interval, list) or len(span_interval) != 2
                or not isinstance(amplitude_interval, list)
                or len(amplitude_interval) != 2
                or any(not _finite_number(value)
                       for value in span_interval + amplitude_interval)
                or span_interval[1] <= span_interval[0]
                or any(abs(float(a) - float(b)) > 0.02
                       for a, b in zip(span_interval, amplitude_interval))):
            return _disposition("abstain_invalid_evidence", row,
                                "active span coverage and amplitude intervals do not match")
        frames, observed = span.get("frames"), span.get("observed_frames")
        value = amplitude.get("amplitude")
        if (not isinstance(frames, int) or isinstance(frames, bool) or frames <= 0
                or not isinstance(observed, int) or isinstance(observed, bool)
                or observed < 0 or observed > frames or not _finite_number(value)
                or float(value) < 0):
            return _disposition("abstain_invalid_evidence", row,
                                "active span evidence has invalid measurements")
        observed_frac = span.get("observed_frac")
        exact_frac = observed / frames
        if (observed_frac is not None
                and (not _finite_number(observed_frac)
                     or abs(float(observed_frac) - exact_frac) > 0.0011)):
            return _disposition("abstain_invalid_evidence", row,
                                "reported observed fraction conflicts with frame counts")
        if exact_frac < float(min_observed_frac):
            return _disposition("abstain_inadequate_coverage", row,
                                "an active span has inadequate observed pose coverage")

    turnarounds = row.get("candidate_turnarounds")
    rejections = row.get("rejections")
    if not isinstance(turnarounds, list) or not isinstance(rejections, list):
        return _disposition("abstain_invalid_evidence", row,
                            "candidate and rejection evidence is missing")
    if not turnarounds:
        return _disposition("abstain_no_turnarounds", row,
                            "no explicit turnaround exists to account for")
    if any(not _finite_number(item) or float(item) < 0 for item in turnarounds):
        return _disposition("abstain_invalid_evidence", row,
                            "turnaround timestamp is invalid")

    candidate_rejections: list[tuple[float, str]] = []
    for rejection in rejections:
        if not isinstance(rejection, dict):
            continue
        match = _CANDIDATE_TIME.fullmatch(str(rejection.get("what", "")))
        reason = str(rejection.get("reason", "")).lower()
        if match and any(marker in reason for marker in _PHYSICAL_REJECTION_MARKERS):
            candidate_rejections.append((float(match.group(1)), reason))

    unaccounted = [float(turn) for turn in turnarounds
                   if not any(abs(float(turn) - rejected_at) <= 0.02
                              for rejected_at, _ in candidate_rejections)]
    if unaccounted:
        return _disposition("abstain_unaccounted_turnaround", row,
                            "each turnaround must have an explicit physical rejection")

    result = _disposition("candidate_geometry_zero", row,
                          "all observed turnarounds were physically rejected")
    result["evidence"] = {
        "movement": movement,
        "activeSpans": len(coverage),
        "minimumObservedFraction": round(min(
            span["observed_frames"] / span["frames"] for span in coverage), 4),
        "turnarounds": [float(x) for x in turnarounds],
        "physicalRejections": [
            {"atSeconds": at, "reason": reason}
            for at, reason in candidate_rejections
            if any(abs(float(turn) - at) <= 0.02 for turn in turnarounds)
        ],
        "warning": "shadow eligibility only; never a measured result",
    }
    return result
