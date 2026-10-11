#!/usr/bin/env python
"""Ask several multimodal models which technique faults matter, in order.

The geometric layer's failure is not measurement, it is judgement. It computes
`lockout_pct` to four decimals and cannot tell whether that is the thing worth
saying: it fires on 55% of judged clip-rules where a real fault is present on
13%, and when its own alarms are ranked by distance-past-threshold the top one
is right 32% of the time against a random baseline of 27%. The correct fault is
usually AMONG the ones that fired - an oracle picking the best of them scores
0.682 - so what is missing is a ranker, not a detector.

This is that ranker. Each model sees frames from the technique window and the
movement's own rule vocabulary, and returns at most three faults in order of
how much they matter, or an explicit "clean". Three, not all of them, because
coaching is one cue at a time: the primary is what the athlete is told, and the
two behind it are what a curious athlete can expand.

Two properties this needs that a single call does not give:

  * **"Clean" has to be reachable.** A prompt that asks "what are the three
    faults" on footage of good technique will invent three, which is the exact
    failure being fixed. The models are told to return an empty list and are
    scored on doing so.
  * **Models are polled independently and merged.** One fluent model is a
    confident single opinion; agreement between two that never saw each other's
    answer is evidence. The merge is a Borda count over ranks, and the payload
    records who voted for what, so a disagreement is visible rather than
    averaged away.

The vocabulary is `rules.py`, so every fault named here has a geometric
primitive behind it and the measurement can be attached as evidence.

Usage:
  python scripts/rank_faults.py --limit 20
  python scripts/rank_faults.py --models mimo-v2.5,glm5.3-flash,qwen3.8-flash
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from barra.rules import RULES  # noqa: E402

API_URL = os.environ.get("NAN_BASE_URL", "https://api.nan.builders") + \
    "/v1/chat/completions"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")
DATASET = ROOT / "data" / "calisthenics"
DEFAULT_MODELS = ("mimo-v2.5", "glm5.3-flash", "qwen3.8-flash")
TOP_N = 3

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, flush=True)


def sample_window(path: Path, start: float, end: float, n: int = 12) -> list:
    """`n` frames spread across the technique window, in time order."""
    span = max(0.1, end - start)
    ts = [round(start + span * (i + 0.5) / n, 2) for i in range(n)]
    out = []
    with tempfile.TemporaryDirectory() as td:
        for t in ts:
            f = Path(td) / f"f{int(t * 100)}.jpg"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                     "-i", str(path), "-frames:v", "1",
                     "-vf", "scale=512:-2", "-q:v", "5", str(f)],
                    capture_output=True, timeout=60, check=True)
            except Exception:  # noqa: BLE001 - a missing frame is not fatal
                continue
            if f.exists():
                out.append((t, base64.b64encode(f.read_bytes()).decode()))
    return out


def prompt_for(movement: str) -> tuple[str, list[str]]:
    rules = RULES[movement]
    ids = [r.id.split(".", 1)[1] for r in rules]
    lines = [f'  - "{r.id.split(".", 1)[1]}" ({r.name}, {r.phase} phase): '
             f'{r.observable}.' for r in rules]
    body = "\n".join(lines)
    text = f"""You are a strength coach reviewing ONE clip of a "{movement}".
These frames are sampled in time order from the part of the clip where the
movement is actually performed.

These are the only faults you may name. The description after each is exactly
what it means - judge that, not your general impression:

{body}

Return the faults that are ACTUALLY VISIBLE, at most {TOP_N}, ordered by how
much they matter to this athlete right now: the first is the one thing you
would say to them, the rest are secondary.

Rules for your answer:
- Name a fault only if you can SEE it in these frames. Do not infer it from
  what usually goes wrong in this movement.
- Most clips of competent technique have ZERO faults. If the technique is
  sound, return an empty list. That is a normal and expected answer, not a
  failure to find something.
- Never pad the list to three. One real fault beats three guesses.
- "severity" is how much it matters: major | moderate | minor.

