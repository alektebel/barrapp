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
# Knees held this far above the hips (torso-lengths) means the legs are being
# raised, not hanging. Measured on real clips the gap is wide and unambiguous:
# hanging legs sit at -0.33 to -0.69, a knee raise at +0.54.
KNEES_UP = 0.10
# A hold is a clip that sits still, not one that moves a short distance. Total
# range cannot tell the two apart - a 23-second inverted hold and a deliberately
# shallow pull-up both swept about 0.65 torso-lengths - but time spent parked
# can: the hold stays within this band of its own median for most of the clip,
# while a set keeps leaving it.
#
# Measured: 0.62 for the real hold against 0.49 for a hanging knee raise, 0.37
# for a shallow pull-up and 0.04-0.16 for the muscle-up sets. The gap above the
# knee raise is not large, and the threshold sits in it deliberately close to
# the hold: a clip wrongly called a hold reports "not measurable", while a hold
# wrongly accepted invents repetitions out of drift. Those costs are not equal.
HOLD_BAND = 0.20
HOLD_FRAC = 0.55


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


def _parked(a: np.ndarray) -> float:
    """Fraction of observed frames sitting within HOLD_BAND of the median."""
    a = a[np.isfinite(a)]
    if a.size < 6:
        return 0.0
    return float(np.mean(np.abs(a - np.median(a)) <= HOLD_BAND))


def _angle(pts: np.ndarray, a: int, b: int, c: int, ok: np.ndarray,
           min_conf: float = MIN_CONF) -> np.ndarray:
    """Interior angle at joint b (degrees), 180 = fully extended.

    Used for the lever/planche straight-arm and straight-leg checks, and for
    the pistol's bent supporting knee. Points are raw (T,17,3) keypoints.

    `ok` is a per-FRAME mask. It used to be indexed with the three KEYPOINT
    indices - ok[a] & ok[b] & ok[c] - which reads three arbitrary frames and
    broadcasts their conjunction over the whole clip: one unconfident frame
    numbered 5, 7 or 9 turned every elbow angle in the clip into NaN, and
    otherwise the mask waved through frames where the joint was never seen.
    The three joints are now masked by their own confidence, per frame, which
    is what min_conf was always there to do.
    """
    pa, pb, pc = pts[:, a, :2], pts[:, b, :2], pts[:, c, :2]
    v1 = pa - pb
    v2 = pc - pb
    denom = np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cosang = np.where(denom > 1e-6,
                          np.clip(np.sum(v1 * v2, axis=1) / denom, -1.0, 1.0), 0.0)
    deg = np.degrees(np.arccos(cosang))
    seen = (np.asarray(ok, dtype=bool)
            & (pts[:, a, 2] >= min_conf)
            & (pts[:, b, 2] >= min_conf)
            & (pts[:, c, 2] >= min_conf))
    return np.where(seen, deg, np.nan)


def _frac(a: np.ndarray, thresh: float) -> float:
    """Fraction of observed frames at or above a threshold, NaN-safe."""
    a = a[np.isfinite(a)]
    return float(np.mean(a >= thresh)) if a.size else float("nan")


