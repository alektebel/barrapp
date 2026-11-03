"""Independent measurement channels for late-fusion consensus.

Each channel estimates one quantity from one family of observables. Channels
that share a family (pose/pose, vision/vision) must not count as two votes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

import numpy as np

FAMILY_POSE = "P"
FAMILY_VISION = "V"
FAMILY_PIXEL = "M"
FAMILY_PRIOR = "H"
FAMILY_TIME = "T"
FAMILY_USER = "U"


@dataclass
class Estimate:
    value: Any
    confidence: float
    status: str  # "ok" | "abstain"
    evidence: dict
    channel: str = ""
    quantity: str = ""
    family: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Channel:
    name: str
    quantity: str
    family: str
    fn: Callable[..., Estimate]


def _ok(value, confidence: float, **evidence) -> Estimate:
    return Estimate(value=value, confidence=float(confidence), status="ok",
                    evidence=evidence)


def _abstain(reason: str, **evidence) -> Estimate:
    return Estimate(value=None, confidence=0.0, status="abstain",
                    evidence={"reason": reason, **evidence})


def working_set_geometry(kp, fps, vision_window=None) -> Estimate:
    from .working_set import find_working_set
    ws = find_working_set(kp, fps, vision_window=vision_window)
    if ws.source == "whole-clip" and ws.confidence < 0.3:
        return _abstain("no_work_span", **ws.evidence)
    return _ok(
        {"start": ws.start, "end": ws.end, "source": ws.source},
        ws.confidence, **ws.evidence,
    )


def working_set_periodicity(kp, fps) -> Estimate:
    from .joint_periodicity import dominant_drivers, joint_periodicity
    periods = joint_periodicity(kp, fps)
    drivers = dominant_drivers(periods, floor=0.30)
    if not drivers:
        return _abstain("no_periodic_driver")
    top = next(p for p in periods if p.name == drivers[0])
    return _ok(
        {"drivers": drivers, "rate_hz": top.rate_hz},
        float(top.strength),
        strength=top.strength, amplitude=top.amplitude,
    )


def identity_geometry(kp, fps, window=None) -> Estimate:
    from .classify import classify
    from .trace import NullTrace
    sl = slice(None) if window is None else slice(window[0], window[1] + 1)
    det = classify(kp[sl], NullTrace(), fps=fps)
    if det.exercise in ("", "unknown", None) or det.confidence <= 0:
        return _abstain("unknown", reason=det.reason)
    return _ok(det.exercise, det.confidence, reason=det.reason,
               runner_up=det.runner_up)


def identity_drivers(kp, fps, window=None) -> Estimate:
    from .joint_periodicity import identity_hint, joint_periodicity
    sl = slice(None) if window is None else slice(window[0], window[1] + 1)
    periods = joint_periodicity(kp[sl], fps)
    hint = identity_hint(periods)
    if hint in ("hold_or_setup", "mixed"):
        return _abstain(hint)
    # Map soft hints to canonical families for agreement checks.
    mapping = {
        "arm_cycle_legs_hanging": "pull_up",
        "fl_pull_like": "front_lever_pull_up",
        "knee_raise_like": "knee_raise",
        "squat_family": "squat",
        "straight_arm_pull_or_push": "front_lever_pull_up",
        "compound_or_kip": "muscle_up",
    }
    return _ok(mapping.get(hint, hint), 0.45, hint=hint)


def reps_peaks(kp, fps, movement_name: str, window=None) -> Estimate:
    from .ingest import segment_reps_verbose
    from .movements import resolve
    from .trace import NullTrace
    try:
        movement = resolve(movement_name)
    except Exception:  # noqa: BLE001
        return _abstain("unresolved_movement", movement=movement_name)
    sl = slice(None) if window is None else slice(window[0], window[1] + 1)
    kp_w = kp[sl]
    offset = 0 if window is None else int(window[0])
    reps, _ = segment_reps_verbose(kp_w, fps, movement, trace=NullTrace())
    if not reps:
        return _abstain("no_peaks")
    # Re-base frame indices to the full clip.
    spans = [(int(a) + offset, int(b) + offset, int(c) + offset) for a, b, c in reps]
    return _ok(len(spans), 0.7, spans=spans)


def reps_period_times_duration(kp, fps, window=None) -> Estimate:
    from .joint_periodicity import dominant_drivers, joint_periodicity
    sl = slice(None) if window is None else slice(window[0], window[1] + 1)
    periods = joint_periodicity(kp[sl], fps)
    drivers = dominant_drivers(periods, floor=0.30)
    if not drivers:
        return _abstain("no_rate")
    top = next(p for p in periods if p.name == drivers[0])
    if not np.isfinite(top.rate_hz) or top.rate_hz <= 0:
        return _abstain("no_rate")
    n = len(kp[sl])
    dur = n / max(float(fps), 1.0)
    count = int(round(dur * float(top.rate_hz)))
    if count < 1:
        return _abstain("count_lt_1", rate=top.rate_hz, dur=dur)
    return _ok(count, float(top.strength), rate_hz=top.rate_hz, duration_s=dur)


def dip_depth_height(kp, start: int, turn: int, end: int) -> Estimate:
    """Shoulder below elbow at the bottom, in torso lengths (rotation-stable)."""
    from .movements import midpoint, pair_confidence, robust_torso
    torso = robust_torso(kp)
    # turnaround neighborhood
    a = max(start, turn - 2)
    b = min(end, turn + 2)
    sh = midpoint(kp, "left_shoulder", "right_shoulder")[a:b + 1]
    el = midpoint(kp, "left_elbow", "right_elbow")[a:b + 1]
    conf = np.minimum(
        pair_confidence(kp, "left_shoulder", "right_shoulder")[a:b + 1],
        pair_confidence(kp, "left_elbow", "right_elbow")[a:b + 1],
    )
    ok = conf >= 0.4
    if ok.sum() < 2:
        return _abstain("tracking_loss")
    # image y grows down: positive => shoulder lower than elbow
    delta = (sh[:, 1] - el[:, 1]) / torso
    val = float(np.nanmedian(delta[ok]))
    if not np.isfinite(val):
        return _abstain("nan")
    # band: shallow < 0.05, ok 0.05-0.15, deep > 0.15
    if val > 0.15:
        band = "deep"
    elif val < 0.05:
        band = "shallow"
    else:
        band = "ok"
    return _ok(band, 0.75, shoulder_below_elbow=val)


def default_channels() -> list[Channel]:
    return [
        Channel("W1", "working_set", FAMILY_POSE, working_set_geometry),
        Channel("W2", "working_set", FAMILY_POSE, working_set_periodicity),
        Channel("I1", "identity", FAMILY_POSE, identity_geometry),
        Channel("I2", "identity", FAMILY_POSE, identity_drivers),
        Channel("R1", "reps", FAMILY_POSE, reps_peaks),
        Channel("R2", "reps", FAMILY_POSE, reps_period_times_duration),
        Channel("D2", "rep_depth", FAMILY_POSE, dip_depth_height),
    ]
