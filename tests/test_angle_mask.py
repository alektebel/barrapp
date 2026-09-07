"""_angle masks by joint confidence, per frame.

The mask used to be indexed with keypoint indices against a per-frame array,
so whether an elbow angle existed at all depended on how confident frames 5, 7
and 9 happened to be. Both directions of that failure are pinned here.
"""
from __future__ import annotations

import numpy as np

from barra import schema as S
from barra.classify import _angle

LS, LE, LW = (S.KP_INDEX["left_shoulder"], S.KP_INDEX["left_elbow"],
              S.KP_INDEX["left_wrist"])


def _arm(conf: float = 0.9, frames: int = 40) -> np.ndarray:
    kp = np.zeros((frames, 17, 3))
    kp[..., 2] = conf
    kp[:, LS, :2] = (0.0, 0.0)
    kp[:, LE, :2] = (0.0, 1.0)
    kp[:, LW, :2] = (0.0, 2.0)     # collinear: a straight arm, 180 degrees
    return kp


def test_a_straight_arm_measures_180():
    kp = _arm()
    deg = _angle(kp, LS, LE, LW, np.ones(len(kp), bool))
    assert np.allclose(deg, 180.0)


def test_one_low_frame_does_not_erase_the_clip():
    """The old indexing let frame 5 decide the answer for all 40 frames."""
    kp = _arm()
    ok = np.ones(len(kp), bool)
    ok[5] = False
    deg = _angle(kp, LS, LE, LW, ok)
    assert np.isnan(deg[5])
    assert np.isfinite(deg[[0, 1, 20, 39]]).all()


def test_an_unseen_joint_is_not_measured():
    """The old mask ignored the joints' own confidence entirely."""
    kp = _arm()
    kp[10:20, LE, 2] = 0.1           # the elbow itself is not seen
    deg = _angle(kp, LS, LE, LW, np.ones(len(kp), bool))
    assert np.isnan(deg[10:20]).all()
    assert np.isfinite(deg[:10]).all()
