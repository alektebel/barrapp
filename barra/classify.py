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
from .trace import NullTrace, Trace

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
# ...but measured over a WINDOW, not the whole clip. People walk to the bar and
# walk away again, and a percentile spread over the whole video charges that
# approach against the set: one real 40-second clip put its wrists 2.99
# torso-lengths apart end to end while the actual reps never moved them past
# 0.02. The question a classifier can answer before trimming has happened is
# not "were the hands fixed throughout" but "was there a stretch long enough to
# hold a set in which they were", so that is the question asked. Whether any
# particular candidate rep is anchored is still decided per rep, by the
# segmenter, which is where walking is actually rejected.
ANCHOR_WINDOW_S = 3.0
# A landmark seen in fewer than this fraction of a window is not measured well
# enough there to conclude anything from it.
MIN_SEEN = 0.40
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


def _best_window(points: np.ndarray, ok: np.ndarray, torso: float,
                 win: int, step: int = 5) -> tuple[float, float, int, int]:
    """The least-travelled window of `win` frames in which the landmark was
    actually visible: (travel, seen fraction, first frame, last frame).

    Returns the whole clip when it is shorter than a window, and infinite
    travel when no window was seen well enough to measure - which is a
    different failure from "it moved too much", and the caller reports it as
    one.
    """
    n = len(points)
    if n <= win:
        return _travel(points, ok, torso), float(ok.mean()), 0, max(0, n - 1)
    best = (float("inf"), 0.0, 0, win - 1)
    for a in range(0, n - win + 1, step):
        b = a + win
        seen = float(ok[a:b].mean())
        if seen < MIN_SEEN:
            continue
        t = _travel(points[a:b], ok[a:b], torso)
        if t < best[0]:
            best = (t, seen, a, b - 1)
    return best


