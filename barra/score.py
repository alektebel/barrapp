"""Stage 4 - deviation scoring.

A score here is a *distance in the subject's own normalised units*, not a
grade. It says how far this rep sits from the subject's own reference shape.
Whether that distance means anything is decided in stage 5 and nowhere else -
`score_rep` deliberately returns no verdict and no threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import dtw
from . import schema as S
from .config import CONF_FLOOR


@dataclass
class RepScore:
    total: float
    per_joint: np.ndarray        # (J,)
    per_phase: np.ndarray        # (P,)
    residual: np.ndarray         # (J, P) joint x phase
    joint_weights: np.ndarray    # (J,) normalised, sums to 1
    aligned: np.ndarray          # (L, J, 2) test rep on the template timeline
    path: list[tuple[int, int]]


def phase_slices(L: int, bottom_t: int) -> list[tuple[str, slice]]:
    """Fractional segments of the aligned eccentric and concentric paths.

    Phases are fractions of the *aligned* path, not of wall-clock time, so a
    rep that grinds through its last third is compared against the template's
    last third rather than being smeared across the whole concentric.
    """
    n = S.PHASES_PER_HALF
    ecc = np.linspace(0, bottom_t, n + 1).round().astype(int)
    con = np.linspace(bottom_t, L, n + 1).round().astype(int)
    out = []
    for i in range(n):
        a, b = ecc[i], max(ecc[i + 1], ecc[i] + 1)
        out.append((f"ecc_{i+1}", slice(a, b)))
    for i in range(n):
        a, b = con[i], max(con[i + 1], con[i] + 1)
        out.append((f"con_{i+1}", slice(a, b)))
    return out


def joint_weights(test_conf: np.ndarray, template_conf: np.ndarray) -> np.ndarray:
    """Per-joint weights from mean keypoint confidence.

    A joint the pose estimator could not see must not dominate the score: its
    coordinates are mostly estimator noise, and unweighted it would contribute
    a large, meaningless residual. Weights are the product of the test rep's
    and the template's mean confidence for that joint - a joint has to be
    visible in BOTH to count - floored so that a briefly occluded joint is
    down-weighted rather than deleted, and normalised to sum to 1 so that the
    total is comparable across reps.
    """
    w = np.clip(test_conf.mean(axis=0), CONF_FLOOR, 1.0) * np.clip(
        template_conf.mean(axis=0), CONF_FLOOR, 1.0
    )
    total = w.sum()
    if total <= 0:
        return np.full(w.shape, 1.0 / w.size)
    return w / total


def score_rep(
    X: np.ndarray, C: np.ndarray, T: np.ndarray, W: np.ndarray, bottom_t: int
) -> RepScore:
    """Score one time-normalised rep (X, C) against a template (T, W).

    Residual at a (frame, joint) is the Euclidean distance between the aligned
    test position and the template position, in torso-lengths.
    """
    p = dtw.path(X, T)
    aligned = dtw.align_to(X, T)
    aligned_c = dtw.align_weights(C, T.shape[0], p)

    resid_lj = np.linalg.norm(aligned - T, axis=2)          # (L, J)
    wj = joint_weights(aligned_c, W)                        # (J,)

    phases = phase_slices(T.shape[0], bottom_t)
    resid_jp = np.zeros((T.shape[1], len(phases)))
    for k, (_, sl) in enumerate(phases):
        resid_jp[:, k] = resid_lj[sl].mean(axis=0)

    per_joint = resid_lj.mean(axis=0)                       # unweighted, per joint
    per_phase = (resid_jp * wj[:, None]).sum(axis=0)        # weighted across joints
    total = float((per_joint * wj).sum())

    return RepScore(
        total=total,
        per_joint=per_joint,
        per_phase=per_phase,
        residual=resid_jp,
        joint_weights=wj,
        aligned=aligned,
        path=p,
    )


# ---------------------------------------------------------------------------
# CLI stage: score every rep of a video against its bin's template
# ---------------------------------------------------------------------------
def run(video: str | None = None, render_qc: bool = True) -> "pd.DataFrame":
    import pandas as pd

    from . import null as null_mod
    from .config import FLAG_PERCENTILE, PATHS
    from .io_utils import write_csv
    from .template import available_templates, bottom_index, load_rep, load_template
    from .viewpoint import reps_with_bins

    reps = reps_with_bins()
    have = set(available_templates())
    if not have:
        raise SystemExit("no template on disk - run `barra template` first")

    targets = sorted(reps["video"].unique()) if video is None else [video]
    unknown = [v for v in targets if v not in set(reps["video"])]
    if unknown:
        raise SystemExit(f"unknown video(s): {', '.join(unknown)}")

    cache: dict[str, tuple] = {}
    rows = []
    for v in targets:
        sub = reps[reps["video"] == v]
        b = str(sub["bin"].iloc[0])
        if b not in have:
            print(f"  - {v}: bin {b} has no template - skipped "
                  f"(reps in {b} are never compared against another bin)")
            continue
        if b not in cache:
            T, q1, q3, W, bt = load_template(b)
            nl = null_mod.load(b)
            cache[b] = (T, q1, q3, W, bt, nl)
        T, q1, q3, W, bt, nl = cache[b]
        pooled = nl[nl["kind"] == "pooled"]

        for _, r in sub.iterrows():
            try:
                X, C = load_rep(r)
            except ValueError as e:
                print(f"  ! {e}")
                continue
            sc = score_rep(X, C, T, W, bt)
            pct = null_mod.percentile_of(sc.total, pooled["total"].to_numpy())
            thr = null_mod.threshold(pooled["total"].to_numpy(), FLAG_PERCENTILE)
            row = {
                "rep_id": r["rep_id"], "video": v, "session_id": r["session_id"],
                "bin": b, "is_reference": bool(r["rep_id"] in set(
                    pooled["rep_id"])),
                "total": sc.total, "null_percentile": pct,
                "null_p95": thr, "flagged": bool(sc.total > thr),
                "n_null": int(len(pooled)),
            }
            for j, name in enumerate(S.ANALYSIS_JOINTS):
                row[f"joint_{name}"] = float(sc.per_joint[j])
                row[f"joint_pct_{name}"] = null_mod.percentile_of(
                    sc.per_joint[j], pooled[f"joint_{name}"].to_numpy()
                )
                row[f"weight_{name}"] = float(sc.joint_weights[j])
            for pi, name in enumerate(S.PHASE_NAMES):
                row[f"phase_{name}"] = float(sc.per_phase[pi])
                row[f"phase_pct_{name}"] = null_mod.percentile_of(
                    sc.per_phase[pi], pooled[f"phase_{name}"].to_numpy()
                )
            rows.append(row)

            # Never a verdict without its percentile - spec section 11.4.
            print(
                f"  {r['rep_id']:<28} total={sc.total:.4f}  "
                f"null pct={pct:5.1f}  (p95={thr:.4f}, n={len(pooled)})  "
                f"{'FLAGGED' if sc.total > thr else 'within own variation'}"
            )
            if render_qc:
                from .qc import render_overlay

                try:
                    render_overlay(r, sc, T, q1, q3)
                except Exception as e:  # QC video is a convenience, not a result
                    print(f"    (qc overlay skipped: {e})")

    if not rows:
        raise SystemExit("nothing scored")

    new = pd.DataFrame(rows)
    path = PATHS.o(S.P_SCORES)
    if path.exists():
        old = pd.read_csv(path)
        old = old[~old["video"].isin(set(new["video"]))]
        new = pd.concat([old, new], ignore_index=True)
    write_csv(new.sort_values("rep_id"), path)
    return new
