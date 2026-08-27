"""Which exercise is this clip?

The app lets the athlete film without telling us what they did, so the movement
has to be inferred. It is inferred geometrically, from where the hands are and
whether they stay there, because that is what actually distinguishes these
movements:

    squat      feet planted, hands free, hips travel vertically
    dip        hands fixed, shoulders above them, and your LEGS BELOW them
    push-up    hands fixed, shoulders above them, and nothing below them
    pull-up    hands fixed above the head, shoulders never rise above them
    muscle-up  as a pull-up, but the shoulders finish above the hands

The pull-up / muscle-up split is the one that matters most and it is the
cleanest: a pull-up ends with your chin at the bar and your shoulders below it;
a muscle-up ends with your shoulders over it. That is a sign change in one
quantity, not a judgement call.

Nothing here uses a trained classifier. A learned model would need labelled
clips we do not have, and would fail silently on the first movement it had not
seen; these rules fail loudly, and every one of them can be checked by hand
against a still frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import schema as S
from .movements import (MOVEMENTS, midpoint, pair_confidence, robust_torso)

MIN_CONF = 0.5

# Landmarks compared against hand height. Wrists and face are excluded: the
# first is the reference, the second sits above the shoulders in every one of
# these movements and would only dilute the fraction.
_BODY = ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
         "left_hip", "right_hip", "left_knee", "right_knee",
         "left_ankle", "right_ankle"]

# Shoulders this far above the hands (in torso-lengths) counts as "over the bar".
# A pull-up tops out below zero; a muscle-up finishes well above it. The gap is
# wide, so the threshold does not need to be precise.
OVER_BAR = 0.12
# Wrist travel above this many torso-lengths means the hands were not on
# anything fixed. Same constant the segmenter uses to reject walking.
ANCHOR_FIXED = 0.80
# The shoulders must move at least this far relative to the hands for the hands
# to count as a handhold rather than as arms hanging off a moving torso.
ARTICULATION = 0.20
# Fraction of the visible body that hangs below the hands. In a dip your legs
# do; in a push-up your hands are the lowest thing you have.
#
# The obvious discriminator - torso angle - does NOT work, and it is worth
# saying why: filmed head-on, a push-up's torso is foreshortened onto almost
# nothing, so the shoulder-to-hip line projects near-vertical and reads exactly
# like a dip. Measured on real footage it came out at 5 degrees from vertical.
# This test compares heights instead, which projection does not distort, and it
# works from whatever keypoints happen to be visible - on that same clip the
# ankles were never seen at all.
BELOW_HANDS_DIP = 0.25
LOW_MARGIN = 0.15


@dataclass
class Classification:
    exercise: str
    confidence: float
    reason: str
    features: dict = field(default_factory=dict)
    runner_up: str | None = None

    @property
    def certain(self) -> bool:
        return self.confidence >= 0.65


def _travel(points: np.ndarray, ok: np.ndarray, torso: float) -> float:
    if ok.sum() < 5:
        return float("inf")
    p = points[ok] / torso
    span = np.percentile(p, 95, axis=0) - np.percentile(p, 5, axis=0)
    return float(np.hypot(*span))


def features(kp: np.ndarray) -> dict:
    """Geometric summary of a clip, in torso-lengths. Every value is scale-free
    so it means the same thing whatever the camera distance."""
    torso = robust_torso(kp)
    wrist = midpoint(kp, "left_wrist", "right_wrist")
    shoulder = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    ankle = midpoint(kp, "left_ankle", "right_ankle")

    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_CONF
    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_CONF
    a_ok = pair_confidence(kp, "left_ankle", "right_ankle") >= MIN_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_CONF
    ws = w_ok & s_ok

    # image y grows downward, so this is height of the shoulders above the hands
    above = np.where(ws, (wrist[:, 1] - shoulder[:, 1]) / torso, np.nan)
    hip_over_ankle = np.where(a_ok & h_ok, (ankle[:, 1] - hip[:, 1]) / torso, np.nan)

    # Angle of the torso from vertical. Kept as a diagnostic only - see
    # BELOW_HANDS_DIP for why it is not used to decide anything.
    dx = np.abs(shoulder[:, 0] - hip[:, 0])
    dy = np.abs(shoulder[:, 1] - hip[:, 1])
    tilt = np.where(s_ok & h_ok, np.degrees(np.arctan2(dx, np.maximum(dy, 1e-6))), np.nan)

    # How much of the body hangs below the hands, over frames where the hands
    # were seen. Uses whatever landmarks are confident in that frame rather
    # than requiring a fixed set.
    below = []
    for i in range(len(kp)):
        if not w_ok[i]:
            continue
        heights = [
            (kp[i, S.KP_INDEX[n], 1] - wrist[i, 1]) / torso
            for n in _BODY if kp[i, S.KP_INDEX[n], 2] >= MIN_CONF
        ]
        if heights:
            below.append(float(np.mean([h > LOW_MARGIN for h in heights])))

    def pct(a, q):
        a = a[np.isfinite(a)]
        return float(np.percentile(a, q)) if a.size else float("nan")

    return {
        "n_frames": int(len(kp)),
        "wrist_seen": float(w_ok.mean()),
        "ankle_seen": float(a_ok.mean()),
        "wrist_travel": _travel(wrist, w_ok, torso),
        "ankle_travel": _travel(ankle, a_ok, torso),
        # negative = hands above the shoulders, i.e. hanging
        "shoulder_above_hands_p05": pct(above, 5),
        "shoulder_above_hands_p95": pct(above, 95),
        "hands_overhead_frac": float(np.nanmean(above < -0.05)) if ws.any() else 0.0,
        "hands_below_frac": float(np.nanmean(above > 0.05)) if ws.any() else 0.0,
        # How much the shoulders move RELATIVE TO the hands. Large when the
        # hands are on something and the body moves past them; near zero when
        # the arms just hang off a torso that is moving as one piece.
        "arm_articulation": pct(above, 95) - pct(above, 5),
        "hip_travel": (pct(hip_over_ankle, 95) - pct(hip_over_ankle, 5))
        if np.isfinite(pct(hip_over_ankle, 95)) else float("nan"),
        "torso_tilt": pct(tilt, 50),
        "body_below_hands": float(np.median(below)) if below else float("nan"),
    }


def classify(kp: np.ndarray) -> Classification:
    """Decide the movement, or say the clip does not show one we know.

    Order matters. Hanging is checked first because it is the most specific
    shape; then the squat, because "the hands did not move much" is NOT enough
    on its own to mean the hands were on something - arms hanging at the sides
    of a torso that is squatting move roughly as far as the hips do, and an
    anchor test alone reads that as a dip. What separates them is whether the
    shoulders move relative to the hands at all.
    """
    f = features(kp)
    anchored = f["wrist_travel"] <= ANCHOR_FIXED and f["wrist_seen"] >= 0.4
    articulated = np.isfinite(f["arm_articulation"]) and f["arm_articulation"] >= ARTICULATION
    planted = f["ankle_travel"] <= ANCHOR_FIXED and f["ankle_seen"] >= 0.4

    if anchored and articulated and f["hands_overhead_frac"] >= 0.35:
        peak = f["shoulder_above_hands_p95"]
        if peak >= OVER_BAR:
            margin = min(1.0, (peak - OVER_BAR) / 0.35)
            return Classification(
                "muscle_up", 0.70 + 0.28 * margin,
                f"hanging from a fixed bar, and the shoulders finish {peak:.2f} "
                "torso-lengths above the hands",
                f, runner_up="pull_up",
            )
        margin = min(1.0, (OVER_BAR - peak) / 0.35)
        return Classification(
            "pull_up", 0.70 + 0.25 * margin,
            f"hanging from a fixed bar, and the shoulders never rise above the "
            f"hands (peak {peak:+.2f} torso-lengths)",
            f, runner_up="muscle_up",
        )

    if planted and not articulated and np.isfinite(f["hip_travel"]) and f["hip_travel"] >= 0.35:
        return Classification(
            "squat", 0.78,
            f"feet stayed put, the hips moved through {f['hip_travel']:.2f} "
            "torso-lengths, and the arms did not move relative to the torso",
            f, runner_up=None,
        )

    if anchored and articulated and f["hands_below_frac"] >= 0.80:
        below = f["body_below_hands"]
        if not np.isfinite(below):
            return Classification(
                "unknown", 0.0,
                "hands fixed below the shoulders, but too little of the body was "
                "seen to tell a dip from a push-up",
                f,
            )
        if below >= BELOW_HANDS_DIP:
            return Classification(
                "dip", 0.78,
                f"hands fixed below the shoulders, with {below:.0%} of the body "
                "hanging below them - the legs are off the ground",
                f, runner_up="push_up",
            )
        return Classification(
            "push_up", 0.78,
            "hands fixed below the shoulders and nothing hanging below them, so "
            "the hands are on the floor rather than on bars",
            f, runner_up="dip",
        )

    if not anchored and not planted:
        return Classification(
            "unknown", 0.0,
            "the hands are not on anything fixed and the feet are not planted, so "
            "this clip does not show a movement barra can measure",
            f,
        )
    return Classification(
        "unknown", 0.0,
        "the clip does not match any movement barra knows: the hands are "
        f"{'fixed' if anchored else 'moving'} and the shoulders move "
        f"{f['arm_articulation']:.2f} torso-lengths relative to them",
        f,
    )


def label(exercise: str) -> str:
    if exercise in MOVEMENTS:
        return exercise.replace("_", "-").replace("muscle-up", "Muscle-up").title() \
            if exercise != "muscle_up" else "Muscle-up"
    return "Unknown"


HUMAN = {
    "muscle_up": "Muscle-up",
    "pull_up": "Pull-up",
    "dip": "Dip",
    "push_up": "Push-up",
    "squat": "Squat",
    "unknown": "Not recognised",
}
