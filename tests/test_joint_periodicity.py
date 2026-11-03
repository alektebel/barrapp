from __future__ import annotations

import numpy as np

from barra.joint_periodicity import (
    dominant_drivers,
    identity_hint,
    joint_periodicity,
)


def _sine_clip(hz: float = 0.5, fps: float = 30.0, seconds: float = 8.0,
               drive: str = "shoulder") -> np.ndarray:
    """Synthetic COCO-17 clip with one oscillating chain."""
    T = int(fps * seconds)
    kp = np.zeros((T, 17, 3), dtype=np.float32)
    kp[:, :, 2] = 0.9
    t = np.arange(T) / fps
    wave = 40.0 * np.sin(2 * np.pi * hz * t)
    # Base standing/hanging pose in pixel space.
    for i, name in enumerate([
        "nose", "left_eye", "right_eye", "left_ear", "right_ear",
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle",
    ]):
        pass
    # indices from schema order: use numeric COCO layout
    # 5/6 shoulders, 7/8 elbows, 9/10 wrists, 11/12 hips, 13/14 knees, 15/16 ankles
    kp[:, 5, 0] = 80
    kp[:, 6, 0] = 120
    kp[:, 5, 1] = 100
    kp[:, 6, 1] = 100
    kp[:, 11, 0] = 85
    kp[:, 12, 0] = 115
    kp[:, 11, 1] = 180
    kp[:, 12, 1] = 180
    kp[:, 9, 0] = 80
    kp[:, 10, 0] = 120
    kp[:, 9, 1] = 40   # hands above shoulders (hang)
    kp[:, 10, 1] = 40
    kp[:, 7, 0] = 80
    kp[:, 8, 0] = 120
    kp[:, 7, 1] = 70
    kp[:, 8, 1] = 70
    kp[:, 13, 0] = 85
    kp[:, 14, 0] = 115
    kp[:, 13, 1] = 240
    kp[:, 14, 1] = 240
    kp[:, 15, 0] = 85
    kp[:, 16, 0] = 115
    kp[:, 15, 1] = 300
    kp[:, 16, 1] = 300
    if drive == "shoulder":
        # shoulders rise/fall relative to fixed wrists
        kp[:, 5, 1] = 100 + wave
        kp[:, 6, 1] = 100 + wave
        kp[:, 7, 1] = 70 + wave * 0.5
        kp[:, 8, 1] = 70 + wave * 0.5
    elif drive == "knee":
        kp[:, 13, 1] = 240 - np.abs(wave)
        kp[:, 14, 1] = 240 - np.abs(wave)
    return kp


def test_shoulder_drive_detected():
    kp = _sine_clip(drive="shoulder")
    periods = joint_periodicity(kp, fps=30.0)
    drivers = dominant_drivers(periods, floor=0.25)
    assert "shoulder_above_hands" in drivers
    assert identity_hint(periods) in {
        "arm_cycle_legs_hanging", "straight_arm_pull_or_push", "mixed",
        "compound_or_kip",
    }


def test_flat_clip_is_hold_or_setup():
    kp = _sine_clip(hz=0.0, drive="shoulder")
    # zero wave → overwrite to constant
    kp[:, 5, 1] = 100
    kp[:, 6, 1] = 100
    periods = joint_periodicity(kp, fps=30.0)
    assert identity_hint(periods) == "hold_or_setup"
