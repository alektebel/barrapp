"""Per-track failure classification.

The old model asked whether a technique was "perfect" - a single judgement, and
a bad one, because a model cannot see a body from one still. This module does
the opposite: it classifies each measured rep or hold into the COMMON failure
types that actually occur, from the geometry that was already measured.

Each failure is a threshold on a measured signal, so it is deterministic and
testable, and it is stated with the number behind it: a fired fault carries the
value, the threshold and the comparison that fired it, which is what the phone
renders and what the trace records.

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
   distance from the hips - never could. A squat has its own classifier now,
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
    everything needed to explain the call travels with it.
    """
    name: str
    primitive: str
    value: float | None
    threshold: float
    comparison: str          # "<", "<=", ">", ">="
    unit: str = ""
    robustness: str = "SCALED"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "primitive": self.primitive,
            "value": (None if self.value is None else round(float(self.value), 4)),
            "threshold": round(float(self.threshold), 4),
            "comparison": self.comparison,
            "unit": self.unit,
            "class": self.robustness,
        }


def _fire(ev: Evidence, primitive: str, comparison: str, threshold: float,
          name: str) -> Fault | None:
    """The fault, if the measurement exists AND crosses the threshold.

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
                 m.robustness)


def _collect(*faults: Fault | None) -> list[Fault]:
    return [f for f in faults if f is not None]


# ---------------------------------------------------------------------------
# Shared bar rules - wrist-origin movements only
# ---------------------------------------------------------------------------
def _bar_faults(ev: Evidence) -> list[Fault]:
    """The five faults defined for a body hanging from its hands.

    Every one of them is measured against the hands. On a hip-origin track they
    would be measured against the hips, which is why they are not offered there.
    """
    return _collect(
        _fire(ev, "swing", ">", SWING_TORSO, "momentum"),
        _fire(ev, "lockout_pct", "<", LOCKOUT_MIN * 100, "lockout"),
        _fire(ev, "hang_pct", "<", HANG_MIN * 100, "dead hang"),
        _fire(ev, "tempo_ratio", "<", CONTROLLED_TEMPO, "control"),
        _fire(ev, "stalled_frac", ">=", THRESHOLDS.stalled_frac, "stall"),
    )


# ---------------------------------------------------------------------------
# Front lever
# ---------------------------------------------------------------------------
def front_lever(ev: Evidence) -> list[Fault]:
    """The failures a front lever was measured to have."""
    return _collect(
        _fire(ev, "body_line_deg", "<", STRICT_HORIZONTAL, "poor range of motion"),
        # Bent elbows are the visible face of failed scapular retraction: the
        # shoulders are not held down and back, so the arms take the load.
        _fire(ev, "arms_straight_frac", "<", THRESHOLDS.arms_straight_frac,
              "poor scapular retraction"),
        _fire(ev, "legs_straight_frac", "<", THRESHOLDS.legs_straight_frac,
              "bent knees"),
        _fire(ev, "hip_pike_deg", "<", PIKE, "piked hips"),
        _fire(ev, "swing", ">", SWING_TORSO, "momentum"),
    )


# ---------------------------------------------------------------------------
# Planche
# ---------------------------------------------------------------------------
def planche(ev: Evidence) -> list[Fault]:
    return _collect(
        _fire(ev, "body_line_deg", "<", STRICT_HORIZONTAL, "poor range of motion"),
        # A planche is pushed from the shoulders; bent elbows mean the shoulders
        # are not protracted and the arms are doing the pushing instead.
        _fire(ev, "arms_straight_frac", "<", THRESHOLDS.arms_straight_frac,
              "poor scapular protraction"),
        _fire(ev, "legs_straight_frac", "<", THRESHOLDS.legs_straight_frac,
              "bent knees"),
        _fire(ev, "hip_pike_deg", "<", PIKE, "piked body"),
        _fire(ev, "swing", ">", SWING_TORSO, "momentum"),
    )


# ---------------------------------------------------------------------------
# Muscle-up
# ---------------------------------------------------------------------------
def muscle_up(ev: Evidence) -> list[Fault]:
    """The bar faults, extended with what a muscle-up adds over a pull-up."""
    return _bar_faults(ev) + _collect(
        _fire(ev, "transition_s", ">", THRESHOLDS.transition_s, "poor transition"),
        _fire(ev, "arms_straight_frac", "<", THRESHOLDS.bent_arms_frac, "bent arms"),
    )


# ---------------------------------------------------------------------------
# Pull-up
# ---------------------------------------------------------------------------
def pull_up(ev: Evidence) -> list[Fault]:
    """The bar faults plus the two the coaching literature cites most.

    `no active hang` is the bottom of the rep seen at the elbow rather than at
    the shoulder: the athlete never straightens the arms between reps. `too
    fast` is measured against the SET'S OWN median concentric, so it is one
    athlete on one day compared with themselves - no absolute seconds, nothing
    that moves when the camera does.
    """
    return _bar_faults(ev) + _collect(
        _fire(ev, "start_elbow_deg", "<", THRESHOLDS.active_hang_deg,
              "no active hang"),
        _fire(ev, "fast_ratio", "<", THRESHOLDS.fast_rep_frac, "too fast"),
    )


# ---------------------------------------------------------------------------
# Dip
# ---------------------------------------------------------------------------
def dip(ev: Evidence) -> list[Fault]:
    """A dip starts locked out at the top and turns around at the bottom.

    So both ends are read at the elbow rather than as a share of arm reach: the
    top is where the arms should be straight, and the bottom is where going
    past ninety degrees stops being depth and starts being the shoulder.
    """
    return _collect(
        _fire(ev, "start_elbow_deg", "<", STRAIGHT_ARM, "lockout"),
        _fire(ev, "bottom_elbow_deg", "<", THRESHOLDS.dip_bottom_deg, "too deep"),
        _fire(ev, "turn_speed", ">", THRESHOLDS.bounce_speed, "bounce at bottom"),
        _fire(ev, "tempo_ratio", "<", CONTROLLED_TEMPO, "control"),
        _fire(ev, "stalled_frac", ">=", THRESHOLDS.stalled_frac, "stall"),
    )


# ---------------------------------------------------------------------------
# Push-up
# ---------------------------------------------------------------------------
def push_up(ev: Evidence) -> list[Fault]:
    """A push-up is a plank that bends: the body line is half of the movement.

    `sagging hips` is the hip's distance from the shoulder-ankle line, which
    only exists from the side - filmed head-on the whole line projects to
    nothing - so it is a PLANAR primitive and does not fire from an unknown
    viewpoint.
    """
    return _collect(
        _fire(ev, "travel", "<", THRESHOLDS.push_up_depth, "poor range of motion"),
        _fire(ev, "start_elbow_deg", "<", STRAIGHT_ARM, "lockout"),
        _fire(ev, "hip_sag", ">", THRESHOLDS.hip_sag, "sagging hips"),
        _fire(ev, "tempo_ratio", "<", CONTROLLED_TEMPO, "control"),
        _fire(ev, "stalled_frac", ">=", THRESHOLDS.stalled_frac, "stall"),
    )


# ---------------------------------------------------------------------------
# Squat
# ---------------------------------------------------------------------------
def squat(ev: Evidence) -> list[Fault]:
    """A squat measured where a squat happens: at the hips, over the ankles.

    Depth is the hip's drop from THIS rep's own standing height, so it needs no
    ruler and no reference athlete, and because it is purely vertical it does
    not change when the camera walks around. Valgus and heel rise are planar
    and gated accordingly.
    """
    return _collect(
        _fire(ev, "squat_depth", "<", THRESHOLDS.squat_depth, "poor range of motion"),
        _fire(ev, "tempo_ratio", "<", CONTROLLED_TEMPO, "uncontrolled descent"),
        _fire(ev, "knee_valgus", ">", PISTOL_VALGUS, "knee valgus"),
        _fire(ev, "heel_rise", ">", THRESHOLDS.heel_rise, "heel raise"),
        _fire(ev, "stalled_frac", ">=", THRESHOLDS.stalled_frac, "stall"),
    )


# ---------------------------------------------------------------------------
# Pistol squat
# ---------------------------------------------------------------------------
def pistol_squat(ev: Evidence) -> list[Fault]:
    return _collect(
        _fire(ev, "pistol_depth", "<", PISTOL_DEPTH, "poor range of motion"),
        _fire(ev, "knee_valgus", ">", PISTOL_VALGUS, "knee valgus"),
        _fire(ev, "heel_rise", ">", THRESHOLDS.heel_rise, "heel raise"),
        _fire(ev, "torso_lean", "<", THRESHOLDS.lean_back, "leaning back"),
        _fire(ev, "tempo_ratio", "<", CONTROLLED_TEMPO, "uncontrolled descent"),
        _fire(ev, "swing", ">", SWING_TORSO, "arm swing"),
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
CLASSIFIERS = {
    "front_lever": front_lever,
    "planche": planche,
    "muscle_up": muscle_up,
    "pull_up": pull_up,
    "dip": dip,
    "push_up": push_up,
    "squat": squat,
    "pistol_squat": pistol_squat,
}

# The failure types each track can produce, for the harness and the UI.
TRACK_FAILURES: dict[str, tuple[str, ...]] = {
    "front_lever": ("poor range of motion", "poor scapular retraction",
                    "bent knees", "piked hips", "momentum"),
    "planche": ("poor range of motion", "poor scapular protraction",
                "bent knees", "piked body", "momentum"),
    "muscle_up": ("momentum", "lockout", "dead hang", "control", "stall",
                  "poor transition", "bent arms"),
    "pull_up": ("momentum", "lockout", "dead hang", "control", "stall",
                "no active hang", "too fast"),
    "dip": ("lockout", "too deep", "bounce at bottom", "control", "stall"),
    "push_up": ("poor range of motion", "lockout", "sagging hips", "control",
                "stall"),
    "squat": ("poor range of motion", "uncontrolled descent", "knee valgus",
              "heel raise", "stall"),
    "pistol_squat": ("poor range of motion", "knee valgus", "heel raise",
                     "leaning back", "uncontrolled descent", "arm swing"),
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
}


def classify_faults(track: str, ev: Evidence) -> list[Fault]:
    """The faults one rep or hold of `track` was measured to have.

    An unknown track produces nothing - not a guess borrowed from a movement
    that happens to share a classifier.
    """
    fn = CLASSIFIERS.get(track)
    return fn(ev) if fn else []


def classify_failures(track: str, values: dict | Evidence,
                      view: View = UNKNOWN_VIEW) -> list[str]:
    """Fault NAMES only - the shape the hold path and the harness still use."""
    ev = (values if isinstance(values, Evidence)
          else Evidence.from_values(values, track=track, view=view))
    return [f.name for f in classify_faults(track, ev)]


def all_tracks() -> tuple[str, ...]:
    return tuple(CLASSIFIERS)


def all_fault_names() -> tuple[str, ...]:
    """Every fault name any track can produce, in a stable order."""
    seen: dict[str, None] = {}
    for names in TRACK_FAILURES.values():
        for n in names:
            seen.setdefault(n, None)
    return tuple(seen)
