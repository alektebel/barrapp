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
DIP = Movement(
    name="dip", origin="wrist", direction="descending", signal="shoulder_above_bar",
    min_rep_s=0.6, turn_label="bottom", aliases=("dips",),
)

MOVEMENTS = {m.name: m for m in (SQUAT, MUSCLE_UP, PULL_UP, DIP)}
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
def midpoint(kp: np.ndarray, a: str, b: str) -> np.ndarray:
    return 0.5 * (kp[:, S.KP_INDEX[a], :2] + kp[:, S.KP_INDEX[b], :2])


def pair_confidence(kp: np.ndarray, a: str, b: str) -> np.ndarray:
    return np.minimum(kp[:, S.KP_INDEX[a], 2], kp[:, S.KP_INDEX[b], 2])


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

    if movement.signal == "shoulder_above_bar":
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
