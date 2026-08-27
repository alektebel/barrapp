"""Synthetic fixture generator - a self-test harness, NOT validation.

`barra selftest` builds a fake subject doing squats: a 3D two-link leg model
projected to a camera at a chosen azimuth, with per-rep variation, per-frame
keypoint noise, and optional deliberately induced errors. It writes keypoints
and rep segmentation straight into out/, so the entire pipeline downstream of
pose estimation can be run and checked without a single video.

What this is for: catching bugs in normalisation, binning, DBA, the DTW
alignment, the null construction and the report. What it is emphatically NOT
for: any claim that the tool works. The noise model here is invented, so a
detection rate measured against it measures the noise model, not reality. Only
`barra validate` on real labelled footage can answer that, and the report says
so wherever synthetic data was used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import schema as S
from .config import PATHS
from .ingest import keypoints_to_frame
from .io_utils import write_csv, write_parquet

# Segment lengths as multiples of torso (shoulder-mid to hip-mid), roughly
# adult proportions. The hip travels back as it descends, which is what keeps
# the shank angle in a realistic 25-35 degree range at the bottom.
FEMUR, TIBIA, TORSO = 0.92, 0.88, 1.0
HALF_SHOULDER, HALF_HIP = 0.55, 0.35
HALF_KNEE, HALF_ANKLE = 0.33, 0.30
STAND_H, BOTTOM_H = 1.76, 1.02
HIP_TRAVEL_BACK = 0.40


def _knee(hip_xy: np.ndarray, ankle_xy: np.ndarray) -> np.ndarray:
    """Forward-bulging solution of the two-link leg."""
    d = hip_xy - ankle_xy
    dist = float(np.linalg.norm(d))
    dist = min(dist, FEMUR + TIBIA - 1e-6)
    a = (TIBIA**2 - FEMUR**2 + dist**2) / (2 * dist)
    h = float(np.sqrt(max(TIBIA**2 - a**2, 0.0)))
    u = d / max(dist, 1e-9)
    perp = np.array([u[1], -u[0]])          # +x-ish, knee travels forward
    if perp[0] < 0:
        perp = -perp
    return ankle_xy + a * u + h * perp


def _pose_3d(depth: float, lean: float, knee_bias: float, valgus: float,
             side_shift: float) -> dict[str, np.ndarray]:
    """One frame of the model, in body coordinates (x fwd, y up, z left)."""
    H = STAND_H + (BOTTOM_H - STAND_H) * depth
    hip_x = -HIP_TRAVEL_BACK * depth
    hip = np.array([hip_x, H])
    joints: dict[str, np.ndarray] = {}

    sh_dir = np.array([np.sin(lean), np.cos(lean)])
    shoulder = hip + TORSO * sh_dir

    for sgn, side in ((+1.0, "left"), (-1.0, "right")):
        ankle = np.array([0.0, 0.0])
        k = _knee(hip, ankle)
        k = k + np.array([knee_bias * depth, 0.0])
        z_knee = sgn * HALF_KNEE - sgn * valgus * depth
        joints[f"{side}_hip"] = np.array([hip[0], hip[1], sgn * HALF_HIP + side_shift])
        joints[f"{side}_knee"] = np.array([k[0], k[1], z_knee + side_shift])
        joints[f"{side}_ankle"] = np.array([ankle[0], ankle[1], sgn * HALF_ANKLE])
        s = np.array([shoulder[0], shoulder[1], sgn * HALF_SHOULDER + side_shift])
        joints[f"{side}_shoulder"] = s
        joints[f"{side}_elbow"] = s + np.array([-0.22, -0.26, sgn * 0.16])
        joints[f"{side}_wrist"] = s + np.array([-0.10, -0.05, sgn * 0.22])

    head = np.array([shoulder[0] + 0.10 * np.sin(lean), shoulder[1] + 0.32, 0.0])
    joints["nose"] = head
    for n, dz in (("left_eye", 0.05), ("right_eye", -0.05),
                  ("left_ear", 0.09), ("right_ear", -0.09)):
        joints[n] = head + np.array([-0.03, 0.02, dz])
    return joints


def _depth_profile(n: int, ecc_frac: float, pause: float) -> np.ndarray:
    """0 -> 1 -> 0 with a smooth turnaround; ecc_frac shifts the turnaround."""
    t = np.linspace(0.0, 1.0, n)
    b = np.clip(ecc_frac, 0.2, 0.8)
    d = np.where(t <= b, t / b, (1.0 - t) / (1.0 - b))
    d = np.clip(d, 0.0, 1.0)
    d = 0.5 - 0.5 * np.cos(np.pi * d)                 # ease in/out
    return np.clip(d * (1.0 + pause * np.exp(-((t - b) ** 2) / 0.004)), 0.0, 1.0)


def make_rep(rng: np.random.Generator, azimuth_deg: float, n_frames: int,
             error: str | None = None, noise_px: float = 2.2,
             px_per_torso: float = 190.0) -> tuple[np.ndarray, int]:
    """One rep of pixel-space COCO-17 keypoints, plus its turnaround frame."""
    ecc = float(np.clip(rng.normal(0.48, 0.04), 0.3, 0.7))
    pause = float(abs(rng.normal(0.0, 0.05)))
    depth_gain = float(np.clip(rng.normal(1.0, 0.05), 0.75, 1.2))
    lean_amp = float(np.clip(rng.normal(0.30, 0.035), 0.1, 0.7))
    knee_bias = float(rng.normal(0.0, 0.025))
    valgus = float(abs(rng.normal(0.0, 0.012)))
    side_shift = float(rng.normal(0.0, 0.02))

    # Induced errors. Magnitudes are chosen once, here, before any threshold is
    # looked at, and are of the order a coach would call visible.
    if error == "excess_forward_lean":
        lean_amp += 0.30
    elif error == "knee_valgus":
        valgus += 0.16
    elif error == "shallow_depth":
        depth_gain *= 0.62
    elif error == "knee_travel":
        knee_bias += 0.26
    elif error == "lateral_shift":
        side_shift += 0.18

    prof = _depth_profile(n_frames, ecc, pause) * depth_gain
    theta = np.radians(azimuth_deg)
    cx, cy = 640.0, 700.0

    frames = np.zeros((n_frames, 17, 3), dtype=np.float32)
    for f, d in enumerate(prof):
        j3 = _pose_3d(d, lean_amp * d, knee_bias, valgus, side_shift)
        for name, i in S.KP_INDEX.items():
            x, y, z = j3[name]
            u = x * np.cos(theta) + z * np.sin(theta)
            frames[f, i, 0] = cx + u * px_per_torso + rng.normal(0, noise_px)
            frames[f, i, 1] = cy - y * px_per_torso + rng.normal(0, noise_px)
            # the far side of the body is less visible the more side-on it is
            far = (z < 0) and (abs(np.sin(theta)) < 0.5)
            frames[f, i, 2] = float(np.clip(
                rng.normal(0.72 if far else 0.93, 0.05), 0.05, 1.0))
    return frames, int(np.argmax(prof))


def make_set(rng: np.random.Generator, azimuth_deg: float, n_reps: int,
             error: str | None = None, fps: float = 30.0) -> tuple[np.ndarray, list]:
    """A set: several reps plus standing frames between them."""
    chunks, marks = [], []
    cursor = 0
    for _ in range(n_reps):
        n = int(rng.integers(46, 74))
        rep, bottom = make_rep(rng, azimuth_deg, n)
        if error:
            rep, bottom = make_rep(rng, azimuth_deg, n, error=error)
        pad = int(rng.integers(8, 16))
        stand, _ = make_rep(rng, azimuth_deg, 2 * pad)
        stand = stand[:pad] * 0 + stand[:1]          # hold the standing pose
        chunks.append(stand); chunks.append(rep)
        marks.append((cursor + pad, cursor + pad + bottom, cursor + pad + n - 1))
        cursor += pad + n
    tail, _ = make_rep(rng, azimuth_deg, 20)
    chunks.append(tail[:10] * 0 + tail[:1])
    return np.concatenate(chunks, axis=0), marks


SETS = [
    # (video stem, session, azimuth, n_reps, induced error, edge-of-bin?)
    ("2026-08-01__squat__set01", "2026-08-01", 8.0, 6, None, False),
    ("2026-08-01__squat__set02", "2026-08-01", 11.0, 6, None, False),
    ("2026-08-08__squat__set01", "2026-08-08", 9.0, 6, None, False),
    ("2026-08-08__squat__set02", "2026-08-08", 14.0, 6, None, False),
    ("2026-08-15__squat__set01", "2026-08-15", 10.0, 6, None, False),
    ("2026-08-15__squat__set02", "2026-08-15", 18.5, 4, None, True),
    ("2026-08-15__squat__err01", "2026-08-15", 10.0, 4, "excess_forward_lean", False),
    ("2026-08-15__squat__err02", "2026-08-15", 12.0, 4, "knee_valgus", False),
    ("2026-08-15__squat__err03", "2026-08-15", 9.0, 4, "shallow_depth", False),
    ("2026-08-15__squat__err04", "2026-08-15", 11.0, 4, "knee_travel", False),
    ("2026-08-15__squat__err05", "2026-08-15", 88.0, 4, None, False),  # frontal
]


def generate(seed: int = 7) -> pd.DataFrame:
    """Write synthetic keypoints, reps.csv and labels.csv into out/."""
    PATHS.ensure()
    rng = np.random.default_rng(seed)
    rep_rows, label_rows = [], []

    for stem, session, az, n_reps, error, edge in SETS:
        kp, marks = make_set(rng, az, n_reps, error)
        write_parquet(keypoints_to_frame(kp), PATHS.o(S.P_KEYPOINTS, f"{stem}.parquet"))
        for i, (a, b, c) in enumerate(marks):
            rid = f"{stem}#r{i:02d}"
            rep_rows.append(dict(
                rep_id=rid, video=stem, session_id=session, exercise="squat",
                set_index=0, rep_index=i, start_frame=a, bottom_frame=b,
                end_frame=c, fps=30.0))
            label_rows.append(dict(rep_id=rid, label=error or "clean",
                                   edge_of_bin=edge, note="synthetic"))
        print(f"  + {stem}: {len(kp)} frames, {len(marks)} reps"
              f"{f' [{error}]' if error else ''} at ~{az:.0f} deg")

    reps = pd.DataFrame(rep_rows)
    write_csv(reps, PATHS.o(S.P_REPS))
    write_csv(pd.DataFrame(label_rows), PATHS.o(S.P_LABELS))
    (PATHS.out / "SYNTHETIC").write_text(
        "The artefacts in this directory were produced by `barra selftest` from a\n"
        "simulated subject. They exercise the pipeline; they validate nothing.\n"
        "Delete this directory before ingesting real footage.\n"
    )
    print(f"  wrote {len(reps)} synthetic reps and out/labels.csv")
    return reps
