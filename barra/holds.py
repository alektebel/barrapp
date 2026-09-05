"""Which static position is this clip holding?

A clip that sits still is not a failure to find repetitions. It is a different
kind of result: calisthenics is half holds - dead hangs, levers, planches,
handstands, L-sits - and until now a hold reached the athlete as "not a set",
which is true and useless. The 23-second inverted hang in the sample clips is
the case that motivated this: real training, correctly refused as a set, and
reported as nothing.

Holds are recognised the same way the movements are: geometrically, from where
the hands are relative to the shoulders and which way the body points, in
torso-lengths so the camera distance does not matter. There is no learned
model. Every rule below can be checked against a still frame by eye, and every
one of them is written down next to the number it was compared against.

What is measured is **duration**: the longest stretch in which the body stayed
parked. That is the only quantity a hold has that a single camera can measure
honestly. Whether the lever was flat, whether the handstand was straight - those
are angles in the image plane, and docs/FINDINGS.md shows a few degrees of
camera azimuth moves them more than technique does. So the angle is reported as
a feature, and the seconds are the result.

The vocabulary, and the geometry that separates each entry:

    hanging (hands above the shoulders)
      dead_hang       body vertical below the bar, arms long
      flexed_hang     body vertical below the bar, shoulders pulled up the arm
      inverted_hang   hips above the shoulders, body vertical - skin-the-cat
                      territory, and the sample clip that started this
      front_lever     body horizontal below the bar, face up
      back_lever      body horizontal below the bar, face down
      lever           body horizontal, which way the face points not seen
    supporting (hands below the shoulders)
      handstand       hips above the shoulders, body vertical
      plank           body horizontal above the hands
      l_sit           torso vertical, legs out level in front
      support_hold    torso vertical, hands at hip height, legs hanging
    hold              parked, on something fixed, none of the above

Front versus back lever hangs on one landmark, the nose, and side-on it is a
small signal. The confidence says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import schema as S
from .movements import midpoint, pair_confidence, robust_torso

MIN_CONF = 0.5

# A frame counts as parked when the tracked quantities sit within this many
# torso-lengths of their median. Same band the set/hold gate in classify.py
# uses, so the two agree about what "still" means.
BAND = 0.20
# A gap in the parked run shorter than this is bridged: a wobble, a frame the
# estimator lost, not the end of the hold.
MAX_GAP_S = 0.4
# Below this a hold is not reported as one. A couple of seconds still is a
# pause between attempts, not a position being held.
MIN_HOLD_S = 3.0
# ...and the held stretch has to be a real share of the time spent in the
# position's family (hands above or below the shoulders). A 10-second clip of
# jump-to-bar attempts contains a 2.6-second dead hang between them, and
# calling that clip "a dead hang" would be true of a quarter of it and wrong
# about the session. The walk to the bar is not in the family and does not
# dilute a real hold.
MIN_HOLD_SHARE = 0.40
# Ankles this far above the hips (torso-lengths) while the torso is level
# means the legs point up, not out: the body is folded, not in a lever.
LEGS_UP = 0.40

# Body pointing more than this far from vertical is horizontal: a lever or a
# plank rather than a hang or a handstand.
HORIZONTAL_DEG = 55.0
VERTICAL_DEG = 40.0
# Hips this far above the shoulders (torso-lengths, +up) means inverted.
INVERTED = 0.30
# Shoulders this far below the hands means the arms are long: a dead hang.
LONG_ARMS = -0.60
# Knees closer than this to the hips means tucked.
TUCK = 0.60
# Nose this far above (below) the shoulders decides front (back) lever.
FACE = 0.05
# Ankles reaching this far out horizontally from the hips, at hip height,
# is an L.
L_REACH = 0.70

HUMAN = {
    "dead_hang": "Dead hang",
    "flexed_hang": "Flexed-arm hang",
    "inverted_hang": "Inverted hang",
    "front_lever": "Front lever",
    "back_lever": "Back lever",
    "lever": "Lever",
    "tuck_front_lever": "Tuck front lever",
    "tuck_back_lever": "Tuck back lever",
    "tuck_lever": "Tuck lever",
    "handstand": "Handstand",
    "plank": "Plank",
    "l_sit": "L-sit",
    "support_hold": "Support hold",
    "hold": "Static hold",
}

# Where each hold sits in the skill graph (barra/skills.py), when it does.
# The handstand is deliberately not mapped to one of the two graph entries:
# the camera cannot tell a chest-to-wall handstand from a freestanding one
# unless the wall is in shot, and it is not asked to.
SKILL = {
    "dead_hang": "dead_hang",
    "front_lever": "front_lever",
    "back_lever": "back_lever",
    "tuck_front_lever": "tuck_front_lever",
    "tuck_back_lever": "tuck_back_lever",
    "plank": "plank",
    "l_sit": "l_sit",
    "inverted_hang": "skin_the_cat",
}


@dataclass
class Hold:
    exercise: str
    confidence: float
    reason: str
    seconds: float
    start_s: float
    end_s: float
    features: dict = field(default_factory=dict)
    runner_up: str | None = None

    @property
    def label(self) -> str:
        return HUMAN.get(self.exercise, "Static hold")

    @property
    def skill(self) -> str | None:
        return SKILL.get(self.exercise)

    def as_dict(self) -> dict:
        return {
            "exercise": self.exercise,
            "label": self.label,
            "skill": self.skill,
            "confidence": round(float(self.confidence), 2),
            "reason": self.reason,
            "seconds": round(float(self.seconds), 1),
            "startS": round(float(self.start_s), 2),
            "endS": round(float(self.end_s), 2),
            "runnerUp": self.runner_up,
        }


def _nanmedian(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")


def longest_parked_run(series: list[np.ndarray], fps: float,
                       band: float = BAND, max_gap_s: float = MAX_GAP_S,
                       mask: np.ndarray | None = None) -> tuple[int, int]:
    """The longest stretch of frames in which every series stays within
    `band` of its own median, bridging gaps shorter than `max_gap_s`.

    Frames where a series was not measured neither break nor extend the run:
    an unseen landmark is not evidence of movement, and it is not evidence of
    stillness either. Frames outside `mask` are never parked: standing next
    to the bar before a hang is perfectly still, and is not the hang.
    Returns (first, last) frame, or (-1, -1) when nothing was parked at all.
    """
    n = len(series[0]) if series else 0
    if n == 0:
        return -1, -1
    parked = np.ones(n, dtype=bool)
    seen = np.zeros(n, dtype=bool)
    for a in series:
        ok = np.isfinite(a)
        if mask is not None:
            ok = ok & mask
        if ok.sum() < 6:
            continue
        med = np.median(a[ok])
        parked &= ~ok | (np.abs(a - med) <= band)
        seen |= ok
    parked &= seen
    if mask is not None:
        parked &= mask
    gap = int(round(max_gap_s * fps))
    best = (-1, -1)
    start = None
    last_true = None
    for i, p in enumerate(parked):
        if p:
            if start is None:
                start = i
            last_true = i
        elif start is not None and i - last_true > gap:
            if last_true - start > best[1] - best[0]:
                best = (start, last_true)
            start = None
    if start is not None and last_true is not None and last_true - start > best[1] - best[0]:
        best = (start, last_true)
    return best


def features(kp: np.ndarray, fps: float = 30.0, family: str | None = None) -> dict:
    """Body geometry over the parked stretch, in torso-lengths, +up.

    `family` is "hanging" (hands above the shoulders) or "support" (hands
    below them), when the caller has already established which. The parked
    stretch is then searched only in frames of that family, so the still
    seconds spent standing beside the bar cannot be reported as the hold.
    """
    torso = robust_torso(kp)

    def pt(a, b):
        return midpoint(kp, a, b), pair_confidence(kp, a, b) >= MIN_CONF

    wrist, w_ok = pt("left_wrist", "right_wrist")
    shoulder, s_ok = pt("left_shoulder", "right_shoulder")
    hip, h_ok = pt("left_hip", "right_hip")
    knee, k_ok = pt("left_knee", "right_knee")
    ankle, a_ok = pt("left_ankle", "right_ankle")
    nose = kp[:, S.KP_INDEX["nose"], :2]
    n_ok = kp[:, S.KP_INDEX["nose"], 2] >= MIN_CONF

    def rel(up, lo, ok):
        # image y grows downward: (lo_y - up_y) is positive when `up` is above
        return np.where(ok, (lo[:, 1] - up[:, 1]) / torso, np.nan)

    shoulder_above_hands = rel(shoulder, wrist, w_ok & s_ok)
    hip_above_shoulder = rel(hip, shoulder, h_ok & s_ok)
    ankle_above_hip = rel(ankle, hip, a_ok & h_ok)
    knee_above_hip = rel(knee, hip, k_ok & h_ok)
    nose_above_shoulder = rel(nose, shoulder, n_ok & s_ok)

    dx = np.abs(shoulder[:, 0] - hip[:, 0])
    dy = np.abs(shoulder[:, 1] - hip[:, 1])
    tilt = np.where(s_ok & h_ok,
                    np.degrees(np.arctan2(dx, np.maximum(dy, 1e-6))), np.nan)
    knee_dist = np.where(k_ok & h_ok,
                         np.linalg.norm(knee - hip, axis=1) / torso, np.nan)
    ankle_reach = np.where(a_ok & h_ok, np.abs(ankle[:, 0] - hip[:, 0]) / torso, np.nan)

    # Frames where the hands were not seen are neutral - not in the family,
    # not out of it - so a wrist the estimator loses for a second inside a
    # hold does not cut the hold in two.
    mask = None
    measured = np.isfinite(shoulder_above_hands)
    if family == "hanging":
        mask = ~measured | (shoulder_above_hands < -0.05)
    elif family == "support":
        mask = ~measured | (shoulder_above_hands > 0.05)
    family_s = float((mask & measured).sum() / (fps or 30.0)) if mask is not None \
        else float(measured.sum() / (fps or 30.0))
    first, last = longest_parked_run(
        [shoulder_above_hands, hip_above_shoulder, knee_above_hip], fps, mask=mask)
    if first < 0:
        window = slice(0, len(kp))
        seconds = 0.0
    else:
        window = slice(first, last + 1)
        seconds = (last - first + 1) / (fps or 30.0)

    def med(a):
        return _nanmedian(a[window])

    return {
        "torso_px": float(torso),
        "held_s": float(seconds),
        "held_from_s": float(first / (fps or 30.0)) if first >= 0 else float("nan"),
        "held_to_s": float((last + 1) / (fps or 30.0)) if first >= 0 else float("nan"),
        "clip_s": float(len(kp) / (fps or 30.0)),
        # Time spent with the hands where this family of hold needs them. The
        # held stretch is judged against this, not against the whole clip, so
        # the walk to the bar does not dilute a hold and a set of attempts
        # around a short hang does.
        "family_s": family_s,
        "shoulder_above_hands": med(shoulder_above_hands),
        "hip_above_shoulder": med(hip_above_shoulder),
        "ankle_above_hip": med(ankle_above_hip),
        "knee_above_hip": med(knee_above_hip),
        "nose_above_shoulder": med(nose_above_shoulder),
        "tilt_deg": med(tilt),
        "knee_dist": med(knee_dist),
        "ankle_reach": med(ankle_reach),
        "wrist_seen": float(w_ok.mean()),
        "ankle_seen": float(a_ok.mean()),
        "nose_seen": float(n_ok.mean()),
    }


def _finite(x: float) -> bool:
    return bool(np.isfinite(x))


def classify_hold(kp: np.ndarray, fps: float = 30.0, trace=None,
                  family: str | None = None) -> Hold | None:
    """Name the position being held, or None when the clip was not held long
    enough to call a hold at all.

    Called by classify() once it has established that the hands are on
    something fixed and the body is parked. It does not re-check either: the
    gate is the caller's, this is the vocabulary.
    """
    f = features(kp, fps, family)
    if trace is not None:
        trace.step("hold geometry", family=family, **f)
    share = min(1.0, f["held_s"] / f["family_s"]) if f["family_s"] > 0 else 0.0
    if f["held_s"] < MIN_HOLD_S or share < MIN_HOLD_SHARE:
        if trace is not None:
            trace.reject("hold", "not held long enough, or for enough of the clip, "
                         "to be the position the clip shows",
                         held_s=f["held_s"], min_hold_s=MIN_HOLD_S,
                         held_share=share, min_share=MIN_HOLD_SHARE)
        return None

    above = f["shoulder_above_hands"]
    inverted = f["hip_above_shoulder"]
    tilt = f["tilt_deg"]
    face = f["nose_above_shoulder"]
    tucked = _finite(f["knee_dist"]) and f["knee_dist"] < TUCK

    def out(exercise, confidence, reason, runner_up=None):
        if trace is not None:
            trace.decision(exercise, reason, confidence=confidence,
                           held_s=f["held_s"], tilt_deg=tilt,
                           hip_above_shoulder=inverted,
                           shoulder_above_hands=above)
        return Hold(exercise, confidence, reason, f["held_s"],
                    f["held_from_s"], f["held_to_s"], f, runner_up)

    if not _finite(above):
        return out("hold", 0.40,
                   "the body stays parked on something fixed, but the hands "
                   "and shoulders were not both seen well enough to say which "
                   "position it is")

    hanging = above < -0.05
    horizontal = _finite(tilt) and tilt >= HORIZONTAL_DEG
    vertical = _finite(tilt) and tilt <= VERTICAL_DEG
    hips_up = _finite(inverted) and inverted >= INVERTED

    if hanging:
        legs_up = _finite(f["ankle_above_hip"]) and f["ankle_above_hip"] >= LEGS_UP
        if horizontal and legs_up:
            # The torso reads level but the legs point at the ceiling: the body
            # is folded at the hips, upside down - the sample clip's inverted
            # hold, whose torso the estimator flattened to 6 degrees while
            # putting the ankles 1.75 torso-lengths above the hips.
            return out(
                "inverted_hang", 0.75,
                f"hanging with the torso {tilt:.0f} degrees from vertical but "
                f"the ankles {f['ankle_above_hip']:.2f} torso-lengths above the "
                "hips - the body is folded and upside down, not laid out level",
                runner_up="tuck_front_lever",
            )
        if horizontal:
            base = "tuck_" if tucked else ""
            if _finite(face) and abs(face) >= FACE:
                front = face > 0
                kind = base + ("front_lever" if front else "back_lever")
                other = base + ("back_lever" if front else "front_lever")
                margin = min(1.0, (abs(face) - FACE) / 0.20)
                return out(
                    kind, 0.55 + 0.20 * margin,
                    f"hanging with the body {tilt:.0f} degrees from vertical - "
                    f"a lever - and the nose {abs(face):.2f} torso-lengths "
                    f"{'above' if front else 'below'} the shoulders, so the "
                    f"face points {'up' if front else 'down'}"
                    + (", knees tucked to the hips" if tucked else ""),
                    runner_up=other,
                )
            return out(
                base + "lever", 0.50,
                f"hanging with the body {tilt:.0f} degrees from vertical - a "
                "lever - but which way the face points was not seen, so front "
                "or back is not decided"
                + (", knees tucked to the hips" if tucked else ""),
                runner_up=base + "front_lever",
            )
        if hips_up:
            return out(
                "inverted_hang", 0.80,
                f"hanging from something fixed with the hips {inverted:.2f} "
                "torso-lengths above the shoulders - upside down",
                runner_up="back_lever",
            )
        if above <= LONG_ARMS:
            return out(
                "dead_hang", 0.80,
                f"hanging with the shoulders {-above:.2f} torso-lengths below "
                "the hands - arms long - and the body still",
                runner_up="flexed_hang",
            )
        return out(
            "flexed_hang", 0.70,
            f"hanging with the shoulders only {-above:.2f} torso-lengths below "
            "the hands, so the arms are bent and the body is held up the bar",
            runner_up="dead_hang",
        )

    # Supporting: the hands are below the shoulders.
    if hips_up and vertical:
        return out(
            "handstand", 0.80,
            f"on the hands with the hips {inverted:.2f} torso-lengths above "
            f"the shoulders and the body {tilt:.0f} degrees from vertical",
            runner_up="plank",
        )
    if horizontal:
        return out(
            "plank", 0.75,
            f"on the hands with the body {tilt:.0f} degrees from vertical and "
            "held level",
            runner_up="support_hold",
        )
    reach = f["ankle_reach"]
    legs_level = _finite(f["ankle_above_hip"]) and abs(f["ankle_above_hip"]) < 0.35
    if vertical and _finite(reach) and reach >= L_REACH and legs_level:
        return out(
            "l_sit", 0.70,
            f"torso upright on the hands with the ankles {reach:.2f} "
            "torso-lengths out from the hips at hip height - the legs make an L",
            runner_up="support_hold",
        )
    if vertical and _finite(f["ankle_above_hip"]) and f["ankle_above_hip"] < -0.6:
        return out(
            "support_hold", 0.65,
            "torso upright on the hands with the legs hanging below - a "
            "support on bars",
            runner_up="l_sit",
        )
    return out(
        "hold", 0.40,
        f"parked on something fixed, body {tilt:.0f} degrees from vertical, "
        "but not in a position barra has a name for",
    )
