"""Per-track failure classification.

The old model asked whether a technique was "perfect" - a single judgement, and
a bad one, because a model cannot see a body from one still. This module does
the opposite: it classifies each measured rep or hold into the COMMON failure
types that actually occur, from the geometry that was already measured.

Each failure is a threshold on a measured signal, so it is deterministic and
testable, and it is stated with the number behind it. The taxonomy is per
track: a front lever fails in different ways from a pistol squat. Shared basics
(poor range of motion, momentum) appear where they apply.

The thresholds are pinned here because the phone (Cues.kt) and this module must
agree. Change them together, or the app starts saying things the harness never
tested.
"""
from __future__ import annotations

import math

# ---- straightness: 180 = fully extended -------------------------------------
STRAIGHT_ARM = 160.0
STRAIGHT_LEG = 160.0

# ---- body line: 0 = vertical, 90 = horizontal -------------------------------
# A lever or planche wants the body horizontal. Anything below this band is a
# range-of-motion failure (the body has not come up to the line).
HORIZONTAL = 70.0
STRICT_HORIZONTAL = 75.0

# ---- hip pike: 180 = fully straight -----------------------------------------
# A piked body flexes the hips. This is the "sagging hips" / broken body line.
PIKE = 150.0

# ---- shared bar faults, mirrors barra/faults.py -----------------------------
SWING_TORSO = 0.4
LOCKOUT_MIN = 0.85
HANG_MIN = 0.75
CONTROLLED_TEMPO = 0.70
STALL_RATE = 0.20

# How deep a pistol must go for the ROM to count (hip depth below the standing
# ankle, in torso-lengths).
PISTOL_DEPTH = 0.55
# How far the standing knee may travel sideways before it counts as valgus
# (knee collapse inward), in torso-lengths.
PISTOL_VALGUS = 0.12


def _f(x, default: float | None = None) -> float | None:
    if x is None:
        return default
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


# ---------------------------------------------------------------------------
# Front lever
# ---------------------------------------------------------------------------
def front_lever(values: dict) -> list[str]:
    """The failures a front lever was measured to have."""
    out: list[str] = []
    body = _f(values.get("body_line_deg"))
    if body is not None and body < STRICT_HORIZONTAL:
        out.append("poor range of motion")     # body not held horizontal
    if _f(values.get("arms_straight_frac"), 1.0) < 0.6:
        # Bent elbows are the visible face of failed scapular retraction: the
        # shoulders are not held down and back, so the arms take the load.
        out.append("poor scapular retraction")
    if _f(values.get("legs_straight_frac"), 1.0) < 0.6:
        out.append("bent knees")
    pike = _f(values.get("hip_pike_deg"))
    if pike is not None and pike < PIKE:
        out.append("piked hips")
    if _f(values.get("swing"), 0.0) > SWING_TORSO:
        out.append("momentum")
    return out


# ---------------------------------------------------------------------------
# Planche
# ---------------------------------------------------------------------------
def planche(values: dict) -> list[str]:
    out: list[str] = []
    body = _f(values.get("body_line_deg"))
    if body is not None and body < STRICT_HORIZONTAL:
        out.append("poor range of motion")
    if _f(values.get("arms_straight_frac"), 1.0) < 0.6:
        # A planche is pushed from the shoulders; bent elbows mean the shoulders
        # are not protracted and the arms are doing the pushing instead.
        out.append("poor scapular protraction")
    if _f(values.get("legs_straight_frac"), 1.0) < 0.6:
        out.append("bent knees")
    pike = _f(values.get("hip_pike_deg"))
    if pike is not None and pike < PIKE:
        out.append("piked body")
    if _f(values.get("swing"), 0.0) > SWING_TORSO:
        out.append("momentum")
    return out


