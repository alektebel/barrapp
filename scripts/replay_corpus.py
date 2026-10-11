"""Run every corpus clip through the production path and record what came out.

    python scripts/replay_corpus.py --out data/golden/baseline.jsonl [--workers 2]
    python scripts/replay_corpus.py --compare data/golden/baseline.jsonl data/golden/run.jsonl

One JSON line per clip: what went in (file, claimed class, split, the silver
label) and what came out (movement, reps, score, blockers), plus every sentinel
violation the run recorded. It is the baseline every later change is compared
against, so it runs the same `process_job` the worker runs - with the LLM and
vision passes OFF, because a baseline that moves when a remote model has a bad
day is not a baseline.

Keypoints are cached (out/keypoints/), so the first pass pays for pose and every
later pass costs seconds per clip. Resumable: clips already in --out are
skipped.

Split: a clip is `test` when its content hash falls in the last fifth, else
`dev`. Thresholds are tuned on dev; test is only looked at to approve.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "calisthenics"
PROD = ROOT / "data" / "prod"

# Movements the classifier can name but the pipeline cannot measure: the right
# answer on these clips is an abstention, never a count.
UNMEASURABLE = {"deadlift", "bench_press", "barbell_squat", "handstand",
                "human_flag", "back_lever"}


def split_of(key: str) -> str:
    return "test" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 5 == 0 else "dev"


def _silver() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = DATA / "labels.csv"
    if path.exists():
        for row in csv.DictReader(path.open()):
            out[row["file"]] = {"trick": row.get("detected_trick") or None,
                                "reps": int(row["reps_estimate"]) if (row.get("reps_estimate") or "").isdigit() else None,
                                "source": "vision-model"}
    return out


def _declared() -> dict[str, dict]:
    out: dict[str, dict] = {}
    path = DATA / "capture.csv"
    if path.exists():
        for row in csv.DictReader(path.open()):
            out[row["file"]] = {"trick": row.get("movement") or None, "source": "declared"}
    return out


def corpus() -> list[dict]:
    silver, declared = _silver(), _declared()
    clips = []
    for f in sorted((DATA / "videos").rglob("*")):
        if f.suffix.lower() not in {".mp4", ".mov", ".webm", ".mkv"}:
            continue
        rel = f.relative_to(DATA).as_posix()
        claimed = f.parent.name
        label = declared.get(rel) or silver.get(rel)
        clips.append({"file": str(f), "rel": rel, "claimed": claimed,
                      "split": split_of(rel), "label": label,
                      "expect_abstain": claimed in UNMEASURABLE})
    for f in sorted(PROD.glob("*.mp4")) if PROD.exists() else []:
        clips.append({"file": str(f), "rel": f"prod/{f.name}", "claimed": None,
                      "split": split_of(f.name), "label": None, "expect_abstain": False})
    return clips


def _run_one(clip: dict) -> dict:
    # Remote models off: see the module docstring.
    for k in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY", "DEEPSEEK_API_KEY"):
        os.environ.pop(k, None)
    os.environ["NAN_BASE_URL"] = ""
    os.environ.setdefault("BARRA_SENTINEL", "record")
    sys.path[:0] = [str(ROOT), str(ROOT / "server")]
    from barra.posecache import load_or_estimate
    from barra.trace import Trace
    from process import process_job

    t0 = time.time()
    row = {k: clip[k] for k in ("rel", "claimed", "split", "label", "expect_abstain")}
    try:
        video = Path(clip["file"])
        pose = load_or_estimate(video, write_cache=True, trace=Trace("cache"))
        r = process_job({"id": video.stem, "exercise": "auto"}, video, pose=pose)
        row.update({
            "exercise": r.get("exercise"), "n_reps": r.get("n_reps"),
            "n_candidates": r.get("n_candidates"), "sessionScore": r.get("sessionScore"),
            "duration_s": r.get("duration_s"), "blockers": r.get("blockers") or [],
            "fusion": ((r.get("detected") or {}).get("fusion") or {}).get("status"),
            "traceId": r.get("traceId"),
        })
        row["sentinel"] = _violations(r.get("traceId"))
    except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the corpus
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    row["elapsed_s"] = round(time.time() - t0, 1)
    return row


def _violations(trace_id: str | None) -> list[dict]:
    if not trace_id:
        return []
    root = Path(os.environ.get("BARRA_TRACE_DIR", str(ROOT / "out" / "traces")))
    for path in root.rglob(f"{trace_id}*.json"):
        data = json.loads(path.read_text())
        return [v for e in data.get("entries", []) if e.get("kind") == "sentinel"
                for v in (e.get("data") or {}).get("violations", [])]
    return []


def run(out: Path, workers: int, limit: int | None) -> None:
    done = set()
    if out.exists():
        done = {json.loads(l)["rel"] for l in out.read_text().splitlines() if l.strip()}
    todo = [c for c in corpus() if c["rel"] not in done][:limit]
    print(f"{len(done)} done, {len(todo)} to run, {workers} worker(s)", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=workers) as pool, out.open("a") as fh:
        futures = {pool.submit(_run_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i}/{len(todo)}] {row['rel']} -> {row.get('exercise')} "
                  f"reps={row.get('n_reps')} {row.get('error', '')} ({row['elapsed_s']}s)",
                  flush=True)


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    errors = sum(1 for r in rows if r.get("error"))
    zero = sum(1 for r in rows if not r.get("error") and not r.get("n_reps"))
    sentinel = sum(1 for r in rows if r.get("sentinel"))
    abstain = [r for r in rows if r.get("expect_abstain")]
    fabricated = sum(1 for r in abstain if (r.get("n_reps") or 0) > 0)
    named = [r for r in rows if r.get("claimed") and not r.get("expect_abstain") and not r.get("error")]
    agree = sum(1 for r in named if r.get("exercise") == r["claimed"])
    return {"clips": n, "errors": errors, "zero_reps": zero, "sentinel_violations": sentinel,
            "unmeasurable_clips": len(abstain), "fabricated_on_unmeasurable": fabricated,
            "movement_agrees_with_folder": f"{agree}/{len(named)}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "golden" / "baseline.jsonl")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--summary", type=Path)
    a = ap.parse_args()
    if a.summary:
        rows = [json.loads(l) for l in a.summary.read_text().splitlines() if l.strip()]
        print(json.dumps(summary(rows), indent=2))
        return
    run(a.out, a.workers, a.limit)


if __name__ == "__main__":
    main()
