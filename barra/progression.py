"""Am I ready for the next progression?

This is the decision calisthenics actually turns on, it is made constantly, and
it is currently made by feel. Every app in the market either ignores it or asks
the athlete to self-report the answer it then acts on. See
[docs/MARKET.md](../docs/MARKET.md).

Two things are kept strictly apart here, and the separation is the whole point:

  * **Whether a rep counts is measured.** A rep is verified when it was
    segmented out of the footage, survived the plausibility checks, and got a
    score. Nothing else counts. That judgement comes from the measurement core
    and carries a trace id that can be replayed.

  * **How many verified reps earn the next step is a convention.** The numbers
    in LADDER below are a published standard, not a discovery. They are close
    to the rule the sport already uses - roughly three sets of ten controlled
    reps before moving on - and they are written here in the open so they can be
    argued with and changed. Presenting them as though they fell out of the data
    would be exactly the dishonesty this project exists to avoid.

So the claim the app is entitled to make is narrow and defensible: *you have N
verified reps against a standard of M, and here is the trace for every one of
them.* Not "you are ready", on our authority. The standard is stated; the
evidence is measured; the athlete can see both.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Quality bands, matching the score the rest of the pipeline produces.
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
SOLID = 47
STRONG = 73


@dataclass(frozen=True)
class Step:
    """One rung: what you are working towards, and what earns it.

    `target_measurable` says whether barra can verify the movement you are
    progressing TO. Where it cannot, the app says so rather than implying it
    will keep refereeing after the step - a ladder that quietly stops working
    is worse than one that says where it ends.
    """
    towards: str
    towards_label: str
    reps: int
    quality: int
    days: int
    target_measurable: bool = True
    note: str = ""


# The published standard. Deliberately conservative: the cost of holding
# someone back a session is a session, and the cost of waving them onto a
# muscle-up they cannot hold is a shoulder.
LADDER: dict[str, Step] = {
    "push_up": Step(
        "dip", "Dip", reps=15, quality=SOLID, days=2,
        note="Dips load the same push pattern through a longer range.",
    ),
    "dip": Step(
        "muscle_up", "Muscle-up", reps=10, quality=SOLID, days=2,
        note="The dip is the second half of a muscle-up. The transition is the "
             "other half - a pull-up standard applies too.",
    ),
    "pull_up": Step(
        "muscle_up", "Muscle-up", reps=8, quality=SOLID, days=2,
        note="The muscle-up transition needs the pull to finish high and under "
             "control, which is what the quality bar is for.",
    ),
    "muscle_up": Step(
        "weighted_muscle_up", "Weighted or strict muscle-up",
        reps=5, quality=STRONG, days=2, target_measurable=False,
        note="Barra cannot verify added load from video, so it stops refereeing "
             "here and this becomes a training decision rather than a measured one.",
    ),
    "knee_raise": Step(
        "toes_to_bar", "Toes to bar", reps=12, quality=SOLID, days=2,
        target_measurable=False,
        note="Toes to bar is not in the measured vocabulary yet, so barra can "
             "confirm you have earned the attempt but not score the attempt.",
    ),
    "squat": Step(
        "pistol_squat", "Pistol squat", reps=20, quality=SOLID, days=2,
        target_measurable=False,
        note="A pistol is single-leg, and barra measures the hips as one point, "
             "so it cannot tell the two apart.",
    ),
}


@dataclass
class Day:
    """One training day's worth of VERIFIED reps for one movement."""
    date: str
    reps: int
    quality: int | None


@dataclass
class Verdict:
    movement: str
    step: Step | None
    ready: bool
    qualifying_days: list[str] = field(default_factory=list)
    best_reps: int = 0
    best_quality: int | None = None
    standard: str = ""
    evidence: str = ""
    missing: str = ""

    @property
    def headline(self) -> str:
        if self.step is None:
            return "No progression tracked for this movement"
        if self.ready:
            return f"Ready to work {self.step.towards_label}"
        return f"Working towards {self.step.towards_label}"

    def as_dict(self) -> dict:
        return {
            "movement": self.movement,
            "towards": self.step.towards if self.step else None,
            "towardsLabel": self.step.towards_label if self.step else None,
            "ready": self.ready,
            "headline": self.headline,
            "standard": self.standard,
            "evidence": self.evidence,
            "missing": self.missing,
            "qualifyingDays": self.qualifying_days,
            "bestReps": self.best_reps,
            "bestQuality": self.best_quality,
            "targetMeasurable": self.step.target_measurable if self.step else False,
            "note": self.step.note if self.step else "",
        }


