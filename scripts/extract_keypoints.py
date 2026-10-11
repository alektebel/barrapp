#!/usr/bin/env python
"""Extract and cache pose keypoints for the whole labelled corpus.

Pose is the expensive stage, and it is the one every later experiment depends
on: a classifier retrain, a fault threshold sweep and an evaluation run all read
``out/keypoints/<stem>.parquet``. So it is paid once, here, and every other
script becomes cheap.

Two properties this needs that an in-process loop does not give:

  * **One bad clip must not end the batch.** A corrupt container, an AV1 stream
    the host cannot decode, or a clip big enough to be OOM-killed would take the
    whole run with it. Each clip is posed in its own subprocess, so a kill costs
    that clip and nothing else; the failure is recorded with its reason.
  * **It is resumable.** A clip whose parquet already exists is skipped, so the
    batch can be stopped and restarted as the corpus grows.

Usage:
  python scripts/extract_keypoints.py                       # whole corpus, GPU if present
  python scripts/extract_keypoints.py --tricks squat,dip
  python scripts/extract_keypoints.py --workers 3 --device cpu
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VIDEOS = ROOT / "data" / "calisthenics" / "videos"
KEYPOINTS = ROOT / "out" / "keypoints"
LEDGER = ROOT / "out" / "keypoints" / "extraction.json"

_CHILD = """
import sys, time
from pathlib import Path
sys.path.insert(0, ROOT_PLACEHOLDER)
from barra.posecache import load_or_estimate
from barra.ingest import probe_video
v = Path(sys.argv[1])
info = {}
try:
    info = probe_video(v)
except Exception:
    pass
fps = float(info.get("fps") or 30.0) or 30.0
t = time.time()
r = load_or_estimate(v, fresh=False, write_cache=True, fallback_fps=fps)
print("OK", r.keypoints.shape[0], round(r.fps, 2), round(time.time() - t, 1))
""".replace("ROOT_PLACEHOLDER", repr(str(ROOT)))


def _device_default() -> str:
    try:
        import torch  # noqa: PLC0415
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:  # noqa: BLE001 - no torch means cpu, not a crash
        pass
    return "cpu"


def ensure_decodable(video: Path) -> str:
    """Transcode to the corpus recipe if the container is not already it.

    Pose reads frames through ffmpeg, and the estimator falls over on some of
    what a scrape brings home: AV1 streams raise "Get current frame error",
    and oversized ones have OOM-killed the worker and once corrupted the heap
    ("double free or corruption"). The scraper normalises what it downloads,
    but clips that arrive any other way - a browser extension, a manual copy -
    never pass through it, and the failure surfaces here, seventeen clips into
    a batch, as a reason nobody connects back to the container.

    `normalize_video` is a no-op on a clip that already conforms, so this is
    cheap to always do and only ever touches a clip about to be posed for the
    first time.
    """
    import subprocess as sp  # noqa: PLC0415

    try:
        r = sp.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name,height", "-of",
                    "csv=p=0", str(video)],
                   capture_output=True, text=True, timeout=60)
    except (OSError, sp.SubprocessError):
        return ""
    parts = ((r.stdout or "").strip() + ",,").split(",")
    codec, height = parts[0], parts[1]
    if codec == "h264" and height.isdigit() and int(height) <= 720:
        return ""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from scrape_calisthenics import normalize_video  # noqa: PLC0415
    normalize_video(video)
    return f"{codec}/{height or '?'}"


def pose_one(video: Path, device: str, timeout: int) -> dict:
    env = dict(os.environ)
    env["BARRA_POSE_BACKEND"] = env.get("BARRA_POSE_BACKEND", "ultralytics")
    env["BARRA_POSE_DEVICE"] = device
    started = time.time()
    try:
        p = subprocess.run([sys.executable, "-u", "-c", _CHILD, str(video)],
                           capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"clip": video.name, "trick": video.parent.name, "ok": False,
                "reason": "timeout", "runtimeS": round(time.time() - started, 1)}
    line = next((l for l in p.stdout.splitlines() if l.startswith("OK ")), "")
    if p.returncode == 0 and line:
        _, frames, fps, secs = line.split()
        return {"clip": video.name, "trick": video.parent.name, "ok": True,
                "frames": int(frames), "fps": float(fps), "runtimeS": float(secs)}
    reason = "killed (out of memory)" if p.returncode == -9 else (
        (p.stderr.strip().splitlines() or ["unknown"])[-1][:200])
    return {"clip": video.name, "trick": video.parent.name, "ok": False,
            "reason": reason, "returncode": p.returncode,
            "runtimeS": round(time.time() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tricks", default="", help="comma-separated class filter")
    ap.add_argument("--device", default=_device_default())
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--redo", action="store_true", help="re-pose clips already cached")
    ap.add_argument("--no-normalise", action="store_true",
                    help="pose the container as it is, even if the estimator "
                         "is known to choke on it")
    ap.add_argument("--labelled-only", action="store_true",
                    help="only clips that already have a vision label, so "
                         "every clip posed carries a technique window too")
    args = ap.parse_args()

    want = {t.strip() for t in args.tricks.split(",") if t.strip()}
    KEYPOINTS.mkdir(parents=True, exist_ok=True)

    clips = sorted(p for p in VIDEOS.rglob("*.mp4")
                   if not want or p.parent.name in want)
    if args.labelled_only:
        # Posing a clip the labeller has not seen adds it to every corpus that
        # reads the keypoint cache - carrying a folder label nobody checked and
        # no technique window, so it is featurised across the whole video
        # including the talking head. Pose is cheap; a corpus quietly diluted
        # with unwindowed clips is not.
        labelled = set()
        for j in (ROOT / "data" / "calisthenics" / "labels").rglob("*.json"):
            try:
                v = json.loads(j.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            f = v.get("file")
            if f and (v.get("detected_trick") or "").strip() not in ("", "none"):
                labelled.add(Path(f).name)
        before = len(clips)
        clips = [p for p in clips if p.name in labelled]
        print(f"--labelled-only: {len(clips)} of {before} clips have a vision "
              f"label", flush=True)
    todo = [p for p in clips
            if args.redo or not (KEYPOINTS / f"{p.stem}.parquet").exists()]
    print(f"{len(clips)} clips, {len(todo)} to pose, device={args.device}", flush=True)

    if not args.no_normalise:
        fixed = [(p, was) for p in todo if (was := ensure_decodable(p))]
        if fixed:
            print(f"transcoded {len(fixed)} clip(s) the estimator cannot read:",
                  flush=True)
            for p, was in fixed:
                print(f"  {p.parent.name}/{p.name}: {was} -> h264/<=720",
                      flush=True)

    rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for row in pool.map(lambda p: pose_one(p, args.device, args.timeout), todo):
            done += 1
            rows.append(row)
            mark = "ok " if row["ok"] else "FAIL"
            extra = row.get("frames", row.get("reason", ""))
            print(f"[{done}/{len(todo)}] {mark} {row['trick']}/{row['clip']} {extra}",
                  flush=True)

    failed = [r for r in rows if not r["ok"]]
    cached = sum(1 for p in clips if (KEYPOINTS / f"{p.stem}.parquet").exists())
    summary = {"clips": len(clips), "posed": len(rows), "failed": len(failed),
               "cached": cached, "coverage": round(cached / max(1, len(clips)), 3),
               "device": args.device, "failures": failed}
    LEDGER.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "failures"}, indent=2))
    for r in failed:
        print(f"  failed: {r['trick']}/{r['clip']}: {r.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