def features(kp: np.ndarray, fps: float = 30.0) -> dict:
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

    win = int(max(15, min(len(kp), round(ANCHOR_WINDOW_S * (fps or 30.0)))))
    w_win = _best_window(wrist, w_ok, torso, win)
    a_win = _best_window(ankle, a_ok, torso, win)

    return {
        "n_frames": int(len(kp)),
        "fps": float(fps or 30.0),
        "window_frames": win,
        "wrist_seen": float(w_ok.mean()),
        "ankle_seen": float(a_ok.mean()),
        # Whole-clip spans, kept because they are what a human sees in the
        # video; the windowed values below are what the gates actually use.
        "wrist_travel": _travel(wrist, w_ok, torso),
        "ankle_travel": _travel(ankle, a_ok, torso),
        "wrist_window_travel": w_win[0],
        "wrist_window_seen": w_win[1],
        "wrist_window_s": [round(w_win[2] / (fps or 30.0), 2),
                           round(w_win[3] / (fps or 30.0), 2)],
        "ankle_window_travel": a_win[0],
        "ankle_window_seen": a_win[1],
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


def _why_not(kind: str, travel: float, seen: float) -> str:
    """Name the condition that actually failed.

    Worth the few lines: the previous message said "hands not fixed" whatever
    went wrong, and on a real clip it printed that verdict directly above a
    wrist travel of 0.27 against a threshold of 0.80 - a trace contradicting
    its own evidence, which is worse than no trace, because it sends you to
    read the wrong code.
    """
    if not np.isfinite(travel) or seen < MIN_SEEN:
        return f"the {kind} were never seen clearly enough for long enough"
    return f"the {kind} moved {travel:.2f} torso-lengths, past {ANCHOR_FIXED}"


def classify(kp: np.ndarray, trace: Trace | None = None,
             fps: float = 30.0) -> Classification:
    """Decide the movement, or say the clip does not show one we know.

    Order matters. Hanging is checked first because it is the most specific
    shape; then the squat, because "the hands did not move much" is NOT enough
    on its own to mean the hands were on something - arms hanging at the sides
    of a torso that is squatting move roughly as far as the hips do, and an
    anchor test alone reads that as a dip. What separates them is whether the
    shoulders move relative to the hands at all.
    """
    tr = trace or NullTrace()
    tr.stage("classify")
    f = features(kp, fps)
    anchored = (f["wrist_window_travel"] <= ANCHOR_FIXED
                and f["wrist_window_seen"] >= MIN_SEEN)
    articulated = np.isfinite(f["arm_articulation"]) and f["arm_articulation"] >= ARTICULATION
    planted = (f["ankle_window_travel"] <= ANCHOR_FIXED
               and f["ankle_window_seen"] >= MIN_SEEN)
    tr.step("geometry measured", **f)
    # The three tests every branch below is built from, each with the number and
    # the threshold it was compared against - and, for the two windowed ones,
    # the stretch of clip the number came from, so the frame can be found.
    tr.step(
        "gates",
        anchored=anchored, wrist_window_travel=f["wrist_window_travel"],
        wrist_window_seen=f["wrist_window_seen"], wrist_window_s=f["wrist_window_s"],
        wrist_travel_whole_clip=f["wrist_travel"],
        anchor_max=ANCHOR_FIXED, seen_min=MIN_SEEN,
        articulated=articulated, arm_articulation=f["arm_articulation"],
        articulation_min=ARTICULATION,
        planted=planted, ankle_window_travel=f["ankle_window_travel"],
        ankle_window_seen=f["ankle_window_seen"],
    )

    if anchored and articulated and f["hands_overhead_frac"] >= 0.35:
        peak = f["shoulder_above_hands_p95"]
        if peak >= OVER_BAR:
            margin = min(1.0, (peak - OVER_BAR) / 0.35)
            tr.decision("muscle_up", "the shoulders finish above the hands",
                        peak_above_hands=peak, over_bar_threshold=OVER_BAR,
                        confidence=0.70 + 0.28 * margin)
            return Classification(
                "muscle_up", 0.70 + 0.28 * margin,
                f"hanging from a fixed bar, and the shoulders finish {peak:.2f} "
                "torso-lengths above the hands",
                f, runner_up="pull_up",
            )
        margin = min(1.0, (OVER_BAR - peak) / 0.35)
        tr.decision("pull_up", "the shoulders never rise above the hands",
                    peak_above_hands=peak, over_bar_threshold=OVER_BAR,
                    confidence=0.70 + 0.25 * margin)
        return Classification(
            "pull_up", 0.70 + 0.25 * margin,
            f"hanging from a fixed bar, and the shoulders never rise above the "
            f"hands (peak {peak:+.2f} torso-lengths)",
            f, runner_up="muscle_up",
        )

    if planted and not articulated and np.isfinite(f["hip_travel"]) and f["hip_travel"] >= 0.35:
        tr.decision("squat", "feet planted, hips travelling, arms rigid to the torso",
                    hip_travel=f["hip_travel"], hip_travel_min=0.35,
                    ankle_travel=f["ankle_travel"])
        return Classification(
            "squat", 0.78,
            f"feet stayed put, the hips moved through {f['hip_travel']:.2f} "
            "torso-lengths, and the arms did not move relative to the torso",
            f, runner_up=None,
        )

    if anchored and articulated and f["hands_below_frac"] >= 0.80:
        below = f["body_below_hands"]
        if not np.isfinite(below):
            tr.reject("dip/push-up", "too little of the body was seen to tell them apart",
                      body_below_hands=below)
            return Classification(
                "unknown", 0.0,
                "hands fixed below the shoulders, but too little of the body was "
                "seen to tell a dip from a push-up",
                f,
            )
        if below >= BELOW_HANDS_DIP:
            tr.decision("dip", "the legs hang below the hands",
                        body_below_hands=below, dip_threshold=BELOW_HANDS_DIP)
            return Classification(
                "dip", 0.78,
                f"hands fixed below the shoulders, with {below:.0%} of the body "
                "hanging below them - the legs are off the ground",
                f, runner_up="push_up",
            )
        tr.decision("push_up", "nothing hangs below the hands, so they are on the floor",
                    body_below_hands=below, dip_threshold=BELOW_HANDS_DIP)
        return Classification(
            "push_up", 0.78,
            "hands fixed below the shoulders and nothing hanging below them, so "
            "the hands are on the floor rather than on bars",
            f, runner_up="dip",
        )

    if not anchored and not planted:
        hands = _why_not("hands", f["wrist_window_travel"], f["wrist_window_seen"])
        feet = _why_not("feet", f["ankle_window_travel"], f["ankle_window_seen"])
        tr.reject("any movement", f"{hands}, and {feet}",
                  wrist_window_travel=f["wrist_window_travel"],
                  wrist_window_seen=f["wrist_window_seen"],
                  ankle_window_travel=f["ankle_window_travel"],
                  ankle_window_seen=f["ankle_window_seen"],
                  anchor_max=ANCHOR_FIXED, seen_min=MIN_SEEN,
                  window_s=ANCHOR_WINDOW_S)
        return Classification(
            "unknown", 0.0,
            f"no {ANCHOR_WINDOW_S:.0f}-second stretch of this clip shows hands on "
            f"something fixed or feet planted ({hands}, and {feet}), so it does "
            "not show a movement barra can measure",
            f,
        )
    tr.reject("any movement", "no branch matched",
              anchored=anchored, articulated=articulated, planted=planted,
              hands_overhead_frac=f["hands_overhead_frac"],
              hands_below_frac=f["hands_below_frac"])
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