def verified_reps(reps: list[dict]) -> list[dict]:
    """The reps that count towards a progression.

    A rep counts when it was found in the footage, survived the plausibility
    checks, was scored, and was scored on ALL of its components. A rep the
    segmenter proposed and the anchor test then rejected is not a rep the
    athlete did badly - it is a rep barra did not measure, and the two must not
    be added together.

    `complete` is the strict part and it is deliberate. A standard phrased as
    "15 verified reps" is a claim about full repetitions, so counting reps whose
    range was never measured would be counting evidence that does not exist: on
    a head-on push-up clip the torso ruler fails for the whole set, and those 19
    reps say nothing about how deep they were. Older payloads have no
    `complete` field, so their scored reps are accepted rather than silently
    dropped from a history recorded before the distinction existed.
    """
    return [r for r in reps
            if r.get("score") is not None and r.get("plausible", True)
            and r.get("complete", True)]


def _band(q: int | None) -> str:
    if q is None:
        return "unscored"
    return "strong" if q >= STRONG else "solid" if q >= SOLID else "below the bar"


def assess(movement: str, days: list[Day]) -> Verdict:
    """Referee one movement against its published standard."""
    step = LADDER.get(movement)
    v = Verdict(movement=movement, step=step, ready=False)
    if step is None:
        v.evidence = "Barra has no progression ladder for this movement yet."
        return v

    v.standard = (
        f"{step.reps} verified reps in one session at {step.quality} or better, "
        f"on {step.days} separate days."
    )

    qualifying = [d for d in days
                  if d.reps >= step.reps and (d.quality or 0) >= step.quality]
    v.qualifying_days = [d.date for d in sorted(qualifying, key=lambda d: d.date)]

    best = max(days, key=lambda d: (d.reps, d.quality or 0), default=None)
    if best is not None:
        v.best_reps = best.reps
        v.best_quality = best.quality

    if not days:
        v.evidence = "No verified reps of this movement yet."
        v.missing = f"Film a set. {step.reps} verified reps is the bar."
        return v

    v.evidence = (
        f"Best session: {v.best_reps} verified rep"
        f"{'' if v.best_reps == 1 else 's'} at {v.best_quality} "
        f"({_band(v.best_quality)}) on {best.date}. "
        f"{len(v.qualifying_days)} of {step.days} days clear the standard."
    )

    if len(v.qualifying_days) >= step.days:
        v.ready = True
        v.missing = ""
        return v

    # What is actually short - reps, quality, or repetition of the day.
    gaps: list[str] = []
    if v.best_reps < step.reps:
        gaps.append(f"{step.reps - v.best_reps} more verified rep"
                    f"{'' if step.reps - v.best_reps == 1 else 's'} in one session")
    elif (v.best_quality or 0) < step.quality:
        gaps.append(f"the same volume at {step.quality} or better "
                    f"(best so far {v.best_quality})")
    short_days = step.days - len(v.qualifying_days)
    if v.qualifying_days:
        gaps.append(f"{short_days} more qualifying day"
                    f"{'' if short_days == 1 else 's'}")
    v.missing = "Still needed: " + ", and ".join(gaps) + "."
    return v


def from_sessions(movement: str, sessions: list[dict]) -> Verdict:
    """Convenience wrapper over the payload shape the server already produces.

    Each session is {"date": ..., "reps": [rep, ...]}; only verified reps are
    counted and the day's quality is their median, not their mean - one
    exceptional rep should not carry a session over the line.
    """
    days: list[Day] = []
    for s in sessions:
        good = verified_reps(s.get("reps") or [])
        if not good:
            continue
        scores = sorted(int(r["score"]) for r in good)
        median = scores[len(scores) // 2] if len(scores) % 2 else \
            (scores[len(scores) // 2 - 1] + scores[len(scores) // 2]) // 2
        days.append(Day(date=str(s.get("date") or ""), reps=len(good), quality=median))
    return assess(movement, days)
