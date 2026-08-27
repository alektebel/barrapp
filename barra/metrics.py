"""Per-rep objective metrics.

These exist because the full-skeleton deviation score of stages 4-5 is far more
fragile than it looks: `docs/FINDINGS.md` shows a few degrees of camera movement
displacing the normalised skeleton more than a deliberate technique error does.
When the footage is handheld, or shot from a different side on different days,
that score cannot support a between-session claim and the tool must not pretend
otherwise.

These metrics are chosen for how much of that fragility they avoid, and each one
is labelled with what it actually survives:

  INVARIANT   pure timing and counts. Independent of camera position, distance,
              lens and which side you filmed from. Comparable across any two
              sessions.
  SCALED      a length divided by the subject's own torso length. Independent of
              camera distance, but foreshortened as the camera swings off-axis,
              so only comparable within a viewpoint bin.
  PLANAR      only meaningful from a particular view - left/right symmetry needs
              a frontal or posterior camera, fore-aft swing needs a sagittal one.

Nothing here is a verdict. A metric is a measurement; deciding whether a change
in one means anything is `barra progress`, which compares it against the
subject's own within-session spread.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import schema as S
from .movements import Movement, midpoint, pair_confidence, robust_torso

# metric name -> (robustness class, human label, unit, higher_is_better|None)
METRIC_SPEC: dict[str, tuple[str, str, str, bool | None]] = {
    "concentric_s":       ("INVARIANT", "Concentric duration", "s", False),
    "eccentric_s":        ("INVARIANT", "Eccentric duration", "s", None),
    "total_s":            ("INVARIANT", "Rep duration", "s", None),
    "tempo_ratio":        ("INVARIANT", "Eccentric : concentric", "x", None),
    "transition_s":       ("INVARIANT", "Transition through the bar", "s", False),
    "top_hold_s":         ("INVARIANT", "Time held near lockout", "s", None),
    "rom":                ("SCALED", "Range of motion", "torso", True),
    "peak_height":        ("SCALED", "Lockout height above bar", "torso", True),
    "start_depth":        ("SCALED", "Start position below bar", "torso", True),
    "shoulder_asymmetry": ("PLANAR", "Shoulder asymmetry (concentric)", "torso", False),
    "turn_asymmetry":     ("PLANAR", "Shoulder asymmetry at turnaround", "torso", False),
    "swing":              ("PLANAR", "Body swing relative to the bar", "torso", False),
}

# A rep whose pose is this poor is measured but never compared.
MIN_REP_QUALITY = 0.55

# Tolerance on the anatomical plausibility checks: the subject's own segment
# lengths are themselves estimated from the same pose stream, so the band has
# to allow for error in the yardstick as well as in the measurement.
PLAUSIBILITY_MARGIN = 1.20


def arm_reach(kp: np.ndarray, min_conf: float = 0.6) -> float:
    """Extended shoulder-to-wrist reach for THIS clip, in its own torso-lengths.

    Measured per clip, not from the pooled subject profile, and that is
    deliberate. On real footage the torso-length divisor is not stable between
    clips - on this project's own muscle-up data the same person's arm:torso
    ratio came out anywhere from 0.76 to 1.9 depending on the clip, which is a
    statement about the hip landmarks during a muscle-up, not about his arms.
    A plausibility check built on the pooled figure therefore inherits that
    error and starts rejecting good reps. Measured inside one clip, numerator
    and denominator share the same divisor and the comparison is sound even
    when the divisor is not.

    A high percentile rather than a median, for the same reason the viewpoint
    calibration uses one: projection and elbow flexion can only ever shorten an
    apparent limb, never lengthen it.
    """
    reach = []
    for side in ("left", "right"):
        sh = kp[:, S.KP_INDEX[f"{side}_shoulder"]]
        wr = kp[:, S.KP_INDEX[f"{side}_wrist"]]
        ok = np.minimum(sh[:, 2], wr[:, 2]) >= min_conf
        if ok.sum() >= 10:
            d = np.linalg.norm(sh[ok, :2] - wr[ok, :2], axis=1)
            reach.append(np.percentile(d, 97))
    if not reach:
        return float("nan")
    return float(np.mean(reach) / robust_torso(kp))


def implausibilities(values: dict[str, float], movement: Movement,
                     arm: float) -> list[str]:
    """Physical checks against the subject's own anatomy.

    Keypoint confidence is not accuracy. A pose estimator handed a small,
    distant, motion-blurred subject returns confident nonsense, and every
    confidence-based quality score waves it through. These checks catch it,
    because geometry does not care how sure the model was: on a bar movement
    the shoulders cannot rise further above the hands than the arms are long.

    Direction matters. An ASCENDING bar movement starts hanging below the hands,
    so a rep that starts above them is a segmentation failure. A DESCENDING one
    - a dip, a push-up - starts above them by construction, and applying the
    hanging check to it rejects every correct rep. Found the hard way on a clip
    of 19 perfectly segmented push-ups, none of which scored.
    """
    if movement.origin != "wrist" or not usable_reference(arm):
        return []
    limit = arm * PLAUSIBILITY_MARGIN
    out = []
    peak, depth = values.get("peak_height"), values.get("start_depth")
    if np.isfinite(peak) and abs(peak) > limit:
        out.append(
            f"shoulders reach {abs(peak):.2f} torso from the hands but the arms "
            f"are only {arm:.2f} long - the wrist or shoulder track is wrong"
        )
    if movement.direction == "ascending":
        if np.isfinite(depth) and depth < 0:
            out.append(
                f"rep starts {-depth:.2f} torso ABOVE the bar, so the detected "
                "start is not a hang"
            )
        elif np.isfinite(depth) and depth > limit:
            out.append(
                f"rep starts {depth:.2f} torso below the bar, deeper than an "
                f"arm length ({arm:.2f})"
            )
    if np.isfinite(values.get("rom", np.nan)) and values["rom"] > 2 * limit:
        out.append(f"range of motion {values['rom']:.2f} torso exceeds twice the arm reach")
    return out


# Anatomical band for shoulder-to-wrist reach in torso-lengths. Real adults sit
# near 1.2. Outside this band the TORSO is what was measured wrongly, not the
# arm - filmed head-on, a push-up's torso projects to almost nothing and the
# ratio came out at 2.7 on real footage. Every length in torso units is then
# meaningless, so they are reported as unmeasurable rather than scored.
REACH_BAND = (0.60, 1.90)


def usable_reference(arm: float) -> bool:
    return bool(np.isfinite(arm) and REACH_BAND[0] <= arm <= REACH_BAND[1])


@dataclass
class RepMetrics:
    values: dict[str, float]
    quality: dict[str, float]
    problems: list[str]

    @property
    def plausible(self) -> bool:
        return not self.problems

    def row(self) -> dict:
        return {
            **self.values,
            **{f"q_{k}": v for k, v in self.quality.items()},
            "plausible": self.plausible,
            "problems": "; ".join(self.problems),
        }


def _series(kp: np.ndarray, movement: Movement) -> dict[str, np.ndarray]:
    """Bar-referenced (or hip-referenced) geometry for a whole clip."""
    torso = robust_torso(kp)
    if movement.origin == "wrist":
        origin = midpoint(kp, "left_wrist", "right_wrist")
        origin_conf = pair_confidence(kp, "left_wrist", "right_wrist")
    else:
        origin = midpoint(kp, "left_hip", "right_hip")
        origin_conf = pair_confidence(kp, "left_hip", "right_hip")

    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    ls = kp[:, S.KP_INDEX["left_shoulder"], :2]
    rs = kp[:, S.KP_INDEX["right_shoulder"], :2]

    return {
        "torso": torso,
        # image y grows downward, so origin_y - point_y is height ABOVE the origin
        "shoulder_above": (origin[:, 1] - sh[:, 1]) / torso,
        "hip_above": (origin[:, 1] - hip[:, 1]) / torso,
        "hip_lateral": (hip[:, 0] - origin[:, 0]) / torso,
        "shoulder_tilt": np.abs(ls[:, 1] - rs[:, 1]) / torso,
        "conf": np.minimum(
            origin_conf, pair_confidence(kp, "left_shoulder", "right_shoulder")
        ),
        "conf_all": kp[:, S.ANALYSIS_IDX, 2].mean(axis=1),
    }


def rep_metrics(kp: np.ndarray, start: int, turn: int, end: int, fps: float,
                movement: Movement, anatomy: dict | None = None) -> RepMetrics:
    s = _series(kp, movement)
    sl = slice(start, end + 1)
    up = slice(start, turn + 1)

    above = s["shoulder_above"][sl]
    conf = s["conf"][sl]
    n = max(len(above), 1)
    fps = max(float(fps), 1.0)

    peak = float(np.nanmax(above)) if n else np.nan
    begin = float(above[0]) if n else np.nan

    # Transition: time the shoulders spend crossing the plane of the bar. On a
    # muscle-up this is the part that fails, and it is pure timing, so it is
    # comparable across sessions filmed however you like.
    band = 0.15
    crossing = np.abs(s["shoulder_above"][up]) <= band
    transition_s = float(crossing.sum()) / fps

    # Time spent near lockout, as a fraction of the rep's own amplitude, so a
    # shallow rep is not credited with a long hold.
    hold_gate = begin + 0.85 * (peak - begin) if np.isfinite(peak) else np.inf
    top_hold_s = float((above >= hold_gate).sum()) / fps

    concentric_s = max(turn - start, 1) / fps
    eccentric_s = max(end - turn, 1) / fps

    lateral = s["hip_lateral"][sl]
    lateral = lateral[np.isfinite(lateral)]
    swing = float(np.percentile(lateral, 95) - np.percentile(lateral, 5)) if lateral.size else np.nan

    tilt_up = s["shoulder_tilt"][up]
    tilt_up = tilt_up[np.isfinite(tilt_up)]

    values = {
        "concentric_s": concentric_s,
        "eccentric_s": eccentric_s,
        "total_s": (end - start) / fps,
        "tempo_ratio": eccentric_s / concentric_s,
        "transition_s": transition_s,
        "top_hold_s": top_hold_s,
        "rom": peak - begin,
        "peak_height": peak,
        "start_depth": -begin,          # positive = started from a deeper hang
        "shoulder_asymmetry": float(np.median(tilt_up)) if tilt_up.size else np.nan,
        "turn_asymmetry": float(s["shoulder_tilt"][turn]),
        "swing": swing,
    }

    mean_conf = float(np.nanmean(conf)) if n else 0.0
    quality = {
        "mean_conf": mean_conf,
        "turn_conf": float(s["conf"][turn]),
        "body_conf": float(np.nanmean(s["conf_all"][sl])),
        "observed_frac": float(np.mean(conf >= 0.35)) if n else 0.0,
    }
    quality["rep"] = float(
        np.mean([quality["mean_conf"], quality["turn_conf"],
                 quality["body_conf"], quality["observed_frac"]])
    )
    arm = arm_reach(kp)
    quality["arm_reach"] = arm
    problems = implausibilities(values, movement, arm)
    return RepMetrics(values, quality, problems)


def compute_all(reps: pd.DataFrame, keypoints_of,
                anatomy: dict | None = None) -> pd.DataFrame:
    """Metrics for every rep in reps.csv. `keypoints_of(video)` returns (T,17,3)."""
    from .movements import resolve

    rows = []
    cache: dict[str, np.ndarray] = {}
    for _, r in reps.iterrows():
        v = str(r["video"])
        if v not in cache:
            cache[v] = keypoints_of(v)
        m = rep_metrics(
            cache[v], int(r["start_frame"]), int(r["turn_frame"]), int(r["end_frame"]),
            float(r["fps"]), resolve(r.get("exercise")), anatomy,
        )
        rows.append({
            "rep_id": r["rep_id"], "video": v, "session_id": str(r["session_id"]),
            "exercise": r.get("exercise"), "rep_index": int(r["rep_index"]),
            **m.row(),
        })
    return pd.DataFrame(rows)
