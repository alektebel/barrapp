"""A squat filmed with the arms held forward and the feet out of frame must not
be confidently called a dip.

The dip/squat boundary is the one case the geometry genuinely cannot settle
without knowable feet: a squat with the arms extended forward has fixed hands,
articulated arms and most of the body below them - which is the whole dip
signature. The honest answer is an abstention that names the ambiguity, not a
confident dip (which is what was happening on real squat footage whose feet the
camera cut off). A real dip keeps its feet visible, so it still passes.
"""
from __future__ import annotations

import numpy as np

from barra import schema as S
from barra.classify import classify


def _squat_like(n: int = 60) -> np.ndarray:
    """Hands fixed forward, shoulders/hips descending, feet never seen."""
    kp = np.zeros((n, 17, 3))
    conf = 0.9
    for i in range(n):
        frac = i / (n - 1)
        hip_y = 1.20 + 0.60 * (0.5 - 0.5 * np.cos(2 * np.pi * frac))
        kp[i, S.KP_INDEX["left_hip"]] = (0.45, hip_y, conf)
        kp[i, S.KP_INDEX["right_hip"]] = (0.55, hip_y, conf)
        kp[i, S.KP_INDEX["left_shoulder"]] = (0.45, hip_y - 0.60, conf)
        kp[i, S.KP_INDEX["right_shoulder"]] = (0.55, hip_y - 0.60, conf)
        kp[i, S.KP_INDEX["left_elbow"]] = (0.45, hip_y - 0.30, conf)
        kp[i, S.KP_INDEX["right_elbow"]] = (0.55, hip_y - 0.30, conf)
        # wrists fixed in space, forward and low (below the shoulders)
        kp[i, S.KP_INDEX["left_wrist"]] = (0.45, 1.30, conf)
        kp[i, S.KP_INDEX["right_wrist"]] = (0.55, 1.30, conf)
        kp[i, S.KP_INDEX["left_knee"]] = (0.46, hip_y + 0.40, conf)
        kp[i, S.KP_INDEX["right_knee"]] = (0.54, hip_y + 0.40, conf)
        # ankles NOT seen (confidence 0) - the squat's feet are out of frame
        kp[i, S.KP_INDEX["left_ankle"]] = (0.40, 2.0, 0.0)
        kp[i, S.KP_INDEX["right_ankle"]] = (0.60, 2.0, 0.0)
    return kp


def test_squat_with_unseen_feet_is_abstained_not_dip():
    c = classify(_squat_like())
    assert c.exercise == "unknown", c.exercise
    # It must name the ambiguity, not claim a dip.
    assert "squat" in c.reason.lower() and "feet" in c.reason.lower()
    assert c.runner_up in ("squat", "push_up")


def test_visible_hanging_feet_still_a_dip():
    # Same fixed-hands descending body, but the feet are seen and they hang (a
    # dip): this must NOT be abstained - it is a supported dip.
    n = 60
    kp = _squat_like()
    conf = 0.9
    for i in range(n):
        kp[i, S.KP_INDEX["left_ankle"]] = (0.40, 1.60, conf)
        kp[i, S.KP_INDEX["right_ankle"]] = (0.60, 1.60, conf)
    c = classify(kp)
    # The feet may be slight differing, but they are seen and the body hangs.
    assert c.exercise != "unknown"
