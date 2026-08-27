"""Stage 3 - reference template by DTW barycentre averaging.

Reference reps are marked BY HAND (`barra mark-reference`). There is no
automatic selection of "good" reps anywhere in this codebase: with no labels,
any automatic choice would be some function of the deviation score itself, and
the template would then be defined as "the reps that score well against the
template". That is circular and it manufactures a tight null distribution out
of nothing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import dtw
from . import schema as S
from .config import DBA_ITERATIONS, PATHS, RESAMPLE_LENGTH
from .io_utils import read_csv, write_csv, write_parquet
from .normalise import rep_trajectory
from .viewpoint import reps_with_bins, usable_bins


# ---------------------------------------------------------------------------
# Reference marking
# ---------------------------------------------------------------------------
def mark_reference(video: str, rep_specs: list[str], replace: bool = False) -> pd.DataFrame:
    reps = reps_with_bins()
    in_video = reps[reps["video"] == video]
    if in_video.empty:
        raise SystemExit(
            f"no reps for video {video!r}. Known videos: "
            + ", ".join(sorted(reps['video'].unique()))
        )

    wanted: set[str] = set()
    if len(rep_specs) == 1 and rep_specs[0].lower() == "all":
        wanted = set(in_video["rep_id"])
    else:
        by_index = {str(int(r["rep_index"])): r["rep_id"] for _, r in in_video.iterrows()}
        known = set(in_video["rep_id"])
        for spec in rep_specs:
            spec = spec.strip()
            if spec in known:
                wanted.add(spec)
            elif spec in by_index:
                wanted.add(by_index[spec])
            elif "-" in spec and all(p.isdigit() for p in spec.split("-", 1)):
                lo, hi = (int(p) for p in spec.split("-", 1))
                for i in range(lo, hi + 1):
                    if str(i) in by_index:
                        wanted.add(by_index[str(i)])
                    else:
                        raise SystemExit(f"{video}: no rep index {i}")
            else:
                raise SystemExit(
                    f"{video}: cannot resolve rep {spec!r}. Use a rep_index "
                    f"(0..{len(in_video)-1}), a range like 2-7, a full rep_id, or 'all'."
                )

    path = PATHS.o(S.P_REFERENCE)
    existing = pd.read_csv(path) if path.exists() and not replace else pd.DataFrame(
        columns=["rep_id", "video", "bin"]
    )
    existing = existing[existing["video"] != video] if replace else existing
    add = reps[reps["rep_id"].isin(wanted)][["rep_id", "video", "bin"]]
    out = (
        pd.concat([existing, add], ignore_index=True)
        .drop_duplicates(subset="rep_id")
        .sort_values("rep_id")
    )
    write_csv(out, path)

    print(f"  marked {len(add)} reference reps from {video}")
    for b, n in out["bin"].value_counts().items():
        flag = "" if n >= S.MIN_REFERENCE_REPS else f"  (need {S.MIN_REFERENCE_REPS})"
        print(f"    {b:<10} {n:>3} reference reps total{flag}")
    return out


def load_reference() -> pd.DataFrame:
    return read_csv(PATHS.o(S.P_REFERENCE), "mark-reference")


# ---------------------------------------------------------------------------
# Template construction
# ---------------------------------------------------------------------------
def load_rep(row: pd.Series, length: int = RESAMPLE_LENGTH) -> tuple[np.ndarray, np.ndarray]:
    """Time-normalised trajectory and confidence for one rep."""
    X, C = rep_trajectory(row["video"], int(row["start_frame"]), int(row["end_frame"]))
    if X.shape[0] < 4:
        raise ValueError(f"{row['rep_id']}: only {X.shape[0]} frames")
    return dtw.resample(X, length), dtw.resample(C, length)


def bottom_index(row: pd.Series, length: int = RESAMPLE_LENGTH) -> int:
    """Where the rep's turnaround falls after time normalisation.

    Reused from stage 0's segmentation rather than re-derived: in the
    normalised frame the hip midpoint IS the origin, so hip height carries no
    depth information any more and the turnaround has to come from the raw
    trajectory that defined the rep in the first place.
    """
    start, bottom, end = (int(row[k]) for k in ("start_frame", "bottom_frame", "end_frame"))
    span = max(end - start, 1)
    return int(round(np.clip((bottom - start) / span, 0.0, 1.0) * (length - 1)))


def pairwise_dtw(series: list[np.ndarray]) -> np.ndarray:
    n = len(series)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            D[i, j] = D[j, i] = dtw.distance(series[i], series[j])
    return D


def medoid(series: list[np.ndarray], D: np.ndarray | None = None) -> int:
    D = pairwise_dtw(series) if D is None else D
    return int(np.argmin(D.sum(axis=1)))


def dba(series: list[np.ndarray], weights: list[np.ndarray] | None = None,
        iterations: int = DBA_ITERATIONS, init: int | None = None) -> np.ndarray:
    """DTW barycentre averaging over multivariate trajectories.

    Initialised at the medoid rather than at an arithmetic mean: an arithmetic
    mean of unaligned reps is already smeared across the time axis, and DBA
    converges to a local optimum, so starting from a real rep keeps the
    template a shape the subject actually produces.
    """
    if not series:
        raise ValueError("no series to average")
    ref = series[medoid(series) if init is None else init].copy()
    L = ref.shape[0]
    for _ in range(iterations):
        acc = np.zeros_like(ref)
        wsum = np.zeros((L,) + ref.shape[1:-1] + (1,), dtype=np.float64)
        for k, s in enumerate(series):
            p = dtw.path(s, ref)
            w = weights[k] if weights is not None else np.ones(s.shape[:2])
            for i, j in p:
                wj = w[i][..., None]
                acc[j] += s[i] * wj
                wsum[j] += wj
        new = np.divide(acc, np.maximum(wsum, 1e-9))
        shift = float(np.linalg.norm(new - ref) / max(np.linalg.norm(ref), 1e-9))
        ref = new
        if shift < 1e-4:
            break
    return ref


def build_bin_template(bin_name: str, ref_rows: pd.DataFrame) -> dict:
    series, weights, ids, bottoms = [], [], [], []
    for _, r in ref_rows.iterrows():
        try:
            X, C = load_rep(r)
        except ValueError as e:
            print(f"    ! skipping {e}")
            continue
        series.append(X)
        weights.append(C)
        ids.append(r["rep_id"])
        bottoms.append(bottom_index(r))

    if len(series) < S.MIN_REFERENCE_REPS:
        raise SystemExit(
            f"{bin_name}: only {len(series)} usable reference reps, "
            f"{S.MIN_REFERENCE_REPS} required. Mark more with `barra mark-reference`."
        )

    T = dba(series, weights)
    # Pointwise band: spread of the reference reps once each is aligned to the
    # template. This is a description of the reference set, not a decision
    # rule - the decision rule is the leave-one-out null in stage 5.
    # One warping path per reference rep, reused for the coordinate band, the
    # confidence weights and the turnaround - they must all describe the same
    # alignment, not three independently recomputed ones.
    paths = [dtw.path(s_, T) for s_ in series]
    aligned = np.stack([dtw.align_to(s_, T) for s_ in series])        # (N, L, J, 2)
    q1 = np.percentile(aligned, 25, axis=0)
    q3 = np.percentile(aligned, 75, axis=0)
    conf_w = np.stack(
        [dtw.align_weights(w, T.shape[0], pth) for w, pth in zip(weights, paths)]
    ).mean(axis=0)

    # Turnaround on the template timeline: each reference rep's own bottom,
    # carried through its warping path onto the template, then the median.
    mapped = []
    for pth, b in zip(paths, bottoms):
        js = [j for i, j in pth if i == b]
        mapped.append(int(np.median(js)) if js else T.shape[0] // 2)
    bottom_t = int(np.clip(np.median(mapped), 1, T.shape[0] - 2))

    L, J = T.shape[0], T.shape[1]
    cols: dict[str, np.ndarray] = {"t": np.arange(L)}
    for j, name in enumerate(S.ANALYSIS_JOINTS):
        cols[f"t_{name}_x"] = T[:, j, 0]
        cols[f"t_{name}_y"] = T[:, j, 1]
        cols[f"q1_{name}_x"] = q1[:, j, 0]
        cols[f"q1_{name}_y"] = q1[:, j, 1]
        cols[f"q3_{name}_x"] = q3[:, j, 0]
        cols[f"q3_{name}_y"] = q3[:, j, 1]
        cols[f"w_{name}"] = conf_w[:, j]
    df = pd.DataFrame(cols)
    df["bottom_t"] = bottom_t
    df["n_reference"] = len(series)
    write_parquet(df, PATHS.o(S.P_TEMPLATE.format(bin=bin_name)))
    print(f"  + {bin_name}: template from {len(series)} reference reps, "
          f"L={L}, J={J}, turnaround at t={bottom_t}")
    return {"bin": bin_name, "n_reference": len(series), "rep_ids": ids,
            "bottom_t": bottom_t}


def run() -> list[dict]:
    reps = reps_with_bins()
    ref = load_reference()
    marked = reps[reps["rep_id"].isin(set(ref["rep_id"]))]
    ok_bins = usable_bins(reps)

    built = []
    for b in sorted(marked["bin"].unique()):
        rows = marked[marked["bin"] == b]
        if b == "UNKNOWN":
            print(f"  - UNKNOWN: {len(rows)} marked reps ignored (no comparable viewpoint)")
            continue
        if b not in ok_bins:
            print(f"  - {b}: underpowered bin ({len(reps[reps['bin']==b])} reps "
                  f"< {S.MIN_REPS_PER_BIN}) - excluded")
            continue
        built.append(build_bin_template(b, rows))
    if not built:
        raise SystemExit(
            "no template could be built. Mark at least "
            f"{S.MIN_REFERENCE_REPS} reference reps inside one usable viewpoint bin."
        )
    return built


def load_template(bin_name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Returns (T, q1, q3, conf_weights, bottom_t)."""
    from .io_utils import read_parquet

    df = read_parquet(PATHS.o(S.P_TEMPLATE.format(bin=bin_name)), "template")
    L, J = len(df), len(S.ANALYSIS_JOINTS)
    T = np.zeros((L, J, 2)); q1 = np.zeros((L, J, 2)); q3 = np.zeros((L, J, 2))
    W = np.zeros((L, J))
    for j, name in enumerate(S.ANALYSIS_JOINTS):
        T[:, j, 0] = df[f"t_{name}_x"]; T[:, j, 1] = df[f"t_{name}_y"]
        q1[:, j, 0] = df[f"q1_{name}_x"]; q1[:, j, 1] = df[f"q1_{name}_y"]
        q3[:, j, 0] = df[f"q3_{name}_x"]; q3[:, j, 1] = df[f"q3_{name}_y"]
        W[:, j] = df[f"w_{name}"]
    return T, q1, q3, W, int(df["bottom_t"].iloc[0])


def available_templates() -> list[str]:
    return sorted(
        p.stem.replace("template_", "")
        for p in PATHS.out.glob("template_*.parquet")
    )
