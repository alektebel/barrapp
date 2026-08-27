"""Persistent memory across sessions.

`out/` is scratch: it is rebuilt from scratch on every run and is gitignored.
Anything that must survive to the *next* training session lives in `profile/`,
which is committed. That split is the whole point - a tool that forgets what
last month looked like cannot say anything about progress.

    profile/subject.json    the subject's anatomy and viewpoint calibration,
                            accumulated over every clip ever ingested
    profile/sessions.jsonl  append-only ledger, one record per video ever seen
    profile/reps.parquet    per-rep metrics for every rep ever measured

Design rules, in order of importance:

1. **Append-only, never destructive.** Re-ingesting a video updates its record
   in place, keyed by a hash of the video's own bytes. Deleting `out/` never
   loses history; the ledger is the memory.
2. **Content-addressed.** The key is the video's SHA-256, not its filename.
   Re-encoding or renaming a clip is detected as a new observation rather than
   silently overwriting the old one, and the same clip ingested twice does not
   double-count.
3. **Provenance on every number.** Each record carries the pose backend, the
   code version and the timestamp that produced it. A metric measured by a
   different backend is not comparable with one measured by another, and the
   ledger has to make that visible rather than hide it in an average.
4. **Plain formats.** JSON lines and parquet, readable without this tool. If
   the memory can only be read by the thing that wrote it, it is not memory.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .config import PATHS

PROFILE_DIRNAME = "profile"
SUBJECT = "subject.json"
LEDGER = "sessions.jsonl"
REPS = "reps.parquet"


def profile_dir() -> Path:
    d = PATHS.root / PROFILE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def video_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(v) -> str:
    """Empty pandas cells arrive as float NaN, which is truthy - `str(v or "")`
    quietly writes the string "nan" into the ledger."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return ""
    return str(v)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def read_ledger() -> pd.DataFrame:
    path = profile_dir() / LEDGER
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return pd.DataFrame(rows)


def write_ledger(df: pd.DataFrame) -> Path:
    path = profile_dir() / LEDGER
    with open(path, "w") as f:
        for _, r in df.iterrows():
            f.write(json.dumps({k: _json_safe(v) for k, v in r.items()},
                               sort_keys=True) + "\n")
    return path


