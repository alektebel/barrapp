#!/usr/bin/env python3
"""Classify and cut the calisthenics dataset with MiMo (api.nan.builders).

For every clip in data/calisthenics/metadata.csv:
  1. Sample timestamped frames with ffmpeg.
  2. Ask mimo-v2.6-flash (vision) to verify the trick, write a one-line description,
     and report the time window where the person is actually performing the
     technique (intros, talking heads, and title cards excluded).
  3. Trim the clip in place to that window (re-encode, same 720p recipe as the
     scraper) when the window is sane; the original is always re-downloadable
     from source_url, so nothing is lost.

Outputs:
  data/calisthenics/labels/<trick>/<clip-stem>.json   full model verdict
  data/calisthenics/labels.csv                        flat summary ledger

Usage:
  python scripts/label_calisthenics.py [--workers 3] [--limit N] [--no-trim]
      [--force] [--dataset DIR]
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API_URL = "https://api.nan.builders/v1/chat/completions"
MODEL = "mimo-v2.6-flash"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
TRICKS = [
    "muscle_up", "pull_up", "dip", "push_up", "squat", "knee_raise",
    "pistol_squat", "handstand", "front_lever", "planche", "back_lever",
    "human_flag", "bench_press", "deadlift", "barbell_squat",
    "split_squat", "bulgarian_split_squat",
    "weighted_pull_up", "weighted_dip", "weighted_squat",
]

PROMPT = """You are labeling a calisthenics/weightlifting training dataset.
These frames were sampled at fixed timestamps from ONE video clip, in time order:
{frame_list}

The dataset claims the trick is "{claimed_trick}" (claimed duration {duration}s).

