"""A baseline quality proxy for one rep.

This is the number the app puts on a rep. It needs saying plainly what it is
and what it is not.

It IS: a bounded 0-100 combination of three things that are measurable from the
clip and have a direction people already agree on - you covered more of the
range, you lowered under control rather than dropping, you moved without
stalling. Every component is shown separately with its own number, so the total
can always be taken apart.

It is NOT a technique grade, and it is not the deviation score. It has no null
distribution behind it, so it cannot tell you whether a change between two reps
exceeds your own rep-to-rep variation - that is what `barra progress` is for.
The app must never present it as a verdict, and the wording it ships with says
"baseline proxy" for that reason.

Why these three components and not others
-----------------------------------------
Only quantities that survive a change of camera angle are allowed in. For a bar
movement that is a friendlier test than it sounds: the movement is vertical, and
rotating a camera about the vertical axis does not foreshorten vertical
distances. Height above the bar and every duration therefore hold up across the
azimuth changes that wreck the sagittal-plane work in docs/FINDINGS.md.

Horizontal quantities do not hold up. Swing and left/right symmetry are
genuinely useful and genuinely viewpoint-dependent, so they are measured and
returned, but deliberately kept OUT of the score: folding them in would make the
number mean something different depending on where the athlete stood their
phone, which is the exact failure this project exists to avoid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Component weights. Fixed here, before any clip is scored, so the number cannot
# be tuned after the fact to make a session look better.
WEIGHTS = {"range": 0.40, "control": 0.25, "smoothness": 0.35}

# A descent at least this fraction of the ascent's duration counts as controlled.
CONTROLLED_TEMPO = 0.70
# Progress below this fraction of the rep's mean ascent rate counts as a stall.
STALL_RATE = 0.20


@dataclass
class Quality:
    score: int | None                  # 0-100, or None when not measurable
    components: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    note: str = ""

    @property
    def measurable(self) -> bool:
        return self.score is not None


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0)) if np.isfinite(x) else 0.0


def range_component(values: dict, arm: float) -> tuple[float, str]:
    """Did the rep use the range the athlete's own arms make available?

    Scored against arm reach measured in the same clip, so the reference is the
    athlete rather than a population norm, and numerator and denominator share a
    divisor. Hang depth and lockout height count equally: half a rep from the
    top and half from the bottom are the same amount of missing rep.
    """
    from .metrics import usable_reference

    if not usable_reference(arm):
        return float("nan"), (
            "the torso-length ruler is not usable on this clip "
            f"(arm reads {arm:.2f} torso), so range cannot be scored"
            if np.isfinite(arm) else "arm reach could not be measured"
        )
    hang = _clip01(values.get("start_depth", float("nan")) / arm)
    lockout = _clip01(values.get("peak_height", float("nan")) / arm)
    return 0.5 * (hang + lockout), (
        f"hang {hang:.0%} of full, lockout {lockout:.0%} of full"
    )


def control_component(values: dict) -> tuple[float, str]:
    """Was the descent lowered or dropped?

    One-sided on purpose. Dropping off the bar scores badly; taking longer than
    the ascent does not score better than taking a similar time, because a very
    slow descent is a choice rather than a fault and this proxy has no business
    ranking choices.
    """
    tempo = values.get("tempo_ratio", float("nan"))
    if not np.isfinite(tempo):
        return float("nan"), "no descent measured"
    return _clip01(tempo / CONTROLLED_TEMPO), f"descent {tempo:.2f}x the ascent"


def smoothness_component(signal: np.ndarray, start: int, turn: int) -> tuple[float, str]:
    """How much of the ascent was spent not going anywhere.

    A rep that grinds to a halt halfway and recovers has a visibly different
    trace from one that rises in a single arc, and the difference is in the
    ascent's rate, not its total time - so a strong slow rep is not punished for
    being slow.
    """
    seg = np.asarray(signal[start:turn + 1], dtype=float)
    if seg.size < 6:
        return float("nan"), "ascent too short to assess"
    step = np.diff(seg)
    total = seg[-1] - seg[0]
    if total <= 1e-9:
        return 0.0, "the ascent made no net progress"
    mean_rate = total / step.size
    stalled = float(np.mean(step < STALL_RATE * mean_rate))
    return _clip01(1.0 - stalled), (
        "no stall in the ascent" if stalled < 0.05
        else f"{stalled:.0%} of the ascent made no progress"
    )


def score_rep(values: dict, arm: float, signal: np.ndarray | None = None,
              start: int = 0, turn: int = 0, plausible: bool = True,
              rep_quality: float = 1.0, min_rep_quality: float = 0.55,
              trace=None, label: str = "") -> Quality:
    """Combine the components into the number the app shows.

    Returns `score=None` rather than a low score when the rep could not be
    measured. A pose failure is not bad technique, and showing it as a low mark
    would be the single most misleading thing this app could do.
    """
    from .trace import NullTrace
    tr = trace or NullTrace()
    tr.stage("quality")
    context = {}
    if not plausible:
        tr.reject(label or "rep", "not scored: the pose estimate is not physically possible")
        return Quality(None, note="This rep could not be measured - the pose "
                                  "estimate is not physically possible.")
    if rep_quality < min_rep_quality:
        tr.reject(label or "rep", "not scored: too little of the rep was tracked",
                  rep_quality=rep_quality, min_rep_quality=min_rep_quality)
        return Quality(None, note="Too little of this rep was tracked well "
                                  "enough to score.")

    comps: dict[str, dict] = {}
    r, r_why = range_component(values, arm)
    c, c_why = control_component(values)
    s, s_why = (smoothness_component(signal, start, turn)
                if signal is not None else (float("nan"), "no trace available"))

    for name, value, why in (("range", r, r_why), ("control", c, c_why),
                             ("smoothness", s, s_why)):
        comps[name] = {"value": None if not np.isfinite(value) else round(float(value), 3),
                       "weight": WEIGHTS[name], "why": why}

    usable = {k: v for k, v in comps.items() if v["value"] is not None}
    if not usable:
        tr.reject(label or "rep", "not scored: no component could be measured")
        return Quality(None, comps, note="None of the components could be measured.")

    weight = sum(v["weight"] for v in usable.values())
    total = sum(v["value"] * v["weight"] for v in usable.values()) / weight
    for name, c in comps.items():
        tr.step(f"component {name}", value=c["value"], weight=c["weight"], why=c["why"])
    if weight < 0.999:
        context["partial"] = (
            "Scored on "
            + ", ".join(sorted(usable))
            + f" only ({weight:.0%} of the usual weight)."
        )

    # Deliberately excluded from the score, reported beside it.
    for name, key, why in (
        ("swing", "swing", "body travel relative to the bar"),
        ("symmetry", "shoulder_asymmetry", "left/right shoulder difference"),
    ):
        v = values.get(key, float("nan"))
        if np.isfinite(v):
            context[name] = {"value": round(float(v), 3), "unit": "torso",
                             "why": why + " - needs a consistent camera side, "
                                          "so it is not part of the score"}

    score = int(round(100 * total))
    tr.decision(f"{label or 'rep'} scored {score}",
                "weighted mean of the components that could be measured",
                score=score, effective_weight=weight,
                components={k: v["value"] for k, v in comps.items()})
    return Quality(score, comps, context)


def band(score: int | None) -> str:
    """Coarse label for the UI. Wide bands on purpose: this proxy does not have
    the resolution to justify finer ones, and a number to the point is a claim
    about precision that is not there."""
    if score is None:
        return "unmeasured"
    if score >= 80:
        return "strong"
    if score >= 60:
        return "solid"
    if score >= 40:
        return "shaky"
    return "broken down"
