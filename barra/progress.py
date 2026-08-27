"""Cross-session progress, measured against the subject's own within-session
variation.

The discipline is the same one stage 5 applies to the deviation score, moved
onto scalar metrics: a number on its own means nothing, and a difference
between two session medians means nothing until you know how much that number
moves from rep to rep *inside* a single session.

So the null here is the pooled within-session rep-to-rep spread. A
between-session change is reported as a multiple of it, never as a bare
difference, and is called supported only when three things hold at once:

  1. both sessions have enough reps for a median to mean anything,
  2. the change exceeds the within-session noise by a clear margin,
  3. the metric is comparable between those two sessions at all - a length
     measured from behind and a length measured from the front are different
     quantities, so viewpoint-sensitive metrics are gated on the viewpoint bin.

When those do not hold, this module says so and says what would fix it. The
required-reps calculation is the useful half of a negative result: it converts
"not enough data" into a number of reps to record next session.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import METRIC_SPEC, MIN_REP_QUALITY

# A median from fewer reps than this is not a session summary, it is one rep.
MIN_REPS_PER_SESSION = 3
# Change must exceed this many pooled within-session SDs to be called supported.
EFFECT_THRESHOLD = 2.0
# Target change used for the "how many reps would I need" calculation.
DEFAULT_TARGET_FRAC = 0.10


def _pooled_noise(df: pd.DataFrame, metric: str) -> tuple[float, int, int]:
    """Within-session rep-to-rep spread, pooled over sessions.

    Deviations are taken from each session's OWN median, so a real
    between-session shift does not leak into the noise estimate and inflate it.
    """
    devs, n_sessions = [], 0
    for _, g in df.groupby("session_id"):
        v = g[metric].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        if v.size < 2:
            continue
        devs.append(v - np.median(v))
        n_sessions += 1
    if not devs:
        return float("nan"), 0, 0
    pooled = np.concatenate(devs)
    # ddof accounts for the median estimated per session
    sd = float(np.sqrt(np.sum(pooled ** 2) / max(len(pooled) - n_sessions, 1)))
    return sd, n_sessions, int(len(pooled))


def _reps_needed(sd: float, target: float) -> float:
    """Reps per session to detect a change of `target`, two-sided, 5% and 80%.

    n >= 2 * (z_{0.975} + z_{0.80})^2 * sd^2 / target^2
    """
    if not np.isfinite(sd) or target <= 0 or sd <= 0:
        return float("nan")
    return float(np.ceil(2 * (1.96 + 0.8416) ** 2 * (sd / target) ** 2))


def session_table(reps: pd.DataFrame) -> pd.DataFrame:
    """One row per session: rep count, quality, viewpoint, per-metric medians."""
    rows = []
    for sid, g in reps.groupby("session_id"):
        row = {
            "session_id": str(sid),
            "n_reps": int(len(g)),
            "n_usable": int((g["q_rep"] >= MIN_REP_QUALITY).sum()),
            "mean_quality": float(g["q_rep"].mean()),
            "bins": ",".join(sorted({str(b) for b in g.get("bin", pd.Series(dtype=str)).dropna()}))
            or "unknown",
            "side": ",".join(sorted({str(x) for x in g.get("side", pd.Series(dtype=str)).dropna()}))
            or "unknown",
            "arm_reach": float(np.nanmedian(g["q_arm_reach"]))
            if "q_arm_reach" in g.columns else np.nan,
        }
        for m in METRIC_SPEC:
            if m in g.columns:
                v = g[m].to_numpy(dtype=float)
                v = v[np.isfinite(v)]
                row[m] = float(np.median(v)) if v.size else np.nan
                row[f"{m}__n"] = int(v.size)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("session_id").reset_index(drop=True)


# How far the subject's apparent arm:torso ratio may drift between two sessions
# before lengths measured in torso-units stop being comparable.
MAX_SCALE_DRIFT = 0.15


def _comparable(a: pd.Series, b: pd.Series, robustness: str) -> tuple[bool, str]:
    """Is this metric comparable between these two sessions?

    Three gates, and every one of them was earned by real footage rather than
    guessed at:

      viewpoint  - a length foreshortens as the camera swings off-axis, so a
                   length from one bin is not the same quantity as a length
                   from another.
      side       - front and back are mirror images; a left shoulder compared
                   against a right one is not a measurement.
      scale      - the torso-length divisor is itself estimated from the pose,
                   and on real footage it drifts between clips. If the
                   subject's own arm:torso ratio moves between two sessions,
                   the ruler changed, and any change in a length measured with
                   it is uninterpretable.
    """
    if robustness == "INVARIANT":
        return True, ""
    ba, bb = str(a.get("bins", "unknown")), str(b.get("bins", "unknown"))
    if "unknown" in (ba, bb) or not ba or not bb:
        return False, "viewpoint of one session is unknown"
    if ba != bb:
        return False, f"filmed from different viewpoints ({ba} vs {bb})"
    if "," in ba:
        return False, f"a session mixes viewpoints ({ba})"

    sa, sb = a.get("side", "unknown"), b.get("side", "unknown")
    if robustness == "PLANAR":
        if "unknown" in (str(sa), str(sb)):
            return False, "camera side of one session is unknown"
        if sa != sb:
            return False, (
                f"filmed from opposite sides ({sa} vs {sb}); left and right are "
                "mirrored between them"
            )

    ra, rb = a.get("arm_reach", np.nan), b.get("arm_reach", np.nan)
    if np.isfinite(ra) and np.isfinite(rb) and min(ra, rb) > 0:
        drift = abs(ra - rb) / min(ra, rb)
        if drift > MAX_SCALE_DRIFT:
            return False, (
                f"the torso-length ruler drifted {drift:.0%} between these "
                f"sessions (arm:torso {ra:.2f} vs {rb:.2f}), so lengths measured "
                "in torso units are not the same quantity"
            )
    return True, ""


def compare(reps: pd.DataFrame, sessions: pd.DataFrame | None = None) -> dict:
    sessions = session_table(reps) if sessions is None else sessions
    order = sessions["session_id"].tolist()

    noise = {}
    for m in METRIC_SPEC:
        if m in reps.columns:
            sd, ns, nd = _pooled_noise(reps, m)
            noise[m] = {"sd": sd, "n_sessions": ns, "n_deviations": nd,
                        "robustness": METRIC_SPEC[m][0]}

    comparisons = []
    pairs = [(order[i], order[i + 1]) for i in range(len(order) - 1)]
    if len(order) > 2:
        pairs.append((order[0], order[-1]))

    for a_id, b_id in pairs:
        a = sessions[sessions["session_id"] == a_id].iloc[0]
        b = sessions[sessions["session_id"] == b_id].iloc[0]
        for m, (robustness, label, unit, higher_better) in METRIC_SPEC.items():
            if m not in sessions.columns:
                continue
            va, vb = a[m], b[m]
            if not (np.isfinite(va) and np.isfinite(vb)):
                continue
            sd = noise.get(m, {}).get("sd", float("nan"))
            na, nb = int(a.get(f"{m}__n", 0)), int(b.get(f"{m}__n", 0))
            change = float(vb - va)

            ok_view, view_reason = _comparable(a, b, robustness)
            enough = na >= MIN_REPS_PER_SESSION and nb >= MIN_REPS_PER_SESSION
            se = (sd * np.sqrt(1 / max(na, 1) + 1 / max(nb, 1))
                  if np.isfinite(sd) and sd > 0 else float("nan"))
            effect = change / se if np.isfinite(se) and se > 0 else float("nan")

            reasons = []
            if not ok_view:
                reasons.append(view_reason)
            if not enough:
                reasons.append(
                    f"only {na} and {nb} reps; {MIN_REPS_PER_SESSION} per session "
                    "is the minimum for a median to mean anything"
                )
            if not np.isfinite(sd):
                reasons.append(
                    "no within-session spread could be estimated - no session has "
                    "two or more reps of this metric"
                )
            supported = bool(
                ok_view and enough and np.isfinite(effect)
                and abs(effect) >= EFFECT_THRESHOLD
            )
            if ok_view and enough and np.isfinite(effect) and not supported:
                reasons.append(
                    f"change is {abs(effect):.1f}x the noise, below the "
                    f"{EFFECT_THRESHOLD:.0f}x bar"
                )

            direction = None
            if higher_better is not None and supported:
                direction = "better" if (change > 0) == higher_better else "worse"

            comparisons.append({
                "from": a_id, "to": b_id, "metric": m, "label": label,
                "unit": unit, "robustness": robustness,
                "from_value": float(va), "to_value": float(vb), "change": change,
                "pct_change": float(change / va * 100) if va else np.nan,
                "n_from": na, "n_to": nb,
                "noise_sd": sd, "effect": effect,
                "supported": supported, "direction": direction,
                "blockers": reasons,
            })

    # A spread estimated from a handful of deviations is itself very uncertain,
    # so the reps-needed figures below inherit that uncertainty. Flagged rather
    # than dropped: an unreliable estimate of "you need more reps" is still
    # more useful than silence, as long as it is labelled.
    requirements = {}
    for m, nz in noise.items():
        sd = nz["sd"]
        typical = float(np.nanmedian(sessions[m])) if m in sessions.columns else np.nan
        target = abs(typical) * DEFAULT_TARGET_FRAC if np.isfinite(typical) else np.nan
        requirements[m] = {
            "sd": sd, "typical": typical, "target": target,
            "reps_per_session": _reps_needed(sd, target),
            "label": METRIC_SPEC[m][1], "unit": METRIC_SPEC[m][2],
            "robustness": nz["robustness"],
            "n_deviations": nz["n_deviations"],
            "estimate_reliable": bool(nz["n_deviations"] >= 8),
        }

    return {
        "sessions": sessions,
        "comparisons": pd.DataFrame(comparisons),
        "noise": noise,
        "requirements": requirements,
        "verdict": _verdict(sessions, comparisons),
    }


def _verdict(sessions: pd.DataFrame, comparisons: list[dict]) -> dict:
    n_sessions = len(sessions)
    usable = sessions[sessions["n_reps"] >= MIN_REPS_PER_SESSION]
    supported = [c for c in comparisons if c["supported"]]

    if n_sessions < 2:
        return {"trackable": False, "statement":
                "Progress cannot be assessed: the profile holds one session. "
                "Two sessions is the minimum, and each needs enough reps for a "
                "median to mean anything."}
    if len(usable) < 2:
        thin = ", ".join(
            f"{r['session_id']} ({r['n_reps']} rep{'s' if r['n_reps'] != 1 else ''})"
            for _, r in sessions.iterrows()
        )
        return {"trackable": False, "statement":
                f"Progress cannot be assessed yet: {thin}. Fewer than "
                f"{MIN_REPS_PER_SESSION} usable reps in a session means the "
                "session median is one or two reps, and rep-to-rep variation "
                "cannot be separated from session-to-session change at all."}
    if not supported:
        return {"trackable": True, "statement":
                "Sessions are comparable, but no metric changed by more than "
                f"{EFFECT_THRESHOLD:.0f}x the subject's own rep-to-rep variation. "
                "That is a real result: on this evidence, technique is stable "
                "rather than improving or declining."}
    better = [c for c in supported if c["direction"] == "better"]
    worse = [c for c in supported if c["direction"] == "worse"]
    parts = []
    if better:
        parts.append("improved in " + ", ".join(sorted({c["label"] for c in better})))
    if worse:
        parts.append("declined in " + ", ".join(sorted({c["label"] for c in worse})))
    neutral = [c for c in supported if c["direction"] is None]
    if neutral:
        parts.append("changed in " + ", ".join(sorted({c["label"] for c in neutral})))
    return {"trackable": True, "statement":
            "Measurable change beyond rep-to-rep variation: " + "; ".join(parts) + "."}
