#!/usr/bin/env python3
"""Harness for the nan.builders models: one clip, one prompt, every model.

Sends the same technique-study request (three frames of a real clip) to each
candidate and records who answers, who refuses, and what they say. Written to
compare the multimodal models the provider exposes; the text-only models are
probed too, so the vision roster is measured, not assumed.

Usage:
  NAN_API_KEY=... python tools/nan_harness.py [clip frames dir] [outdir]

The key is read from $NAN_API_KEY, or from opencode's auth store when that is
absent. Frames are three stills the ffmpeg step cut from the clip; the report
and the raw replies land in out/nan_harness/.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BASE_URL = os.environ.get("NAN_BASE_URL", "https://api.nan.builders/v1").rstrip("/")

CANDIDATES = [
    "gemma4",
    "glm5.3-flash",
    "qwen3.8-flash",
    "qwen3.6",
    "minimax-h3",
    "mimo-v2.5",
    "deepseek-v4-flash",
]

SYSTEM = """You are barrapp's technique analyst. You study stills from a calisthenics \
clip and write a technique study: what the exercise is, what the body is doing \
well, what breaks down, and one correction to try next set. Then you give a \
quality verdict of the rep shown, on the scale the app uses: clean / minor / \
major, with one sentence of why. Be concrete and brief; no warmer, no filler."""

USER_TEXT = (
    "Technique study and quality, please. These are three stills (start, middle, "
    "end) from one clip of my training. Tell me the exercise, what you see in "
    "each still, the main fault if any, one correction, and the quality verdict: "
    "clean / minor / major."
)

REQUEST_TIMEOUT = 90


def load_key() -> str:
    key = os.environ.get("NAN_API_KEY", "").strip()
    if key:
        return key
    auth = Path.home() / ".local/share/opencode/auth.json"
    if auth.exists():
        data = json.loads(auth.read_text())
        key = data.get("nan", {}).get("key", "")
        if key:
            return key
    raise SystemExit("no nan key: set NAN_API_KEY or log in via opencode")


def load_frames(frames_dir: Path) -> list[str]:
    uris = []
    for p in sorted(frames_dir.glob("*.jpg")):
        uris.append("data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode())
    if not uris:
        raise SystemExit(f"no frames in {frames_dir}")
    return uris


def call(model: str, key: str, frames: list[str],
         system: str = SYSTEM, user: str = USER_TEXT) -> dict:
    content = [{"type": "text", "text": user}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in frames]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content}],
        "temperature": 0.4,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "barrapp-harness/1.0"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"] or ""
        return {"ok": True, "secs": round(time.monotonic() - started, 1), "text": text.strip()}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        return {"ok": False, "secs": round(time.monotonic() - started, 1),
                "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:  # noqa: BLE001 - the harness reports, not crashes
        return {"ok": False, "secs": round(time.monotonic() - started, 1),
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    frames_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/opencode/nan_harness/frames")
    outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out" / "nan_harness"
    outdir.mkdir(parents=True, exist_ok=True)
    key = load_key()
    frames = load_frames(frames_dir)
    print(f"{len(frames)} frames, {len(frames[0]) // 1400} KB each, {len(CANDIDATES)} models\n")

    results = {}
    for model in CANDIDATES:
        res = call(model, key, frames)
        results[model] = res
        head = (res.get("text") or res.get("error", ""))[:90].replace("\n", " ")
        print(f"{model:20s} {'ok ' if res['ok'] else 'NO '} {res['secs']:5.1f}s  {head}")
        if res["ok"]:
            (outdir / f"{model}.md").write_text(res["text"] + "\n")

    (outdir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    vision = [m for m, r in results.items() if r["ok"]]
    print(f"\naccepts images ({len(vision)}): {', '.join(vision) or 'none'}")
    print(f"report + raw replies: {outdir}")


if __name__ == "__main__":
    main()
