"""Stage 1 - anatomical normalisation.

Two things happen here and they are deliberately separated:

  1. `estimate_anatomy` measures the subject's segment lengths once, over every
     high-confidence frame of every video, and persists them with their
     interquartile ranges. This is the subject's *anatomy*: it is what makes
     later comparisons self-referential rather than cross-subject.

  2. `normalise_video` expresses each frame in a subject-normalised frame:
     hip midpoint at the origin, torso length 1.

IMPORTANT - rotation is NOT removed.
Torso lean in the image plane is signal, not nuisance. A full Procrustes
alignment would rotate each frame to a canonical orientation and in doing so
would erase exactly the quantity a lifter most often deviates in (how far the
torso pitches forward through the concentric phase). So the transform here is
translation + isotropic scale only. Reflection is not removed either: a rep
filmed from the subject's other side is a different viewpoint, not the same rep
mirrored, and stage 2 is what keeps those apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema as S
from .config import CONF_FLOOR, MIN_MEAN_CONFIDENCE, PATHS
from .ingest import frame_to_keypoints, load_reps
from .io_utils import read_parquet, write_json, write_parquet

EPS = 1e-8


def _seg_lengths(kp: np.ndarray, name: str) -> tuple[np.ndarray, np.ndarray]:
    a, b = S.SEGMENTS[name]
    ia, ib = S.KP_INDEX[a], S.KP_INDEX[b]
    d = np.linalg.norm(kp[:, ia, :2] - kp[:, ib, :2], axis=1)
    c = np.minimum(kp[:, ia, 2], kp[:, ib, 2])
    return d, c


def _midpoint(kp: np.ndarray, a: str, b: str) -> np.ndarray:
    return 0.5 * (kp[:, S.KP_INDEX[a], :2] + kp[:, S.KP_INDEX[b], :2])


def torso_length(kp: np.ndarray) -> np.ndarray:
    """Apparent hip-midpoint to shoulder-midpoint distance, per frame."""
    return np.linalg.norm(
        _midpoint(kp, "left_shoulder", "right_shoulder")
        - _midpoint(kp, "left_hip", "right_hip"),
        axis=1,
    )


def frame_confidence(kp: np.ndarray) -> np.ndarray:
    """Mean confidence over the scored joints only."""
    return kp[:, S.ANALYSIS_IDX, 2].mean(axis=1)


def estimate_anatomy(videos: list[str]) -> dict:
    """Median segment lengths (in pixels, per video) plus scale-free ratios.

    Absolute pixel lengths are not comparable between videos - camera distance
    differs - so the persisted anatomy is expressed as ratios to torso length,
    which is what stage 2 calibrates against.
    """
    per_seg: dict[str, list[float]] = {k: [] for k in S.SEGMENTS}
    torso_px: dict[str, float] = {}
    n_frames_used = 0

    for v in videos:
        df = read_parquet(PATHS.o(S.P_KEYPOINTS, f"{v}.parquet"), "ingest")
        kp = frame_to_keypoints(df)
        keep = frame_confidence(kp) >= MIN_MEAN_CONFIDENCE
        if keep.sum() < 10:
            continue
        n_frames_used += int(keep.sum())
        t = np.median(torso_length(kp[keep]))
        if t <= EPS:
            continue
        torso_px[v] = float(t)
        for name in S.SEGMENTS:
            d, c = _seg_lengths(kp, name)
            m = keep & (c >= MIN_MEAN_CONFIDENCE)
            if m.sum() >= 10:
                per_seg[name].extend((d[m] / t).tolist())

    if n_frames_used == 0:
        raise SystemExit(
            f"no frames reached mean confidence {MIN_MEAN_CONFIDENCE}. "
            "The pose estimates are too poor to normalise - check framing, "
            "lighting and that one person only is in shot."
        )

    segments = {}
    for name, vals in per_seg.items():
        if not vals:
            continue
        a = np.asarray(vals)
        q1, q3 = np.percentile(a, [25, 75])
        segments[name] = {
            "ratio_to_torso_median": float(np.median(a)),
            "iqr_low": float(q1),
            "iqr_high": float(q3),
            "n_frames": int(a.size),
        }

    # Mean of left/right torso as the reference segment; both are 1.0 by
    # construction only if the shoulder/hip midpoints coincide with the
    # individual joints, which they do not, so record them explicitly.
    anatomy = {
        "min_mean_confidence": MIN_MEAN_CONFIDENCE,
        "n_frames_used": n_frames_used,
        "torso_pixels_per_video": torso_px,
        "segments": segments,
        "true_shoulder_width_ratio": segments.get("shoulder_width", {}).get(
            "ratio_to_torso_median"
        ),
    }
    write_json(anatomy, PATHS.o(S.P_ANATOMY))
    return anatomy


def normalise_video(video: str, anatomy: dict, scale_mode: str = "per_set") -> pd.DataFrame:
    """Translate to hip midpoint, scale to torso length 1, keep rotation.

    scale_mode:
      per_set   - divide every frame by the set's median apparent torso length
                  (default). Camera distance is fixed within a set, so this
                  removes distance while *preserving* torso foreshortening,
                  which changes as the subject pitches toward or away from the
                  camera. That foreshortening is the same class of signal as
                  lean, so cancelling it would repeat the mistake the spec
                  warns about for rotation.
      per_frame - divide each frame by its own apparent torso length, the
                  literal reading of the spec. Scale-invariant frame to frame,
                  but blind to foreshortening. Offered so the choice can be
                  tested rather than argued about.
    """
    df = read_parquet(PATHS.o(S.P_KEYPOINTS, f"{video}.parquet"), "ingest")
    kp = frame_to_keypoints(df)
    hip = _midpoint(kp, "left_hip", "right_hip")
    t = torso_length(kp)

    if scale_mode == "per_frame":
        good = frame_confidence(kp) >= MIN_MEAN_CONFIDENCE
        fill = float(np.median(t[good])) if good.any() else float(np.median(t))
        scale = np.where(t > EPS, t, fill)
    elif scale_mode == "per_set":
        good = frame_confidence(kp) >= MIN_MEAN_CONFIDENCE
        s = float(np.median(t[good])) if good.sum() >= 10 else float(np.median(t))
        if s <= EPS:
            raise SystemExit(f"{video}: torso length is degenerate; cannot normalise")
        scale = np.full(len(t), s)
    else:
        raise SystemExit(f"unknown scale mode {scale_mode!r}")

    cols: dict[str, np.ndarray] = {"frame": df["frame"].to_numpy()}
    for name in S.COCO17:
        i = S.KP_INDEX[name]
        cols[f"n_{name}_x"] = ((kp[:, i, 0] - hip[:, 0]) / scale).astype(np.float32)
        cols[f"n_{name}_y"] = ((kp[:, i, 1] - hip[:, 1]) / scale).astype(np.float32)
        cols[f"c_{name}"] = kp[:, i, 2].astype(np.float32)
    cols["torso_px"] = t.astype(np.float32)
    cols["scale_px"] = scale.astype(np.float32)
    cols["frame_conf"] = frame_confidence(kp).astype(np.float32)

    out = pd.DataFrame(cols)
    write_parquet(out, PATHS.o(S.P_NORMALISED, f"{video}.parquet"))
    return out


def run(scale_mode: str = "per_set") -> dict:
    reps = load_reps()
    videos = sorted(reps["video"].unique())
    anatomy = estimate_anatomy(videos)
    print(f"  anatomy from {anatomy['n_frames_used']} high-confidence frames")
    for name, s in sorted(anatomy["segments"].items()):
        print(
            f"    {name:<16} {s['ratio_to_torso_median']:.3f} torso "
            f"[IQR {s['iqr_low']:.3f}-{s['iqr_high']:.3f}]"
        )
    for v in videos:
        d = normalise_video(v, anatomy, scale_mode)
        print(f"  + {v}: {len(d)} frames normalised (scale={scale_mode})")
    return anatomy


def rep_trajectory(video: str, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    """Scored-joint trajectory for one rep.

    Returns (X, C) where X is (frames, joints, 2) normalised coordinates and C
    is (frames, joints) confidences.
    """
    df = read_parquet(PATHS.o(S.P_NORMALISED, f"{video}.parquet"), "normalise")
    sl = df[(df["frame"] >= start) & (df["frame"] <= end)]
    n = len(sl)
    X = np.zeros((n, len(S.ANALYSIS_JOINTS), 2), dtype=np.float64)
    C = np.zeros((n, len(S.ANALYSIS_JOINTS)), dtype=np.float64)
    for j, name in enumerate(S.ANALYSIS_JOINTS):
        X[:, j, 0] = sl[f"n_{name}_x"].to_numpy()
        X[:, j, 1] = sl[f"n_{name}_y"].to_numpy()
        C[:, j] = np.clip(sl[f"c_{name}"].to_numpy(), CONF_FLOOR, 1.0)
    return X, C
