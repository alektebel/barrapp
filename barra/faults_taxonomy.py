"""Per-track failure classification - the "observed" face of the rule registry.

The old model asked whether a technique was "perfect" - a single judgement, and
a bad one, because a model cannot see a body from one still. This module does
the opposite: it classifies each measured rep or hold into the COMMON failure
types that actually occur, from the geometry that was already measured.

Each failure is a threshold on a measured signal, so it is deterministic and
testable, and it is stated with the number behind it: a fired fault carries the
value, the threshold and the comparison that fired it, which is what the phone
renders and what the trace records.

The rules themselves live in barra/rules.py as data - stable id, phase,
primitive, threshold, what is observed - and this module is the compatibility
face over them: the same `classify_faults` / `classify_failures` /
`TRACK_FAILURES` the server, the harness and the debug tool already call. The
full assessment (observed / not observed / unobservable, per rule) is
`barra.rules.assess`; a Fault here is one `observed` row of that.

Three rules hold everywhere in here, and they are the ones the previous version
broke:

1. A predicate reads an `Evidence` record, never a bare dict, so an absent
   measurement is `None` and cannot satisfy a condition. "bent arms" used to
   default a missing `arms_straight_frac` to 1.0 - perfect - which made the
   fault unfireable on any rep, since nothing on the rep path produced that
   key at all.
2. Bar faults belong to bar movements. `shoulder_above` is measured against the
   movement's ORIGIN, and on a hip-origin track that origin is the hips
   themselves: a squat reported peak_height 1.0 and start_depth -1.0 on every
   rep, so "dead hang" fired unconditionally and "momentum" - the hips'
   distance from the hips - never could. A squat has its own rules now,
   reading an ankle-referenced depth.
3. A PLANAR quantity is not fired from an unknowable viewpoint. Knee valgus is
   a frontal measurement and torso lean a sagittal one; docs/FINDINGS.md
   already showed a 10-degree azimuth change outweighing a deliberate error.
   The evidence layer blocks them, and a blocked fault is reported as
   unmeasured rather than as clean.

Thresholds are named here and defined once in config.py, which `validate`
fingerprints.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import THRESHOLDS
from .evidence import UNKNOWN_VIEW, Evidence, View
from .rules import (OBSERVED, RULES, VARIANT_UNSPECIFIED, Assessment, Rule,
                    assess, rules_for)

# Every threshold below is a name for one field of config.THRESHOLDS. Nothing
# here holds its own number: this module and barra/faults.py used to keep
# separate copies of the same three constants, and the phone a third, so the
# only thing keeping them equal was a comment asking future readers to be
# careful. Now they cannot disagree.

# ---- straightness: 180 = fully extended -------------------------------------
STRAIGHT_ARM = THRESHOLDS.straight_arm
STRAIGHT_LEG = THRESHOLDS.straight_leg

# ---- body line: 0 = vertical, 90 = horizontal -------------------------------
# A lever or planche wants the body horizontal. Anything below this band is a
# range-of-motion failure (the body has not come up to the line).
HORIZONTAL = THRESHOLDS.horizontal
STRICT_HORIZONTAL = THRESHOLDS.strict_horizontal

# ---- hip pike: 180 = fully straight -----------------------------------------
# A piked body flexes the hips. This is the "sagging hips" / broken body line.
PIKE = THRESHOLDS.pike

# ---- shared bar faults ------------------------------------------------------
SWING_TORSO = THRESHOLDS.swing_torso
LOCKOUT_MIN = THRESHOLDS.lockout_min
HANG_MIN = THRESHOLDS.hang_min
CONTROLLED_TEMPO = THRESHOLDS.controlled_tempo
STALL_RATE = THRESHOLDS.stall_rate

# How deep a pistol must go for the ROM to count (hip depth below the standing
# ankle, in torso-lengths).
PISTOL_DEPTH = THRESHOLDS.pistol_depth
# How far the standing knee may travel sideways before it counts as valgus
# (knee collapse inward), in torso-lengths.
PISTOL_VALGUS = THRESHOLDS.pistol_valgus


# ---------------------------------------------------------------------------
# What a fired fault is
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Fault:
    """A fault, with the number that fired it.

    The phone used to re-derive these by regular expression from the prose in
    the range component's why-string, which meant a copy edit could silently
    switch off fault detection on every device. It renders `name` now, and
    everything needed to explain the call travels with it - including, since
    the registry, the stable `id` and the `phase` the number was read in.
    """
    name: str
    primitive: str
    value: float | None
    threshold: float
    comparison: str          # "<", "<=", ">", ">="
    unit: str = ""
    robustness: str = "SCALED"
    id: str = ""
    phase: str = "rep"
    interval_s: list[float] | None = None

    def as_dict(self) -> dict:
        out = {
            "name": self.name,
            "primitive": self.primitive,
            "value": (None if self.value is None else round(float(self.value), 4)),
            "threshold": round(float(self.threshold), 4),
            "comparison": self.comparison,
            "unit": self.unit,
            "class": self.robustness,
            "errorId": self.id,
            "phase": self.phase,
        }
        if self.interval_s is not None:
            out["intervalS"] = self.interval_s
        return out


def _fault_of(a: Assessment, fps: float | None = None) -> Fault:
    m = a.rule
    interval = None
    if fps and a.phase_window is not None:
        interval = [round(a.phase_window[0] / fps, 2), round(a.phase_window[1] / fps, 2)]
    from .evidence import PRIMITIVES, SCALED
    spec = PRIMITIVES.get(m.primitive, (SCALED, "", ""))
    return Fault(m.name, m.primitive, a.value, m.threshold, m.comparison,
                 spec[2], spec[0], m.id, m.phase, interval)


def _fire(ev: Evidence, primitive: str, comparison: str, threshold: float,
          name: str) -> Fault | None:
    """One ad-hoc predicate outside the registry. Kept for callers that still
    build a rule inline; the registry is where rules belong.

    Not measured means not fired - and, crucially, not clean either: the caller
    reports `ev.unmeasured()` beside the faults so the two are told apart.
    """
    value = ev.value(primitive)
    if value is None:
        return None
    fired = {
        "<": value < threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        ">=": value >= threshold,
    }[comparison]
    if not fired:
        return None
    m = ev.get(primitive)
    return Fault(name, primitive, value, threshold, comparison, m.unit,
                 m.robustness, phase=m.phase)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def _classifier(track: str):
    def fn(ev: Evidence, variant: str = VARIANT_UNSPECIFIED,
           fps: float | None = None) -> list[Fault]:
        return [_fault_of(a, fps) for a in assess(track, ev, variant)
                if a.status == OBSERVED]
    fn.__name__ = track
    fn.__doc__ = f"The faults one rep or hold of {track} was measured to have."
    return fn


CLASSIFIERS = {track: _classifier(track) for track in RULES}

front_lever = CLASSIFIERS["front_lever"]
planche = CLASSIFIERS["planche"]
muscle_up = CLASSIFIERS["muscle_up"]
pull_up = CLASSIFIERS["pull_up"]
dip = CLASSIFIERS["dip"]
push_up = CLASSIFIERS["push_up"]
squat = CLASSIFIERS["squat"]
pistol_squat = CLASSIFIERS["pistol_squat"]

# The failure types each track can produce, for the harness and the UI.
# Derived from the registry, in registry order, without duplicates.
TRACK_FAILURES: dict[str, tuple[str, ...]] = {
    track: tuple(dict.fromkeys(r.name for r in rules))
    for track, rules in RULES.items()
}

# Errors these movements are commonly coached on that this pipeline does NOT
# measure, and why. Data rather than prose, so the app can state what it is not
# looking at instead of implying the list is complete. Adding a row here is how
# you decline to measure something; inventing a threshold for it is not.
NOT_MEASURED: dict[str, str] = {
    "gaze": "head direction needs a face-on view no training clip has",
    "grip type": "hand orientation is below the resolution of a 2D wrist point",
    "wrist loading": "no load or joint-torque signal exists in a video",
    "elbow flare": "the 90-degree flare check needs a camera overhead",
    "lumbar rounding": "there are no spine landmarks between shoulders and hips",
    "breathing": "not visible",
    "scapular position": "the shoulder landmark does not resolve retraction or "
                         "protraction; the lever/planche labels measure elbow "
                         "extension and say so",
    "heel contact": "the heel is not a landmark; the planted-ankle rise is the "
                    "proxy and is labelled as one",
}


def classify_faults(track: str, ev: Evidence,
                    variant: str = VARIANT_UNSPECIFIED,
                    fps: float | None = None) -> list[Fault]:
    """The faults one rep or hold of `track` was measured to have.

    An unknown track produces nothing - not a guess borrowed from a movement
    that happens to share a classifier.
    """
    fn = CLASSIFIERS.get(track)
    return fn(ev, variant, fps) if fn else []


def classify_failures(track: str, values: dict | Evidence,
                      view: View = UNKNOWN_VIEW,
                      variant: str = VARIANT_UNSPECIFIED) -> list[str]:
    """Fault NAMES only - the shape the hold path and the harness still use."""
    ev = (values if isinstance(values, Evidence)
          else Evidence.from_values(values, track=track, view=view))
    return [f.name for f in classify_faults(track, ev, variant)]


def all_tracks() -> tuple[str, ...]:
    return tuple(CLASSIFIERS)


def all_fault_names() -> tuple[str, ...]:
    """Every fault name any track can produce, in a stable order."""
    seen: dict[str, None] = {}
    for names in TRACK_FAILURES.values():
        for n in names:
            seen.setdefault(n, None)
    return tuple(seen)


def rules_of(track: str) -> tuple[Rule, ...]:
    """The registry rows for one track, for anything that wants to show them."""
    return rules_for(track)
