"""Stage 6 - validation protocol. Mandatory before the tool may be believed.

Reports detection rate per induced error type AND false positive rate on
held-out clean reps. Always both. A detection rate on its own is not evidence
of anything: a tool that flags every rep detects every error.

Ground truth comes from out/labels.csv, written by the user:

    rep_id,label,edge_of_bin,note
    2026-08-27__squat__set01#r00,clean,false,
    2026-08-27__squat__set03#r02,knee_valgus,false,deliberate
    2026-08-27__squat__set05#r01,clean,true,filmed at ~19 deg

`label` is "clean" or a name the user chose for the induced error. The names
are not interpreted anywhere in this codebase - the tool has no idea what
"knee_valgus" means and makes no claim about why a rep deviated.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import null as null_mod
from . import schema as S
from .config import (FLAG_PERCENTILE, MAX_ACCEPTABLE_FPR,
                     MIN_ACCEPTABLE_DETECTION, PATHS)
from .io_utils import config_fingerprint, read_csv, read_json, write_json
from .score import score_rep
from .template import load_rep, load_template
from .viewpoint import reps_with_bins

LOCK = "threshold_lock.json"


def _threshold_lock() -> dict:
    """Record the decision-threshold fingerprint the first time labels exist.

    Section 8 forbids tuning a threshold after seeing labels. This cannot stop
    anyone editing config.py, but it makes the edit visible: the lock is
    written on the first validate run and every later run compares against it.
    """
    path = PATHS.o(LOCK)
    now = {"config_fingerprint": config_fingerprint(), "flag_percentile": FLAG_PERCENTILE}
    if not path.exists():
        write_json({**now, "locked_at": pd.Timestamp.utcnow().isoformat()}, path)
        return {**now, "changed_since_lock": False, "first_run": True}
    prev = read_json(path, "validate")
    changed = (
        prev.get("config_fingerprint") != now["config_fingerprint"]
        or prev.get("flag_percentile") != now["flag_percentile"]
    )
    return {**now, "changed_since_lock": bool(changed), "first_run": False,
            "locked": prev}


def load_labels() -> pd.DataFrame:
    df = read_csv(PATHS.o(S.P_LABELS), "validate (write out/labels.csv by hand)")
    if "label" not in df.columns or "rep_id" not in df.columns:
        raise SystemExit("labels.csv needs at least rep_id and label columns")
    if "edge_of_bin" not in df.columns:
        df["edge_of_bin"] = False
    df["edge_of_bin"] = df["edge_of_bin"].fillna(False).astype(str).str.lower().isin(
        ["true", "1", "yes"]
    )
    df["label"] = df["label"].astype(str).str.strip()
    return df


def run() -> dict:
    from .template import available_templates, bottom_index

    reps = reps_with_bins()
    labels = load_labels()
    ref_ids = set(read_csv(PATHS.o(S.P_REFERENCE), "mark-reference")["rep_id"])
    lock = _threshold_lock()

    unknown = set(labels["rep_id"]) - set(reps["rep_id"])
    if unknown:
        raise SystemExit(
            f"labels.csv names {len(unknown)} unknown rep_id(s), e.g. "
            f"{sorted(unknown)[:3]}. Rep ids come from out/reps.csv."
        )

    m = labels.merge(reps, on="rep_id", how="left")
    m["is_reference"] = m["rep_id"].isin(ref_ids)
    results = {"bins": {}, "threshold_lock": lock,
               "flag_percentile": FLAG_PERCENTILE}

    for b in sorted(set(m["bin"]) & set(available_templates())):
        sub = m[m["bin"] == b]
        clean = sub[sub["label"].str.lower() == "clean"]
        held_out = clean[~clean["is_reference"]]
        n_clean = len(clean)
        holdout_frac = len(held_out) / n_clean if n_clean else 0.0

        entry: dict = {
            "n_labelled": int(len(sub)),
            "n_clean": int(n_clean),
            "n_clean_held_out": int(len(held_out)),
            "clean_holdout_fraction": round(holdout_frac, 3),
        }

        if holdout_frac < S.MIN_CLEAN_HOLDOUT_FRAC:
            need = int(np.ceil(S.MIN_CLEAN_HOLDOUT_FRAC * n_clean)) - len(held_out)
            entry["error"] = (
                f"only {holdout_frac:.0%} of clean reps are held out of the "
                f"reference set; {S.MIN_CLEAN_HOLDOUT_FRAC:.0%} is required. "
                f"Un-mark at least {need} more clean rep(s) as reference "
                "(`barra mark-reference <video> <ids> --replace`) and rebuild "
                "the template. FPR must never be estimated on reps that built "
                "the template."
            )
            results["bins"][b] = entry
            print(f"  ! {b}: {entry['error']}")
            continue

        T, q1, q3, W, bt = load_template(b)
        nl = null_mod.load(b)
        pooled = nl[nl["kind"] == "pooled"]
        thr = null_mod.threshold(pooled["total"].to_numpy(), FLAG_PERCENTILE)

        rows = []
        for _, r in sub.iterrows():
            if r["is_reference"]:
                continue   # scored inside the null already; never a test case
            try:
                X, C = load_rep(r)
            except ValueError:
                continue
            sc = score_rep(X, C, T, W, bt)
            pct = null_mod.percentile_of(sc.total, pooled["total"].to_numpy())
            rows.append({
                "rep_id": r["rep_id"], "label": r["label"],
                "edge_of_bin": bool(r["edge_of_bin"]),
                "session_id": r["session_id"],
                "total": sc.total, "null_percentile": pct,
                "flagged": bool(sc.total > thr),
            })

        res = pd.DataFrame(rows)
        if res.empty:
            entry["error"] = "no non-reference labelled reps to test"
            results["bins"][b] = entry
            continue

        is_clean = res["label"].str.lower() == "clean"
        core = res[is_clean & ~res["edge_of_bin"]]
        edge = res[is_clean & res["edge_of_bin"]]

        fpr = float(core["flagged"].mean()) if len(core) else float("nan")
        fpr_edge = float(edge["flagged"].mean()) if len(edge) else float("nan")
        all_clean_fpr = float(res[is_clean]["flagged"].mean())

        detection = {}
        for label, g in res[~is_clean].groupby("label"):
            detection[label] = {
                "n": int(len(g)),
                "detected": int(g["flagged"].sum()),
                "rate": float(g["flagged"].mean()),
                "median_percentile": float(g["null_percentile"].median()),
            }
        errs = res[~is_clean]
        overall_det = float(errs["flagged"].mean()) if len(errs) else float("nan")

        entry.update({
            "threshold": thr,
            "null": null_mod.resolution_note(pooled["total"].to_numpy()),
            "fpr_core_clean": fpr,
            "n_core_clean": int(len(core)),
            "fpr_edge_of_bin": fpr_edge,
            "n_edge_clean": int(len(edge)),
            "fpr_all_clean": all_clean_fpr,
            "detection_overall": overall_det,
            "detection_by_error": detection,
            "per_rep": res.to_dict("records"),
        })
        entry["verdict"] = _verdict(fpr, overall_det, entry)
        entry["session_analysis"] = _session_analysis(nl, res)
        results["bins"][b] = entry
        _print_bin(b, entry)

    if not results["bins"]:
        raise SystemExit("no labelled reps fall in a bin that has a template")

    results["overall_verdict"] = _overall(results["bins"])
    write_json(results, PATHS.o(S.P_VALIDATION))
    print(f"\n  VERDICT: {results['overall_verdict']['statement']}")
    return results


def _verdict(fpr: float, detection: float, entry: dict) -> dict:
    reasons = []
    works = True
    if np.isnan(fpr) or entry["n_core_clean"] < 5:
        works = False
        reasons.append(
            f"too few held-out clean reps ({entry['n_core_clean']}) to estimate "
            "a false positive rate; the FPR figure is not usable evidence"
        )
    elif fpr > MAX_ACCEPTABLE_FPR:
        works = False
        reasons.append(
            f"false positive rate {fpr:.0%} exceeds the {MAX_ACCEPTABLE_FPR:.0%} "
            "limit - it flags the subject's own clean reps too often"
        )
    if np.isnan(detection):
        works = False
        reasons.append("no induced-error reps were labelled, so detection rate is unknown")
    elif detection < MIN_ACCEPTABLE_DETECTION:
        works = False
        reasons.append(
            f"detection rate {detection:.0%} is below the "
            f"{MIN_ACCEPTABLE_DETECTION:.0%} floor - the induced errors fall "
            "inside the subject's own rep-to-rep variation"
        )
    return {"works": works, "reasons": reasons,
            "fpr": None if np.isnan(fpr) else fpr,
            "detection": None if np.isnan(detection) else detection}


def _session_analysis(nl: pd.DataFrame, res: pd.DataFrame) -> dict:
    """Can a change be tracked between sessions, or is it swamped by drift?

    Compares the width of the within-reference (pooled) null against the
    cross-session null. If holding out a whole session widens the null
    materially, then two sessions of the same technique already look different
    to this tool, and any between-session change smaller than that gap is not
    measurable.
    """
    pooled = nl[nl["kind"] == "pooled"]["total"].to_numpy()
    cross = nl[nl["kind"] == "cross_session"]["total"].to_numpy()
    out = {
        "pooled_p95": float(np.percentile(pooled, 95)),
        "pooled_median": float(np.median(pooled)),
        "cross_session_available": bool(cross.size > 0),
    }
    if cross.size == 0:
        out["conclusion"] = (
            "Not measurable: reference reps come from a single session. Mark "
            "reference reps on at least two different days before making any "
            "claim about progress between sessions."
        )
        return out

    out.update({
        "cross_session_p95": float(np.percentile(cross, 95)),
        "cross_session_median": float(np.median(cross)),
        "inflation_ratio": float(np.median(cross) / max(np.median(pooled), 1e-9)),
    })
    clean = res[res["label"].str.lower() == "clean"]
    by_session = (
        clean.groupby("session_id")["total"].median().to_dict() if len(clean) else {}
    )
    out["clean_median_by_session"] = {k: float(v) for k, v in by_session.items()}
    if len(by_session) >= 2:
        vals = np.array(list(by_session.values()))
        out["between_session_spread"] = float(vals.max() - vals.min())
        out["exceeds_cross_session_null"] = bool(
            out["between_session_spread"] > out["cross_session_p95"]
        )
    ratio = out["inflation_ratio"]
    out["conclusion"] = (
        f"Holding out a whole session inflates the median null deviation by "
        f"{ratio:.2f}x. A between-session change must exceed "
        f"{out['cross_session_p95']:.4f} torso-lengths before it can be "
        "distinguished from ordinary session-to-session drift."
    )
    return out


def _overall(bins: dict) -> dict:
    usable = {b: e for b, e in bins.items() if "verdict" in e}
    if not usable:
        return {"works": False, "statement":
                "the tool does not work: no bin completed the validation protocol"}
    works = [b for b, e in usable.items() if e["verdict"]["works"]]
    if works:
        b = works[0]
        e = usable[b]
        return {"works": True, "bins_passing": works, "statement":
                f"the tool works in {', '.join(works)}: FPR "
                f"{e['verdict']['fpr']:.0%} on held-out clean reps, detection "
                f"{e['verdict']['detection']:.0%} on induced errors"}
    reasons = "; ".join(
        f"{b}: {'; '.join(e['verdict']['reasons'])}" for b, e in usable.items()
    )
    return {"works": False, "bins_passing": [], "statement":
            f"the tool does not work on this data - {reasons}"}


def _print_bin(b: str, e: dict) -> None:
    print(f"\n  [{b}]")
    print(f"    null (leave-one-out, n={e['null']['n']}): "
          f"median {e['null']['median']:.4f}, p95 {e['null']['p95']:.4f} torso-lengths")
    print(f"    threshold (p{FLAG_PERCENTILE:g} of null) = {e['threshold']:.4f}")
    print(f"    FPR on held-out clean reps (n={e['n_core_clean']}): "
          f"{e['fpr_core_clean']:.0%}")
    if e["n_edge_clean"]:
        print(f"    FPR on clean reps at the edge of the bin "
              f"(n={e['n_edge_clean']}): {e['fpr_edge_of_bin']:.0%}")
    for label, d in sorted(e["detection_by_error"].items()):
        print(f"    detection  {label:<24} {d['detected']}/{d['n']} "
              f"= {d['rate']:.0%}  (median null pct {d['median_percentile']:.0f})")
    for r in e["verdict"]["reasons"]:
        print(f"    ! {r}")
    print(f"    {e['session_analysis']['conclusion']}")
