"""The regression gate: this run against the saved one, tolerance per metric.

A gate that blocks on any wiggle blocks every commit; one that blocks on
nothing is decoration. So each metric carries its own tolerance, written
next to it, and the gate blocks only on a drop past that tolerance.
Improvements never block. Metrics whose denominator changed by more than
one clip are reported but never gate: a smaller denominator is a weaker
measurement, not a regression.

The golden metrics gate on absolute rates (movement accuracy, forbidden
faults, retained non-reps). The judge metrics gate on their mean rubric
score. Everything else in a run directory is informational.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# kind -> tolerance on the drop of `rate` (absolute, 0-1 scale). A metric
# not listed here is informational.
TOLERANCES = {
    "movement": 0.05,       # one clip of eight flipping is 0.125; noise below
    "repCount": 0.05,
    "forbidden": 0.0,       # a forbidden fault firing is always a regression
    "notReps": 0.0,
    "phaseScoped": 0.0,
    "unobservable": 0.0,
}


@dataclass
class GateResult:
    blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"blocked": self.blocked, "reasons": self.reasons,
                "metrics": self.metrics}


def _rate(row: dict) -> float | None:
    r = row.get("rate")
    return None if r is None else float(r)


def compare_to_baseline(current: dict, baseline_path: Path) -> GateResult:
    """Compare grade_run output against a saved baseline's grade.json.

    Blocking rules, stated so they can be argued with:
      * any metric whose rate drops by more than its tolerance blocks;
      * a zero-tolerance metric dropping at all blocks - for the must-not
        registries there is no acceptable nonzero;
      * allPassed going from true to false blocks even when the rollup
        rates held, because a clip that stopped grading is a regression
        the rollup cannot see.
    """
    result = GateResult()
    baseline_file = Path(baseline_path)
    if not baseline_file.exists():
        # No baseline is not a pass: the first run saves one and says so.
        result.reasons.append(
            f"no baseline at {baseline_file}; run with --save-baseline first")
        result.blocked = False   # advisory on the very first run
        return result
    baseline = json.loads(baseline_file.read_text())

    cur_roll = current.get("rollup") or {}
    base_roll = baseline.get("rollup") or {}
    for kind, tol in TOLERANCES.items():
        cur, base = cur_roll.get(kind), base_roll.get(kind)
        if base is None and cur is None:
            continue
        cr, br = _rate(cur or {}), _rate(base or {})
        row = {"metric": kind, "current": cr, "baseline": br, "tolerance": tol}
        if cur is not None and base is not None:
            row["currentPass"] = cur.get("pass")
            row["baselinePass"] = base.get("pass")
        if cr is not None and br is not None and br - cr > tol:
            result.blocked = True
            row["regression"] = True
            result.reasons.append(
                f"{kind}: {br:.3f} -> {cr:.3f} (drop {br - cr:.3f} > tol {tol})")
        result.metrics.append(row)

    # Denominator drift is reported, never gating: more or fewer graded
    # clips changes what the rates mean.
    cb, bb = current.get("gradedClips"), baseline.get("gradedClips")
    if cb is not None and bb is not None and cb != bb:
        result.metrics.append({"metric": "gradedClips", "current": cb,
                               "baseline": bb, "note": "informational"})

    if baseline.get("allPassed") and not current.get("allPassed"):
        result.blocked = True
        result.reasons.append("allPassed went true -> false "
                              "(a graded check started failing)")
    return result
