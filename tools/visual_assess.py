#!/usr/bin/env python3
"""Assess one clip's training visually with the top-3 nan.builders models.

The harness run ranked the vision models; this tool takes the three best
(glm5.3-flash, qwen3.8-flash, deepseek-v4-flash), shows each of them a denser
spread of stills cut across the whole clip, and renders their technique
assessments next to the frames they were looking at, so the feedback can be
checked against the training it describes.

Usage:
  python tools/visual_assess.py [clip stem] [n frames]

Writes out/nan_harness/visual_report.html (frames + per-model study + the
locally tallied verdict consensus) and visual_assess.md (the consensus only).
Frames land beside the report; out/ is gitignored, so nothing lands in git.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nan_harness import BASE_URL, load_key  # noqa: E402
import urllib.request  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "out" / "nan_harness"
FRAMEDIR = OUTDIR / "assess_frames"

MODELS = ["glm5.3-flash", "qwen3.8-flash", "deepseek-v4-flash"]

SYSTEM = """You are barrapp's technique analyst. You study stills cut at even \
intervals across one calisthenics clip and assess the training shown: for each \
still, one line on what the body is doing; then the main fault across the set, \
one correction to try next set, and a quality verdict for the rep on the app's \
scale: clean / minor / major. Concrete and brief; no filler."""

USER_TEXT = (
    "Assess my training, visually. These {n} stills are evenly spaced across one "
    "clip, in order. For each still, one line: what the body is doing. Then: "
    "main fault, one correction, and the quality verdict — clean / minor / major."
)

REQUEST_TIMEOUT = 120


def cut_frames(stem: str, n: int) -> list[Path]:
    clip = next(
        (p for d in (ROOT / "data" / "videos", ROOT) if (p := d / f"{stem}.mp4").exists()),
        None,
    )
    if clip is None:
        raise SystemExit(f"no clip {stem}")
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True, check=True).stdout.strip())
    FRAMEDIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        t = dur * (i + 0.5) / n  # stills centred in their slice, not on the cut
        out = FRAMEDIR / f"{stem}_{i + 1:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(clip),
             "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "4", str(out), "-y"],
            check=True)
        paths.append(out)
    return paths


def call(model: str, key: str, frames: list[Path]) -> dict:
    content: list[dict] = [{
        "type": "text", "text": USER_TEXT.format(n=len(frames)),
    }]
    content += [{
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()},
    } for p in frames]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
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
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def verdicts(text: str) -> list[str]:
    found = re.findall(r"\b(clean|minor|major)\b", text.lower())
    return found


def consensus(replies: dict[str, str]) -> dict:
    tally: dict[str, int] = {}
    for model, text in replies.items():
        vs = verdicts(text)
        if vs:
            # The verdict the model committed to is its last one; the words can
            # also appear mid-sentence while quoting the scale.
            tally[vs[-1]] = tally.get(vs[-1], 0) + 1
    order = sorted(tally, key=tally.get, reverse=True)  # type: ignore[arg-type]
    corrections = []
    for text in replies.values():
        m = re.search(r"(?:correction|fix|cue)[^\n:]*:?\s*(.+)", text, re.IGNORECASE)
        if m:
            corrections.append(m.group(1).strip().rstrip("*"))
    return {
        "verdict": order[0] if order else "unknown",
        "tally": tally,
        "corrections": corrections,
    }


def html_report(stem: str, frames: list[Path], replies: dict[str, str]) -> str:
    parts = ["""<!doctype html><meta charset="utf-8">
<title>barrapp — visual training assessment</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;
      color:#1a1a1a;line-height:1.5}
 h1{font-size:1.4rem} h2{font-size:1.05rem;margin-top:28px;border-bottom:1px solid #ddd;
      padding-bottom:4px}
 .frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
 .frames figure{margin:0} .frames img{width:100%;border-radius:8px;display:block}
 .frames figcaption{font-size:.75rem;color:#666;text-align:center;padding-top:2px}
 pre{white-space:pre-wrap;font-family:inherit;background:#f6f6f6;border:1px solid #e2e2e2;
     border-radius:8px;padding:12px 14px;font-size:.9rem}
 .consensus{background:#eef6ee;border:1px solid #cde3cd;border-radius:8px;padding:12px 14px}
</style>"""]
    parts.append(f"<h1>Visual training assessment — {stem}</h1>")
    parts.append(f"<p>{len(frames)} stills, evenly spaced across the clip, shown to "
                 f"{', '.join(MODELS)}.</p><h2>What the models saw</h2><div class='frames'>")
    for i, p in enumerate(frames):
        rel = Path("assess_frames") / p.name
        parts.append(f"<figure><img src='{rel}'><figcaption>still {i + 1}</figcaption></figure>")
    parts.append("</div>")
    for model, text in replies.items():
        parts.append(f"<h2>{model}</h2><pre>{text}</pre>")
    c = consensus(replies)
    tally = " · ".join(f"{k}: {v}" for k, v in c["tally"].items()) or "—"
    corr = "".join(f"<li>{x}</li>" for x in c["corrections"])
    parts.append(
        f"<h2>Consensus</h2><div class='consensus'><p><b>Verdict tally:</b> {tally} → "
        f"<b>{c['verdict']}</b></p><p><b>Corrections offered:</b></p><ul>{corr}</ul></div>")
    return "\n".join(parts)


def main() -> None:
    stem = sys.argv[1] if len(sys.argv) > 1 else "VID-20260827-WA0010"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    frames = cut_frames(stem, n)
    key = load_key()
    print(f"{len(frames)} stills from {stem} -> {FRAMEDIR}\n")

    replies: dict[str, str] = {}
    for model in MODELS:
        try:
            text = call(model, key, frames)
        except Exception as exc:  # noqa: BLE001 - one model failing must not kill the report
            text = f"(failed: {type(exc).__name__}: {exc})"
        replies[model] = text
        head = text[:80].replace("\n", " ")
        print(f"{model:20s} {head}")

    c = consensus(replies)
    report = html_report(stem, frames, replies)
    (OUTDIR / "visual_report.html").write_text(report + "\n")
    (OUTDIR / "visual_assess.md").write_text(
        f"# Visual training assessment — {stem}\n\n"
        f"Models: {', '.join(MODELS)}\n\n"
        f"Verdict tally: " + " · ".join(f"{k} {v}" for k, v in c["tally"].items()) +
        f" → **{c['verdict']}**\n\n## Corrections\n" +
        "".join(f"- {x}\n" for x in c["corrections"]))
    print(f"\nverdict tally: {c['tally']} -> {c['verdict']}")
    print(f"report: {OUTDIR / 'visual_report.html'}")


if __name__ == "__main__":
    main()
