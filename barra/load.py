"""Ask the athlete for added load when a set looks weighted.

Barra cannot SEE a belt or plate in 2D pose — a weighted dip is geometrically
a dip. When an independent signal (vision skill, locate prose, upload name,
or the athlete's recent weighted history) says the set was loaded, the phone
asks for kilograms. The declaration is stored beside the measurement; it
never invents a number from video.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# Measured base → skill the athlete claims when they declare load.
WEIGHTED_FOR = {
    "dip": "weighted_dip",
    "pull_up": "weighted_pull_up",
    "muscle_up": "weighted_muscle_up",
}
BASE_FOR = {w: b for b, w in WEIGHTED_FOR.items()}

_HINT = re.compile(
    r"weighted|lastrad\w*|lastre|weight[\s_-]?belt|dip\s*belt|"
    r"chaleco|disco|plate|kg\b|kilogram",
    re.IGNORECASE,
)


def _slug(label: Any) -> str | None:
    """Preserve weighted_* ids; do not collapse them to the base movement."""
    if label is None:
        return None
    text = str(label).strip()
    if not text or text.lower() in {"auto", "unknown", "none", "null"}:
        return None
    import re
    slug = (text.lower().replace(" ", "_").replace("-", "_").replace("/", "_"))
    slug = re.sub(r"[^a-z0-9_]", "", slug).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if slug in BASE_FOR or slug in WEIGHTED_FOR:
        return slug
    # Common free-text → weighted skill before movements.resolve collapses it.
    if "lastrad" in slug or slug.startswith("weighted_"):
        if "dip" in slug or "fondo" in slug:
            return "weighted_dip"
        if "pull" in slug or "dominad" in slug:
            return "weighted_pull_up"
        if "muscle" in slug:
            return "weighted_muscle_up"
    try:
        from .fusion import _canonical
        return _canonical(text)
    except Exception:  # noqa: BLE001
        return slug or None


def _canon(label: Any) -> str | None:
    return _slug(label)


def _text_blob(*parts: Any) -> str:
    bits: list[str] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, Mapping):
            for k in ("exercise", "detected_exercise", "description",
                      "label", "name", "reason"):
                v = p.get(k)
                if v:
                    bits.append(str(v))
        else:
            bits.append(str(p))
    return " ".join(bits)


def asks_load(*,
              exercise: str | None,
              declared: str | None = None,
              vision_label: Any = None,
              model_exercise: str | None = None,
              recent: Mapping[str, Any] | list | None = None,
              locate: Mapping[str, Any] | None = None,
              ) -> dict:
    """Whether the phone should ask for added kilograms.

    Returns a payload fragment: `asksLoad`, `weightedExercise`, `baseExercise`,
    `reasons`, and `loadKg` (null until the athlete declares).
    """
    base = _canon(exercise)
    weighted = None
    if base in WEIGHTED_FOR:
        weighted = WEIGHTED_FOR[base]
    elif base in BASE_FOR:
        weighted = base
        base = BASE_FOR[base]
    if not weighted or not base:
        return {
            "asksLoad": False,
            "weightedExercise": None,
            "baseExercise": _canon(exercise),
            "reasons": [],
            "loadKg": None,
        }

    reasons: list[str] = []

    for who, label in (("declared", declared),
                       ("vision", vision_label),
                       ("model", model_exercise)):
        can = _canon(label)
        if can == weighted or can in BASE_FOR:
            reasons.append(f"{who}:{can}")
        elif label and _HINT.search(str(label)):
            reasons.append(f"{who}_text")

    blob = _text_blob(locate, vision_label)
    if blob and _HINT.search(blob):
        reasons.append("locate_or_vision_text")

    if isinstance(recent, Mapping):
        for name in recent:
            can = _canon(name)
            if can == weighted or can in BASE_FOR:
                reasons.append(f"recent:{can}")
                break
    elif isinstance(recent, list):
        for item in recent:
            can = _canon(item if not isinstance(item, Mapping)
                         else item.get("exercise") or item.get("name"))
            if can == weighted or can in BASE_FOR:
                reasons.append(f"recent:{can}")
                break

    # Dedup while keeping order.
    seen: set[str] = set()
    ordered = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            ordered.append(r)

    return {
        "asksLoad": bool(ordered),
        "weightedExercise": weighted,
        "baseExercise": base,
        "reasons": ordered,
        "loadKg": None,
    }


def refine_asks_load(result: dict, locate: Mapping[str, Any] | None) -> dict:
    """Re-evaluate after localize prose arrives (handler post-measure)."""
    if not isinstance(result, dict):
        return result
    if result.get("loadKg") not in (None, "", 0, 0.0):
        # Already declared — leave alone.
        return result
    info = asks_load(
        exercise=result.get("exercise"),
        declared=None,
        vision_label=(result.get("detected") or {}).get("runnerUp"),
        model_exercise=((result.get("model") or {}).get("classification")
                        or {}).get("exercise"),
        recent=None,
        locate=locate,
    )
    if not info["asksLoad"] and not result.get("asksLoad"):
        return result
    # Keep an earlier true ask; upgrade false → true when locate hints load.
    if info["asksLoad"] or result.get("asksLoad"):
        out = dict(result)
        out["asksLoad"] = True
        out["weightedExercise"] = (
            info.get("weightedExercise") or result.get("weightedExercise"))
        out["baseExercise"] = (
            info.get("baseExercise") or result.get("baseExercise")
            or result.get("exercise"))
        prev = list(result.get("loadReasons") or [])
        for r in info.get("reasons") or []:
            if r not in prev:
                prev.append(r)
        out["loadReasons"] = prev
        if "loadKg" not in out:
            out["loadKg"] = None
        return out
    return result


def apply_declared_load(result: dict, kg: float) -> dict:
    """Stamp a declared load onto a finished result (no re-measure)."""
    out = dict(result or {})
    kg = float(kg)
    if not (kg > 0):
        raise ValueError("kg must be positive")
    base = out.get("baseExercise") or out.get("exercise")
    weighted = out.get("weightedExercise") or WEIGHTED_FOR.get(_canon(base) or "")
    out["loadKg"] = round(kg, 2)
    out["asksLoad"] = False
    out["declaredLoad"] = True
    if weighted:
        out["weightedExercise"] = weighted
        out["skillClaim"] = weighted
        # Human label for the phone; measured track stays the base geometry.
        from .classify import HUMAN
        label = HUMAN.get(weighted) or weighted.replace("_", " ")
        out["clientLabel"] = f"{label} · {kg:g} kg"
        det = dict(out.get("detected") or {})
        det["label"] = f"{label} ({kg:g} kg)"
        out["detected"] = det
    return out
