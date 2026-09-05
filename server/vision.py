"""The multimodal pass: a vision model studies the technique, not the numbers.

The measurement pipeline is geometric - pose landmarks in, numbers out - and
the text model that writes the prose only ever sees those numbers. This module
closes the gap: it shows a vision model the stills cut at each rep's turning
point (see barra/frames.py) together with what was measured, and lets it say
in the report what the geometry cannot.

Optional by design. Without a key the pipeline behaves exactly as before; with
one, the vision pass runs after measurement and owns the three prose keys.
A failure here degrades to the text report, never to a failed job.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

REQUEST_TIMEOUT = 60

SYSTEM = """You are barrapp's technique analyst. You look at stills taken at \
each rep's turning point of one calisthenics set, alongside what was measured.

Rules:
- The measurements are ground truth for numbers. Never invent or contradict a \
measured value; you add what the stills show that the geometry missed.
- Study each still in order: posture, bar path, lockout, grip, body line.
- Say the main fault you can SEE, and one concrete correction for the next set.
- Second person, plain sentences, no coaching slogans, no filler.
Return JSON with keys: headline (one line), narrative (short paragraphs), \
nextSession (one sentence of what to film or attempt next)."""


def _config() -> tuple[str, str, str] | None:
    """(base_url, key, model) when a vision endpoint is configured."""
    base = (os.environ.get("BARRA_VISION_BASE_URL")
            or os.environ.get("NAN_BASE_URL") or "").rstrip("/")
    key = os.environ.get("BARRA_VISION_API_KEY") or os.environ.get("NAN_API_KEY") or ""
    model = os.environ.get("BARRA_VISION_MODEL", "glm5.3-flash")
    if base and key.strip():
        return base, key.strip(), model
    return None


def _user_text(art) -> str:
    lines = [f"Clip trimmed to the technique: "
             f"{art.clip.name if art.clip else 'cut unavailable'}."]
    for label, path in zip(art.labels, art.stills):
        lines.append(f"- {path.name}: {label}")
    lines.append(
        "Assess the technique these stills show. "
        "Return the JSON object described in the system message.")
    return "\n".join(lines)


def technique_note(art) -> dict | None:
    """{headline, narrative, nextSession} from the stills, or None."""
    cfg = _config()
    if cfg is None or not art or not art.stills:
        return None
    base, key, model = cfg

    content: list[dict] = [{"type": "text", "text": _user_text(art)}]
    for path in art.stills:
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode()
        except OSError:
            continue
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        })
    if len(content) < 2:
        return None

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Same lesson as the objectives chat: a script-looking client is
            # answered by the provider's edge with a 403.
            "User-Agent": "barrapp-vision/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        parsed = json.loads(data["choices"][0]["message"]["content"])
    except (urllib.error.URLError, KeyError, IndexError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None

    note = {k: (parsed.get(k) or "").strip() for k in
            ("headline", "narrative", "nextSession")}
    if not note["narrative"]:
        return None
    return note
