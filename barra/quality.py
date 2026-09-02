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
#
# Control used to sit here at 0.25 and it does not any more, because it is a
# FAULT DETECTOR rather than a graded measure - see control_penalty below. A
# detector inside a weighted mean is a constant: it reads 1.0 for every rep
# without the fault, which was 86% of them, and 0.25 x 1.0 became a floor under
# every score. Measured on the sample clips that floor was the whole story of
# why a "0-100" score only ever used 76-100, and why an unmeasurable range
# pushed the floor up to 0.42 and the observed span up to 88-100.
WEIGHTS = {"range": 0.40, "smoothness": 0.35}

# A descent at least this fraction of the ascent's duration counts as controlled.
CONTROLLED_TEMPO = 0.70
# What dropping the descent entirely costs, as a fraction of the score. Set to
# the weight control used to carry, so the fault costs exactly what it did
# before - the change removes the constant, not the penalty.
CONTROL_PENALTY = 0.25
# Progress below this fraction of the rep's mean ascent rate counts as a stall.
STALL_RATE = 0.20

# Band boundaries.
#
# Boundaries converted, not re-tuned, when control left the weighted mean.
#
# Control sat at its ceiling for 86% of reps, so the old score was
# 0.25 + 0.75 x graded and no rep could score below 25. Removing that floor
# changes what a given number means, so the boundaries were mapped back through
# it to keep the SAME reps on the same side of each line:
#
#     old 80  ->  (80 - 25) / 75  ->  73
#     old 60  ->  (60 - 25) / 75  ->  47
#     old 40  ->  (40 - 25) / 75  ->  20
#
# This is a restatement of an existing convention in a changed unit, not a
# recalibration to make scores look better - a muscle-up that read 78 (solid)
# now reads 56, and is still solid. The boundaries remain conventions and are
# still unvalidated: see docs/QUALITY.md.
STRONG, SOLID, SHAKY = 73, 47, 20


@dataclass
class Quality:
    score: int | None                  # 0-100, or None when not measurable
    components: dict = field(default_factory=dict)
    penalties: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    note: str = ""

    @property
    def measurable(self) -> bool:
        return self.score is not None

    @property
    def complete(self) -> bool:
        """Every graded component was measured.

        A rep scored on part of its weight is a weaker piece of evidence than
        one scored on all of it, and the difference has to be carried rather
        than averaged away: on a head-on push-up clip the torso ruler fails, so
        range is unmeasurable for the entire set and the score says nothing
        about how deep those reps were.
        """
        return (self.score is not None
                and all(self.components.get(k, {}).get("value") is not None
                        for k in WEIGHTS))


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


def control_penalty(values: dict) -> tuple[float, str]:
    """Was the descent lowered, or dropped? Returns 0.0 when there is no fault.

    One-sided on purpose, and that is exactly why it is a penalty rather than a
    component. Dropping off the bar is a fault; taking LONGER than the ascent is
    a choice, and this proxy has no business ranking choices - so every rep that
    is not dropped scores the same. Inside a weighted mean that sameness is a
    constant, and a constant in an average does nothing but compress the range
    of the total. Outside it, the same judgement costs nothing when the fault is
    absent and the full CONTROL_PENALTY when the descent is a free fall.
    """
    tempo = values.get("tempo_ratio", float("nan"))
    if not np.isfinite(tempo):
        return 0.0, "no descent measured, so no control penalty applied"
    shortfall = _clip01(1.0 - tempo / CONTROLLED_TEMPO)
    if shortfall <= 0.0:
        return 0.0, f"descent {tempo:.2f}x the ascent - controlled"
    return CONTROL_PENALTY * shortfall, (
        f"descent {tempo:.2f}x the ascent, under the {CONTROLLED_TEMPO:.2f}x "
        "that counts as controlled"
    )


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

    # How evenly the ascent was paced, not how many frames sat below a
    # threshold. Counting frames makes the frame count the denominator: a
    # 0.9-second push-up at 25fps has an eleven-frame ascent, so the component
    # can only ever take eleven values, and on a real set it took five across
    # nineteen reps. Grading each frame's shortfall does not fix it either,
    # because a frame is either well clear of the floor or stopped, and the
    # graded band in between is narrow - that version still gave seven values
    # across twenty-five different stall depths.
    #
    # A rep that rises at a steady rate has mean rate equal to its fast rate. A
    # rep that grinds to a halt and then snatches through has a mean far below
    # it. That ratio is continuous by construction and needs no threshold.
    # p90 rather than max, so one jittery frame cannot define "fast".
    fast = float(np.percentile(step, 90))
    if fast <= 1e-9:
        return 0.0, "the ascent never moved at a usable rate"
    evenness = _clip01(mean_rate / fast)

    # Reported rather than scored: a plain stalled-frame count is what a person
    # reads, even though scoring on it is what quantised the component.
    stalled = float(np.mean(step < STALL_RATE * mean_rate))
    return evenness, (
        "paced evenly through the ascent" if evenness >= 0.95
        else (f"{stalled:.0%} of the ascent made no progress" if stalled >= 0.05
              else f"the ascent ran at {evenness:.0%} of its own best rate")
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
    s, s_why = (smoothness_component(signal, start, turn)
                if signal is not None else (float("nan"), "no trace available"))
    penalty, p_why = control_penalty(values)

    for name, value, why in (("range", r, r_why), ("smoothness", s, s_why)):
        comps[name] = {"value": None if not np.isfinite(value) else round(float(value), 3),
                       "weight": WEIGHTS[name], "why": why}
    penalties = {"control": {"value": round(float(penalty), 3), "why": p_why}}

    usable = {k: v for k, v in comps.items() if v["value"] is not None}
    if not usable:
        tr.reject(label or "rep", "not scored: no component could be measured")
        return Quality(None, comps, penalties,
                       note="None of the components could be measured.")

    # Range is required, and this is the one place the score refuses on
    # something other than a tracking failure. Smoothness on its own says the
    # rep was continuous; it says nothing about whether the movement happened.
    # Scored on smoothness alone a shallow, twitchy half-rep reads 100, which is
    # exactly what a head-on push-up clip produced - 19 reps at 94 on a clip
    # where depth was never measured at all. A quality score that cannot see
    # how much of the movement occurred is not a quality score.
    if comps["range"]["value"] is None:
        tr.reject(label or "rep", "not scored: range could not be measured",
                  reason=comps["range"]["why"])
        return Quality(None, comps, penalties,
                       note="Range of motion could not be measured on this clip, "
                            "and a quality score without it would say nothing "
                            "about how much of the movement happened. Film from "
                            "the side so the torso is not foreshortened.")

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

    # The fault is applied AFTER the mean, so a rep without it pays nothing.
    total *= (1.0 - penalty)
    score = int(round(100 * total))
    tr.decision(f"{label or 'rep'} scored {score}",
                "weighted mean of the measured components, less any fault penalty",
                score=score, effective_weight=weight, control_penalty=penalty,
                components={k: v["value"] for k, v in comps.items()})
    return Quality(score, comps, penalties, context)


def band(score: int | None) -> str:
    """Coarse label for the UI. Wide bands on purpose: this proxy does not have
    the resolution to justify finer ones, and a number to the point is a claim
    about precision that is not there."""
    if score is None:
        return "unmeasured"
    if score >= STRONG:
        return "strong"
    if score >= SOLID:
        return "solid"
    if score >= SHAKY:
        return "shaky"
    return "broken down"
