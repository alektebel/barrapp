"""Fusion between the interpretable geometric detector and learned detectors.

The geometric classifier is trustworthy because it states the measurement that
decided each label. A learned model and a vision label are useful second
opinions, but they are not interchangeable evidence: they can be confident on
out-of-taxonomy movements, and labels scraped from the same VLM family can agree
with themselves while both are wrong.

This module therefore makes the vote conservative:
  * it only promotes a learned/vision label when it has repeated independent
    support or, for an unknown geometric call, when the learned label is strong;
  * it never erases the geometric reason; it attaches a status that downstream
    reports can display as review;
  * aliases are resolved before voting, so `pull-up` and `pull_up` count as one.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

GEOMETRY_STRONG_MARGIN = 0.85
MODEL_ACCEPT_CONFIDENCE = 0.82
MODEL_ACCEPT_MARGIN = 0.20
OVERRIDE_GEOMETRY_CONFIDENCE = 0.74
MODEL_OVERRIDE_GEOMETRY_CONFIDENCE = 0.82
# A 7-class softmax can have a moderate max probability even when its runner-up
# is far behind. The margin is the useful evidence for overriding a weak geometric
# call, as long as the model is not a coin flip.
MODEL_OVERRIDE_MIN_CONFIDENCE = 0.40


def _label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return str(value.get("exercise") or value.get("label") or "").strip()
    return str(value).strip()


def _known(label: str) -> bool:
    return _canonical(label) is not None


def _canonical(label: str) -> Optional[str]:
    if not label or label == "unknown":
        return None
    try:
        from .movements import resolve
        return resolve(label).name
    except SystemExit:
        return label if _known(label) else None


def _same(a: str, b: str) -> bool:
    ca, cb = _canonical(a), _canonical(b)
    return bool(ca and cb and ca == cb)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def fuse_detection(geometry: Mapping[str, Any] | str,
                   model: Optional[Mapping[str, Any]] = None,
                   nan_label: Any = None) -> dict:
    """Return a final suggested exercise and why, without hiding disagreement.

    `geometry` may be a label or a `detected` dict. `model` may be a label or a
    `model_classify()` dict with `confidence` and `marginToRunnerUp`.
    `nan_label` may be a label or dict with `label`/`exercise`.
    """
    g_label = _label(geometry)
    m_label = _label(model)
    n_label = (_label(nan_label.get("label") or nan_label.get("exercise"))
               if isinstance(nan_label, Mapping) else _label(nan_label))

    g_conf = _float(geometry.get("confidence") if isinstance(geometry, Mapping) else 0.0)
    m_conf = _float(model.get("confidence") if isinstance(model, Mapping) else 0.0)
    m_margin = _float(model.get("marginToRunnerUp") if isinstance(model, Mapping) else 0.0)

    known = [x for x in (g_label, m_label, n_label) if _known(x)]
    votes: dict[str, list[str]] = {}
    for lab in known:
        can = _canonical(lab)
        if can:
            votes.setdefault(can, []).append(lab)

    if votes:
        best_can = max(votes, key=lambda c: (len(votes[c]),
                                             1 if g_label and _same(g_label, c) else 0))
        best = best_can
        support = len(votes[best_can])
        if support >= 2:
            if _same(g_label, best):
                status = "geometry-model-agree"
                confidence = max(0.80, g_conf)
            elif support >= 2 and (not _known(g_label)
                                   or g_conf < OVERRIDE_GEOMETRY_CONFIDENCE):
                status = "majority"
                confidence = max(m_conf, 0.75)
            else:
                status = "geometry-reviewed"
                confidence = max(g_conf, m_conf) * 0.90
                best = g_label
            return {
                "exercise": best,
                "confidence": round(float(confidence), 4),
                "status": status,
                "geometry": g_label or None,
                "model": m_label or None,
                "nan": n_label or None,
                "reason": f"{support} independent signal(s) agree on {best}",
            }

    if _known(g_label):
        if (_known(m_label) and not _same(g_label, m_label)
                and g_conf < MODEL_OVERRIDE_GEOMETRY_CONFIDENCE
                and m_conf >= MODEL_OVERRIDE_MIN_CONFIDENCE
                and m_margin >= MODEL_ACCEPT_MARGIN):
            return {
                "exercise": m_label,
                "confidence": round(m_conf, 4),
                "status": "model-overrides-weak-geometry",
                "geometry": g_label,
                "model": m_label,
                "nan": n_label or None,
                "reason": "the learned classifier is clear while the geometric margin is weak",
            }
        if _known(m_label) and not _same(g_label, m_label):
            status = "geometry-reviewed"
        elif g_conf >= GEOMETRY_STRONG_MARGIN:
            status = "geometry-strong"
        else:
            status = "geometry-only"
        return {
            "exercise": g_label,
            "confidence": round(g_conf, 4),
            "status": status,
            "geometry": g_label,
            "model": m_label or None,
            "nan": n_label or None,
            "reason": "geometry decided the movement",
        }

    if (_known(m_label) and m_conf >= MODEL_ACCEPT_CONFIDENCE
            and m_margin >= MODEL_ACCEPT_MARGIN):
        return {
            "exercise": m_label,
            "confidence": round(m_conf, 4),
            "status": "unknown-model-accept",
            "geometry": g_label or None,
            "model": m_label,
            "nan": n_label or None,
            "reason": "geometry abstained, but the learned classifier is strong",
        }

    return {
        "exercise": "unknown",
        "confidence": 0.0,
        "status": "abstain",
        "geometry": g_label or None,
        "model": m_label or None,
        "nan": n_label or None,
        "reason": "no detector had enough support to name the movement",
    }
