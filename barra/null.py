"""Stage 5 - the null distribution. This is the core of the tool.

No deviation number may be reported without this. A raw DTW residual of, say,
0.08 torso-lengths is meaningless on its own: the only question that matters is
how it compares with the distance between two reps the subject themselves would
call the same rep.

The null is built by leave-one-out over the reference reps: hold one out,
rebuild the template by DBA from the rest, score the held-out rep against it.
The held-out rep never contributes to the template it is scored against, which
is what stops the null from being artificially tight.

Two nulls are produced:

  pooled          - the template is rebuilt from every other reference rep.
                    This is the subject's rep-to-rep variation.
  cross_session   - the template is rebuilt only from reference reps recorded
                    on OTHER days. This is rep-to-rep variation plus whatever
                    changes between sessions: camera placement, warm-up, shoes,
                    load, fatigue, the estimator's own day-to-day behaviour.

The gap between those two is the answer to "can we track progress between
sessions". If cross_session is much wider than pooled, then a change measured
across sessions is mostly session nuisance and a genuine technique change has
to be large before it can be seen at all.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema as S
from .config import FLAG_PERCENTILE, PATHS
from .io_utils import read_parquet, write_parquet
from .score import score_rep
from .template import dba, load_rep, turn_index, pairwise_dtw
from .viewpoint import reps_with_bins

MIN_LOO_TEMPLATE_REPS = 4   # below this a rebuilt template is not meaningful


def _template_bottom(series_bottoms: list[int], fallback: int) -> int:
    return int(np.median(series_bottoms)) if series_bottoms else fallback


def loo_null(
    rows: pd.DataFrame, restrict: str = "pooled"
) -> pd.DataFrame:
    """Leave-one-out null over a set of reference reps.

    restrict:
      pooled        - rebuild from all other reference reps
      cross_session - rebuild only from reference reps of other sessions
    """
    series, weights, ids, sessions, bottoms = [], [], [], [], []
    for _, r in rows.iterrows():
        try:
            X, C = load_rep(r)
        except ValueError:
            continue
        series.append(X); weights.append(C)
        ids.append(r["rep_id"]); sessions.append(str(r["session_id"]))
        bottoms.append(turn_index(r))

    n = len(series)
    if n < S.MIN_REFERENCE_REPS:
        raise SystemExit(
            f"only {n} usable reference reps; {S.MIN_REFERENCE_REPS} required "
            "before a null distribution means anything."
        )
    D = pairwise_dtw(series)

    out = []
    for k in range(n):
        if restrict == "pooled":
            keep = [i for i in range(n) if i != k]
        elif restrict == "cross_session":
            keep = [i for i in range(n) if sessions[i] != sessions[k]]
        else:
            raise ValueError(restrict)
        if len(keep) < MIN_LOO_TEMPLATE_REPS:
            continue

        sub = [series[i] for i in keep]
        subw = [weights[i] for i in keep]
        subD = D[np.ix_(keep, keep)]
        init = int(np.argmin(subD.sum(axis=1)))
        T = dba(sub, subw, init=init)
        Wc = np.stack([w for w in subw]).mean(axis=0)
        bt = _template_bottom([bottoms[i] for i in keep], T.shape[0] // 2)

        sc = score_rep(series[k], weights[k], T, Wc, bt)
        row = {
            "rep_id": ids[k],
            "session_id": sessions[k],
            "kind": restrict,
            "n_template_reps": len(keep),
            "total": sc.total,
        }
        for j, name in enumerate(S.ANALYSIS_JOINTS):
            row[f"joint_{name}"] = float(sc.per_joint[j])
        for pi, name in enumerate(S.PHASE_NAMES):
            row[f"phase_{name}"] = float(sc.per_phase[pi])
        out.append(row)

    if not out:
        raise SystemExit(
            f"could not build a {restrict} null: not enough reps left after "
            "holding one out. For cross_session you need reference reps from "
            "at least two sessions."
        )
    return pd.DataFrame(out)


def build(bin_name: str, reference_ids: set[str]) -> pd.DataFrame:
    reps = reps_with_bins()
    rows = reps[(reps["bin"] == bin_name) & (reps["rep_id"].isin(reference_ids))]
    parts = [loo_null(rows, "pooled")]

    n_sessions = rows["session_id"].nunique()
    if n_sessions >= 2:
        try:
            parts.append(loo_null(rows, "cross_session"))
        except SystemExit as e:
            print(f"    - cross-session null unavailable: {e}")
    else:
        print(
            f"    - cross-session null unavailable: reference reps come from "
            f"{n_sessions} session(s). Mark reference reps on at least two "
            "different days to measure session-to-session drift."
        )

    df = pd.concat(parts, ignore_index=True)
    write_parquet(df, PATHS.o(S.P_NULL.format(bin=bin_name)))

    for kind, g in df.groupby("kind"):
        v = g["total"].to_numpy()
        print(
            f"  + {bin_name} null [{kind}]: n={len(v)} "
            f"median={np.median(v):.4f} p95={np.percentile(v, 95):.4f} "
            f"max={v.max():.4f} (torso-lengths)"
        )
    return df


def load(bin_name: str) -> pd.DataFrame:
    return read_parquet(PATHS.o(S.P_NULL.format(bin=bin_name)), "template")


# ---------------------------------------------------------------------------
# Decision rule
# ---------------------------------------------------------------------------
def percentile_of(value: float, null_values: np.ndarray) -> float:
    """Empirical percentile of `value` within the null.

    Uses the mean of the strict and non-strict ranks, so a value equal to a
    null observation is not silently pushed to one side.
    """
    v = np.asarray(null_values, dtype=float)
    if v.size == 0:
        return float("nan")
    below = float((v < value).sum())
    equal = float((v == value).sum())
    return 100.0 * (below + 0.5 * equal) / v.size


def threshold(null_values: np.ndarray, pct: float = FLAG_PERCENTILE) -> float:
    return float(np.percentile(np.asarray(null_values, dtype=float), pct))


def resolution_note(null_values: np.ndarray) -> dict:
    """How wide the null is, in the units a deviation would have to exceed.

    Reported so that a wide null is stated as the finding rather than hidden
    behind a confident-looking flag. `p95` is the smallest total deviation this
    tool can call abnormal at all; anything a technique error does that is
    smaller than that is invisible to it, by construction.
    """
    v = np.asarray(null_values, dtype=float)
    med = float(np.median(v))
    p95 = float(np.percentile(v, 95))
    return {
        "n": int(v.size),
        "median": med,
        "p95": p95,
        "iqr": float(np.percentile(v, 75) - np.percentile(v, 25)),
        "spread_ratio": float(p95 / med) if med > 0 else float("inf"),
        "min_detectable_deviation": p95,
        "resolution_limited": bool(v.size < 12),
    }
