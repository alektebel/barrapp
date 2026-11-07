"""Stamp a declared load onto a finished result.

Lives in the API zip (not under barra/) so POST /v1/jobs/{id}/load works
without the worker package. Keep the mapping in sync with barra/load.py.
"""
from __future__ import annotations

WEIGHTED_FOR = {
    "dip": "weighted_dip",
    "pull_up": "weighted_pull_up",
    "muscle_up": "weighted_muscle_up",
}

_HUMAN = {
    "weighted_dip": "Weighted dip",
    "weighted_pull_up": "Weighted pull-up",
    "weighted_muscle_up": "Weighted muscle-up",
}


def apply_declared_load(result: dict, kg: float) -> dict:
    """Stamp a declared load onto a finished result (no re-measure)."""
    out = dict(result or {})
    kg = float(kg)
    if not (kg > 0):
        raise ValueError("kg must be positive")
    base = out.get("baseExercise") or out.get("exercise")
    base_key = str(base or "").strip().lower().replace("-", "_").replace(" ", "_")
    weighted = out.get("weightedExercise") or WEIGHTED_FOR.get(base_key)
    out["loadKg"] = round(kg, 2)
    out["asksLoad"] = False
    out["declaredLoad"] = True
    if weighted:
        out["weightedExercise"] = weighted
        out["skillClaim"] = weighted
        label = _HUMAN.get(weighted) or weighted.replace("_", " ")
        out["clientLabel"] = f"{label} · {kg:g} kg"
        det = dict(out.get("detected") or {})
        det["label"] = f"{label} ({kg:g} kg)"
        out["detected"] = det
    return out
