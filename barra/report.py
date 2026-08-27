"""Stage 7 - report.

Single-file HTML. Every deviation number is rendered next to its null
percentile; the null distribution is drawn before any per-rep claim appears.
That ordering is not cosmetic - it is the whole argument of the tool.
"""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import null as null_mod
from . import schema as S
from .config import (FLAG_PERCENTILE, MAX_ACCEPTABLE_FPR,
                     MIN_ACCEPTABLE_DETECTION, PATHS)
from .io_utils import read_csv, read_json
from .template import available_templates
from .viewpoint import load_viewpoints, reps_with_bins

PLOT_BG = "#12151a"
FG = "#d8dee9"
ACCENT = "#f0a35e"
NULLC = "#5e9ef0"
CROSSC = "#b48ead"


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _style(ax):
    ax.set_facecolor(PLOT_BG)
    for s in ax.spines.values():
        s.set_color("#39414f")
    ax.tick_params(colors=FG, labelsize=8)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)
    ax.grid(alpha=0.15, color=FG, linewidth=0.5)


def _fig(w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(PLOT_BG)
    _style(ax)
    return fig, ax


def plot_null_total(nl: pd.DataFrame, bin_name: str) -> str:
    pooled = nl[nl["kind"] == "pooled"]["total"].to_numpy()
    cross = nl[nl["kind"] == "cross_session"]["total"].to_numpy()
    fig, ax = _fig(7, 3)
    bins = max(6, min(20, len(pooled) // 2))
    ax.hist(pooled, bins=bins, color=NULLC, alpha=0.75,
            label=f"within-reference null (n={len(pooled)})")
    if cross.size:
        ax.hist(cross, bins=bins, color=CROSSC, alpha=0.55,
                label=f"cross-session null (n={len(cross)})")
    p95 = float(np.percentile(pooled, 95))
    ax.axvline(p95, color=ACCENT, lw=2, ls="--",
               label=f"p{FLAG_PERCENTILE:g} = {p95:.4f}")
    ax.set_xlabel("total deviation (torso-lengths)")
    ax.set_ylabel("reference reps")
    ax.set_title(f"{bin_name}: the subject's own rep-to-rep variation")
    leg = ax.legend(fontsize=7, facecolor=PLOT_BG, edgecolor="#39414f")
    for t in leg.get_texts():
        t.set_color(FG)
    return _png(fig)


def plot_null_joints(nl: pd.DataFrame, bin_name: str) -> str:
    pooled = nl[nl["kind"] == "pooled"]
    data = [pooled[f"joint_{j}"].to_numpy() for j in S.ANALYSIS_JOINTS]
    fig, ax = _fig(8, 3.4)
    bp = ax.boxplot(data, patch_artist=True, widths=0.6,
                    medianprops=dict(color=ACCENT, lw=1.5),
                    flierprops=dict(markersize=3, markerfacecolor=FG,
                                    markeredgecolor="none"))
    for b in bp["boxes"]:
        b.set(facecolor=NULLC, alpha=0.55, edgecolor="#39414f")
    for k in ("whiskers", "caps"):
        for a in bp[k]:
            a.set_color("#39414f")
    ax.set_xticklabels([j.replace("_", " ") for j in S.ANALYSIS_JOINTS],
                       rotation=45, ha="right")
    ax.set_ylabel("deviation (torso-lengths)")
    ax.set_title(f"{bin_name}: per-joint null distribution (leave-one-out)")
    return _png(fig)


def plot_rep_joints(row: pd.Series, nl: pd.DataFrame) -> str:
    pooled = nl[nl["kind"] == "pooled"]
    vals = np.array([row[f"joint_{j}"] for j in S.ANALYSIS_JOINTS])
    p50 = np.array([np.percentile(pooled[f"joint_{j}"], 50) for j in S.ANALYSIS_JOINTS])
    p95 = np.array([np.percentile(pooled[f"joint_{j}"], 95) for j in S.ANALYSIS_JOINTS])
    x = np.arange(len(vals))
    fig, ax = _fig(8, 3)
    ax.fill_between(x, 0, p95, color=NULLC, alpha=0.28, step="mid",
                    label="null: up to p95")
    ax.step(x, p50, where="mid", color=NULLC, lw=1.2, label="null median")
    colours = [ACCENT if v > t else "#7f8c9b" for v, t in zip(vals, p95)]
    ax.bar(x, vals, color=colours, width=0.55, label="this rep")
    ax.set_xticks(x)
    ax.set_xticklabels([j.replace("_", " ") for j in S.ANALYSIS_JOINTS],
                       rotation=45, ha="right")
    ax.set_ylabel("deviation (torso-lengths)")
    ax.set_title(f"{row['rep_id']}: per joint, against the subject's own null")
    leg = ax.legend(fontsize=7, facecolor=PLOT_BG, edgecolor="#39414f")
    for t in leg.get_texts():
        t.set_color(FG)
    return _png(fig)


def _channel_separability(validation: dict, bin_name: str, nl: pd.DataFrame,
                          scores: pd.DataFrame) -> dict:
    """Which joints and phases, if any, separate induced errors from the
    subject's own variation - judged by the same rule as the overall verdict,
    applied per channel.

    A channel counts as separable only if it exceeds its own null p95 on at
    least MIN_ACCEPTABLE_DETECTION of error reps AND on at most
    MAX_ACCEPTABLE_FPR of held-out clean reps. Note the multiple-comparison
    problem this creates and which the report states plainly: testing 12 joints
    and 6 phases at the 95th percentile produces about 0.9 exceedances per rep
    by chance alone.
    """
    e = validation.get("bins", {}).get(bin_name, {})
    per_rep = e.get("per_rep") or []
    if not per_rep:
        return {"available": False}
    labelled = pd.DataFrame(per_rep)
    sc = scores.set_index("rep_id")
    pooled = nl[nl["kind"] == "pooled"]

    def rates(prefix: str, names: list[str]) -> list[dict]:
        out = []
        for name in names:
            col = f"{prefix}_{name}"
            if col not in sc.columns or col not in pooled.columns:
                continue
            thr = float(np.percentile(pooled[col], 95))
            det, clean = [], []
            for _, r in labelled.iterrows():
                if r["rep_id"] not in sc.index:
                    continue
                v = float(sc.loc[r["rep_id"], col])
                (clean if str(r["label"]).lower() == "clean" else det).append(v > thr)
            if not det or not clean:
                continue
            d, f = float(np.mean(det)), float(np.mean(clean))
            out.append({
                "name": name, "threshold": thr, "detection": d, "fpr": f,
                "n_error": len(det), "n_clean": len(clean),
                "separable": bool(d >= MIN_ACCEPTABLE_DETECTION
                                  and f <= MAX_ACCEPTABLE_FPR),
            })
        return out

    joints = rates("joint", S.ANALYSIS_JOINTS)
    phases = rates("phase", S.PHASE_NAMES)
    n_tests = len(joints) + len(phases)
    return {
        "available": True,
        "joints": joints,
        "phases": phases,
        "separable_joints": [j["name"] for j in joints if j["separable"]],
        "separable_phases": [p["name"] for p in phases if p["separable"]],
        "n_tests": n_tests,
        "expected_chance_exceedances": round(0.05 * n_tests, 2),
    }


def run() -> str:
    reps = reps_with_bins()          # already carries the bin column
    vp = load_viewpoints()
    counts = reps["bin"].fillna("UNKNOWN").value_counts().to_dict()
    bins_present = available_templates()

    scores = pd.DataFrame()
    p = PATHS.o(S.P_SCORES)
    if p.exists():
        scores = pd.read_csv(p)

    validation = {}
    vpath = PATHS.o(S.P_VALIDATION)
    if vpath.exists():
        validation = read_json(vpath, "validate")

    bin_blocks = []
    for b in bins_present:
        nl = null_mod.load(b)
        pooled = nl[nl["kind"] == "pooled"]["total"].to_numpy()
        block = {
            "name": b,
            "n_reps": int(counts.get(b, 0)),
            "null_total_png": plot_null_total(nl, b),
            "null_joints_png": plot_null_joints(nl, b),
            "resolution": null_mod.resolution_note(pooled),
            "validation": validation.get("bins", {}).get(b, {}),
            "separability": _channel_separability(validation, b, nl, scores)
            if not scores.empty else {"available": False},
            "reps": [],
        }
        if not scores.empty:
            for _, r in scores[scores["bin"] == b].iterrows():
                qc = PATHS.o(S.P_QC, f"{r['rep_id'].replace('#', '_')}.mp4")
                block["reps"].append({
                    "rep_id": r["rep_id"],
                    "session_id": r["session_id"],
                    "total": float(r["total"]),
                    "percentile": float(r["null_percentile"]),
                    "p95": float(r["null_p95"]),
                    "flagged": bool(r["flagged"]),
                    "is_reference": bool(r.get("is_reference", False)),
                    "n_null": int(r["n_null"]),
                    "joints_png": plot_rep_joints(r, nl),
                    "weights": {j: float(r[f"weight_{j}"]) for j in S.ANALYSIS_JOINTS},
                    "phases": {n: (float(r[f"phase_{n}"]), float(r[f"phase_pct_{n}"]))
                               for n in S.PHASE_NAMES},
                    "qc_video": str(qc.relative_to(PATHS.out)) if qc.exists() else None,
                })
        bin_blocks.append(block)

    underpowered = [
        b for b in S.VIEWPOINT_BINS
        if b != "UNKNOWN" and 0 < counts.get(b, 0) < S.MIN_REPS_PER_BIN
    ]

    env = Environment(
        loader=FileSystemLoader(str(PATHS.root / "barra" / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["pct"] = lambda v: "n/a" if v is None or (
        isinstance(v, float) and np.isnan(v)) else f"{v * 100:.0f}%"
    env.filters["num"] = lambda v: "n/a" if v is None or (
        isinstance(v, float) and np.isnan(v)) else f"{v:.4f}"

    html = env.get_template("report.html.j2").render(
        generated=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        counts=counts,
        bins=bin_blocks,
        viewpoints=vp.to_dict("records"),
        underpowered=underpowered,
        min_reps_per_bin=S.MIN_REPS_PER_BIN,
        flag_percentile=FLAG_PERCENTILE,
        max_fpr=MAX_ACCEPTABLE_FPR,
        min_detection=MIN_ACCEPTABLE_DETECTION,
        validation=validation,
        has_validation=bool(validation),
        has_scores=not scores.empty,
    )
    out = PATHS.o(S.P_REPORT)
    out.write_text(html)
    print(f"  + {out}")
    return str(out)
