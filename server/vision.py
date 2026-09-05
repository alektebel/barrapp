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


SECOND_MODEL = "qwen3.8-flash"


def _config() -> tuple[str, str, str] | None:
    """(base_url, key, model) when a vision endpoint is configured."""
    base = (os.environ.get("BARRA_VISION_BASE_URL")
            or os.environ.get("NAN_BASE_URL") or "").rstrip("/")
    key = os.environ.get("BARRA_VISION_API_KEY") or os.environ.get("NAN_API_KEY") or ""
    model = os.environ.get("BARRA_VISION_MODEL", "glm5.3-flash")
    if base and key.strip():
        return base, key.strip(), model
    return None


def _chat(base: str, key: str, model: str, system: str, content: list[dict],
          timeout: int = REQUEST_TIMEOUT) -> str | None:
    """One OpenAI-compatible call; None on any failure, never an raise."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content}],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # Same lesson as the objectives chat: a script-looking client
                 # is answered by the provider's edge with a 403.
                 "User-Agent": "barrapp-vision/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError,
            json.JSONDecodeError, TimeoutError, OSError):
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


# ---- key moment 1: counting when the geometry found nothing ---------------

COUNT_SYSTEM = """You are counting repetitions of one calisthenics movement from stills taken across one video, in order. Rules:
- Count a repetition only where you can see the body having left the rest position and returned to it, or clearly mid-way through doing so.
- Half-seen reps count as one only if the body is visibly far from rest.
- Do not count setup, walking, adjusting grip, or resting between reps.
- If you cannot tell, give your best count and say why in one line.
Return JSON exactly: {"reps": <int>, "note": "<one line>"}"""

COUNT_USER = ("These {n} stills are spread evenly across one clip of {move}, in order. "
              "Count the repetitions and return the JSON object.")


def count_from_clip(video_path, out_dir) -> dict | None:
    """The two-model count over stills spread across the whole clip.

    Two models, because one model guessing is a coin with opinions. When they
    land within one of each other the higher count is taken - a rep half out
    of frame is still a rep of training. When only one answers, that answer
    goes out labelled as single-sourced.
    """
    cfg = _config()
    if cfg is None:
        return None
    base, key, model = cfg
    try:
        from barra.frames import grab_stills
        import subprocess
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True).stdout.strip() or 0)
        if duration <= 0:
            return None
        moments = [duration * (i + 0.5) / 8 for i in range(8)]
        stills = grab_stills(video_path, moments, out_dir, prefix="count")
    except Exception:  # noqa: BLE001
        return None
    if not stills:
        return None

    content: list[dict] = [{"type": "text",
                            "text": COUNT_USER.format(n=len(stills), move="the movement")}]
    for path in stills:
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode()
        except OSError:
            continue
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    if len(content) < 2:
        return None

    import re
    answers: dict[str, int] = {}
    for m in {model, SECOND_MODEL}:
        text = _chat(base, key, m, COUNT_SYSTEM, content)
        if not text:
            continue
        found = re.findall(r'"reps"\s*:\s*(\d+)', text) or re.findall(r"\b(\d+)\b", text)
        if found:
            answers[m] = int(found[0])
    if not answers:
        return None
    values = sorted(answers.values())
    if len(values) == 2 and values[1] - values[0] <= 1:
        reps, agreement = values[1], "both models agree within one"
    elif len(values) == 2:
        reps, agreement = values[0], "the models disagree; the lower count is used"
    else:
        reps, agreement = values[0], f"single model answered ({list(answers)[0]})"
    return {"reps": int(reps), "models": answers, "agreement": agreement}


# ---- key moment 2: a second opinion on the technique verdict ---------------

VERDICT_USER = ("From these stills of one set, give the overall technique verdict "
                "as one word on its own line: clean, minor, or major.")


def technique_second_opinion(art) -> str | None:
    """clean / minor / major from the second model, for cross-reading the
    primary's verdict. None when it cannot answer."""
    cfg = _config()
    if cfg is None or not art or not art.stills:
        return None
    base, key, _ = cfg
    content: list[dict] = [{"type": "text", "text": VERDICT_USER}]
    for path in art.stills:
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode()
        except OSError:
            continue
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    if len(content) < 2:
        return None
    text = _chat(base, key, SECOND_MODEL, SYSTEM, content)
    if not text:
        return None
    for word in ("clean", "minor", "major"):
        if word in text.lower():
            return word
    return None
