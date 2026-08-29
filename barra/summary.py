"""What happened in this session, in sentences a person would actually read.

The report this replaces was a metric dump: every rep listed with its
robustness class in capitals, `r1 - Transition through the bar 0.33 s
(INVARIANT) - Concentric duration 3.50 s (INVARIANT)`. Every number in it was
correct and none of it answered the question the athlete opened the app to ask,
which is "how did that go?".

So the numbers stay - they are on the rep cards, where someone looking for them
will find them - and this module says what they amount to. The rules it works
under are the ones the rest of the project works under:

  * Never a claim the measurement does not support. No "your transition is
    improving" from one session, no cause attributed to a number.
  * A refusal is a result. A clip that produced nothing gets a description of
    what stopped it and what to do differently, not an apology.
  * Say which part is weakest, because that is the one sentence of a report
    anybody acts on.
"""
from __future__ import annotations

BAND_WORD = {
    "strong": "strong",
    "solid": "solid",
    "shaky": "shaky",
    "broken down": "breaking down",
    "unmeasured": "unmeasured",
}

# Plain names for the score's parts. The component keys are internal; these are
# what the sentence says.
PART = {
    "range": "range of motion",
    "control": "control of the descent",
    # Not "smoothness of the pull": the same component scores a push-up, and a
    # push-up has no pull.
    "smoothness": "smoothness through the rep",
}

# What to film differently, per reason the clip failed. Keyed by a distinctive
# fragment of the blocker text rather than an error code, because the blockers
# are written for humans first and are the same strings shown in the trace.
FILMING_ADVICE = [
    ("out of frame", "Tilt the camera up or step back so your hands stay in shot "
                     "for the whole set - they are the reference everything else "
                     "is measured against."),
    ("fixed bar", "Start filming once you are already on the bar, and stop "
                  "before you walk off. Moving around the rig is measured as "
                  "part of the movement."),
    ("around the rig", "Start filming once you are already on the bar, and stop "
                       "before you walk off. Moving around the rig is measured "
                       "as part of the movement."),
    ("not on anything fixed", "Start filming once you are already on the bar. "
                              "Walking to and from the rig is measured as part "
                              "of the movement."),
    ("hold", "Barra counts repetitions, so a hold has nothing to count. Film a "
             "set of reps instead."),
    ("turnaround", "Get the whole rep in frame, top to bottom. A turnaround that "
                   "leaves the shot cannot be timed."),
    ("interpolated", "More light, or a slower phone. Too many frames were "
                     "guessed rather than seen."),
]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _movement(payload: dict) -> str:
    detected = payload.get("detected") or {}
    label = detected.get("label") or (payload.get("exercise") or "").replace("_", " ")
    return (label or "movement").lower()


def _advice(blockers: list[str]) -> str:
    """Advice for the FIRST blocker before any other.

    A clip usually fails for more than one reason, and the pipeline reports
    them in the order it hit them. Searching all of them at once lets a later,
    incidental blocker win: one clip whose real problem was the athlete walking
    around the rig was told to keep the turnaround in frame, because a
    secondary blocker happened to contain the word.
    """
    ordered = [b.lower() for b in blockers if b] or [""]
    for haystack in (ordered[0], " ".join(ordered)):
        for needle, text in FILMING_ADVICE:
            if needle in haystack:
                return text
    return ("Film one set from a fixed spot, with the whole movement in frame "
            "from start to finish.")


def _spread(reps: list[dict]) -> str:
    """How the set held together. Only said when there are enough reps for the
    comparison to mean anything - two reps have a difference, not a trend."""
    times = []
    for r in reps:
        try:
            times.append(float(r.get("total_s")))
        except (TypeError, ValueError):
            continue
    if len(times) < 3:
        return ""
    first, last = times[0], times[-1]
    slowest = max(times)
    if slowest <= 0:
        return ""
    drift = (last - first) / first if first > 0 else 0.0
    if abs(drift) < 0.15:
        return (f"Rep times held steady across the set "
                f"({min(times):.1f}-{max(times):.1f} s).")
    if drift > 0:
        return (f"Reps slowed through the set, {first:.1f} s at the start to "
                f"{last:.1f} s at the end - {drift:.0%} longer.")
    return (f"Reps sped up through the set, {first:.1f} s to {last:.1f} s.")