def _pct(a: np.ndarray, q: float) -> float:
    a = a[np.isfinite(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")


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

    # Where the knees are relative to the hips, and how far they travel. In
    # every bar movement that pulls the body up, the legs hang: the knees sit
    # well below the hips throughout. In a hanging knee raise they come up
    # above them, which is the movement's whole definition.
    knee = midpoint(kp, "left_knee", "right_knee")
    k_ok = pair_confidence(kp, "left_knee", "right_knee") >= MIN_CONF
    knee_over_hip = np.where(k_ok & h_ok, (hip[:, 1] - knee[:, 1]) / torso, np.nan)
    hip_over_hands = np.where(w_ok & h_ok, (wrist[:, 1] - hip[:, 1]) / torso, np.nan)

    win = int(max(15, min(len(kp), round(ANCHOR_WINDOW_S * (fps or 30.0)))))
    w_win = _best_window(wrist, w_ok, torso, win)
    a_win = _best_window(ankle, a_ok, torso, win)

    # ---- progression geometry: the isometric tracks and the pistol ---------
    # Body line: the shoulder-hip line's angle from vertical, in degrees.
    # 0 = hanging vertical, 90 = horizontal. A front lever or planche is a
    # body held horizontal, so this is what separates them from a pull-up or
    # a squat, which are vertical.
    body = np.where(
        s_ok & h_ok,
        np.degrees(np.arctan2(np.abs(shoulder[:, 0] - hip[:, 0]),
                              np.maximum(np.abs(shoulder[:, 1] - hip[:, 1]), 1e-6))),
        np.nan,
    )
    body_line_deg = _pct(body, 50)
    horizontal_frac = _frac(body, 70.0)

    # Straight arm / straight leg, 180 = fully extended. A lever or planche is
    # held on straight arms with a straight body line; bent elbows are the
    # first failure to look for.
    elbow_l = _angle(kp, S.KP_INDEX["left_shoulder"], S.KP_INDEX["left_elbow"],
                     S.KP_INDEX["left_wrist"], s_ok & w_ok)
    elbow_r = _angle(kp, S.KP_INDEX["right_shoulder"], S.KP_INDEX["right_elbow"],
                     S.KP_INDEX["right_wrist"], s_ok & w_ok)
    arms_straight_frac = _frac(np.concatenate([elbow_l, elbow_r]), 160.0)

    knee_l = _angle(kp, S.KP_INDEX["left_hip"], S.KP_INDEX["left_knee"],
                    S.KP_INDEX["left_ankle"], h_ok & a_ok)
    knee_r = _angle(kp, S.KP_INDEX["right_hip"], S.KP_INDEX["right_knee"],
                    S.KP_INDEX["right_ankle"], h_ok & a_ok)
    legs_straight_frac = _frac(np.concatenate([knee_l, knee_r]), 160.0)

    # Legs lifted off the ground: ankle at or above hip height. In a push-up
    # the ankles are below the hips (feet on the floor); in a planche the legs
    # are carried horizontal, so the ankles rise to hip level. image y grows
    # down, so ankle_y <= hip_y means the ankle is at/above the hip.
    ankle_over_hip = np.where(
        a_ok & h_ok, (hip[:, 1] - ankle[:, 1]) / torso, np.nan)
    legs_lifted_frac = _frac(ankle_over_hip, -0.05)

    # Single-leg stance (the pistol): one ankle planted under the hip, the
    # other carried forward at hip height. The planted leg's ankle sits below
    # the hip; the free leg's ankle sits well forward and near hip height.
    # When only one side is confidently seen the planted one is the one whose
    # ankle is lowest; a two-legged squat keeps BOTH ankles below the hips.
    l_ankle_below = _pct((hip[:, 1] - kp[:, S.KP_INDEX["left_ankle"], 1]) / torso, 5)
    r_ankle_below = _pct((hip[:, 1] - kp[:, S.KP_INDEX["right_ankle"], 1]) / torso, 5)
    l_ok_s = kp[:, S.KP_INDEX["left_ankle"], 2] >= MIN_CONF
    r_ok_s = kp[:, S.KP_INDEX["right_ankle"], 2] >= MIN_CONF
    one_side_planted = bool(l_ok_s.mean() >= 0.5 or r_ok_s.mean() >= 0.5)
    # The planted side is the one with the ankle lowest; the free side's ankle
    # is carried forward. A pistol has exactly one low ankle.
    l_low = l_ankle_below > 0.05 if np.isfinite(l_ankle_below) else False
    r_low = r_ankle_below > 0.05 if np.isfinite(r_ankle_below) else False
    single_leg_stance = bool(one_side_planted and (l_low != r_low))

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
        # Fraction of the clip spent within HOLD_BAND of one position, taken
        # on whichever of the shoulders or knees moves LEAST relative to the
        # hands. Both have to be parked for the clip to be a hold: in a knee
        # raise the shoulders barely move, and judging on them alone would call
        # every knee raise a hold.
        "parked_frac": min([_parked(a) for a in (above, knee_over_hip)
                            if np.isfinite(a).sum() >= 6] or [0.0]),
        "knee_over_hip": float(np.nanmedian(knee_over_hip))
        if np.isfinite(knee_over_hip).any() else float("nan"),
        "knee_excursion": pct(knee_over_hip, 95) - pct(knee_over_hip, 5),
        "hip_articulation": pct(hip_over_hands, 95) - pct(hip_over_hands, 5),
        # progression / isometric geometry
        "body_line_deg": body_line_deg,
        "horizontal_frac": horizontal_frac,
        "arms_straight_frac": arms_straight_frac,
        "legs_straight_frac": legs_straight_frac,
        "legs_lifted_frac": legs_lifted_frac,
        "single_leg_stance": single_leg_stance,
        "l_ankle_below": l_ankle_below,
        "r_ankle_below": r_ankle_below,
    }


# Below this the landmark is missing for most of the clip, and whatever travel
# was measured describes the minority of frames it happened to appear in -
# usually the ones where the athlete is NOT on the bar, which is exactly when a
# hand is easiest to see and least informative.
MOSTLY_UNSEEN = 0.50


def _why_not(kind: str, travel: float, seen: float, seen_clip: float = 1.0) -> str:
    """Name the condition that actually failed.

    Worth the few lines: the previous message said "hands not fixed" whatever
    went wrong, and on a real clip it printed that verdict directly above a
    wrist travel of 0.27 against a threshold of 0.80 - a trace contradicting
    its own evidence, which is worse than no trace, because it sends you to
    read the wrong code.
    """
    if not np.isfinite(travel) or seen < MIN_SEEN:
        return f"the {kind} were never seen clearly enough for long enough"
    if seen_clip < MOSTLY_UNSEEN:
        # Report the cause, not the symptom. On one real clip the hands sat
        # above the top edge of the frame for the whole hang, so they were
        # tracked in 31% of it - and almost only while the athlete stood on the
        # ground either side of the set. The resulting 3.1 torso-lengths of
        # "hand travel" is real arithmetic about the wrong frames, and telling
        # the athlete their hands moved too much sends them to fix the wrong
        # thing. What they can act on is the framing.
        return (f"the {kind} were only tracked in {seen_clip:.0%} of the clip - "
                f"they are out of frame for most of it")
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
    # Three-valued on purpose. "Not articulated" and "we could not see the arms
    # well enough to say" are different facts, and collapsing them into one
    # boolean is how a muscle-up filmed side-on came out as a squat: the far
    # arm was occluded, arm_articulation was NaN, and `not articulated` read
    # that NaN as positive evidence that the arms had stayed still. A branch
    # must never be satisfied by a measurement that was never taken.
    arms_measured = bool(np.isfinite(f["arm_articulation"]))
    articulated = arms_measured and f["arm_articulation"] >= ARTICULATION
    rigid_arms = arms_measured and f["arm_articulation"] < ARTICULATION
    planted = (f["ankle_window_travel"] <= ANCHOR_FIXED
               and f["ankle_window_seen"] >= MIN_SEEN)
    parked = f["parked_frac"]
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
        arms_measured=arms_measured, parked_frac=parked, parked_max=HOLD_FRAC,
    )

    # --- the isometric tracks. A front lever and a planche ARE holds, so the
    # hold-rejection below must not swallow them - they are checked first.
    # A front lever is a hang held horizontal (hands overhead, body line near
    # horizontal). A planche is the same body line pressed off the ground
    # (hands below the shoulders, legs carried up).
    if (anchored and f["hands_overhead_frac"] >= 0.35
            and np.isfinite(f["body_line_deg"]) and f["body_line_deg"] >= 70.0):
        tr.decision("front_lever", "hanging from a fixed bar, body held horizontal",
                    body_line_deg=f["body_line_deg"], horizontal_min=70.0,
                    arms_straight_frac=f["arms_straight_frac"],
                    legs_straight_frac=f["legs_straight_frac"], confidence=0.72)
        return Classification(
            "front_lever", 0.72,
            f"hanging from a fixed bar with the body held "
            f"{f['body_line_deg']:.0f} degrees from vertical - a front lever",
            f, runner_up="pull_up",
        )

    if (anchored and f["hands_below_frac"] >= 0.80
            and np.isfinite(f["body_line_deg"]) and f["body_line_deg"] >= 70.0
            and np.isfinite(f["legs_lifted_frac"]) and f["legs_lifted_frac"] >= 0.5):
        tr.decision("planche", "body horizontal on straight arms, legs off the ground",
                    body_line_deg=f["body_line_deg"], horizontal_min=70.0,
                    legs_lifted_frac=f["legs_lifted_frac"], confidence=0.72)
        return Classification(
            "planche", 0.72,
            f"body held {f['body_line_deg']:.0f} degrees from vertical on the "
            f"hands with the legs carried up off the ground - a planche",
            f, runner_up="push_up",
        )

    # A hold is not a set. Checked before anything else, because the branches
    # below ask *which* movement this is and cannot notice that nothing
    # happened: a 23-second inverted hold has hands as fixed as any bar
    # movement and shoulders that drift just enough to look articulated, and
    # was duly reported as a pull-up with two reps invented out of the drift.
    if anchored and f["hands_overhead_frac"] >= 0.35 and parked >= HOLD_FRAC:
        tr.reject("any movement", "the body stays parked - a hold or a rest, not a set",
                  parked_frac=parked, parked_max=HOLD_FRAC, band=HOLD_BAND,
                  arm_articulation=f["arm_articulation"],
                  knee_excursion=f["knee_excursion"])
        return Classification(
            "unknown", 0.0,
            f"hanging from something fixed, but {parked:.0%} of the clip is spent "
            "within a fifth of a torso-length of one position - a hold, or "
            "resting between attempts, rather than a set of repetitions",
            f,
        )

    # Hanging, but with the legs coming up rather than the body. Checked before
    # the pull-up split because a knee raise satisfies every condition of that
    # split except the one that matters, and would otherwise be reported as a
    # pull-up whose shoulders happen never to reach the bar.
    if (anchored and f["hands_overhead_frac"] >= 0.35
            and np.isfinite(f["knee_over_hip"]) and f["knee_over_hip"] >= KNEES_UP
            and f["knee_excursion"] >= f["arm_articulation"]):
        tr.decision("knee_raise", "the knees are carried above the hips, and travel "
                    "further than the shoulders do",
                    knee_over_hip=f["knee_over_hip"], knees_up_threshold=KNEES_UP,
                    knee_excursion=f["knee_excursion"],
                    arm_articulation=f["arm_articulation"], confidence=0.80)
        return Classification(
            "knee_raise", 0.80,
            f"hanging from a fixed bar with the knees carried "
            f"{f['knee_over_hip']:.2f} torso-lengths above the hips and "
            "travelling further than the shoulders - the legs are doing the work",
            f, runner_up="pull_up",
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

    # A pistol is a single-leg squat: one ankle planted under the hips, the
    # other carried forward. Checked before the squat branch because a pistol
    # satisfies every squat condition except the one that matters - there is
    # one low ankle, not two.
    if planted and f["single_leg_stance"] and np.isfinite(f["hip_travel"])             and f["hip_travel"] >= 0.35:
        tr.decision("pistol_squat", "one foot planted, the other carried forward",
                    hip_travel=f["hip_travel"], hip_travel_min=0.35,
                    l_ankle_below=f["l_ankle_below"], r_ankle_below=f["r_ankle_below"],
                    confidence=0.74)
        return Classification(
            "pistol_squat", 0.74,
            "one foot stayed planted and the other leg was carried forward while "
            f"the hips moved through {f['hip_travel']:.2f} torso-lengths - a "
            "single-leg squat",
            f, runner_up="squat",
        )

    if planted and rigid_arms and np.isfinite(f["hip_travel"]) and f["hip_travel"] >= 0.35:
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
        hands = _why_not("hands", f["wrist_window_travel"], f["wrist_window_seen"],
                         f["wrist_seen"])
        feet = _why_not("feet", f["ankle_window_travel"], f["ankle_window_seen"],
                        f["ankle_seen"])
        tr.reject("any movement", f"{hands}, and {feet}",
                  wrist_window_travel=f["wrist_window_travel"],
                  wrist_window_seen=f["wrist_window_seen"],
                  ankle_window_travel=f["ankle_window_travel"],
                  ankle_window_seen=f["ankle_window_seen"],
                  wrist_seen_clip=f["wrist_seen"], ankle_seen_clip=f["ankle_seen"],
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
    "knee_raise": "Hanging knee raise",
    "front_lever": "Front lever",
    "planche": "Planche",
    "pistol_squat": "Pistol squat",
    "unknown": "Not recognised",
}
