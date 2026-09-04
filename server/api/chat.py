"""nan.builder chat for the objectives intake.

OpenAI-compatible: the phone sends the conversation, this module calls
`{NAN_BASE_URL}/chat/completions` with model `qwen3.8-flash`, and parses a
trailing JSON block out of the reply so the app can update the profile and the
goals. The key is server-side only; it never ships in the app.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

NAN_API_KEY = os.environ.get("NAN_API_KEY", "")
NAN_BASE_URL = os.environ.get("NAN_BASE_URL", "").rstrip("/")
NAN_MODEL = os.environ.get("NAN_MODEL", "qwen3.8-flash")

# The Lambda that runs this has a 60s budget; the model usually answers in a
# few seconds, so leave headroom for the response to travel back.
REQUEST_TIMEOUT = 45

SYSTEM = """You are barrapp's onboarding assistant. Talk with the user to learn their
training objectives so the app can set up their profile.

Rules:
- Ask ONE question at a time. Warm, short, concrete.
- Cover, in order: their name, their age, how often they train, and what they
  most want to achieve (a strength goal, a skill, a target rep count).
- Do not invent anything. If they have not said it, ask again.
- When you have everything, end your reply with ONE JSON object on its own
  line, plain JSON, no markdown fences, exactly these keys:
  {"name": "...", "age": 0, "activity": "new|occasional|regular|daily",
   "goal": "...", "focusExercise": "pull_up|push_up|squat|dip|muscle_up|handstand|planche|front_lever|back_lever|human_flag|unknown"}
- Only output that JSON block once, at the very end, when you have all of it.
  Do not output it before then, and do not output anything after it.
"""

# Keys the app actually reads out of the trailing JSON block.
GOAL_KEYS = ("name", "age", "activity", "goal", "focusExercise")


def chat(messages: list[dict]) -> dict:
    """Return {'reply': str, 'goals': dict | None} for one conversation turn."""
    if not NAN_API_KEY.strip() or not NAN_BASE_URL:
        return {"reply": _offline_first_question(), "goals": None}

    body = json.dumps(
        {
            "model": NAN_MODEL,
            "messages": [{"role": "system", "content": SYSTEM}, *messages],
            "temperature": 0.4,
        }
    ).encode()
    req = urllib.request.Request(
        f"{NAN_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {NAN_API_KEY}",
            "Content-Type": "application/json",
            # The provider's edge blocks requests whose client looks like a
            # script; without this the model call comes back HTTP 403.
            "User-Agent": "barrapp-objectives/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
        return {"reply": f"I could not reach the objectives service right now. ({exc})",
                "goals": None}

    goals, reply = _extract_goals(content)
    return {"reply": reply, "goals": goals}


def _extract_goals(text: str) -> tuple[dict | None, str]:
    """Find a trailing plain-JSON block and split it off the reply.

    The model is asked to put the JSON on its own line. Code fences and stray
    whitespace are tolerated, because the cost of failing to find the goals is
    just a rerun, while the cost of swallowing part of the reply is real.
    """
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip().strip("`")
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not any(k in obj for k in GOAL_KEYS):
            continue
        reply = "\n".join(lines[:i] + lines[i + 1:]).strip()
        return obj, reply
    return None, text.strip()


def _offline_first_question() -> str:
    """Used when the key/base URL are not configured, so the screen still works
    in local development and the empty state is not a dead end."""
    return (
        "Hi, I'm barrapp. Tell me what you'd like to get out of training and I'll "
        "set up your profile — a goal to aim for, and how often you train. "
        "What's your name?"
    )