def _weakest(reps: list[dict]) -> str:
    """The lowest-scoring part of the movement, averaged over the scored reps,
    quoted with the measurement that produced it."""
    totals: dict[str, list[float]] = {}
    why: dict[str, str] = {}
    for r in reps:
        if r.get("score") is None:
            continue
        for c in r.get("components") or []:
            name = c.get("name")
            if name is None or c.get("value") is None:
                continue
            totals.setdefault(name, []).append(float(c["value"]))
            why.setdefault(name, str(c.get("why") or ""))
    if not totals:
        return ""
    means = {k: sum(v) / len(v) for k, v in totals.items()}
    worst = min(means, key=means.get)
    best = max(means, key=means.get)
    if means[worst] >= 0.95:
        return "Every part of the movement scored near full."
    line = (f"The weakest part was {PART.get(worst, worst)} at "
            f"{means[worst]:.0%}")
    if why.get(worst):
        line += f" ({why[worst]})"
    if best != worst:
        line += f"; {PART.get(best, best)} was the strongest at {means[best]:.0%}"
    return line + "."


def _unmeasured(reps: list[dict]) -> str:
    """Reps that were found but could not be scored, and how many. Silence here
    would let a set of six report a score built from two."""
    missing = [r for r in reps if r.get("score") is None]
    if not missing:
        return ""
    notes = [r.get("scoreNote") for r in missing if r.get("scoreNote")]
    line = (f"{_plural(len(missing), 'rep')} could not be scored and "
            f"{'is' if len(missing) == 1 else 'are'} left out of the number above")
    return line + (f": {notes[0].lower()}." if notes else ".")


def describe(payload: dict) -> tuple[str, str]:
    """(headline, narrative) for one analysed clip."""
    reps = payload.get("reps") or []
    n = int(payload.get("n_reps") or 0)
    move = _movement(payload)
    blockers = [str(b) for b in (payload.get("blockers") or [])]
    score = payload.get("sessionScore")
    band = str(payload.get("sessionBand") or "unmeasured")

    # ---- nothing countable -------------------------------------------------
    if n == 0:
        detected = payload.get("detected") or {}
        if not detected.get("exercise") or detected.get("exercise") == "unknown":
            headline = "No movement barra can measure"
            opening = (f"Barra could not tell what this clip shows. "
                       f"{blockers[0][0].upper() + blockers[0][1:]}."
                       if blockers else
                       "Barra could not tell what this clip shows.")
        else:
            headline = f"{move.capitalize()} - nothing countable"
            candidates = int(payload.get("n_candidates") or 0)
            opening = (
                f"Recognised as a {move}"
                + (f" and {_plural(candidates, 'possible rep')} found, "
                   "but none survived checking. " if candidates else ", but no rep "
                   "could be picked out of it. ")
                + (blockers[0][0].upper() + blockers[0][1:] + "."
                   if blockers else "")
            )
        return headline, " ".join(x for x in [opening, _advice(blockers)] if x)

    # ---- a measured set ----------------------------------------------------
    parts: list[str] = []
    trim = payload.get("trim") or {}
    duration = payload.get("duration_s")
    working = None
    if trim.get("startS") is not None and trim.get("endS") is not None:
        working = float(trim["endS"]) - float(trim["startS"])

    opening = f"{_plural(n, f'{move} rep')}"
    if working:
        opening += f" across a {working:.0f}-second working set"
        if duration and float(duration) - working > 2.0:
            opening += f", trimmed from {float(duration):.0f} seconds of footage"
    parts.append(opening + ".")

    if score is None:
        headline = f"{_plural(n, f'{move} rep')} - not scored"
        parts.append("None of them could be scored, so there is no number for "
                     "this session.")
    elif n < 3:
        headline = f"{_plural(n, f'{move} rep')}, {BAND_WORD.get(band, band)}"
        parts.append(f"Scored {int(score)} out of 100 - {BAND_WORD.get(band, band)}. "
                     "Three reps is the floor before a session median means "
                     "anything, so treat this as a single observation rather "
                     "than a session.")
    else:
        headline = f"{_plural(n, f'{move} rep')}, {BAND_WORD.get(band, band)}"
        parts.append(f"Scored {int(score)} out of 100 - {BAND_WORD.get(band, band)}.")

    for extra in (_weakest(reps), _spread(reps), _unmeasured(reps)):
        if extra:
            parts.append(extra)

    if blockers:
        parts.append("Also noted: " + blockers[0] + ".")

    return headline, " ".join(parts)
