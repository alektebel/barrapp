"""The split-squat recognition is geometric, so it is testable on keypoints.

A split squat is a squat with the feet fore/aft, so the two ankles sit at
different heights and the hips travel. These tests build simple (T,17,3)
keypoint clips - no videos, no pose - and check that `classify.features`
reports the split-stance geometry and that the classifier routes a rear-foot
elevated stance to bulgarian_split_squat (and a parallel stance away from it).
"""
from __future__ import annotations

import numpy as np

from barra import schema as S
from barra.classify import classify, features


def _clip(hip_y_range: tuple[float, float], rear_ankle_y: float,
          front_ankle_y: float = 2.00, n: int = 60) -> np.ndarray:
    """A sagittal stand->squat->stand clip.

    One foot planted (front/right, at a fixed lower y) and one rear (left)
    whose ankle sits at `rear_ankle_y` (smaller = higher = Bulgarian). The hips
    sweep BELOW the feet only in the sense the feet are far below the standing
    hips, so both ankles stay below the median hip and the stance does not read
    as a pistol's carried free leg; the arms hang at the sides (wrists below the
    shoulders) so the clip is not mistaken for a bar movement.
    """
    kp = np.zeros((n, 17, 3))
    conf = 0.9
    for i in range(n):
        frac = i / (n - 1)
        hip_y = hip_y_range[0] + (hip_y_range[1] - hip_y_range[0]) * (
            0.5 - 0.5 * np.cos(2 * np.pi * frac))
        kp[i, S.KP_INDEX["left_hip"]] = (0.35, hip_y, conf)
        kp[i, S.KP_INDEX["right_hip"]] = (0.65, hip_y, conf)
        kp[i, S.KP_INDEX["left_shoulder"]] = (0.40, hip_y - 0.60, conf)
        kp[i, S.KP_INDEX["right_shoulder"]] = (0.60, hip_y - 0.60, conf)
        kp[i, S.KP_INDEX["left_elbow"]] = (0.40, hip_y - 0.35, conf)
        kp[i, S.KP_INDEX["right_elbow"]] = (0.60, hip_y - 0.35, conf)
        kp[i, S.KP_INDEX["left_wrist"]] = (0.40, hip_y + 0.30, conf)
        kp[i, S.KP_INDEX["right_wrist"]] = (0.60, hip_y + 0.30, conf)
        kp[i, S.KP_INDEX["left_knee"]] = (0.42, hip_y + 0.35, conf)
        kp[i, S.KP_INDEX["right_knee"]] = (0.58, hip_y + 0.35, conf)
        kp[i, S.KP_INDEX["left_ankle"]] = (0.30, rear_ankle_y, conf)
        kp[i, S.KP_INDEX["right_ankle"]] = (0.66, front_ankle_y, conf)
    return kp


def test_features_report_split_stance():
    kp = _clip((0.60, 1.10), rear_ankle_y=1.80)
    f = features(kp, 30.0)
    assert f["split_ankle_heights"] > 0.08
    assert f["rear_raised"] > 0.25
    assert f["hip_travel"] > 0.35


def test_rear_foot_elevated_is_bulgarian():
    kp = _clip((0.60, 1.10), rear_ankle_y=1.80)
    c = classify(kp)
    assert c.exercise == "bulgarian_split_squat", c.exercise
    assert c.runner_up == "split_squat"


def test_moderate_gap_is_plain_split_squat():
    kp = _clip((0.60, 1.10), rear_ankle_y=1.92)
    c = classify(kp)
    assert c.exercise == "split_squat", c.exercise


def test_parallel_stance_is_not_split():
    # Both ankles at the same height: a parallel squat, not a split stance.
    kp = _clip((0.60, 1.10), rear_ankle_y=2.00)
    f = features(kp, 30.0)
    assert f["split_ankle_heights"] < 0.08


def test_movement_profiles_exist():
    from barra.movements import MOVEMENTS
    assert "bulgarian_split_squat" in MOVEMENTS
    assert "split_squat" in MOVEMENTS
