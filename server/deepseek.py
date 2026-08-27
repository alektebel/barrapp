"""DeepSeek write-up of a barra result. Key is left blank on purpose."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM = """You write short reports for barra, a self-referential measurement tool.
Rules:
- Never invent a technique score or a PR.
- Never claim progress unless both sessions have at least 3 usable reps and the change clears within-session spread.
- Label timings INVARIANT, lengths SCALED, left/right PLANAR.
- Quote the actual numbers from the payload (transition_s, concentric_s, rom).
- If the clip produced no reps, say so and say why, in the tool's own geometric terms.
- If data is missing, say what to film next. Do not pad.
- Second person, plain sentences, no coaching slogans.
Return JSON with keys: headline, narrative, nextSession.
"""


def write_report(payload: dict) -> dict:
    fallback = _fallback(payload)
    if not DEEPSEEK_API_KEY.strip():
        return fallback

    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": "Write the report for this job:\n"
                    + json.dumps(payload, indent=2),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
    ).encode()
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        fallback["headline"] = parsed.get("headline") or fallback["headline"]
        fallback["narrative"] = parsed.get("narrative") or fallback["narrative"]
        fallback["nextSession"] = parsed.get("nextSession") or fallback["nextSession"]
        return fallback
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
        fallback["narrative"] = fallback["narrative"] + f"\n\n(DeepSeek failed: {exc})"
        return fallback


def _rep_line(rep: dict) -> str:
    bits = [rep.get("label") or "rep"]
    for metric in rep.get("metrics") or []:
        if metric.get("key") in {"transition_s", "concentric_s", "total_s", "rom", "peak_height"}:
            bits.append(f"{metric['name']} {metric['value']} ({metric['class']})")
    if not rep.get("plausible", True):
        bits.append("rejected")
    return " — ".join(bits)


def _sentence(text: str) -> str:
    """Blockers are written as clause fragments so they can be listed under a
    heading. Dropped into running prose they need to start with a capital and
    end with a stop, or the read-out reads as a sentence that lost its way."""
    text = (text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _fallback(payload: dict) -> dict:
    n = int(payload.get("n_reps") or 0)
    exercise = (payload.get("exercise") or "muscle_up").replace("_", " ")
    blockers = payload.get("blockers") or []
    lines = [_rep_line(r) for r in payload.get("reps") or []]
    numbers = ("\n" + "\n".join(lines)) if lines else ""
    if n == 0:
        headline = f"This {exercise} clip produced no measurable reps."
        narrative = (
            "Nothing was counted. That is a filming or tracking failure, not a training one. "
            + (" ".join(_sentence(b) for b in blockers) if blockers
               else "Trim to the working set and keep the lockout in frame.")
            + numbers
        )
    elif n < 3:
        headline = f"{n} measurable {exercise} rep{'s' if n != 1 else ''} — not enough for a session median."
        narrative = (
            f"Counted {n} usable {exercise} rep(s). Three per session is the floor before "
            "a median means anything, so progress is not trackable yet."
            + numbers
        )
    else:
        headline = f"{n} usable {exercise} reps."
        narrative = (
            "Timing is comparable across cameras (INVARIANT). Lengths are SCALED by torso "
            "and only comparable inside one viewpoint. Left/right numbers are PLANAR."
            + numbers
        )
    return {
        "headline": headline,
        "narrative": narrative,
        "sessions": payload.get("sessions") or [],
        "reps": payload.get("reps") or [],
        "blockers": blockers,
        "nextSession": payload.get("nextSession")
        or "Five or six reps, one set, tripod on a marked spot, same side, lockout in frame, trimmed to the working set.",
    }
