"""Stage 0 - ingest.

The spec assumes a Part A pipeline already produced per-frame keypoints and rep
segmentation, and says to reuse it. This repository had no Part A pipeline in
it, so this module *is* that stage, kept deliberately thin and swappable:

  * pose extraction is delegated to a backend (barra/pose/), never done here;
  * rep segmentation is a documented, inspectable heuristic whose output is a
    plain CSV the user is expected to correct by hand when it is wrong.

If you later drop a real Part A in, point --from-part-a at its keypoint parquet
directory and this module becomes a loader.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter

from . import schema as S
from .config import PATHS
from .io_utils import read_csv, write_csv, write_parquet, video_stem

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

# Recommended filename convention, parsed when data/videos/sessions.csv does
# not name a video explicitly:  YYYY-MM-DD__<exercise>__set<NN>.mp4
FILENAME_RE = re.compile(
    r"^(?P<sess>\d{4}-\d{2}-\d{2})__(?P<exercise>[A-Za-z0-9\-]+)__set(?P<set>\d+)$"
)


@dataclass
class VideoMeta:
    video: str
    path: Path
    session_id: str
    exercise: str
    set_index: int


def discover(videos_dir: Path | None = None) -> list[Path]:
    d = videos_dir or PATHS.videos
    if not d.exists():
        raise SystemExit(f"no video directory at {d} - create it and add clips")
    return sorted(p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def load_metadata(videos: list[Path]) -> list[VideoMeta]:
    """Session metadata comes from data/videos/sessions.csv when present, else
    from the filename convention, else from the file's modification date.

    session_id matters: it is what makes 'track progress between sessions'
    answerable at all. Two reps from the same day are not independent evidence
    about a training block.
    """
    sidecar = PATHS.videos / "sessions.csv"
    table: dict[str, dict] = {}
    if sidecar.exists():
        df = pd.read_csv(sidecar)
        for _, r in df.iterrows():
            table[str(r["video"]).strip()] = r.to_dict()

    metas: list[VideoMeta] = []
    for p in videos:
        stem = p.stem
        row = table.get(stem) or table.get(p.name) or {}
        m = FILENAME_RE.match(stem)
        if "session_id" in row and not pd.isna(row.get("session_id")):
            sess = str(row["session_id"])
        elif m:
            sess = m.group("sess")
        else:
            sess = date.fromtimestamp(p.stat().st_mtime).isoformat()
        exercise = str(row.get("exercise") or (m.group("exercise") if m else "unknown"))
        set_index = int(row.get("set_index") or (m.group("set") if m else 0))
        metas.append(VideoMeta(stem, p, sess, exercise, set_index))
    return metas


# ---------------------------------------------------------------------------
# Pose extraction
# ---------------------------------------------------------------------------
def keypoints_to_frame(kp: np.ndarray) -> pd.DataFrame:
    """(T, 17, 3) -> tidy wide frame matching the keypoints contract."""
    cols: dict[str, np.ndarray] = {"frame": np.arange(kp.shape[0], dtype=np.int64)}
    for name, i in S.KP_INDEX.items():
        cols[f"kp_{name}_x"] = kp[:, i, 0].astype(np.float32)
        cols[f"kp_{name}_y"] = kp[:, i, 1].astype(np.float32)
        cols[f"kp_{name}_c"] = kp[:, i, 2].astype(np.float32)
    return pd.DataFrame(cols)


def frame_to_keypoints(df: pd.DataFrame) -> np.ndarray:
    T = len(df)
    kp = np.zeros((T, 17, 3), dtype=np.float32)
    for name, i in S.KP_INDEX.items():
        kp[:, i, 0] = df[f"kp_{name}_x"].to_numpy()
        kp[:, i, 1] = df[f"kp_{name}_y"].to_numpy()
        kp[:, i, 2] = df[f"kp_{name}_c"].to_numpy()
    return kp


def probe_video(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {"ok": False, "reason": "cannot open"}
    info = {
        "ok": True,
        "fps": cap.get(cv2.CAP_PROP_FPS) or 0.0,
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    info["duration_s"] = info["frames"] / info["fps"] if info["fps"] else 0.0
    return info


# ---------------------------------------------------------------------------
# Rep segmentation
# ---------------------------------------------------------------------------
def _depth_signal(kp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vertical hip-midpoint trajectory, image-y inverted so that 'up' is +.

    Returns (signal, confidence). Low-confidence frames are linearly
    interpolated rather than dropped, so frame indices stay aligned with the
    video for the QC overlay.
    """
    hips = kp[:, [S.KP_INDEX["left_hip"], S.KP_INDEX["right_hip"]], :]
    conf = hips[:, :, 2].mean(axis=1)
    y = hips[:, :, 1].mean(axis=1)
    good = conf >= 0.3
    if good.sum() < 5:
        return np.zeros_like(y), conf
    idx = np.arange(len(y))
    y = np.interp(idx, idx[good], y[good])
    win = max(5, min(31, (len(y) // 10) | 1))
    if len(y) > win:
        y = savgol_filter(y, win, 2)
    return -y, conf


def segment_reps(kp: np.ndarray, fps: float, min_rep_s: float = 0.8) -> list[tuple[int, int, int]]:
    """Split a set into reps on the hip-height trajectory.

    A rep runs top -> bottom -> top. Tops are prominent local maxima of the
    inverted-y signal; the bottom is the minimum between two tops. Prominence
    is scaled to the set's own range, so it does not depend on pixel scale.

    This is a heuristic and it will be wrong on some sets. That is why
    out/reps.csv is a plain editable file: fix it there and re-run. Nothing
    downstream re-derives segmentation.
    """
    sig, _ = _depth_signal(kp)
    if np.allclose(sig, 0):
        return []
    rng = float(np.percentile(sig, 95) - np.percentile(sig, 5))
    if rng <= 0:
        return []
    min_dist = max(1, int(min_rep_s * fps))
    tops, _ = find_peaks(sig, prominence=0.30 * rng, distance=min_dist)
    if len(tops) < 2:
        return []
    reps = []
    for a, b in zip(tops[:-1], tops[1:]):
        bottom = int(a + np.argmin(sig[a : b + 1]))
        depth = min(sig[a], sig[b]) - sig[bottom]
        # reject "reps" that never actually descended
        if depth < 0.30 * rng or (b - a) < min_dist:
            continue
        reps.append((int(a), bottom, int(b)))
    return reps


def ingest(backend_name: str, force: bool = False, from_part_a: Path | None = None) -> pd.DataFrame:
    """Produce out/keypoints/<video>.parquet and out/reps.csv."""
    PATHS.ensure()
    videos = discover()
    if not videos:
        raise SystemExit(
            f"no videos found in {PATHS.videos}\n"
            "Add clips there (see data/videos/README.md for the naming convention)."
        )
    metas = load_metadata(videos)

    rows = []
    for meta in metas:
        kp_path = PATHS.o(S.P_KEYPOINTS, f"{meta.video}.parquet")
        info = probe_video(meta.path)
        if not info["ok"]:
            print(f"  ! {meta.video}: {info['reason']} - skipped")
            continue
        fps = info["fps"] or 30.0

        if from_part_a is not None:
            src = from_part_a / f"{meta.video}.parquet"
            if not src.exists():
                print(f"  ! {meta.video}: no Part A keypoints at {src} - skipped")
                continue
            df = pd.read_parquet(src)
            write_parquet(df, kp_path)
            print(f"  = {meta.video}: loaded Part A keypoints ({len(df)} frames)")
        elif kp_path.exists() and not force:
            df = pd.read_parquet(kp_path)
            print(f"  = {meta.video}: keypoints cached ({len(df)} frames)")
        else:
            from .pose import get_backend

            be = get_backend(backend_name)
            res = be.estimate(meta.path)
            fps = res.fps or fps
            df = keypoints_to_frame(res.keypoints)
            write_parquet(df, kp_path)
            print(f"  + {meta.video}: {len(df)} frames via {be.name}")

        kp = frame_to_keypoints(df)
        for i, (start, bottom, end) in enumerate(segment_reps(kp, fps)):
            rows.append(
                {
                    "rep_id": f"{meta.video}#r{i:02d}",
                    "video": meta.video,
                    "session_id": meta.session_id,
                    "exercise": meta.exercise,
                    "set_index": meta.set_index,
                    "rep_index": i,
                    "start_frame": start,
                    "bottom_frame": bottom,
                    "end_frame": end,
                    "fps": round(float(fps), 4),
                }
            )
        print(f"    {sum(r['video'] == meta.video for r in rows)} reps segmented")

    reps = pd.DataFrame(rows)
    if reps.empty:
        raise SystemExit(
            "no reps segmented from any video. Check out/keypoints/*.parquet, then "
            "write out/reps.csv by hand if the segmenter cannot see the movement."
        )
    write_csv(reps, PATHS.o(S.P_REPS))
    return reps


def load_reps() -> pd.DataFrame:
    return read_csv(PATHS.o(S.P_REPS), "ingest")
