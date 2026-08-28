"""Movement profiles.

A squat and a muscle-up are not the same measurement problem, and pretending
they are produces silent nonsense rather than an error.

Two things differ and both matter:

  Reference frame.  In a squat the feet are fixed and the hips are the thing
  that moves, so a hip-midpoint origin is the natural frame. In a muscle-up the
  hands are fixed on the bar and the WHOLE BODY translates, so a hip-midpoint
  origin cancels exactly the motion being measured. The bar - that is, the
  wrist midpoint - is the fixed reference, and everything is expressed relative
  to it.

  Direction.  A squat starts at the top and descends; a muscle-up starts hanging
  and ascends. The rep segmenter has to know which extremum is the turnaround
  and which is rest, or it segments the gaps between reps instead of the reps.

Adding a movement means adding an entry here, not editing the stages.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import schema as S


@dataclass(frozen=True)
class Movement:
    name: str
    origin: str              # "hip" | "wrist"
    direction: str           # "descending" (rest at top) | "ascending" (rest at bottom)
    signal: str              # what the segmenter tracks
    min_rep_s: float
    turn_label: str          # what the turnaround means, for reports
    aliases: tuple[str, ...] = ()


SQUAT = Movement(
    name="squat", origin="hip", direction="descending", signal="hip_height",
    min_rep_s=0.8, turn_label="bottom",
    aliases=("back-squat", "front-squat", "backsquat"),
)
MUSCLE_UP = Movement(
    name="muscle_up", origin="wrist", direction="ascending",
    signal="shoulder_above_bar", min_rep_s=0.7, turn_label="lockout",
    aliases=("muscleup", "muscle-up", "mu"),
)
PULL_UP = Movement(
    name="pull_up", origin="wrist", direction="ascending",
    signal="shoulder_above_bar", min_rep_s=0.6, turn_label="top",
    aliases=("pullup", "pull-up", "chin_up", "chinup"),
)
# Hanging from the bar with the shoulders still and the legs coming up. It is
# in here because it is what the athlete was actually doing on one of the
# sample clips, and without it that clip was confidently reported as a pull-up
# - a movement whose defining feature (the shoulders rising to the hands) it
# does not contain at all.
KNEE_RAISE = Movement(
    name="knee_raise", origin="wrist", direction="ascending",
    signal="knees_toward_bar", min_rep_s=0.7, turn_label="knees up",
    aliases=("knee-raise", "kneeraise", "leg_raise", "leg-raise", "legraise",
             "hanging_knee_raise", "toes_to_bar", "toes-to-bar", "ttb"),
)
DIP = Movement(
    name="dip", origin="wrist", direction="descending", signal="shoulder_above_bar",
    min_rep_s=0.6, turn_label="bottom", aliases=("dips",),
)
# Geometrically a dip lying down: hands fixed, shoulders above them, body
# descending. What separates the two is which way the torso points - see
# classify.torso_tilt - not anything in this profile.
PUSH_UP = Movement(
    name="push_up", origin="wrist", direction="descending",
    signal="shoulder_above_bar", min_rep_s=0.5, turn_label="bottom",
    aliases=("pushup", "push-up", "press-up", "pressup"),
)

MOVEMENTS = {m.name: m for m in (SQUAT, MUSCLE_UP, PULL_UP, KNEE_RAISE, DIP, PUSH_UP)}
_ALIASES = {a: m for m in MOVEMENTS.values() for a in (m.name, *m.aliases)}

DEFAULT = SQUAT


def resolve(name: str | None) -> Movement:
    """Look up a movement by name or alias. Unknown names are an error, not a
    silent fallback: analysing a muscle-up with squat geometry would produce
    numbers that look fine and mean nothing."""
    if not name:
        return DEFAULT
    key = str(name).strip().lower().replace(" ", "_")
    if key in _ALIASES:
        return _ALIASES[key]
    raise SystemExit(
        f"unknown movement {name!r}. Known: {', '.join(sorted(MOVEMENTS))}.\n"
        "Set it per video in the exercise column of sessions.csv, or add a "
        "profile to barra/movements.py."
    )


# ---------------------------------------------------------------------------
# Geometry helpers, all operating on (T, 17, 3) pixel keypoints
# ---------------------------------------------------------------------------
# A landmark is trusted from this confidence up. Below it the estimator is
# guessing, and for an occluded limb it guesses somewhere plausible rather than
# refusing, which is why the number has to be checked rather than the position.
PAIR_CONF = 0.5
# Both sides have to be confidently seen together in at least this fraction of
# the clip for their midpoint to be the reference. Below it the far side is
# effectively absent and the near one is used alone.
#
# The value sits in a gap that is geometric rather than arbitrary. A camera is
# either roughly square to the athlete, in which case both sides are visible
# almost always, or roughly side-on, in which case the far limb is behind the
# near one and is rarely seen at all. Measured across the sample clips the two
# regimes are 0.68-1.00 and 0.00-0.49, with nothing in between; 0.55 is the
# middle of that gap. Choosing a low threshold is actively harmful: at 0.30 a
# side-on clip kept a midpoint built from the 39% of frames where both wrists
# happened to be seen, and threw away the 50% where the near wrist alone was.
MIN_PAIRED_FRAC = 0.55


def _pair(kp: np.ndarray, a: str, b: str) -> tuple[np.ndarray, np.ndarray]:
    """The body point a left/right pair describes, and how well it is known.

    Both sides seen -> their midpoint, which cancels the small asymmetry of a
    body that is never perfectly square to the lens.

    Only one side seen -> that side, alone. This matters more than it sounds.
    Filmed from the side - the angle most of these movements are *supposed* to
    be filmed from - the far arm and leg are behind the near ones, and the pose
    estimator reports the far wrist at 0.06 confidence while the near one sits
    at 0.42. Taking the minimum of the pair then declares the hands unseen for
    the entire clip, and averaging their positions moves the "hands" halfway to
    wherever the estimator guessed the hidden one was.

    Both are wrong, and the first was wrong in a way that produced a confident
    false answer rather than a refusal: with the wrists reported unseen, the
    arm tests all returned NaN, the squat branch read "not articulated" off
    that NaN, and a muscle-up filmed side-on was classified as a squat. In a
    sagittal view both hands are on the same bar within a few pixels of each
    other, so the visible one is not a compromise - it is the better estimate.
    """
    ia, ib = S.KP_INDEX[a], S.KP_INDEX[b]
    ca, cb = kp[:, ia, 2], kp[:, ib, 2]
    pa, pb = kp[:, ia, :2], kp[:, ib, :2]
    both = (ca >= PAIR_CONF) & (cb >= PAIR_CONF)

    # The choice is made ONCE for the clip, not per frame. Switching between
    # the midpoint and a single side partway through moves the reference point
    # by half the distance between the two landmarks, and every such switch
    # reads downstream as the body having moved. On a real muscle-up that
    # manufactured enough apparent hand travel (0.812 torso-lengths against a
    # limit of 0.80) to reject the clip's only rep - a rep thrown away by a
    # tenth of a percent, on motion that never happened.
    if both.mean() >= MIN_PAIRED_FRAC:
        return 0.5 * (pa + pb), np.minimum(ca, cb)

    # Otherwise the pair is never reliably seen together - the far side is
    # occluded, as it is in any side-on view - so the near side is used for the
    # whole clip and reports its own confidence.
    near_a = ca.mean() >= cb.mean()
    return (pa, ca) if near_a else (pb, cb)


def midpoint(kp: np.ndarray, a: str, b: str) -> np.ndarray:
    return _pair(kp, a, b)[0]


def pair_confidence(kp: np.ndarray, a: str, b: str) -> np.ndarray:
    return _pair(kp, a, b)[1]


def origin_of(kp: np.ndarray, movement: Movement) -> tuple[np.ndarray, np.ndarray]:
    """Origin point per frame, and its confidence."""
    if movement.origin == "wrist":
        return (midpoint(kp, "left_wrist", "right_wrist"),
                pair_confidence(kp, "left_wrist", "right_wrist"))
    return (midpoint(kp, "left_hip", "right_hip"),
            pair_confidence(kp, "left_hip", "right_hip"))


def robust_torso(kp: np.ndarray, torso: np.ndarray | None = None) -> float:
    """One torso length for the whole clip: the median over frames where both
    the shoulder and hip midpoints were seen with reasonable confidence."""
    if torso is None:
        torso = np.linalg.norm(
            midpoint(kp, "left_shoulder", "right_shoulder")
            - midpoint(kp, "left_hip", "right_hip"),
            axis=1,
        )
    conf = np.minimum(pair_confidence(kp, "left_shoulder", "right_shoulder"),
                      pair_confidence(kp, "left_hip", "right_hip"))
    good = (conf >= 0.5) & (torso > 1e-6)
    if good.sum() < 5:
        good = torso > 1e-6
    if good.sum() == 0:
        raise SystemExit("torso length is degenerate on every frame")
    return float(np.median(torso[good]))


# A bar does not move. Measured over real reps this travel is 0.04-0.43 torso
# lengths (handheld camera included); over a subject walking away from the bar
# it is 1.1-4.8. The gap is an order of magnitude, so the threshold sits
# comfortably between rather than being tuned to either side.
MAX_BAR_TRAVEL = 0.80


def anchor_travel(kp: np.ndarray, a: int, b: int, min_conf: float = 0.4) -> float:
    """How far the movement's fixed anchor drifts across a candidate rep, in
    torso-lengths.

    This is the test that separates a rep from a person walking around. A bar
    movement is defined by the hands being ON something fixed; if the wrists
    travel a body-length during the "rep", whatever was measured, it was not a
    rep. The pose estimator will not tell you this - it reported 0.9 confidence
    while tracking a subject strolling toward the camera, hands at his hips,
    and the wrist-referenced signal duly recorded a magnificent muscle-up.

    Robust percentiles rather than min/max, so one stray frame does not reject a
    good rep.
    """
    torso = robust_torso(kp)
    w = midpoint(kp, "left_wrist", "right_wrist")[a:b + 1]
    c = pair_confidence(kp, "left_wrist", "right_wrist")[a:b + 1]
    ok = c >= min_conf
    if ok.sum() < 5:
        return float("inf")
    p = w[ok] / torso
    span = np.percentile(p, 95, axis=0) - np.percentile(p, 5, axis=0)
    return float(np.hypot(*span))


def tracking_signal(kp: np.ndarray, movement: Movement) -> tuple[np.ndarray, np.ndarray]:
    """The scalar the rep segmenter follows, oriented so that MORE = further
    from rest, whichever direction the movement travels.

    Returned in torso-lengths, not pixels, so the prominence thresholds in the
    segmenter mean the same thing on every clip regardless of how far away the
    camera was.

    The scale is one robust number for the whole clip, not the per-frame torso
    length. A per-frame divisor blows up whenever the pose estimator briefly
    collapses the torso - which it does, on real footage - and a single such
    frame produces a value tens of torso-lengths from the rest and silently
    destroys every threshold downstream.
    """
    torso = np.linalg.norm(
        midpoint(kp, "left_shoulder", "right_shoulder")
        - midpoint(kp, "left_hip", "right_hip"),
        axis=1,
    )
    scale = robust_torso(kp, torso)

    if movement.signal == "knees_toward_bar":
        # A hanging knee raise is measured at the knees, not the shoulders:
        # the whole point of the movement is that the shoulders stay where
        # they are while the legs come up. Tracking the shoulders here would
        # follow the swing and call it a rep.
        bar = midpoint(kp, "left_wrist", "right_wrist")
        knee = midpoint(kp, "left_knee", "right_knee")
        raw = (bar[:, 1] - knee[:, 1]) / scale     # + when the knees rise
        conf = np.minimum(pair_confidence(kp, "left_wrist", "right_wrist"),
                          pair_confidence(kp, "left_knee", "right_knee"))
    elif movement.signal == "shoulder_above_bar":
        bar = midpoint(kp, "left_wrist", "right_wrist")
        sh = midpoint(kp, "left_shoulder", "right_shoulder")
        raw = (bar[:, 1] - sh[:, 1]) / scale       # + when shoulders are above the bar
        conf = np.minimum(pair_confidence(kp, "left_wrist", "right_wrist"),
                          pair_confidence(kp, "left_shoulder", "right_shoulder"))
    else:
        hip = midpoint(kp, "left_hip", "right_hip")
        raw = -hip[:, 1] / scale                   # + is up in image coordinates
        conf = pair_confidence(kp, "left_hip", "right_hip")

    # orient so the turnaround is always a maximum
    return (raw if movement.direction == "ascending" else -raw), conf
