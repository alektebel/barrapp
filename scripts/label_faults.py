#!/usr/bin/env python
"""Give the fault layer the ground truth it has never had.

`barra.validate_faults` asks whether each threshold fires where it should. It
has always been able to answer INCONCLUSIVE and nothing else, because
`faults.csv` holds three rows and not one labelled fault: every threshold in
`rules.py` is an unchecked claim.

The labels here come from an independent multimodal read of the frames, and the
vocabulary comes from `rules.py` itself - each fault is put to the model using
the very `observable` string the geometric rule is written against, so the two
are answering the same question rather than two similar-sounding ones. That is
the whole point: a fault the model and the rule disagree about is a threshold
worth looking at, and neither an agreement nor a disagreement means anything if
they were asked different things.

Three verdicts per fault, never two. "unclear" is a real answer - the camera
angle hides the ankle, the clip cuts before lockout - and collapsing it into
"absent" is how a harness quietly manufactures agreement.

Writes one sidecar per clip to <out>/<trick>/<stem>.json.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path("/home/diego/Documents/Development/barrapp")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from barra.rules import RULES  # noqa: E402

API_URL = "https://api.nan.builders/v1/chat/completions"
MODEL = "mimo-v2.6-flash"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")

DATASET = ROOT / "data" / "calisthenics"
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
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
    lines = []
    for r in rules:
        key = r.id.split(".", 1)[1]
        lines.append(f'  - "{key}" ({r.name}, {r.phase} phase): {r.observable}.')
    body = "\n".join(lines)
    text = f"""You are judging EXERCISE TECHNIQUE in a "{movement}".

These frames are sampled in time order from one clip of a person performing it.

For each fault below, decide whether it is visible in this clip. The
description after each name is exactly what the fault means - judge that, not
your general impression of the movement:

{body}

Rules for your answer:
- "present" only if you can actually SEE it in these frames.
- "absent" only if you can see the relevant body part / phase and it is fine.
- "unclear" whenever the frames do not show it: the camera angle hides the
  joint, the phase is not in frame, the person is off-screen, or the clip is
  not really this movement. Do not guess - "unclear" is the correct answer for
  anything you cannot check.

Reply with ONLY a JSON object, no markdown fences:
{{
  "is_the_movement": true|false,
  "reps_visible": <integer>,
  "faults": {{ {", ".join(f'"{i}": "present|absent|unclear"' for i in ids[:3])}, ... one key for EVERY fault listed above }},
  "evidence": {{ "<fault name>": "<short reason, only for ones you marked present>" }}
}}"""
    return text, ids


def call(frames: list, movement: str, api_key: str) -> dict:
    text, ids = prompt_for(movement)
    content: list[dict] = [{"type": "text", "text": text}]
    content += [{"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                for _, b64 in frames]
    # No max_tokens. mimo-v2.5 spends the budget on reasoning tokens first, so
    # a cap of 900 returns finish_reason="length" with an EMPTY content string -
    # a 200 that looks like a parse bug rather than a truncation.
    payload = {"model": MODEL, "temperature": 0,
               "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json", "User-Agent": UA})
    # Matches scripts/label_calisthenics.py: the endpoint rate-limits, and
    # a 429 that gives up is a clip silently missing from the corpus.
    attempts = int(os.environ.get("NAN_MAX_ATTEMPTS", "8") or 8)
    body = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                body = json.load(r)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            code = getattr(e, "code", 0)
            if code in (401, 403, 404) or attempt == attempts - 1:
                raise
            import random
            import time
            time.sleep(min(90.0, 4.0 * (2 ** attempt)) * (0.7 + 0.6 * random.random()))
    raw = body["choices"][0]["message"]["content"]
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
    start, end = raw.find("{"), raw.rfind("}")
    verdict = json.loads(raw[start:end + 1])
    # Keep only the vocabulary we asked about, and default anything the model
    # omitted to "unclear" rather than silently treating it as absent.
    faults = {i: str(verdict.get("faults", {}).get(i, "unclear")).lower()
              for i in ids}
    verdict["faults"] = {k: (v if v in ("present", "absent", "unclear")
                             else "unclear") for k, v in faults.items()}
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True,
                    help="directory of movement-label sidecars (for windows)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    api_key = os.environ.get("NAN_API_KEY", "")
    if not api_key:
        print("NAN_API_KEY not set", file=sys.stderr)
        return 1

    windows: dict[str, tuple[float, float]] = {}
    detected: dict[str, str] = {}
    for j in a.labels.rglob("*.json"):
        try:
            v = json.loads(j.read_text())
        except Exception:  # noqa: BLE001
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
        if movement not in RULES:
            continue
        # Only clips the vision pass already confirmed are this movement:
        # fault labels on a misfiled clip are noise with a confident face on.
        if detected.get(p.name) != movement:
            continue
        out = a.out / movement / f"{p.stem}.json"
        if out.exists() and not a.force:
            continue
        todo.append((p, movement))
    if a.limit:
        todo = todo[: a.limit]

    print(f"{len(todo)} clips to fault-label "
          f"({len(RULES)} movements have rules)", flush=True)
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
            v = call(frames, movement, api_key)
            v["file"] = str(p.relative_to(DATASET))
            v["movement"] = movement
            v["window"] = [s, e]
            out = a.out / movement / f"{p.stem}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(v, indent=1))
            done["n"] += 1
            present = [k for k, x in v["faults"].items() if x == "present"]
            log(f"  [{done['n']}] {movement}/{p.name} reps={v.get('reps_visible')} "
                f"present={present or '-'}")
        except Exception as e:  # noqa: BLE001
            log(f"  [err] {p.name}: {type(e).__name__} {str(e)[:140]}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, todo))
    print(f"\nlabelled {done['n']}/{len(todo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
