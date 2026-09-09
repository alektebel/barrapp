"""Measure an isometric hold (front lever, planche) as one observation.

A lever and a planche are not a set of repetitions. The rep segmenter counts
turnarounds; a hold has one. So a hold is measured as one observation per
attempt: how long the body was held, and how well it was held - the body line
angle, whether the arms and legs stayed straight, whether the hips piked.

The values produced here are exactly what the failure taxonomy
(barra/faults_taxonomy.py) reads, so a hold is classified into failure types
just like a rep is. It produces no 0-100 score: a hold's quality is its body
line and its failures, not a number a model has to invent.
"""
from __future__ import annotations

import numpy as np

from . import schema as S
from .classify import _angle, _frac, _pct
from .faults_taxonomy import HORIZONTAL
from .movements import midpoint, pair_confidence, robust_torso

MIN_HOLD_S = 0.6          # a hold shorter than this is not a hold
MIN_HOLD_CONF = 0.35      # landmarks below this are not measured


def _hold_metrics(kp: np.ndarray, a: int, b: int, fps: float) -> dict:
    """The geometry of one hold attempt, in the units the taxonomy reads."""
    torso = robust_torso(kp)
    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    ankle = midpoint(kp, "left_ankle", "right_ankle")

    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_HOLD_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_HOLD_CONF
    a_ok = pair_confidence(kp, "left_ankle", "right_ankle") >= MIN_HOLD_CONF
    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_HOLD_CONF

    body = np.where(
        s_ok & h_ok,
        np.degrees(np.arctan2(np.abs(sh[:, 0] - hip[:, 0]),
                              np.maximum(np.abs(sh[:, 1] - hip[:, 1]), 1e-6))),
        np.nan,
    )
    elbow = np.concatenate([
        _angle(kp, S.KP_INDEX["left_shoulder"], S.KP_INDEX["left_elbow"],
               S.KP_INDEX["left_wrist"], s_ok & w_ok),
        _angle(kp, S.KP_INDEX["right_shoulder"], S.KP_INDEX["right_elbow"],
               S.KP_INDEX["right_wrist"], s_ok & w_ok),
    ])
    knee = np.concatenate([
        _angle(kp, S.KP_INDEX["left_hip"], S.KP_INDEX["left_knee"],
               S.KP_INDEX["left_ankle"], h_ok & a_ok),
        _angle(kp, S.KP_INDEX["right_hip"], S.KP_INDEX["right_knee"],
               S.KP_INDEX["right_ankle"], h_ok & a_ok),
    ])
    pike = np.concatenate([
        _angle(kp, S.KP_INDEX["left_shoulder"], S.KP_INDEX["left_hip"],
               S.KP_INDEX["left_knee"], s_ok & h_ok),
        _angle(kp, S.KP_INDEX["right_shoulder"], S.KP_INDEX["right_hip"],
               S.KP_INDEX["right_knee"], s_ok & h_ok),
    ])

    seg = slice(a, b + 1)
    body_seg = body[seg]
    hip_lat = (hip[:, 0] - sh[:, 0])[seg] / torso
    hip_lat = hip_lat[np.isfinite(hip_lat)]
    swing = float(np.percentile(hip_lat, 95) - np.percentile(hip_lat, 5)) \
        if hip_lat.size else np.nan

    return {
        "body_line_deg": _pct(body_seg, 50),
        "horizontal_frac": _frac(body_seg, HORIZONTAL),
        "arms_straight_frac": _frac(elbow, 160.0),
        "legs_straight_frac": _frac(knee, 160.0),
        "hip_pike_deg": _pct(pike, 50),
        "swing": swing,
        "sustain_s": (b - a) / fps,
    }


def _holds_signal(kp: np.ndarray) -> np.ndarray:
    """Per-frame body-line angle (degrees from vertical), NaN-safe."""
    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_HOLD_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_HOLD_CONF
    return np.where(
        s_ok & h_ok,
        np.degrees(np.arctan2(np.abs(sh[:, 0] - hip[:, 0]),
                              np.maximum(np.abs(sh[:, 1] - hip[:, 1]), 1e-6))),
        np.nan,
    )


