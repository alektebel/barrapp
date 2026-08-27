"""Stage 2 - viewpoint estimation and binning.

Deviation scores are only comparable between reps filmed from similar angles,
so every downstream comparison is within-bin and the binning has to be honest
about its own uncertainty.

Geometry
--------
Azimuth theta is the angle between the camera axis and the movement plane.
theta = 0 is a pure side-on (sagittal) view. The shoulder line is
mediolateral, i.e. perpendicular to the movement plane, so its apparent length
shrinks by sin(theta):

    apparent_shoulder_width / torso_length = R_true * sin(theta)

where R_true is the subject's own shoulder-width-to-torso ratio. Inverting:

    theta = asin( clip(R_apparent / R_true, 0, 1) )

Calibration and its failure mode
--------------------------------
R_true is taken from the *widest* view the subject has actually been filmed
from, since projection can only ever shrink the apparent ratio. If the subject
has never been filmed near-frontally, that maximum is itself foreshortened,
R_true is underestimated, and every azimuth is biased upward - sagittal sets
can be pushed into OBLIQUE. The estimator detects this (the calibration comes
out below the anatomical prior) and says so rather than quietly binning wrong.
Pass --true-shoulder-ratio to supply a measured value and remove the guess.

Conditioning: d(theta)/d(R) blows up as R_apparent approaches R_true, so
near-frontal azimuths carry wide intervals and near-sagittal ones are tight.
That asymmetry is real and is reported, not smoothed away.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema as S
from .config import MIN_MEAN_CONFIDENCE, PATHS
from .ingest import frame_to_keypoints, load_reps
from .io_utils import read_json, read_parquet, write_csv
from .normalise import torso_length

# Adult shoulder-width : torso-length (shoulder-mid to hip-mid) ratio. Used
# only as a floor on the calibration, and only to raise the alarm when the
# footage cannot calibrate itself.
ANATOMICAL_PRIOR_RATIO = 1.10
CALIBRATION_TOLERANCE = 0.15   # relative slack on R_true for the interval


def _apparent_ratios(video: str) -> np.ndarray:
    df = read_parquet(PATHS.o(S.P_KEYPOINTS, f"{video}.parquet"), "ingest")
    kp = frame_to_keypoints(df)
    ls, rs = S.KP_INDEX["left_shoulder"], S.KP_INDEX["right_shoulder"]
    w = np.linalg.norm(kp[:, ls, :2] - kp[:, rs, :2], axis=1)
    t = torso_length(kp)
    conf = np.minimum(kp[:, ls, 2], kp[:, rs, 2])
    ok = (conf >= MIN_MEAN_CONFIDENCE) & (t > 1e-6)
    return (w[ok] / t[ok]) if ok.any() else np.array([])


def _theta_deg(r_app: np.ndarray | float, r_true: float) -> np.ndarray | float:
    return np.degrees(np.arcsin(np.clip(np.asarray(r_app) / r_true, 0.0, 1.0)))


def _bin_of(theta: float) -> str:
    for name, (lo, hi) in S.BIN_EDGES_DEG.items():
        if lo <= theta < hi:
            return name
    return "FRONTAL" if theta >= 65.0 else "UNKNOWN"


# Share of the azimuth interval that must fall inside a bin before that bin is
# accepted. Set high because the costs are asymmetric: an UNKNOWN set is merely
# excluded, whereas a set placed in the wrong bin silently pollutes a template
# and every null distribution and score derived from it.
MIN_BIN_SHARE = 0.80


def _bin_with_uncertainty(med: float, lo: float, hi: float) -> tuple[str, bool]:
    """Bin the median, but fall back to UNKNOWN when the interval straddles a
    boundary. An honestly-unknown viewpoint is more useful than a confident
    wrong one."""
    b = _bin_of(med)
    if _bin_of(lo) == _bin_of(hi) == b:
        return b, False
    grid = np.linspace(lo, hi, 201)
    share = float(np.mean([_bin_of(t) == b for t in grid]))
    return (b, True) if share >= MIN_BIN_SHARE else ("UNKNOWN", True)


def run(true_shoulder_ratio: float | None = None) -> pd.DataFrame:
    reps = load_reps()
    anatomy = read_json(PATHS.o(S.P_ANATOMY), "normalise")
    videos = sorted(reps["video"].unique())

    per_video = {v: _apparent_ratios(v) for v in videos}
    usable = {v: r for v, r in per_video.items() if r.size >= 10}
    if not usable:
        raise SystemExit("no video has enough high-confidence shoulder frames to bin")

    if true_shoulder_ratio is not None:
        r_true, calib = float(true_shoulder_ratio), "user-supplied"
        calib_warning = None
    else:
        observed_max = max(float(np.percentile(r, 90)) for r in usable.values())
        r_true, calib = observed_max, "widest-observed-view"
        calib_warning = (
            None
            if observed_max >= ANATOMICAL_PRIOR_RATIO * 0.85
            else (
                f"calibration R_true={observed_max:.3f} is well below the anatomical "
                f"prior ({ANATOMICAL_PRIOR_RATIO:.2f}); no clip appears to be filmed "
                "near-frontally, so azimuths are biased HIGH and bins may be wrong. "
                "Measure the subject's shoulder-width:torso ratio and pass "
                "--true-shoulder-ratio."
            )
        )

    rows = []
    rng = np.random.default_rng(0)
    for v in videos:
        r = per_video[v]
        meta = reps[reps["video"] == v].iloc[0]
        if r.size < 10:
            rows.append(
                dict(
                    video=v, session_id=meta["session_id"], azimuth_deg=np.nan,
                    azimuth_lo=np.nan, azimuth_hi=np.nan, bin="UNKNOWN",
                    bin_uncertain=True, n_frames_used=int(r.size),
                    ratio_median=np.nan, ratio_std=np.nan,
                )
            )
            continue

        med_r = float(np.median(r))
        boot = np.median(rng.choice(r, size=(400, r.size), replace=True), axis=1)
        # widen by the calibration slack: R_true low -> theta high, and vice versa
        lo = float(np.percentile(_theta_deg(boot, r_true * (1 + CALIBRATION_TOLERANCE)), 2.5))
        hi = float(np.percentile(_theta_deg(boot, r_true * (1 - CALIBRATION_TOLERANCE)), 97.5))
        med = float(_theta_deg(med_r, r_true))
        b, uncertain = _bin_with_uncertainty(med, lo, hi)
        rows.append(
            dict(
                video=v, session_id=meta["session_id"], azimuth_deg=round(med, 2),
                azimuth_lo=round(lo, 2), azimuth_hi=round(hi, 2), bin=b,
                bin_uncertain=uncertain, n_frames_used=int(r.size),
                ratio_median=round(med_r, 4), ratio_std=round(float(np.std(r)), 4),
            )
        )

    vp = pd.DataFrame(rows)
    vp["calibration_method"] = calib
    vp["r_true"] = round(r_true, 4)
    write_csv(vp, PATHS.o(S.P_VIEWPOINTS))

    counts = rep_counts(reps, vp)
    print(f"  calibration R_true = {r_true:.3f} ({calib})")
    if calib_warning:
        print(f"  ! {calib_warning}")
    print(f"  {'bin':<10} {'reps':>5} {'videos':>7}   status")
    for b in S.VIEWPOINT_BINS:
        n = counts.get(b, 0)
        nv = int((vp["bin"] == b).sum())
        status = (
            "excluded (UNKNOWN viewpoint)" if b == "UNKNOWN"
            else "UNDERPOWERED - excluded" if n < S.MIN_REPS_PER_BIN
            else "usable"
        )
        print(f"  {b:<10} {n:>5} {nv:>7}   {status}")
    for _, r in vp.iterrows():
        if r["bin_uncertain"] and r["bin"] != "UNKNOWN":
            print(f"  ! {r['video']}: bin {r['bin']} is uncertain "
                  f"({r['azimuth_lo']:.0f}-{r['azimuth_hi']:.0f} deg)")
    return vp


def rep_counts(reps: pd.DataFrame, vp: pd.DataFrame) -> dict[str, int]:
    m = reps.merge(vp[["video", "bin"]], on="video", how="left")
    return m["bin"].fillna("UNKNOWN").value_counts().to_dict()


def load_viewpoints() -> pd.DataFrame:
    from .io_utils import read_csv

    return read_csv(PATHS.o(S.P_VIEWPOINTS), "viewpoints")


def reps_with_bins() -> pd.DataFrame:
    reps, vp = load_reps(), load_viewpoints()
    m = reps.merge(
        vp[["video", "bin", "azimuth_deg", "bin_uncertain"]], on="video", how="left"
    )
    m["bin"] = m["bin"].fillna("UNKNOWN")
    return m


def usable_bins(m: pd.DataFrame) -> list[str]:
    """Bins with enough reps to compare within. UNKNOWN is never usable."""
    counts = m["bin"].value_counts()
    return [
        b for b in S.VIEWPOINT_BINS
        if b != "UNKNOWN" and counts.get(b, 0) >= S.MIN_REPS_PER_BIN
    ]
