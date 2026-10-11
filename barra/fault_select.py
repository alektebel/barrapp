"""Clip-level fault selection: consensus gate + primary cue ranking.

Per-rep assessments stay honest measurements. Coaching is different: telling
an athlete seven things that are wrong 85% of the time trains them to ignore
the app. This module turns the rep table into what the athlete should hear.

Two policies, both measured on the labelled calisthenics fault set:

* **min-reps consensus** — a clip-level fault requires the same error on at
  least `fault_min_reps` judged reps (or every rep when the set is shorter).
  One-rep pose jitter was the bulk of the false-alarm storm.
* **primary by normalised exceedance** — among clip-level faults, rank by how
  far past threshold the worst firing rep sits, in units of |threshold|. Weak
  as a ranker (barely beats random) but doubles coaching precision versus
  dumping every alarm, and attaches a number the phone can show.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .config import THRESHOLDS


def _exceedance(value: float, threshold: float, comparison: str) -> float:
    scale = abs(float(threshold)) + 1e-6
    if comparison in ("<", "<="):
        return (float(threshold) - float(value)) / scale
    return (float(value) - float(threshold)) / scale


def clip_fault_counts(reps: Sequence[Mapping[str, Any]],
                      min_count: Optional[int] = None) -> dict[str, int]:
    """How many reps showed each failure name, after the consensus gate.

    Failures under the gate are dropped from the clip-level read-out. Per-rep
    `faults` / `assessments` are untouched so a curious athlete can still open
    a single rep and see what fired.
    """
    need = THRESHOLDS.fault_min_reps if min_count is None else int(min_count)
    counts: dict[str, int] = {}
    for rep in reps:
        for f in rep.get("failures") or []:
            counts[f] = counts.get(f, 0) + 1
    n_reps = len(reps)
    if n_reps <= 0:
        return {}
    # A one-rep or one-hold set cannot clear a two-rep bar; require every
    # judged attempt instead of silently deleting the only evidence.
    gate = min(max(1, need), n_reps)
    return {name: n for name, n in counts.items() if n >= gate}


def primary_from_assessments(
        per_rep_assessments: Sequence[Sequence[Any]],
        min_count: Optional[int] = None) -> Optional[dict]:
    """The single coaching cue: highest normalised exceedance among consensus faults.

    `per_rep_assessments` is the list of per-rep Assessment lists (or their
    `as_dict` rows). Returns None when nothing clears the consensus gate.
    """
    need = THRESHOLDS.fault_min_reps if min_count is None else int(min_count)
    n_reps = len(per_rep_assessments)
    if n_reps <= 0:
        return None
    gate = min(max(1, need), n_reps)

    # errorId -> list of (exceedance, row dict, correction)
    fired: dict[str, list[tuple[float, dict, str]]] = {}
    for assessments in per_rep_assessments:
        for a in assessments:
            if hasattr(a, "as_dict"):
                row = a.as_dict()
                correction = getattr(getattr(a, "rule", None), "correction", "") or ""
            else:
                row = dict(a)
                correction = str(row.get("correction") or "")
            if row.get("status") != "observed":
                continue
            ev = row.get("evidence") or {}
            value, threshold = ev.get("value"), ev.get("threshold")
            comparison = ev.get("comparison") or row.get("comparison")
            if value is None or threshold is None or not comparison:
                continue
            try:
                ex = _exceedance(float(value), float(threshold), str(comparison))
            except (TypeError, ValueError):
                continue
            eid = str(row.get("errorId") or "")
            if not eid:
                continue
            fired.setdefault(eid, []).append((ex, row, correction))

    candidates = []
    for eid, hits in fired.items():
        if len(hits) < gate:
            continue
        best_ex, best_row, correction = max(hits, key=lambda h: h[0])
        candidates.append((best_ex, eid, best_row, len(hits), correction))
    if not candidates:
        return None
    best_ex, eid, row, n_obs, correction = max(candidates, key=lambda c: c[0])
    ev = row.get("evidence") or {}
    return {
        "errorId": eid,
        "name": row.get("name") or eid.split(".", 1)[-1],
        "phase": row.get("phase"),
        "observedReps": n_obs,
        "exceedance": round(float(best_ex), 4),
        "value": ev.get("value"),
        "threshold": ev.get("threshold"),
        "comparison": ev.get("comparison"),
        "correction": correction or None,
        "rankBy": "normalised-exceedance",
    }