def hold_attempts(kp: np.ndarray, fps: float, movement,
                  trace=None, variant: str = "unspecified") -> list[dict]:
    """The hold attempts in a clip, each as a rep-shaped observation.

    An attempt is a contiguous run where the body line is held at or past the
    horizontal band. Sustains shorter than MIN_HOLD_S are not attempts - a
    transient horizontal posture is not a hold, and the segmenter's sustained
    requirement is what separates the two.

    `variant` is the DECLARED variant (full / tuck / straddle) or unspecified.
    Rules written for another variant are left out of the assessment.
    """
    from .evidence import Evidence
    from .phases import hold_phases, phases_as_dict
    from .rules import assess
    from .trace import NullTrace
    tr = trace or NullTrace()
    body = _holds_signal(kp)
    n = len(body)
    if n < 3:
        return []
    held = np.isfinite(body) & (body >= HORIZONTAL)

    # Find contiguous runs of `held` frames, then trim each to where the body
    # was actually measured well enough to conclude anything.
    attempts: list[dict] = []
    i = 0
    while i < n:
        if not held[i]:
            i += 1
            continue
        j = i
        while j < n and held[j]:
            j += 1
        if (j - i) / fps >= MIN_HOLD_S:
            vals = _hold_metrics(kp, i, j - 1, fps)
            track = movement.name
            label = f"h{len(attempts) + 1}"
            ph = hold_phases(i, j - 1, fps)
            ev = Evidence(track=track)
            for key, value in vals.items():
                ev.add(key, value, phase="hold", window=(i, j - 1))
            assessments = assess(track, ev, variant)
            attempts.append({
                "label": label,
                "startS": round(i / fps, 2),
                "endS": round(j / fps, 2),
                "phases": phases_as_dict(ph, fps),
                "assessments": [a.as_dict(label, fps) for a in assessments],
                "assessmentBlocked": None,
                "faults": [{"name": a.rule.name, "primitive": a.rule.primitive,
                            "value": None if a.value is None else round(float(a.value), 4),
                            "threshold": round(float(a.rule.threshold), 4),
                            "comparison": a.rule.comparison, "unit": "",
                            "class": "SCALED", "errorId": a.rule.id,
                            "phase": "hold"}
                           for a in assessments if a.fired],
                "unmeasured": ev.unmeasured(),
                "viewBlocked": ev.view_blocked(),
                "metrics": [
                    {"name": "Sustain", "value": f"{vals['sustain_s']:.2f} s",
                     "class": "INVARIANT", "key": "sustain_s"},
                    {"name": "Body line", "value": f"{vals['body_line_deg']:.0f}°",
                     "class": "SCALED", "key": "body_line_deg"},
                    {"name": "Straight arms", "value": f"{vals['arms_straight_frac']:.0%}",
                     "class": "SCALED", "key": "arms_straight_frac"},
                    {"name": "Straight legs", "value": f"{vals['legs_straight_frac']:.0%}",
                     "class": "SCALED", "key": "legs_straight_frac"},
                ],
                "failures": [a.rule.name for a in assessments if a.fired],
                "plausible": True,
                "problems": [],
                "score": None,
                "band": "hold",
                "scoreNote": "A hold is not scored out of 100 - its body line "
                             "and failures are the read-out.",
                "complete": False,
                "penalties": [],
                "components": [],
                "aside": [],
                "trace": [],
            })
        i = j

    tr.step("hold attempts", n=len(attempts),
            attempts=[{"startS": a["startS"], "endS": a["endS"],
                       "failures": a["failures"],
                       "assessments": a["assessments"]} for a in attempts])
    return attempts


def hold_assessments(attempts: list[dict]) -> list[list]:
    """The Assessment objects behind each attempt's rows, rebuilt for the
    clip-level roll-up. Attempts carry dicts (the payload shape); the summary
    wants the objects, so the rows are re-read through the registry."""
    from .rules import Assessment, rule_by_id

    out = []
    for att in attempts:
        rows = []
        for row in att.get("assessments") or []:
            rule = rule_by_id(row.get("errorId", ""))
            if rule is None:
                continue
            ev = row.get("evidence") or {}
            rows.append(Assessment(rule, row.get("status", "unobservable"),
                                   ev.get("value"), "",
                                   (row.get("availability") or {}).get("detail", "")))
        out.append(rows)
    return out


def clip_failures(reps: list[dict]) -> dict[str, int]:
    """How many attempts showed each failure, for the clip-level read-out."""
    counts: dict[str, int] = {}
    for rep in reps:
        for f in rep.get("failures") or []:
            counts[f] = counts.get(f, 0) + 1
    return counts
