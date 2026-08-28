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

from .movements import resolve

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
    view: str | None = None      # declared camera side, overrides estimation
    bin: str | None = None       # declared viewpoint bin, overrides estimation


def discover(videos_dir: Path | None = None) -> list[Path]:
    d = videos_dir or PATHS.videos
    if not d.exists():
        raise SystemExit(f"no video directory at {d} - create it and add clips")
    return sorted(p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXTS)


def load_metadata(videos: list[Path], videos_dir: Path | None = None) -> list[VideoMeta]:
    """Session metadata comes from <videos_dir>/sessions.csv when present, else
    from the filename convention, else from the file's modification date.

    session_id matters: it is what makes 'track progress between sessions'
    answerable at all. Two reps from the same day are not independent evidence
    about a training block.
    """
    sidecar = (videos_dir or PATHS.videos) / "sessions.csv"
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
        view = row.get("view")
        view = None if view is None or pd.isna(view) else str(view).strip().lower()
        vbin = row.get("bin")
        vbin = None if vbin is None or pd.isna(vbin) else str(vbin).strip().upper()
        metas.append(VideoMeta(stem, p, sess, exercise, set_index, view, vbin))
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
def _clean_signal(sig: np.ndarray, conf: np.ndarray,
                  min_conf: float = 0.35) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate short low-confidence gaps, smooth, and report which frames
    were actually observed.

    Frames are interpolated rather than dropped so that indices stay aligned
    with the video - the QC overlay and every reported timestamp depend on
    that. `valid` records what was really seen, so a rep sitting on top of a
    long invented stretch can be rejected later.
    """
    valid = np.isfinite(sig) & (conf >= min_conf)
    if valid.sum() < 5:
        return np.zeros_like(sig), valid
    idx = np.arange(len(sig))
    out = np.interp(idx, idx[valid], sig[valid])
    win = max(5, min(21, (len(out) // 12) | 1))
    if len(out) > win:
        out = savgol_filter(out, win, 2)
    return out, valid


def segment_reps(kp: np.ndarray, fps: float, movement=None,
                 max_invented_frac: float = 0.4,
                 max_half_rep_s: float = 4.0, trace=None) -> list[tuple[int, int, int]]:
    """See `segment_reps_verbose`; returns the reps only."""
    return segment_reps_verbose(kp, fps, movement, max_invented_frac,
                                max_half_rep_s, trace)[0]


def segment_reps_verbose(kp: np.ndarray, fps: float, movement=None,
                         max_invented_frac: float = 0.4,
                         max_half_rep_s: float = 4.0,
                         trace=None,
                         ) -> tuple[list[tuple[int, int, int]], list[str]]:
    """Split a set into reps on the movement's own tracking signal.

    The signal is oriented by the movement profile so that the turnaround is
    always a maximum, whichever way the movement travels: a squat descends to
    its bottom, a muscle-up ascends to its lockout, and both come out of
    `tracking_signal` as a peak. One segmenter therefore covers both, instead
    of one that silently segments the gaps between reps when handed the wrong
    exercise.

    A rep runs rest -> turnaround -> rest, with the boundaries taken where the
    signal crosses a fixed fraction of the rep's own amplitude. Reps built
    mostly from interpolated frames are rejected: they are a claim about
    footage the pose estimator never saw.

    This is a heuristic and it will be wrong on some sets. That is why
    out/reps.csv is a plain editable file: fix it there and re-run. Nothing
    downstream re-derives segmentation.
    """
    from .movements import DEFAULT, MAX_BAR_TRAVEL, anchor_travel, tracking_signal
    from .trace import NullTrace

    tr = trace or NullTrace()
    movement = movement or DEFAULT
    tr.stage("segment")
    reasons: list[str] = []
    raw, conf = tracking_signal(kp, movement)
    sig, valid = _clean_signal(raw, conf)
    tr.step("signal built", movement=movement.name, signal=movement.signal,
            frames=int(len(sig)), observed_frames=int(valid.sum()),
            observed_frac=float(valid.mean()) if len(valid) else 0.0)
    if not valid.any():
        tr.reject("all reps", "no frame had a usable pose for this movement's landmarks")
        return [], ["no frame had a usable pose for this movement's landmarks"]

    rest = float(np.percentile(sig[valid], 15))
    apex = float(np.percentile(sig[valid], 97))
    amplitude = apex - rest
    tr.step("amplitude", rest_p15=rest, apex_p97=apex, amplitude=amplitude)
    if amplitude <= 1e-6:
        tr.reject("all reps", "the tracked signal never moved")
        return [], ["the tracked signal never moved - no movement detected"]

    min_dist = max(1, int(movement.min_rep_s * fps))
    peaks, _ = find_peaks(sig, prominence=0.35 * amplitude, distance=min_dist)
    tr.step("candidate turnarounds", count=int(len(peaks)),
            at_seconds=[round(float(p) / fps, 2) for p in peaks],
            prominence_required=0.35 * amplitude, min_separation_frames=min_dist)
    if len(peaks) == 0:
        tr.reject("all reps", "no turnaround stood out from the noise",
                  prominence_required=0.35 * amplitude)
        return [], ["no turnaround stood out from the noise"]

    # Boundaries: cross a 30%-of-amplitude gate to leave the peak, then keep
    # walking outward while the signal is still falling, so the rep ends at the
    # actual rest position rather than at the gate.
    #
    # This matters more than it looks. Stopping at the gate would make every
    # amplitude metric measure the distance from an arbitrary threshold instead
    # of from the hang, and every duration metric omit the slowest part of the
    # rep - both wrong in the same direction on every rep, which is exactly the
    # kind of bias that survives averaging.
    gate = rest + 0.30 * amplitude
    max_half = int(max_half_rep_s * fps)
    reps: list[tuple[int, int, int]] = []
    for pk in peaks:
        at = round(float(pk) / fps, 2)
        if sig[pk] < rest + 0.6 * amplitude:
            tr.reject(f"candidate at {at}s", "peak too shallow to be a turnaround",
                      peak_value=float(sig[pk]), required=rest + 0.6 * amplitude)
            continue
        if not valid[pk]:
            # The turnaround itself was never observed. Everything a rep record
            # asserts is anchored to it, so an interpolated peak is not a rep.
            reasons.append(
                f"turnaround at {pk / fps:.1f}s was never actually tracked - "
                "the subject left frame or the pose was lost at the top"
            )
            tr.reject(f"candidate at {at}s", "the turnaround itself was never tracked",
                      frame=int(pk))
            continue

        def walk(i: int, step: int) -> int:
            n, limit = 0, len(sig) - 1
            while 0 <= i + step <= limit and sig[i + step] > gate and n < max_half:
                i += step
                n += 1
            while 0 <= i + step <= limit and sig[i + step] < sig[i] and n < max_half:
                i += step
                n += 1
            return i

        a, b = walk(pk, -1), walk(pk, +1)
        if b - a < max(3, min_dist // 2):
            reasons.append(f"candidate at {pk / fps:.1f}s was too brief to be a rep")
            tr.reject(f"candidate at {at}s", "too brief to be a rep",
                      frames=int(b - a), min_frames=max(3, min_dist // 2))
            continue
        if valid[a:b + 1].mean() < (1.0 - max_invented_frac):
            reasons.append(
                f"candidate at {pk / fps:.1f}s is mostly interpolated - "
                f"only {valid[a:b + 1].mean():.0%} of its frames were tracked"
            )
            tr.reject(f"candidate at {at}s", "mostly interpolated frames",
                      observed_frac=float(valid[a:b + 1].mean()),
                      min_observed=1.0 - max_invented_frac)
            continue
        # The anchor a bar movement is measured against has to stay put.
        if movement.origin == "wrist":
            travel = anchor_travel(kp, a, b)
            if travel > MAX_BAR_TRAVEL:
                reasons.append(
                    f"candidate at {pk / fps:.1f}s: the hands travelled "
                    f"{travel:.1f} torso-lengths, so they were not on a fixed bar "
                    "- this is movement around the rig, not a rep"
                )
                tr.reject(f"candidate at {at}s", "the hands were not on anything fixed",
                          wrist_travel=float(travel), max_travel=MAX_BAR_TRAVEL,
                          window_s=[round(a / fps, 2), round(b / fps, 2)])
                continue
        # Two reps may legitimately share a boundary frame: a lifter with a
        # tight cadence returns to the same rest position and goes again, so
        # one rep ends exactly where the next begins. Only a substantial
        # overlap means the segmenter has found the same rep twice.
        if reps:
            prev_a, _, prev_b = reps[-1]
            overlap = min(b, prev_b) - max(a, prev_a)
            if overlap > 0.25 * min(b - a, prev_b - prev_a):
                if sig[pk] <= sig[reps[-1][1]]:
                    tr.reject(f"candidate at {at}s", "overlaps a stronger rep already found",
                              overlap_frames=int(overlap),
                              this_peak=float(sig[pk]), kept_peak=float(sig[reps[-1][1]]))
                    continue
                tr.note("replaced an earlier weaker overlapping rep",
                        dropped_at_s=round(reps[-1][1] / fps, 2))
                reps.pop()
        reps.append((int(a), int(pk), int(b)))
        tr.decision(f"rep {len(reps)}", "accepted",
                    window_s=[round(a / fps, 2), round(b / fps, 2)],
                    turnaround_s=at, frames=[int(a), int(pk), int(b)])
    tr.step("segmentation complete", accepted=len(reps),
            rejected=len(peaks) - len(reps))
    if not reps and not reasons:
        reasons.append("candidates were found but none met the rep criteria")
    return reps, reasons


def ingest(backend_name: str, force: bool = False, from_part_a: Path | None = None,
           videos_dir: Path | None = None) -> pd.DataFrame:
    """Produce out/keypoints/<video>.parquet and out/reps.csv."""
    PATHS.ensure()
    d = videos_dir or PATHS.videos
    videos = discover(d)
    if not videos:
        raise SystemExit(
            f"no videos found in {d}\n"
            "Add clips there (see data/videos/README.md for the naming convention)."
        )
    metas = load_metadata(videos, d)

    rows: list[dict] = []
    diagnostics: list[dict] = []
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
        movement = resolve(meta.exercise)
        found, why = segment_reps_verbose(kp, fps, movement)
        diagnostics.append({
            "video": meta.video, "session_id": meta.session_id,
            "exercise": movement.name, "n_reps": len(found),
            "n_frames": len(df), "fps": round(float(fps), 4),
            "mean_confidence": round(float(kp[:, S.ANALYSIS_IDX, 2].mean()), 4),
            "reasons": " | ".join(dict.fromkeys(why)),
        })
        for i, (start, turn, end) in enumerate(found):
            rows.append(
                {
                    "rep_id": f"{meta.video}#r{i:02d}",
                    "video": meta.video,
                    "session_id": meta.session_id,
                    "exercise": movement.name,
                    "set_index": meta.set_index,
                    "view": meta.view or "",
                    "declared_bin": meta.bin or "",
                    "rep_index": i,
                    "start_frame": start,
                    "turn_frame": turn,
                    "end_frame": end,
                    "fps": round(float(fps), 4),
                }
            )
        n = sum(r["video"] == meta.video for r in rows)
        print(f"    {n} reps segmented")
        if not n and why:
            for reason in dict.fromkeys(why):
                print(f"      - {reason}")

    write_csv(pd.DataFrame(diagnostics), PATHS.o(S.P_INGEST_LOG))
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