# ---------------------------------------------------------------------------
# Muscle-up / bar
# ---------------------------------------------------------------------------
def muscle_up(values: dict) -> list[str]:
    """The bar faults, extended with what a muscle-up adds over a pull-up.

    The first five mirror barra/faults.py so the phone and the harness still
    agree on the ones they already named.
    """
    out: list[str] = []
    if _f(values.get("swing"), 0.0) > SWING_TORSO:
        out.append("momentum")
    lockout = _f(values.get("lockout_pct"))
    if lockout is not None and lockout < LOCKOUT_MIN * 100:
        out.append("lockout")                 # poor ROM at the top
    hang = _f(values.get("hang_pct"))
    if hang is not None and hang < HANG_MIN * 100:
        out.append("dead hang")               # poor ROM at the bottom
    tempo = _f(values.get("tempo_ratio"))
    if tempo is not None and tempo < CONTROLLED_TEMPO:
        out.append("control")                 # descent was dropped
    if _f(values.get("stalled_frac"), 0.0) >= 0.05:
        out.append("stall")
    transition = _f(values.get("transition_s"))
    if transition is not None and transition > 0.60:
        out.append("poor transition")
    if _f(values.get("arms_straight_frac"), 1.0) < 0.5:
        out.append("bent arms")
    return out


# ---------------------------------------------------------------------------
# Pistol squat
# ---------------------------------------------------------------------------
def pistol_squat(values: dict) -> list[str]:
    out: list[str] = []
    depth = _f(values.get("pistol_depth"))
    if depth is not None and depth < PISTOL_DEPTH:
        out.append("poor range of motion")    # not deep enough
    valgus = _f(values.get("knee_valgus"))
    if valgus is not None and valgus > PISTOL_VALGUS:
        out.append("knee valgus")             # the standing knee caves inward
    if _f(values.get("heel_raise"), 0.0) > 0.20:
        out.append("heel raise")              # ankle mobility / calf tightness
    lean = _f(values.get("torso_lean"))
    if lean is not None and lean < -0.30:
        out.append("leaning back")            # over-compensating, hips forward
    tempo = _f(values.get("tempo_ratio"))
    if tempo is not None and tempo < CONTROLLED_TEMPO:
        out.append("uncontrolled descent")
    if _f(values.get("swing"), 0.0) > SWING_TORSO:
        out.append("arm swing")
    return out


# ---------------------------------------------------------------------------
# Enriching a rep's measured values for the classifiers
# ---------------------------------------------------------------------------
def values_for_rep(metrics: dict, arm: float, signal,
                   start: int, turn: int) -> dict:
    """Turn the standard rep metrics into the keys the classifiers read.

    `metrics` is the dict from barra.metrics.rep_metrics. The classifiers want
    a few things the rep metrics do not carry directly (lockout/hang as a
    percent of the athlete's own arm, the stalled fraction, the pistol's depth),
    so they are derived here, in one place.
    """
    out: dict = dict(metrics)
    if _np_isfinite(arm) and arm > 0:
        if out.get("peak_height") is not None and _np_isfinite(out["peak_height"]):
            out["lockout_pct"] = out["peak_height"] / arm * 100.0
        if out.get("start_depth") is not None and _np_isfinite(out["start_depth"]):
            out["hang_pct"] = out["start_depth"] / arm * 100.0

    # The stalled fraction is the smoothness component's read-out: what share of
    # the ascent made no progress. Recomputing it here keeps the failure text
    # consistent with the score, without threading the component through.
    if signal is not None and len(signal) > 0:
        seg = np.asarray(signal[start:turn + 1], dtype=float)
        if seg.size >= 6:
            step = np.diff(seg)
            total = seg[-1] - seg[0]
            if total > 1e-9:
                mean_rate = total / step.size
                out["stalled_frac"] = float(np.mean(step < STALL_RATE * mean_rate))

    # A pistol's depth is its range of motion: how far the hips dropped.
    if out.get("rom") is not None and _np_isfinite(out["rom"]):
        out["pistol_depth"] = out["rom"]
    return out


