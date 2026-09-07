"""Which faults were measured, read out of the payload the server ships.

The payload states them. This module used to RE-DERIVE them: regular
expressions over the human-readable why-strings ("lockout 76% of full"),
compared against its own copies of the thresholds, exactly as the phone did.
Two things were wrong with that. A copy edit to a sentence - "lockout 76% of
full reach", say - silently switched fault detection off in the harness and on
every device, with no test able to see it. And the numbers behind the
comparison lived in three files that nothing kept equal.

So `faults` is now a structured array on each rep row: the fault's name, the
primitive it was measured on, that measurement's value, the threshold and the
comparison. Reading it is a lookup. The regex path survives only for payloads
written before the field existed, is marked deprecated, and is scheduled for
removal after one release.

What each of the shared bar faults means, and the number that carries it:

  momentum   body travel relative to the bar exceeded SWING_TORSO
             torso-lengths. A strict rep barely leaves the plumb line; a kip
             does not pretend otherwise.
  lockout    the top of the rep reached less than LOCKOUT_MIN of the athlete's
             own arm reach.
  dead hang  the bottom of the rep started from less than HANG_MIN of that
             same reach. Half reps are short from one end or the other; this
             is the bottom half of that story.
  control    the descent fell rather than lowered (tempo_ratio under
             CONTROLLED_TEMPO).
  stall      the ascent stopped and snatched through.

The per-track faults each movement adds to those are defined in
barra/faults_taxonomy.py, and every name any track can produce is in
FAULT_NAMES.

A fault absent is not scored as anything - these are one-sided observations,
like the control penalty itself. The harness decides what that is worth. A
fault that could not be MEASURED is a third thing again, and lives in the rep
row's `unmeasured` and `viewBlocked` lists rather than being confused with
either.
"""
from __future__ import annotations

import math
import re

from .config import THRESHOLDS
from .faults_taxonomy import all_fault_names

# Names kept for readability at the call sites; the values live in config.py,
# which is the file `validate` fingerprints. Two modules holding their own copy
# of 0.85 is how a threshold moves on one side of the wire only.
SWING_TORSO = THRESHOLDS.swing_torso
LOCKOUT_MIN = THRESHOLDS.lockout_min
HANG_MIN = THRESHOLDS.hang_min

_LOCKOUT_RE = re.compile(r"lockout (\d+)% of full")
_HANG_RE = re.compile(r"hang (\d+)% of full")
_STALL_RE = re.compile(r"% of the ascent made no progress")


def rep_faults(rep: dict) -> list[str]:
    """The faults one rep row (as shipped in payload['reps']) was measured to have."""
    faults = rep.get("faults")
    if isinstance(faults, list) and faults:
        return [f.get("name", "") for f in faults if isinstance(f, dict)]
    failures = rep.get("failures")
    if isinstance(failures, list):
        # The server has classified this rep; an empty list means it measured
        # clean, which is an answer, not a missing one.
        return list(failures)
    return _legacy_rep_faults(rep)


def rep_fault_evidence(rep: dict) -> list[dict]:
    """The fired faults with the numbers behind them, empty for old payloads."""
    faults = rep.get("faults")
    return [f for f in faults if isinstance(f, dict)] if isinstance(faults, list) else []


def _legacy_rep_faults(rep: dict) -> list[str]:
    """DEPRECATED. Payloads written before `faults` and `failures` existed.

    Reads the faults back out of prose the scoring layer wrote for a human,
    which is why it is being removed: the parse is coupled to wording nobody
    thinks of as an interface. Remove one release after every stored payload
    carries the structured field.
    """
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


def clip_unmeasured(payload: dict) -> dict[str, int]:
    """How many reps could not measure each primitive, blocked views included.

    The counterpart to clip_fault_counts: a set where "knee valgus" never fired
    because the camera was never in front of the athlete should not read the
    same as one where the knees were tracked and stayed out.
    """
    counts: dict[str, int] = {}
    for rep in payload.get("reps") or []:
        for key in list(rep.get("unmeasured") or []) + list(rep.get("viewBlocked") or []):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _value(rep: dict, section: str, name: str) -> float | None:
    for entry in rep.get(section) or []:
        if entry.get("name") == name:
            v = entry.get("value")
            if isinstance(v, (int, float)) and math.isfinite(v):
                return float(v)
    return None


# Every fault name any track can produce. The harness tallies against this, so
# a fault added to the taxonomy shows up as INCONCLUSIVE until clips are
# labelled for it, rather than not showing up at all.
FAULT_NAMES = all_fault_names()
