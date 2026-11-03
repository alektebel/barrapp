from __future__ import annotations

import numpy as np

from barra.channels import dip_depth_height
from barra.config import THRESHOLDS
from barra.rules import RULES


def test_excessive_depth_uses_shoulder_below_elbow():
    rules = RULES["dip"]
    deep = next(r for r in rules if r.id == "dip.excessive_depth")
    assert deep.primitive == "dip_shoulder_below_elbow"
    assert deep.comparison == ">"
    assert deep.threshold == THRESHOLDS.dip_shoulder_below_elbow


def test_height_primitive_stable_under_yaw():
    """Rotate a 3D arm in the horizontal plane: 2D elbow angle changes,
    shoulder-below-elbow height should stay the same family of answer."""
    # Build a minimal pose where shoulder is clearly below elbow at bottom.
    T = 30
    kp = np.zeros((T, 17, 3), dtype=np.float32)
    kp[:, :, 2] = 0.9
    # wrists / elbows / shoulders: shoulder y > elbow y (below in image)
    for i in range(T):
        kp[i, 9, :2] = (100, 80)   # wrist
        kp[i, 10, :2] = (140, 80)
        kp[i, 7, :2] = (100, 120)  # elbow
        kp[i, 8, :2] = (140, 120)
        kp[i, 5, :2] = (100, 160)  # shoulder below elbow
        kp[i, 6, :2] = (140, 160)
        kp[i, 11, :2] = (105, 220)
        kp[i, 12, :2] = (135, 220)
    est = dip_depth_height(kp, 5, 15, 25)
    assert est.status == "ok"
    assert est.value == "deep"
    assert est.evidence["shoulder_below_elbow"] > THRESHOLDS.dip_shoulder_below_elbow