Reply with ONLY a JSON object, no markdown fences:
{{
  "is_the_movement": true|false,
  "faults": [
    {{"name": "<one of the names above>", "severity": "major|moderate|minor",
      "why": "<what you saw, one short clause>"}}
  ]
}}"""
    return text, ids


def call(frames: list, movement: str, model: str, api_key: str) -> dict:
    text, ids = prompt_for(movement)
    content: list[dict] = [{"type": "text", "text": text}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                for _, b64 in frames]
    # No max_tokens: these models spend the budget on reasoning before emitting
    # content, so a cap returns finish_reason="length" with an EMPTY string - a
    # 200 that reads as a JSON parse bug rather than a truncation.
    payload = {"model": model, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json", "User-Agent": UA})
    attempts = int(os.environ.get("NAN_MAX_ATTEMPTS", "8") or 8)
    body = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = json.load(r)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", 0)
            if code in (401, 403, 404) or attempt == attempts - 1:
                raise
            import random
            import time
            time.sleep(min(90.0, 4.0 * (2 ** attempt)) * (0.7 + 0.6 * random.random()))
    raw = (body["choices"][0]["message"]["content"] or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    verdict = json.loads(raw[start:end + 1])

    # Keep only names this movement actually defines, preserve the model's
    # order, drop duplicates, and cap the list. A model that invents a fault
    # name has not found a new fault, it has left the vocabulary.
    seen: set[str] = set()
    ranked: list[dict] = []
    for f in (verdict.get("faults") or []):
        name = str((f or {}).get("name", "")).strip()
        if name in ids and name not in seen:
            seen.add(name)
            ranked.append({"name": name,
                           "severity": str(f.get("severity", "")).lower()[:8],
                           "why": str(f.get("why", ""))[:160]})
    return {"model": model, "isTheMovement": bool(verdict.get("is_the_movement", True)),
            "ranked": ranked[:TOP_N],
            "dropped": [f.get("name") for f in (verdict.get("faults") or [])
                        if str((f or {}).get("name", "")).strip() not in ids]}


def merge(votes: list[dict]) -> dict:
    """Borda count over each model's ranking, ties broken by first-place votes.

    Rank 1 is worth `TOP_N` points, rank 2 one fewer, and so on, so a fault
    every model puts second outranks one a single model put first. A model
    returning an empty list is not abstaining - it is voting that the clip is
    clean, and that vote is counted.
    """
    points: dict[str, float] = defaultdict(float)
    firsts: dict[str, int] = defaultdict(int)
    backers: dict[str, list[str]] = defaultdict(list)
    clean = 0
    for v in votes:
        if not v["ranked"]:
            clean += 1
            continue
        for i, f in enumerate(v["ranked"]):
            points[f["name"]] += TOP_N - i
            backers[f["name"]].append(v["model"])
            if i == 0:
                firsts[f["name"]] += 1

    order = sorted(points, key=lambda n: (-points[n], -firsts[n], n))
    ranked = [{"name": n, "points": points[n], "firstPlaceVotes": firsts[n],
               "models": backers[n], "agreed": len(backers[n]) > 1}
              for n in order[:TOP_N]]
    return {
        "primary": ranked[0] if ranked else None,
        "secondary": ranked[1:],
        "cleanVotes": clean,
        "modelsAsked": len(votes),
        # A clip every model called clean is a real answer, and the one the
        # geometric layer almost never gives.
        "verdict": "clean" if clean == len(votes) else "faults",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "fault-ranked")
    ap.add_argument("--labels", type=Path, default=DATASET / "labels")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    api_key = os.environ.get("NAN_API_KEY", "")
    if not api_key:
        print("NAN_API_KEY not set", file=sys.stderr)
        return 1
    models = [m.strip() for m in a.models.split(",") if m.strip()]

    windows: dict[str, tuple[float, float]] = {}
    detected: dict[str, str] = {}
    for j in a.labels.rglob("*.json"):
        try:
            v = json.loads(j.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        f = v.get("file")
        if not f:
            continue
        name = Path(f).name
        detected[name] = (v.get("detected_trick") or "").strip()
        try:
            s, e = float(v["technique_start"]), float(v["technique_end"])
            if e - s >= 3.0:
                windows[name] = (s, e)
        except (KeyError, TypeError, ValueError):
            pass

    todo = []
    for p in sorted((DATASET / "videos").rglob("*.mp4")):
        movement = p.parent.name
        if movement not in RULES or detected.get(p.name) != movement:
            continue
        out = a.out / movement / f"{p.stem}.json"
        if out.exists() and not a.force:
            continue
        todo.append((p, movement))
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(todo)} clips to rank, models={models}", flush=True)
    done = {"n": 0}

    def work(item) -> None:
        p, movement = item
        try:
            s, e = windows.get(p.name, (0.0, 0.0))
            if e - s < 3.0:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(p)], capture_output=True, text=True,
                    timeout=30)
                s, e = 0.0, float((r.stdout or "60").strip() or 60)
            frames = sample_window(p, s, e)
            if len(frames) < 4:
                log(f"  [skip] {p.name}: only {len(frames)} frames")
                return
            votes, failed = [], []
            for m in models:
                try:
                    votes.append(call(frames, movement, m, api_key))
                except Exception as e2:  # noqa: BLE001 - one model is not the panel
                    failed.append({"model": m, "error": f"{type(e2).__name__}: "
                                                        f"{str(e2)[:120]}"})
            if not votes:
                log(f"  [err] {p.name}: every model failed")
                return
            row = merge(votes)
            row.update({"file": str(p.relative_to(DATASET)), "movement": movement,
                        "window": [s, e], "votes": votes, "failed": failed})
            out = a.out / movement / f"{p.stem}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(row, indent=1))
            done["n"] += 1
            head = (row["primary"] or {}).get("name", "clean")
            log(f"  [{done['n']}] {movement}/{p.name} -> {head} "
                f"({row['cleanVotes']}/{row['modelsAsked']} said clean)")
        except Exception as e3:  # noqa: BLE001
            log(f"  [err] {p.name}: {type(e3).__name__} {str(e3)[:140]}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    print(f"\nranked {done['n']}/{len(todo)} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
