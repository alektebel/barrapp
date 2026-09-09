"""Phase boundaries for one repetition, defined once.

Every consumer that needs to know "which part of the rep is the ascent" -
metrics, evidence, the quality proxy, the artifact cutter, the trace - used to
work it out for itself from the movement's direction and the (start, turn,
end) triple. Four copies of the same conditional is how the push-up's
concentric and eccentric came out swapped in one place and correct in the
other three. They are computed here, from the movement profile, and read
everywhere else.

Vocabulary (the assessment contract in docs/TECHNIQUE-PIPELINE-IMPLEMENTATION-
PLAN.md, section 3):

    rep         the whole repetition, start..end. Whole-rep summaries keep
                whole-rep scope; nothing here invents an onset for them.
    setup       a short window around the rep's rest position at its start.
                For an ascending movement (pull-up) this is the hang; for a
                descending one (push-up) it is the lockout before lowering.
    lowering    the eccentric half: turn..end when the movement ascends first,
                start..turn when it descends first.
    lifting     the concentric half, the other way round.
    support     a short window around the top of the rep: the turnaround of an
                ascending movement, the start of a descending one.
    turnaround  a short window around the turn of a DESCENDING movement (the
                bottom of a dip or squat). An ascending movement's turn is its
                `support`.
    transition  only for movements that have one (the muscle-up's pass through
                the bar plane). Its extent comes from the signal, not from the
                triple, so it is defined in metrics and merely named here.
    hold        an isometric attempt, onset..exit.

Endpoint windows are `ENDPOINT_WINDOW_S` either side of the frame, clipped to
the rep. The same width the elbow-angle primitives always used.
"""
from __future__ import annotations

from dataclasses import dataclass

ENDPOINT_WINDOW_S = 0.10

# Movements whose lifting phase passes through the plane of the hands. The
# `transition_s` metric is defined for these and for nothing else - it used to
# be computed on every wrist-origin movement, and a push-up's shoulders
# crossing "the bar plane" is a measurement of nothing.
HAS_TRANSITION = frozenset({"muscle_up"})


@dataclass(frozen=True)
class Phase:
    name: str
    start: int          # inclusive frame
    end: int            # inclusive frame

    @property
    def frames(self) -> int:
        return max(0, self.end - self.start + 1)

    def seconds(self, fps: float) -> list[float]:
        fps = max(float(fps), 1.0)
        return [round(self.start / fps, 2), round(self.end / fps, 2)]

    def as_slice(self) -> slice:
        return slice(self.start, self.end + 1)


def _clip(i: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, i))


def endpoint_window(centre: int, fps: float, lo: int, hi: int,
                    half_s: float = ENDPOINT_WINDOW_S) -> tuple[int, int]:
    half = max(1, int(round(half_s * max(float(fps), 1.0))))
    return _clip(centre - half, lo, hi), _clip(centre + half, lo, hi)


def rep_phases(movement, start: int, turn: int, end: int,
               fps: float) -> dict[str, Phase]:
    """The phases of one rep, keyed by name. Always includes `rep`, `setup`,
    `lowering`, `lifting` and `support`; `turnaround` for descending
    movements; `transition` is named only where the movement has one, with
    the lifting phase as its outer bound (metrics narrows it)."""
    start, turn, end = int(start), int(turn), int(end)
    descending = getattr(movement, "direction", "ascending") == "descending"
    phases = {"rep": Phase("rep", start, end)}
    a, b = endpoint_window(start, fps, start, end)
    phases["setup"] = Phase("setup", a, b)
    if descending:
        phases["lowering"] = Phase("lowering", start, turn)
        phases["lifting"] = Phase("lifting", turn, end)
        phases["support"] = Phase("support", a, b)
        ta, tb = endpoint_window(turn, fps, start, end)
        phases["turnaround"] = Phase("turnaround", ta, tb)
    else:
        phases["lifting"] = Phase("lifting", start, turn)
        phases["lowering"] = Phase("lowering", turn, end)
        ta, tb = endpoint_window(turn, fps, start, end)
        phases["support"] = Phase("support", ta, tb)
    if getattr(movement, "name", "") in HAS_TRANSITION:
        lift = phases["lifting"]
        phases["transition"] = Phase("transition", lift.start, lift.end)
    return phases


def transition_band(shoulder_above, phases: dict[str, Phase],
                    band: float) -> Phase | None:
    """The transition as the SIGNAL defines it: the first to the last frame of
    the lifting phase in which the shoulders sit within `band` torso-lengths
    of the plane of the hands. None when the movement has no transition or
    the shoulders never entered the band (a lift that stayed below the bar).

    `rep_phases` names the transition with the whole lift as its outer bound;
    this narrows it, and is what the payload, the trace and the vision
    request should report - "transition 2.12-5.92 s" on a 3.8 s pull is the
    search window, not the transition."""
    outer = phases.get("transition")
    if outer is None or shoulder_above is None:
        return None
    import numpy as np
    sig = np.asarray(shoulder_above, dtype=float)
    lo, hi = outer.start, min(outer.end, len(sig) - 1)
    if hi < lo:
        return None
    idx = np.flatnonzero(np.abs(sig[lo:hi + 1]) <= band)
    if idx.size == 0:
        return None
    return Phase("transition", lo + int(idx[0]), lo + int(idx[-1]))


def ascent(movement, start: int, turn: int, end: int) -> tuple[int, int]:
    """(first, last) frame of the lifting phase - the ascent the smoothness
    and stall measures read. One place, so the quality proxy and the fault
    layer cannot read different halves of the same rep."""
    if getattr(movement, "direction", "ascending") == "descending":
        return int(turn), int(end)
    return int(start), int(turn)


def ascent_signal(signal, movement):
    """The tracked signal oriented so that the lifting phase RISES.

    `tracking_signal` orients every movement so the turnaround is a maximum,
    which for a descending movement means the lifting phase is the signal
    coming back DOWN. The stall and smoothness measures want progress upward,
    so they read the negated signal on those movements."""
    if signal is None:
        return None
    import numpy as np
    sig = np.asarray(signal, dtype=float)
    return -sig if getattr(movement, "direction", "ascending") == "descending" else sig


def hold_phases(start: int, end: int, fps: float) -> dict[str, Phase]:
    """A hold's onset, sustained middle and exit. The onset and exit are the
    endpoint window; the hold is what lies between them."""
    a1, b1 = endpoint_window(start, fps, start, end)
    a2, b2 = endpoint_window(end, fps, start, end)
    mid_a, mid_b = min(b1 + 1, end), max(a2 - 1, start)
    if mid_b < mid_a:
        mid_a, mid_b = start, end
    return {
        "hold": Phase("hold", start, end),
        "onset": Phase("onset", a1, b1),
        "sustained": Phase("sustained", mid_a, mid_b),
        "exit": Phase("exit", a2, b2),
    }


def phases_as_dict(phases: dict[str, Phase], fps: float) -> dict[str, list[float]]:
    return {name: p.seconds(fps) for name, p in phases.items()}