def _json_safe(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return v


def read_reps() -> pd.DataFrame:
    path = profile_dir() / REPS
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------
# Remember
# ---------------------------------------------------------------------------
def remember(videos_dir: Path | None = None, backend: str = "unknown",
             note: str = "") -> dict:
    """Fold the current run in `out/` into the persistent profile.

    Idempotent: running it twice on the same footage changes nothing except the
    `last_seen` timestamps.
    """
    from . import schema as S
    from .ingest import discover, frame_to_keypoints
    from .io_utils import read_csv
    from .metrics import compute_all

    reps = read_csv(PATHS.o(S.P_REPS), "ingest")
    vdir = videos_dir or PATHS.videos
    by_stem = {p.stem: p for p in discover(vdir)} if vdir.exists() else {}

    viewpoints = pd.DataFrame()
    vp_path = PATHS.o(S.P_VIEWPOINTS)
    if vp_path.exists():
        viewpoints = pd.read_csv(vp_path)

    def kp_of(video: str) -> np.ndarray:
        return frame_to_keypoints(
            pd.read_parquet(PATHS.o(S.P_KEYPOINTS, f"{video}.parquet"))
        )

    apath = PATHS.o(S.P_ANATOMY)
    anatomy = json.loads(apath.read_text()) if apath.exists() else None
    metrics = compute_all(reps, kp_of, anatomy)

    # ---- per-video ledger records
    #
    # Driven by the ingest log, not by reps.csv, so that a clip which produced
    # NO usable rep is still remembered. That is the more valuable record of
    # the two: it is the one that tells you a session was wasted and why, and a
    # profile that only remembers successes cannot give that feedback.
    log_path = PATHS.o(S.P_INGEST_LOG)
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()
    if log.empty:
        log = (reps.groupby("video")
               .agg(session_id=("session_id", "first"),
                    exercise=("exercise", "first"), fps=("fps", "first"))
               .assign(n_reps=reps.groupby("video").size(), reasons="")
               .reset_index())

    new_rows = []
    for _, entry in log.iterrows():
        video = str(entry["video"])
        src = by_stem.get(video)
        vh = video_hash(src) if src else f"nohash:{video}"
        mg = metrics[metrics["video"] == video]
        vrow = viewpoints[viewpoints["video"] == video]
        rec = {
            "video_sha": vh,
            "video": video,
            "session_id": str(entry["session_id"]),
            "exercise": str(entry["exercise"]),
            "n_reps": int(entry["n_reps"]),
            "fps": float(entry["fps"]),
            "mean_confidence": float(entry.get("mean_confidence", float("nan"))),
            "no_rep_reasons": _text(entry.get("reasons")),
            "mean_rep_quality": float(mg["q_rep"].mean()) if len(mg) else None,
            "arm_reach": float(mg["q_arm_reach"].median()) if len(mg) else None,
            "bin": str(vrow["bin"].iloc[0]) if len(vrow) else None,
            "side": str(vrow["side"].iloc[0]) if len(vrow) and "side" in vrow else None,
            "azimuth_deg": float(vrow["azimuth_deg"].iloc[0]) if len(vrow) else None,
            "pose_backend": backend,
            "barra_version": __version__,
            "first_seen": _now(),
            "last_seen": _now(),
            "note": note,
        }
        new_rows.append(rec)

    ledger = read_ledger()
    added = updated = 0
    if ledger.empty:
        ledger = pd.DataFrame(new_rows)
        added = len(new_rows)
    else:
        known = set(ledger["video_sha"])
        keep = []
        for rec in new_rows:
            if rec["video_sha"] in known:
                i = ledger.index[ledger["video_sha"] == rec["video_sha"]][0]
                first = ledger.at[i, "first_seen"]
                for k, v in rec.items():
                    ledger.at[i, k] = v
                ledger.at[i, "first_seen"] = first     # never rewrite history
                updated += 1
            else:
                keep.append(rec)
                added += 1
        if keep:
            ledger = pd.concat([ledger, pd.DataFrame(keep)], ignore_index=True)
    ledger = ledger.sort_values(["session_id", "video"]).reset_index(drop=True)
    write_ledger(ledger)

    # ---- per-rep metrics, keyed by video hash so reps follow their source
    sha_of = {r["video"]: r["video_sha"] for r in new_rows}
    metrics = metrics.copy()
    metrics["video_sha"] = metrics["video"].map(sha_of)
    metrics["measured_at"] = _now()
    metrics["pose_backend"] = backend
    old = read_reps()
    if not old.empty:
        old = old[~old["video_sha"].isin(set(metrics["video_sha"]))]
        metrics = pd.concat([old, metrics], ignore_index=True)
    metrics.sort_values(["session_id", "rep_id"]).to_parquet(
        profile_dir() / REPS, index=False
    )

    # ---- subject profile
    subject = update_subject(ledger, metrics)

    empty = ledger[ledger["n_reps"] == 0] if "n_reps" in ledger.columns else ledger.iloc[:0]
    print(f"  ledger: {added} new video(s), {updated} updated, "
          f"{len(ledger)} total across {ledger['session_id'].nunique()} session(s)")
    if len(empty):
        print(f"  {len(empty)} clip(s) produced no usable rep:")
        for _, e in empty.iterrows():
            print(f"    - {e['video']} ({e['session_id']}): "
                  f"{(e.get('no_rep_reasons') or 'no reason recorded')[:110]}")
    print(f"  reps:   {len(metrics)} measured reps in profile/{REPS}")
    print(f"  wrote   profile/{LEDGER}, profile/{REPS}, profile/{SUBJECT}")
    return {"ledger": ledger, "metrics": metrics, "subject": subject,
            "added": added, "updated": updated}


def update_subject(ledger: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    """Anatomy and calibration, merged with whatever the profile already knows.

    Anatomy is re-estimated from all footage rather than averaged with the old
    value, because a later run may simply have better footage. The previous
    estimate is kept in `history` so a sudden change is visible instead of
    silently smoothed away.
    """
    from . import schema as S
    from .io_utils import read_json

    path = profile_dir() / SUBJECT
    prior = json.loads(path.read_text()) if path.exists() else {}

    anatomy = {}
    apath = PATHS.o(S.P_ANATOMY)
    if apath.exists():
        anatomy = read_json(apath, "normalise")

    history = prior.get("history", [])
    if prior.get("anatomy") and prior["anatomy"] != anatomy:
        history.append({"at": prior.get("updated_at"), "anatomy": prior["anatomy"]})

    sessions = sorted(ledger["session_id"].astype(str).unique()) if len(ledger) else []
    subject = {
        "updated_at": _now(),
        "barra_version": __version__,
        "sessions": sessions,
        "n_sessions": len(sessions),
        "n_videos": int(len(ledger)),
        "n_reps": int(len(metrics)),
        "exercises": sorted(ledger["exercise"].dropna().unique().tolist())
        if len(ledger) else [],
        "anatomy": anatomy,
        "history": history[-10:],
    }
    path.write_text(json.dumps(subject, indent=2, sort_keys=True, default=str))
    return subject


def status() -> dict:
    ledger, reps = read_ledger(), read_reps()
    spath = profile_dir() / SUBJECT
    subject = json.loads(spath.read_text()) if spath.exists() else {}
    return {"ledger": ledger, "reps": reps, "subject": subject}
