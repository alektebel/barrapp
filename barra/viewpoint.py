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

# Adult biacromial width : torso length (shoulder midpoint to hip midpoint),
# viewed square on. Roughly 0.40 m over 0.50 m. Used only as a sanity band on
# the self-calibration - a calibration far outside it means the footage cannot
# calibrate itself and the azimuths are not to be trusted.
ANATOMICAL_PRIOR_RATIO = 0.80
ANATOMICAL_PRIOR_RANGE = (0.65, 0.95)
CALIBRATION_TOLERANCE = 0.15   # relative slack on R_true for the interval


def _apparent_ratios(video: str) -> np.ndarray:
    """Apparent shoulder width in torso-lengths, per usable frame.

    The divisor is one robust torso length for the whole clip, not the
    per-frame value. A per-frame divisor turns any frame where the pose
    estimator briefly collapses the torso into a ratio of 50-plus, which then
    sets the calibration for every clip and mis-bins the entire session.
    """
    from .movements import robust_torso

    df = read_parquet(PATHS.o(S.P_KEYPOINTS, f"{video}.parquet"), "ingest")
    kp = frame_to_keypoints(df)
    ls, rs = S.KP_INDEX["left_shoulder"], S.KP_INDEX["right_shoulder"]
    w = np.linalg.norm(kp[:, ls, :2] - kp[:, rs, :2], axis=1)
    t = robust_torso(kp)
    conf = np.minimum(kp[:, ls, 2], kp[:, rs, 2])
    ok = conf >= MIN_MEAN_CONFIDENCE
    return (w[ok] / t) if ok.any() else np.array([])


def camera_side(video: str) -> tuple[str, float]:
    """Which side of the subject the camera is on.

    Azimuth alone cannot tell a camera in front of the subject from one behind
    it: both see the full shoulder width and both come out near 90 degrees. The
    two are mirror images, so pooling them into one bin would compare a left
    shoulder against a right one and call the difference technique.

    The cue is the pose estimator's own anatomical labelling: it names the left
    and right shoulder, so whether anatomical-left sits at greater or lesser
    image x says which way the subject faces. Face-landmark confidence does NOT
    work for this - mediapipe reports near-1.0 visibility for face landmarks
    even on footage shot squarely from behind.
    """
    df = read_parquet(PATHS.o(S.P_KEYPOINTS, f"{video}.parquet"), "ingest")
    kp = frame_to_keypoints(df)
    idx = [S.KP_INDEX[n] for n in
           ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    conf = kp[:, idx, 2].min(axis=1)
    ok = conf >= MIN_MEAN_CONFIDENCE
    if ok.sum() < 10:
        return "unknown", 0.0
    dx = (kp[ok, S.KP_INDEX["left_shoulder"], 0]
          - kp[ok, S.KP_INDEX["right_shoulder"], 0])
    frac_front = float(np.mean(dx > 0))
    agreement = max(frac_front, 1.0 - frac_front)
    if agreement < 0.70:
        return "unknown", agreement
    return ("anterior" if frac_front > 0.5 else "posterior"), agreement


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
        lo, hi = ANATOMICAL_PRIOR_RANGE
        r_true, calib = observed_max, "widest-observed-view"
        calib_warning = None
        if observed_max < lo:
            calib_warning = (
                f"calibration R_true={observed_max:.3f} is below the anatomical band "
                f"{lo:.2f}-{hi:.2f}; no clip appears to be filmed near-frontally, so "
                "azimuths are biased HIGH and bins may be wrong. Measure the "
                "subject's shoulder-width:torso ratio and pass --true-shoulder-ratio."
            )
        elif observed_max > hi:
            calib_warning = (
                f"calibration R_true={observed_max:.3f} is ABOVE the anatomical band "
                f"{lo:.2f}-{hi:.2f}. An apparent shoulder width cannot exceed the "
                "true one, so this is a pose-estimation artefact, not a camera "
                "angle - most likely the torso is being foreshortened by the "
                "movement itself. Every azimuth below is suspect; declare the view "
                "in sessions.csv instead of relying on this estimate."
            )

    rows = []
    rng = np.random.default_rng(0)
    for v in videos:
        r = per_video[v]
        meta = reps[reps["video"] == v].iloc[0]
        declared = str(meta.get("view") or "").strip().lower() or None
        declared_bin = str(meta.get("declared_bin") or "").strip().upper() or None
        if declared_bin and declared_bin not in S.VIEWPOINT_BINS:
            raise SystemExit(
                f"{v}: declared bin {declared_bin!r} is not one of "
                f"{', '.join(S.VIEWPOINT_BINS)}"
            )
        side, side_conf = camera_side(v)
        if declared in ("anterior", "posterior", "left", "right"):
            side, side_conf = declared, 1.0
        if r.size < 10:
            rows.append(
                dict(
                    video=v, session_id=meta["session_id"], azimuth_deg=np.nan,
                    azimuth_lo=np.nan, azimuth_hi=np.nan, bin="UNKNOWN",
                    bin_uncertain=True, n_frames_used=int(r.size),
                    ratio_median=np.nan, ratio_std=np.nan,
                    side=side, side_confidence=round(side_conf, 3),
                    view_key=f"UNKNOWN/{side}",
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
        if declared_bin:
            # A declared viewpoint always wins. The estimator is a convenience
            # for footage nobody annotated, not an authority over the person who
            # was standing there holding the camera.
            b, uncertain = declared_bin, False
        rows.append(
            dict(
                video=v, session_id=meta["session_id"], azimuth_deg=round(med, 2),
                azimuth_lo=round(lo, 2), azimuth_hi=round(hi, 2), bin=b,
                bin_uncertain=uncertain, n_frames_used=int(r.size),
                ratio_median=round(med_r, 4), ratio_std=round(float(np.std(r)), 4),
                side=side, side_confidence=round(side_conf, 3),
                bin_declared=bool(declared_bin), view_key=f"{b}/{side}",
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
    print(f"  {'video':<28}{'side':<11}side conf")
    for _, r in vp.iterrows():
        print(f"  {r['video'][:27]:<28}{r['side']:<11}{r['side_confidence']:.2f}")
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
    cols = ["video", "bin", "azimuth_deg", "bin_uncertain", "side", "view_key"]
    m = reps.merge(vp[[c for c in cols if c in vp.columns]], on="video", how="left")
    m["bin"] = m["bin"].fillna("UNKNOWN")
    if "side" in m.columns:
        m["side"] = m["side"].fillna("unknown")
    return m


def usable_bins(m: pd.DataFrame) -> list[str]:
    """Bins with enough reps to compare within. UNKNOWN is never usable."""
    counts = m["bin"].value_counts()
    return [
        b for b in S.VIEWPOINT_BINS
        if b != "UNKNOWN" and counts.get(b, 0) >= S.MIN_REPS_PER_BIN
    ]
