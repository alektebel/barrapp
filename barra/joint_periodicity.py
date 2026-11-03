"""Per-signal periodicity fingerprint for detect → classify.

A single global periodicity collapses the thing that separates a front-lever
pull from a knee raise: *which* chain is oscillating. This module measures
autocorrelation strength, rate and amplitude on a small set of scale-free
signals (not all 17 COCO joints) so the working-set detector and the identity
classifier can read the same matrix.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from . import schema as S
from .kinematics import _angle, _bilateral, _periodicity, _range
from .movements import midpoint, pair_confidence, robust_torso

MIN_CONF = 0.3


@dataclass(frozen=True)
class SignalPeriod:
    name: str
    strength: float
    rate_hz: float
    amplitude: float  # torso-lengths or degrees, depending on the signal
    unit: str


def _series_bank(kp: np.ndarray) -> dict[str, tuple[np.ndarray, str]]:
    """Eight scalar series. Heights are in torso lengths; angles in degrees."""
    torso = robust_torso(kp)
    shoulder = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    wrist = midpoint(kp, "left_wrist", "right_wrist")
    knee = midpoint(kp, "left_knee", "right_knee")
    ankle = midpoint(kp, "left_ankle", "right_ankle")

    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_CONF
    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_CONF
    k_ok = pair_confidence(kp, "left_knee", "right_knee") >= MIN_CONF
    a_ok = pair_confidence(kp, "left_ankle", "right_ankle") >= MIN_CONF

    elbow = _bilateral(kp, "shoulder", "elbow", "wrist")
    hip_ang = _bilateral(kp, "shoulder", "hip", "knee")

    # Body line: angle of shoulder→hip vs horizontal (image x). 0 = flat.
    sh_ok = s_ok & h_ok
    d = hip - shoulder
    body_line = np.full(len(kp), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        body_line[sh_ok] = np.degrees(np.arctan2(d[sh_ok, 1], d[sh_ok, 0]))

    wrist_abs = np.where(w_ok, wrist[:, 1] / torso, np.nan)

    return {
        "shoulder_above_hands": (
            np.where(w_ok & s_ok, (wrist[:, 1] - shoulder[:, 1]) / torso, np.nan),
            "torso",
        ),
        "elbow_angle": (elbow, "deg"),
        "knee_above_hip": (
            np.where(k_ok & h_ok, (hip[:, 1] - knee[:, 1]) / torso, np.nan),
            "torso",
        ),
        "hip_angle": (hip_ang, "deg"),
        "body_line": (body_line, "deg"),
        "hip_above_hands": (
            np.where(w_ok & h_ok, (wrist[:, 1] - hip[:, 1]) / torso, np.nan),
            "torso",
        ),
        "hip_above_ankle": (
            np.where(a_ok & h_ok, (ankle[:, 1] - hip[:, 1]) / torso, np.nan),
            "torso",
        ),
        "wrist_abs_y": (wrist_abs, "torso"),
    }


def joint_periodicity(kp: np.ndarray, fps: float) -> list[SignalPeriod]:
    """Clip-level fingerprint: one row per signal."""
    fps = float(fps or 30.0) or 30.0
    out: list[SignalPeriod] = []
    for name, (series, unit) in _series_bank(kp).items():
        strength, rate = _periodicity(series, fps)
        amp = _range(series)
        out.append(SignalPeriod(
            name=name,
            strength=float(strength) if np.isfinite(strength) else float("nan"),
            rate_hz=float(rate) if np.isfinite(rate) else float("nan"),
            amplitude=float(amp) if np.isfinite(amp) else float("nan"),
            unit=unit,
        ))
    return out


def dominant_drivers(periods: list[SignalPeriod], floor: float = 0.35
                     ) -> list[str]:
    """Signals whose autocorrelation peak clears `floor`, strongest first."""
    ranked = sorted(
        (p for p in periods if np.isfinite(p.strength) and p.strength >= floor),
        key=lambda p: p.strength,
        reverse=True,
    )
    return [p.name for p in ranked]


def fingerprint_dict(periods: list[SignalPeriod]) -> dict:
    drivers = dominant_drivers(periods)
    return {
        "drivers": drivers,
        "top": drivers[0] if drivers else None,
        "signals": {p.name: asdict(p) for p in periods},
    }


def identity_hint(periods: list[SignalPeriod]) -> str:
    """Cheap label guess from which chains oscillate. Not a classifier."""
    by = {p.name: p for p in periods}
    drivers = set(dominant_drivers(periods, floor=0.30))
    if not drivers:
        return "hold_or_setup"
    shoulder = "shoulder_above_hands" in drivers
    elbow = "elbow_angle" in drivers
    knee = "knee_above_hip" in drivers
    hip_h = "hip_above_ankle" in drivers
    hip_ang = "hip_angle" in drivers
    if hip_h and not shoulder:
        return "squat_family"
    if shoulder and elbow and not knee:
        # push vs pull needs apparatus; hint stays generic
        return "arm_cycle_legs_hanging"
    if shoulder and elbow and knee:
        # FL tuck pull: arms cycle, knees high and often quiet relative to hip
        knee_p = by.get("knee_above_hip")
        if knee_p and (not np.isfinite(knee_p.amplitude) or knee_p.amplitude < 0.25):
            return "fl_pull_like"
        return "compound_or_kip"
    if knee and hip_ang and not elbow:
        return "knee_raise_like"
    if shoulder and not elbow:
        return "straight_arm_pull_or_push"
    return "mixed"