def pistol_geometry(kp, start: int, turn: int, end: int, torso: float) -> dict:
    """Per-leg geometry a pistol needs, from the raw keypoints.

    These are frontal/planar quantities (knee valgus, backward lean), so they
    only mean something from a consistent camera side - the taxonomy keeps that
    caveat on the failure it feeds.
    """
    seg = slice(start, end + 1)
    sh = _mid(kp, "left_shoulder", "right_shoulder")
    hip = _mid(kp, "left_hip", "right_hip")
    knee = _mid(kp, "left_knee", "right_knee")
    ankle = _mid(kp, "left_ankle", "right_ankle")

    # Backward lean: hips ahead of the shoulders (image x grows rightward, so
    # a positive hip-shoulder gap that is large means the hips have gone
    # forward of the shoulders - the "leaning back" compensation).
    lean = (hip[:, 0] - sh[:, 0])[seg] / torso
    lean = lean[np.isfinite(lean)]
    torso_lean = float(np.percentile(lean, 90)) if lean.size else np.nan

    # Knee valgus: the knees deviate sideways from the hip-ankle line. Measured
    # on whichever side is better seen; a big deviation is a collapsed knee.
    dev = []
    for side in ("left", "right"):
        kx = kp[:, S.KP_INDEX[f"{side}_knee"], 0]
        hx = kp[:, S.KP_INDEX[f"{side}_hip"], 0]
        ax = kp[:, S.KP_INDEX[f"{side}_ankle"], 0]
        ok = (kp[:, S.KP_INDEX[f"{side}_knee"], 2] >= MIN_CONF) & \
             (kp[:, S.KP_INDEX[f"{side}_hip"], 2] >= MIN_CONF) & \
             (kp[:, S.KP_INDEX[f"{side}_ankle"], 2] >= MIN_CONF)
        d = np.abs(kx - (hx + ax) / 2.0)[seg] / torso
        d = d[ok[seg] & np.isfinite(d)]
        if d.size:
            dev.append(float(np.percentile(d, 90)))
    knee_valgus = max(dev) if dev else np.nan

    # Heel raise: the standing ankle sits too high above the toe line. We have
    # no toe landmark, so this is approximated by how high the planted ankle is
    # relative to the body - a raised heel lifts the ankle toward the knee.
    # Only reported; it is the weakest of the pistol signals.
    ankle_below = (hip[:, 1] - ankle[:, 1])[seg] / torso
    ankle_below = ankle_below[np.isfinite(ankle_below)]
    heel_raise = float(1.0 - np.percentile(ankle_below, 5)) if ankle_below.size else np.nan

    return {"torso_lean": torso_lean, "knee_valgus": knee_valgus,
            "heel_raise": heel_raise}


# --- small local imports to keep the module self-contained -------------------
import numpy as np
from . import schema as S
from .movements import midpoint as _mid, pair_confidence, robust_torso

MIN_CONF = 0.5

def _np_isfinite(x):
    try:
        return bool(np.isfinite(x))
    except (TypeError, ValueError):
        return False

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
# Track -> the failure classifier. Anything not in here is classified by the
# shared bar rules via muscle_up's overlap with the old faults.
CLASSIFIERS = {
    "front_lever": front_lever,
    "planche": planche,
    "muscle_up": muscle_up,
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
    "pistol_squat": ("poor range of motion", "knee valgus", "heel raise",
                     "leaning back", "uncontrolled descent", "arm swing"),
}


def classify_failures(track: str, values: dict) -> list[str]:
    """The failure types one rep or hold of `track` was measured to have.

    Unknown track -> empty. The shared muscle_up classifier also covers the
    plain bar movements (dip, pull-up, push-up) because those five faults are
    defined for the bar in general.
    """
    fn = CLASSIFIERS.get(track)
    if fn is None:
        # For the older bar movements keep the established five-fault set.
        if track in ("pull_up", "dip", "push_up", "squat"):
            return muscle_up(values)
        return []
    return fn(values)


def all_tracks() -> tuple[str, ...]:
    return tuple(CLASSIFIERS)
