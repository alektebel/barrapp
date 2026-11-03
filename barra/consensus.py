"""Late-fusion consensus with family-discounted agreement and abstention."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .channels import Estimate
from .fusion import _canonical
from .skills import ancestors


def agree_working_set(a: dict | None, b: dict | None, fps: float = 30.0
                      ) -> str:
    if not a or not b:
        return "abstain"
    iou = _tiou(a.get("start"), a.get("end"), b.get("start"), b.get("end"))
    if iou >= 0.5:
        return "agree"
    if iou < 0.2:
        return "disagree"
    return "partial"


def agree_identity(a: Any, b: Any) -> str:
    if a in (None, "", "unknown", "unclear") or b in (None, "", "unknown", "unclear"):
        return "abstain"
    ca, cb = _canonical(str(a)), _canonical(str(b))
    if ca == cb:
        return "agree"
    aa, ab = set(ancestors(ca) or [ca]), set(ancestors(cb) or [cb])
    if ca in ab or cb in aa or (aa & ab):
        return "partial"
    return "disagree"


def agree_reps(a: Any, b: Any) -> str:
    if a is None or b is None:
        return "abstain"
    try:
        ia, ib = int(a), int(b)
    except (TypeError, ValueError):
        return "abstain"
    if abs(ia - ib) <= 1:
        return "agree"
    if max(ia, ib) > 0 and abs(ia - ib) / max(ia, ib) <= 0.15:
        return "agree"
    if abs(ia - ib) >= 3:
        return "disagree"
    return "partial"


def agree_depth(a: Any, b: Any) -> str:
    if a in (None, "unevaluable") or b in (None, "unevaluable"):
        return "abstain"
    if a == b:
        return "agree"
    if {a, b} == {"shallow", "deep"}:
        return "disagree"
    return "partial"


def _tiou(a0, a1, b0, b1) -> float:
    try:
        a0, a1, b0, b1 = int(a0), int(a1), int(b0), int(b1)
    except (TypeError, ValueError):
        return 0.0
    inter = max(0, min(a1, b1) - max(a0, b0) + 1)
    union = max(a1, b1) - min(a0, b0) + 1
    return inter / max(union, 1)


_AGREE = {
    "working_set": agree_working_set,
    "identity": agree_identity,
    "reps": agree_reps,
    "rep_depth": agree_depth,
}


def resolve(estimates: list[Estimate], quantity: str) -> dict:
    """Affirm a value only when ≥2 distinct families agree and none strongly disagree."""
    usable = [e for e in estimates
              if e.quantity == quantity or (not e.quantity and True)]
    # Prefer estimates already tagged with quantity; else assume caller filtered.
    if not any(e.quantity == quantity for e in estimates):
        usable = list(estimates)
    else:
        usable = [e for e in estimates if e.quantity == quantity]

    ok = [e for e in usable if e.status == "ok" and e.value is not None]
    if not ok:
        return {"status": "abstain", "value": None, "reason": "no_ok_channels",
                "votes": []}

    # Family discount: one vote per family (highest confidence).
    by_family: dict[str, Estimate] = {}
    for e in sorted(ok, key=lambda x: x.confidence, reverse=True):
        by_family.setdefault(e.family or "?", e)
    votes = list(by_family.values())
    agree_fn = _AGREE.get(quantity, agree_identity)

    # Find a value supported by ≥2 families.
    for i, a in enumerate(votes):
        supporters = [a]
        for b in votes[i + 1:]:
            if agree_fn(a.value, b.value) in ("agree", "partial"):
                supporters.append(b)
        families = {s.family for s in supporters}
        if len(families) >= 2:
            # Check strong disagreement from other high-confidence votes.
            conflict = False
            for other in votes:
                if other in supporters:
                    continue
                if other.confidence >= 0.7 and agree_fn(a.value, other.value) == "disagree":
                    conflict = True
                    break
            if conflict:
                continue
            # Prefer the canonical parent on partial identity agreement.
            value = a.value
            if quantity == "identity":
                cans = [_canonical(str(s.value)) for s in supporters]
                if len(set(cans)) > 1:
                    # hierarchical backoff: shared ancestor if any
                    sets = [set(ancestors(c) or [c]) for c in cans]
                    shared = set.intersection(*sets) if sets else set()
                    if shared:
                        # pick the most specific shared (longest path ≈ last)
                        value = sorted(shared, key=lambda x: len(ancestors(x) or [x]))[-1]
            return {
                "status": "ok",
                "value": value,
                "confidence": float(sum(s.confidence for s in supporters) / len(supporters)),
                "votes": [{"channel": s.channel or s.family, "value": s.value,
                            "family": s.family, "confidence": s.confidence}
                           for s in supporters],
                "nFamilies": len(families),
            }

    # Single-family: abstain rather than overclaim.
    if len(votes) == 1:
        return {
            "status": "abstain",
            "value": votes[0].value,
            "reason": "single_family",
            "confidence": votes[0].confidence,
            "votes": [{"channel": votes[0].channel, "value": votes[0].value,
                        "family": votes[0].family}],
        }
    return {
        "status": "abstain",
        "value": None,
        "reason": "no_cross_family_agreement",
        "votes": [{"channel": v.channel, "value": v.value, "family": v.family}
                   for v in votes],
    }


def pairwise_matrix(estimates: list[Estimate], quantity: str) -> dict:
    tagged = [e for e in estimates if (e.quantity == quantity or not e.quantity)
              and e.status == "ok"]
    agree_fn = _AGREE.get(quantity, agree_identity)
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for i, a in enumerate(tagged):
        for b in tagged[i + 1:]:
            name_a = a.channel or f"{a.family}:{i}"
            name_b = b.channel or f"{b.family}:{i}+"
            rel = agree_fn(a.value, b.value)
            out[name_a][name_b] = rel
            out[name_b][name_a] = rel
    return dict(out)
