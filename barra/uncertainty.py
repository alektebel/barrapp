"""Uncertainty signals for exercise identity — for confirmation gates.

Each signal is a number where **higher means more uncertain** (more reason to
ask the athlete). They are not calibrated probabilities; they are ranked by
how well they predict a wrong fusion label on the labelled corpus
(`scripts/uncertainty_eval.py`).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

# Fusion statuses scored by empirical error rate on the labelled corpus
# (fusion+vision vs directory/adjudicated trick, 261 clips). Higher = more
# often wrong — note geometry-model-agree is risky when vision did not join.
STATUS_UNCERTAINTY = {
    "abstain": 1.0,
    "geometry-only": 1.0,
    "model-decides": 0.95,
    "geometry-model-agree": 0.74,
    "vision-decides": 0.15,
    "majority": 0.08,
}

# Statuses whose empirical error rate on the labelled corpus (261 clips,
# fusion+vision vs directory/adjudicated trick) cleared ~70%. Asking the
# athlete here catches most fusion mistakes at high precision
# (`scripts/uncertainty_eval.py`, out/uncertainty-eval/report.json).
RISKY_FUSION_STATUSES = frozenset({
    "abstain",
    "geometry-only",
    "model-decides",
    "geometry-model-agree",
})


def _canon(label: Any) -> Optional[str]:
    if label is None:
        return None
    s = str(label).strip().lower().replace("-", "_")
    if s in ("", "unknown", "none", "null", "n/a", "other"):
        return None
    return s


def _f(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def binary_entropy(p: float) -> float:
    """H(p, 1-p) in bits. Monotone with 1-p for p in [0.5, 1]."""
    p = min(1.0, max(0.0, float(p)))
    if p <= 0.0 or p >= 1.0:
        return 0.0
    q = 1.0 - p
    return float(-(p * math.log2(p) + q * math.log2(q)))


def vote_entropy(labels: list[Optional[str]]) -> float:
    """Entropy of the discrete vote distribution over non-abstaining detectors."""
    counts: dict[str, int] = {}
    for lab in labels:
        c = _canon(lab)
        if c:
            counts[c] = counts.get(c, 0) + 1
    n = sum(counts.values())
    if n <= 0:
        return 1.0
    h = 0.0
    for k in counts.values():
        p = k / n
        h -= p * math.log2(p)
    # Max entropy with 3 votes is log2(3) ≈ 1.585; normalise to [0, 1].
    return float(h / math.log2(max(2, min(3, n))))


def signals_from_detectors(
    *,
    truth: str | None = None,
    model: str | None = None,
    model_confidence: float | None = None,
    model_margin: float | None = None,
    geometry: str | None = None,
    geometry_confidence: float | None = None,
    vision: str | None = None,
    fusion: Mapping[str, Any] | None = None,
    fusion_label: str | None = None,
) -> dict[str, float]:
    """Named uncertainty scores (higher = more uncertain)."""
    m = _canon(model)
    g = _canon(geometry)
    v = _canon(vision)
    fus = fusion or {}
    f_label = _canon(fusion_label or fus.get("exercise"))
    f_status = str(fus.get("status") or "")
    f_conf = _f(fus.get("confidence"), 0.0)
    m_conf = _f(model_confidence, 0.0)
    m_margin = _f(model_margin, 0.0)
    g_conf = _f(geometry_confidence, 0.0)

    votes = [m, g, v]
    known = [x for x in votes if x]
    unique = {x for x in known}

    out: dict[str, float] = {
        "model_inv_confidence": 1.0 - m_conf,
        "model_inv_margin": 1.0 - m_margin if model_margin is not None else 1.0,
        "model_binary_entropy": binary_entropy(m_conf),
        "geometry_inv_confidence": 1.0 - g_conf,
        "fusion_inv_confidence": 1.0 - f_conf,
        "fusion_status_uncertainty": float(STATUS_UNCERTAINTY.get(f_status, 0.7)),
        "vote_entropy": vote_entropy(votes),
        "n_unique_votes": float(len(unique)) / 3.0,
        "model_geometry_disagree": 1.0 if (m and g and m != g) else 0.0,
        "model_vision_disagree": 1.0 if (m and v and m != v) else 0.0,
        "geometry_vision_disagree": 1.0 if (g and v and g != v) else 0.0,
        "any_pair_disagree": 1.0 if len(unique) > 1 else 0.0,
        "fusion_abstain": 1.0 if (not f_label or f_status == "abstain") else 0.0,
        "risky_fusion_status": 1.0 if f_status in RISKY_FUSION_STATUSES else 0.0,
        # Composite used as a practical gate candidate.
        "gate_margin_or_disagree": max(
            1.0 - m_margin if model_margin is not None else 0.0,
            1.0 if (m and g and m != g) else 0.0,
            1.0 if (m and v and m != v) else 0.0,
            float(STATUS_UNCERTAINTY.get(f_status, 0.0)),
        ),
    }
    if truth is not None:
        t = _canon(truth)
        out["error_model"] = 1.0 if (t and m and t != m) else (0.0 if t and m else float("nan"))
        out["error_geometry"] = 1.0 if (t and g and t != g) else (
            1.0 if t and not g else (0.0 if t and g else float("nan")))
        out["error_fusion"] = 1.0 if (t and f_label and t != f_label) else (
            1.0 if t and not f_label else (0.0 if t and f_label else float("nan")))
        if v:
            out["error_vision"] = 1.0 if (t and t != v) else 0.0
    return out


def auroc(scores: list[float], labels: list[int]) -> float | None:
    """ROC AUC via Mann–Whitney; None if only one class present."""
    pos = [s for s, y in zip(scores, labels) if y == 1 and s == s]
    neg = [s for s, y in zip(scores, labels) if y == 0 and s == s]
    if not pos or not neg:
        return None
    # AUC = P(score_pos > score_neg) + 0.5 P(equal)
    gt = sum(1 for p in pos for n in neg if p > n)
    eq = sum(1 for p in pos for n in neg if p == n)
    return (gt + 0.5 * eq) / (len(pos) * len(neg))


def average_precision(scores: list[float], labels: list[int]) -> float | None:
    """Area under precision-recall for the positive (error) class."""
    pairs = [(s, y) for s, y in zip(scores, labels) if s == s]
    if not pairs or not any(y == 1 for _, y in pairs) or not any(y == 0 for _, y in pairs):
        return None
    pairs.sort(key=lambda xy: xy[0], reverse=True)
    tp = 0
    fp = 0
    n_pos = sum(y for _, y in pairs)
    prev_recall = 0.0
    ap = 0.0
    for i, (_, y) in enumerate(pairs):
        if y == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / n_pos
        ap += precision * (recall - prev_recall)
        prev_recall = recall
    return float(ap)


def best_threshold(scores: list[float], labels: list[int],
                   *, min_recall: float = 0.5) -> dict[str, float] | None:
    """Threshold that maximises F1 for predicting error, with recall floor."""
    pairs = [(s, y) for s, y in zip(scores, labels) if s == s]
    if not pairs:
        return None
    candidates = sorted({s for s, _ in pairs}, reverse=True)
    best: dict[str, float] | None = None
    n_pos = sum(y for _, y in pairs)
    if n_pos == 0:
        return None
    for thr in candidates:
        tp = sum(1 for s, y in pairs if s >= thr and y == 1)
        fp = sum(1 for s, y in pairs if s >= thr and y == 0)
        fn = n_pos - tp
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / n_pos
        if rec < min_recall:
            continue
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        row = {"threshold": thr, "precision": prec, "recall": rec, "f1": f1,
               "flagged": float(tp + fp), "errorsCaught": float(tp)}
        if best is None or row["f1"] > best["f1"]:
            best = row
    return best


def needs_confirmation(fusion: Mapping[str, Any] | None,
                       *,
                       model_margin: float | None = None,
                       margin_floor: float = 0.32,
                       use_margin: bool = False) -> dict[str, Any]:
    """Whether the athlete should name the exercise before scoring.

    Default rule (best precision on the labelled corpus, ~0.85 P / 0.61 R):
    fusion landed in a risky status (`RISKY_FUSION_STATUSES`). Model margin is
    opt-in (`use_margin=True`) — alone it flags too many correct majority votes.

    Also asks when vision alone decides against a different geometric name
    (jobs 93ebbf6e4894 / cc61dc871b9d, 2026-11-02): vision-decides is usually
    right on the labelled corpus, but a free-text or sideways-clip miss that
    disagrees with geometry must not be scored silently.

    When confirmation is needed the *client* names the exercise freely — there
    is no server-side options list. `detectedLabel` is only the pipeline's
    current guess (optional hint), never a menu of candidates.
    """
    fus = fusion or {}
    status = str(fus.get("status") or "")
    reasons: list[str] = []
    if status in RISKY_FUSION_STATUSES:
        reasons.append(f"fusion_status:{status}")
    if use_margin and model_margin is not None and float(model_margin) < margin_floor:
        reasons.append(f"model_margin:{float(model_margin):.3f}<{margin_floor}")
    if not _canon(fus.get("exercise")):
        reasons.append("fusion_abstain")
    chosen = _canon(fus.get("exercise"))
    geometry = _canon(fus.get("geometry"))
    if (status == "vision-decides" and chosen and geometry
            and chosen != geometry):
        reasons.append(f"detectors_disagree:vision={chosen},geometry={geometry}")
    ask = bool(reasons)
    return {
        "needsConfirmation": ask,
        "reasons": reasons,
        "fusionStatus": status or None,
        # Pipeline guess only — the client types the name; never an options list.
        "detectedLabel": chosen,
        "clientNamesExercise": ask,
        # Kept for older phones that still read this key; same as detectedLabel.
        "suggestedExercise": chosen,
    }


def classification_confidence(
    fusion: Mapping[str, Any] | None = None,
    *,
    geometry_confidence: float | None = None,
    grounding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A single 0–1 confidence for the clip's exercise identity.

    Higher means more confident. This is not a calibrated probability; it
    combines fusion's own confidence with the confirmation gate. When the
    athlete must name the exercise, confidence is capped low so the phone
    cannot present a disputed label as settled.
    """
    fus = fusion or {}
    ground = grounding or {}
    ask = bool(ground.get("needsConfirmation"))
    status = str(fus.get("status") or ground.get("fusionStatus") or "")
    raw = _f(fus.get("confidence"), 0.0)
    if raw <= 0.0 and geometry_confidence is not None:
        raw = _f(geometry_confidence, 0.0)
    # Status prior: majority/vision-backed votes start higher than geometry-only.
    status_prior = 1.0 - float(STATUS_UNCERTAINTY.get(status, 0.7))
    value = max(raw, 0.0) * 0.7 + status_prior * 0.3
    if not _canon(fus.get("exercise")) and not ask:
        value = 0.0
    value = float(max(0.0, min(1.0, value)))
    if value >= 0.75:
        band = "high"
    elif value >= 0.50:
        band = "medium"
    else:
        band = "low"
    # `value` stays the per-clip confidence measure (discriminative across
    # videos). `needsConfirmation` / `clientNamesExercise` are the separate
    # gate that asks the athlete to type the name — not a second collapse of
    # every risky clip to the same number.
    return {
        "value": round(value, 3),
        "band": band,
        "kind": "fusion",
        "needsConfirmation": ask,
        "fusionStatus": status or None,
        "clientNamesExercise": ask,
    }


def rank_signals(rows: list[Mapping[str, Any]], error_key: str,
                 signal_keys: list[str]) -> list[dict[str, Any]]:
    """Rank signals by AUROC then AP for predicting `error_key`."""
    labels = []
    for r in rows:
        e = r.get(error_key)
        if e != e:  # NaN
            labels.append(None)
        else:
            labels.append(int(e))
    ranked = []
    for key in signal_keys:
        scores, ys = [], []
        for r, y in zip(rows, labels):
            if y is None:
                continue
            s = r.get(key)
            if s is None or s != s:
                continue
            scores.append(float(s))
            ys.append(y)
        auc = auroc(scores, ys)
        ap = average_precision(scores, ys)
        thr = best_threshold(scores, ys) if auc is not None else None
        ranked.append({
            "signal": key,
            "n": len(ys),
            "errors": sum(ys),
            "auroc": None if auc is None else round(auc, 4),
            "ap": None if ap is None else round(ap, 4),
            "bestGate": ({k: round(v, 4) if isinstance(v, float) else v
                          for k, v in thr.items()} if thr else None),
        })
    ranked.sort(key=lambda r: (-(r["auroc"] or -1), -(r["ap"] or -1)))
    return ranked
