"""Which faults were measured, read out of the payload the server ships.

The phone (Cues.kt) and this module must agree: both read the same fields of
the rep row, with the same thresholds. The thresholds are pinned here because
this is where the fault-validation harness tunes them; change them together
or the app starts saying things the harness never tested.

What each fault means, and the number that carries it:

  momentum   body travel relative to the bar (the `swing` aside) exceeded
             SWING_TORSO torso-lengths. A strict rep barely leaves the plumb
             line; a kip does not pretend otherwise.
  lockout    the top of the rep reached less than LOCKOUT_MIN of the athlete's
             own arm reach (the `range` component's why string).
  dead hang  the bottom of the rep started from less than HANG_MIN of that
             same reach. Half reps are short from one end or the other; this
             is the bottom half of that story.
  control    the control penalty is non-zero: the descent fell rather than
             lowered (tempo_ratio under CONTROLLED_TEMPO).
  stall      the ascent stopped and snatched through: the smoothness why
             reports frames that made no progress.

A fault absent is not scored as anything - these are one-sided observations,
like the control penalty itself. The harness decides what that is worth.
"""
from __future__ import annotations

import math
import re

SWING_TORSO = 0.4
LOCKOUT_MIN = 0.85
HANG_MIN = 0.75

_LOCKOUT_RE = re.compile(r"lockout (\d+)% of full")
_HANG_RE = re.compile(r"hang (\d+)% of full")
_STALL_RE = re.compile(r"% of the ascent made no progress")


def rep_faults(rep: dict) -> list[str]:
    """The faults one rep row (as shipped in payload['reps']) was measured to have."""
    faults: list[str] = []

    swing = _value(rep, "aside", "swing")
    if swing is not None and swing > SWING_TORSO:
        faults.append("momentum")

    for comp in rep.get("components") or []:
        why = comp.get("why") or ""
        if comp.get("name") == "range":
            lockout = _LOCKOUT_RE.search(why)
            hang = _HANG_RE.search(why)
            if lockout and int(lockout.group(1)) < round(LOCKOUT_MIN * 100):
                faults.append("lockout")
            if hang and int(hang.group(1)) < round(HANG_MIN * 100):
                faults.append("dead hang")
        elif comp.get("name") == "smoothness":
            if _STALL_RE.search(why):
                faults.append("stall")

    for pen in rep.get("penalties") or []:
        if pen.get("name") == "control" and (pen.get("value") or 0) > 0:
            faults.append("control")

    return faults


def clip_fault_counts(payload: dict) -> dict[str, int]:
    """How many reps of the clip showed each fault. Empty when none did."""
    counts: dict[str, int] = {}
    for rep in payload.get("reps") or []:
        for f in rep_faults(rep):
            counts[f] = counts.get(f, 0) + 1
    return counts


def _value(rep: dict, section: str, name: str) -> float | None:
    for entry in rep.get(section) or []:
        if entry.get("name") == name:
            v = entry.get("value")
            if isinstance(v, (int, float)) and math.isfinite(v):
                return float(v)
    return None


FAULT_NAMES = ("momentum", "lockout", "dead hang", "control", "stall")
