"""Online ops signals: pose rate and missed-set suspicion.

Emitted on every measured payload so a dashboard can aggregate without
re-reading traces. Thresholds are conservative: a suspect flag is a review
queue, not a claim that reps were missed.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

# Holds are scored by time-on-position, not by counted reps.
HOLD_EXERCISES = frozenset({
    "front_lever", "back_lever", "planche", "human_flag", "handstand",
})

# Share of frames the athlete looks "on apparatus" before we suspect a set.
MIN_ACTIVE_FRAC = 0.25
# Peak-to-peak of the tracking signal (torso lengths) that looks like work.
MIN_SIGNAL_SPAN = 0.20


def pose_per_video_second(pose_wall_s: float, video_s: float) -> float | None:
    """Seconds of pose wall time per second of video; None if unknown."""
    if video_s is None or float(video_s) <= 0:
        return None
    if pose_wall_s is None or float(pose_wall_s) < 0:
        return None
    return round(float(pose_wall_s) / float(video_s), 4)


def latency_block(pose_wall_s: float | None, video_s: float | None,
                  *, backend: str | None = None) -> dict[str, Any]:
    rate = pose_per_video_second(pose_wall_s or 0.0, video_s or 0.0) if (
        pose_wall_s is not None and video_s is not None) else None
    out: dict[str, Any] = {
        "poseWallS": None if pose_wall_s is None else round(float(pose_wall_s), 3),
        "videoS": None if video_s is None else round(float(video_s), 3),
        "posePerVideoSecond": rate,
    }
    if backend:
        out["poseBackend"] = backend
    return out


def suspect_missed_reps(
    *,
    n_reps: int,
    exercise: str | None,
    is_hold: bool | None = None,
    active_frac: float | None = None,
    signal_span: float | None = None,
    vision_reps_estimate: float | None = None,
    n_candidates: int = 0,
) -> dict[str, Any]:
    """Whether geometry found no reps while the clip still looks like a set.

    True when the counted path is empty but the athlete appears active on the
    apparatus (or a vision estimate claimed reps). Holds never trigger.
    """
    ex = (exercise or "").strip().lower().replace("-", "_")
    hold = bool(is_hold) if is_hold is not None else ex in HOLD_EXERCISES
    evidence: dict[str, Any] = {
        "nReps": int(n_reps),
        "exercise": ex or None,
        "isHold": hold,
        "activeFrac": None if active_frac is None else round(float(active_frac), 3),
        "signalSpan": None if signal_span is None else round(float(signal_span), 3),
        "visionRepsEstimate": vision_reps_estimate,
        "nCandidates": int(n_candidates),
    }
    if int(n_reps) > 0 or hold or not ex or ex == "unknown":
        return {"suspectMissedReps": False, "reasons": [], "evidence": evidence}

    reasons: list[str] = []
    if active_frac is not None and float(active_frac) >= MIN_ACTIVE_FRAC:
        reasons.append(f"active_frac:{float(active_frac):.2f}>={MIN_ACTIVE_FRAC}")
    if signal_span is not None and float(signal_span) >= MIN_SIGNAL_SPAN:
        reasons.append(f"signal_span:{float(signal_span):.2f}>={MIN_SIGNAL_SPAN}")
    if vision_reps_estimate is not None and float(vision_reps_estimate) >= 1:
        reasons.append(f"vision_estimate:{float(vision_reps_estimate):.0f}")
    if int(n_candidates) > 0:
        reasons.append(f"candidates_rejected:{int(n_candidates)}")

    return {
        "suspectMissedReps": bool(reasons),
        "reasons": reasons,
        "evidence": evidence,
    }


def signal_activity(kp, fps: float, movement) -> tuple[float, float]:
    """(active_frac, signal_span_torso) for missed-set detection."""
    import numpy as np
    from .ingest import _clean_signal, active_mask
    from .movements import tracking_signal

    if kp is None or len(kp) < 8:
        return 0.0, 0.0
    raw, conf = tracking_signal(kp, movement)
    sig, valid = _clean_signal(raw, conf)
    active = active_mask(kp, fps, movement)
    active_frac = float(active.mean()) if len(active) else 0.0
    if valid is not None and valid.any():
        span = float(np.nanmax(sig[valid]) - np.nanmin(sig[valid]))
    elif len(sig):
        span = float(np.nanmax(sig) - np.nanmin(sig))
    else:
        span = 0.0
    if span != span:  # NaN
        span = 0.0
    return active_frac, span
