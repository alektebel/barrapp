"""nan.builders chat for the objectives intake.

The phone sends the conversation; this module asks `qwen3.8-flash` through the
one model client (llm.py) and parses a trailing JSON block out of the reply so
the app can update the profile and the goals. The key is server-side only; it
never ships in the app.
"""
from __future__ import annotations

import json
import os

try:  # worker/task root and the API package both put llm beside chat
    import llm
except ImportError:  # local dev imports `api.chat` with server/ on the path
    from api import llm

NAN_MODEL = os.environ.get("NAN_MODEL", "qwen3.8-flash")

# The Lambda that runs this has a 60s budget; the model usually answers in a
# few seconds, so leave headroom for the response to travel back.
REQUEST_TIMEOUT = 45

SYSTEM = """Eres el asistente de bienvenida de barrapp. Habla con la persona para
conocer sus objetivos de entrenamiento y así configurar su perfil. Responde
siempre en español de España.

Reglas:
- Haz UNA pregunta cada vez. Cercano, breve, concreto.
- Cubre, en este orden: su nombre, su edad, cada cuánto entrena y qué quiere
  conseguir sobre todo (un objetivo de fuerza, una habilidad, un número de reps).
- No inventes nada. Si no lo ha dicho, vuelve a preguntar.
- Cuando lo tengas todo, termina tu respuesta con UN objeto JSON en su propia
  línea, JSON plano, sin bloques de código, exactamente con estas claves:
  {"name": "...", "age": 0, "activity": "new|occasional|regular|daily",
   "goal": "...", "focusExercise": "pull_up|push_up|squat|dip|muscle_up|handstand|planche|front_lever|back_lever|human_flag|unknown"}
- Escribe ese JSON una sola vez, al final, cuando lo tengas todo. Ni antes,
  ni nada después. Los valores de "activity" y "focusExercise" van tal cual
  (en inglés): son códigos que lee la app.
"""

# Keys the app actually reads out of the trailing JSON block.
GOAL_KEYS = ("name", "age", "activity", "goal", "focusExercise")


def chat(messages: list[dict]) -> dict:
    """Return {'reply': str, 'goals': dict | None} for one conversation turn."""
    if llm.config() is None:
        return {"reply": _offline_first_question(), "goals": None}

    result = llm.complete(NAN_MODEL, messages, system=SYSTEM, temperature=0.4,
                          timeout=REQUEST_TIMEOUT)
    if not result.ok:
        return {"reply": "Ahora mismo no puedo conectar con el asistente. "
                         "Inténtalo de nuevo en un momento.", "goals": None}
    content = result.text

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
        "Hola, soy barrapp. Cuéntame qué quieres conseguir entrenando y "
        "preparo tu perfil: un objetivo al que apuntar y cada cuánto entrenas. "
        "¿Cómo te llamas?"
    )