Reply with ONLY a JSON object, no markdown fences:
{{
  "detected_trick": one of {trick_list} or "none",
  "agrees": true|false,
  "description": "<one precise sentence: viewpoint, equipment, person, what happens>",
  "technique_start": <first sampled timestamp (s, number) where the person is visibly performing the exercise>,
  "technique_end": <last sampled timestamp (s, number) where the exercise is still visible>,
  "reps_estimate": <integer>
}}
Rules: technique_start/technique_end must be timestamps from the list above and
cover ONLY active performance (no intro, talking head, text cards, resting).
If the exercise is never performed, set detected_trick to "none" and start=end=0."""

print_lock = threading.Lock()


def log(msg: str) -> None:
    with print_lock:
        print(msg, file=sys.stderr, flush=True)


def sample_frames(path: Path, duration: float) -> list[tuple[float, str]]:
    n = 10 if duration > 40 else 6
    ts = [round(duration * (i + 0.5) / n, 1) for i in range(n)]
    out: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory() as td:
        for t in ts:
            f = Path(td) / f"f{int(t * 10)}.jpg"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                     "-i", str(path), "-frames:v", "1",
                     "-vf", "scale=512:-2", "-q:v", "5", str(f)],
                    capture_output=True, timeout=60, check=True)
            except Exception:
                continue
            if f.exists():
                out.append((t, base64.b64encode(f.read_bytes()).decode()))
    return out


def call_mimo(frames: list[tuple[float, str]], claimed: str, duration: float,
              api_key: str) -> dict:
    frame_list = "\n".join(f"  frame {i + 1}: t={t}s" for i, (t, _) in enumerate(frames))
    content: list[dict] = [{"type": "text",
                            "text": PROMPT.format(frame_list=frame_list,
                                                  claimed_trick=claimed,
                                                  duration=duration,
                                                  trick_list=json.dumps(TRICKS))}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                for _, b64 in frames]
    payload = {"model": MODEL, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json",
                                          "User-Agent": UA})
    # The endpoint rate-limits, and a 429 that gives up after four quick tries
    # is a clip silently missing from the corpus. Back off geometrically with
    # jitter and keep going: the batch is long anyway, and a label that arrives
    # a minute late is worth far more than one that never arrives.
    body = None
    attempts = int(os.environ.get("NAN_MAX_ATTEMPTS", "8") or 8)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                body = json.load(r)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", 0)
            # Retry anything that is not a clear, permanent refusal. The
            # enumerated-codes version of this kept losing clips to statuses
            # nobody had thought to list: 524 (Cloudflare timed out waiting on
            # the model) and even 400, whose clips were re-sent unchanged
            # minutes later and labelled fine. Both are transient here, and a
            # status left off the list silently drops a clip from the corpus
            # forever - the one failure mode this batch cannot afford. So the
            # default is retry, and only 401/403/404 - credentials and routing,
            # which no amount of waiting fixes - are allowed to be fatal.
            retryable = (code not in (401, 403, 404)) or not isinstance(
                e, urllib.error.HTTPError)
            if retryable and attempt < attempts - 1:
                import random
                import time
                time.sleep(min(90.0, 4.0 * (2 ** attempt))
                           * (0.7 + 0.6 * random.random()))
                continue
            raise
    text = body["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0)) if m else {"raw": text}


def trim(path: Path, start: float, end: float, duration: float) -> bool:
    """Cut in place to [start, end] with a small margin; True if it cut."""
    if end - start < 4 or end <= start or (end - start) >= duration * 0.95:
        return False
    start = max(0.0, start - 1.0)
    end = min(duration, end + 1.0)
    tmp = path.with_suffix(".cut.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start),
             "-to", str(end), "-i", str(path),
             # The inner quotes are load-bearing: ffmpeg's filtergraph parser
             # splits on commas, so an unquoted min(ih,720) is read as a second
             # filter named "720)" and the whole call fails.
             "-vf", "scale=-2:'min(ih,720)'", "-c:v", "libx264",
             "-preset", "fast", "-crf", "23", "-c:a", "aac",
             "-movflags", "+faststart", str(tmp)],
            capture_output=True, timeout=900, check=True)
        tmp.replace(path)
        return True
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log(f"  [cut] failed {path.name}: {str(e)[:120]}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="data/calisthenics")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-trim", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    api_key = os.environ.get("NAN_API_KEY", "")
    if not api_key:
        print("NAN_API_KEY not set", file=sys.stderr)
        return 1

    root = Path(a.dataset)
    # The corpus is the videos on disk, not the ledger. metadata.csv only ever
    # holds rows a scrape wrote, and the directory has since grown past it - 26
    # clips had no row, so they could never be labelled, and two whole
    # rule-covered movements (split_squat, bulgarian_split_squat) sat at zero
    # labels because of it. The ledger is now consulted for what it does know
    # (duration, fps) and never for what exists.
    meta: dict[str, dict] = {}
    meta_path = root / "metadata.csv"
    if meta_path.exists():
        with open(meta_path) as f:
            for r in csv.DictReader(f):
                meta[r["file"]] = r
    rows = []
    for video in sorted((root / "videos").rglob("*.mp4")):
        rel = str(video.relative_to(root))
        row = dict(meta.get(rel, {}))
        row["file"] = rel
        row["trick"] = video.parent.name
        rows.append(row)
    label_dir = root / "labels"
    label_dir.mkdir(exist_ok=True)

    done = {"n": 0}

    def work(row: dict) -> dict | None:
        path = root / row["file"]
        sidecar = label_dir / Path(row["file"]).with_suffix(".json")
        if sidecar.exists() and not a.force:
            return None
        try:
            duration = float(row.get("duration") or 0) or probe_duration(path)
            frames = sample_frames(path, duration)
            if not frames:
                return None
            verdict = call_mimo(frames, row["trick"], duration, api_key)
            trimmed = False
            if not a.no_trim and verdict.get("agrees"):
                try:
                    s = float(verdict["technique_start"])
                    e = float(verdict["technique_end"])
                    trimmed = trim(path, s, e, duration)
                except (KeyError, TypeError, ValueError):
                    pass
            if trimmed:
                verdict["original_duration"] = duration
                verdict["duration_after_cut"] = probe_duration(path)
            verdict["file"] = row["file"]
            verdict["claimed_trick"] = row["trick"]
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(verdict, indent=1))
            done["n"] += 1
            log(f"  [{done['n']}] {row['file']} -> {verdict.get('detected_trick')} "
                f"agrees={verdict.get('agrees')} cut={trimmed}")
            return verdict
        except Exception as e:
            log(f"  [err] {row['file']}: {str(e)[:160]}")
            return None

    todo = rows[: a.limit] if a.limit else rows
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(work, todo))

    out = root / "labels.csv"
    fieldnames = ["file", "claimed_trick", "detected_trick", "agrees",
                  "reps_estimate", "technique_start", "technique_end",
                  "trimmed", "description"]
    existing: dict[str, dict] = {}
    if out.exists():
        with open(out) as f:
            for r in csv.DictReader(f):
                existing[r["file"]] = r
    # merge: any clip with a sidecar (including ones skipped this run)
    merged: dict[str, dict] = {}
    for j in sorted(label_dir.rglob("*.json")):
        v = json.loads(j.read_text())
        f = v.get("file")
        if not f:
            continue
        merged[f] = {
            "file": f, "claimed_trick": v.get("claimed_trick", ""),
            "detected_trick": v.get("detected_trick", ""),
            "agrees": v.get("agrees", ""),
            "reps_estimate": v.get("reps_estimate", ""),
            "technique_start": v.get("technique_start", ""),
            "technique_end": v.get("technique_end", ""),
            "trimmed": "yes" if "duration_after_cut" in v else "no",
            "description": (v.get("description") or "").replace("\n", " "),
        }
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            if row["file"] in merged:
                w.writerow(merged[row["file"]])
    log(f"wrote {out} ({len(merged)} labeled)")
    return 0


def probe_duration(path: Path) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip())
    except Exception:
        return 60.0


if __name__ == "__main__":
    sys.exit(main())
