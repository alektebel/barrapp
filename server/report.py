"""The written report: headline, narrative and next session, in Spanish.

A model writes the prose (nan.builders: deepseek-v4-flash, then qwen3.8-flash);
a sentinel decides whether it may be used. The old writer (deepseek.py) only
ASKED the model not to invent numbers; in production it never ran at all,
because its key was empty, and every phone got the same English fallback.

A reply is used only when:
  * it is one JSON object with non-empty headline, narrative and nextSession;
  * every number in the headline and narrative exists in the measurement, at
    the precision it is written (13.4 s may read "13 s" or "13,4 s"; a set of
    3 may not read "12"). nextSession is advice and may carry its own numbers.
Otherwise the next model is tried, and then the deterministic text from
barra.summary, with `proseRejected` saying why - so a run that fell back can
be told from one that never asked.

The model sees a digest of the payload, not the payload: the per-rep series
and traces are thousands of numbers that cost tokens and say nothing a
sentence should.
"""
from __future__ import annotations

import json
import math
import os
import re

from barra import i18n
from barra.summary import describe

try:
    import llm
except ImportError:  # tests / local dev with `server/` on the path
    from api import llm

REPORT_MODEL = os.environ.get("BARRA_REPORT_MODEL", "deepseek-v4-flash")
BACKUP_MODEL = os.environ.get("BARRA_REPORT_BACKUP_MODEL", "qwen3.8-flash")
PROSE_KEYS = ("headline", "narrative", "nextSession")

SYSTEM = """Escribes el informe de una serie de calistenia para barrapp, una \
herramienta que mide con geometría (pose estimada desde un vídeo). Escribe en \
español de España, en segunda persona, frases claras, sin eslóganes.

Reglas:
- Nunca inventes una puntuación, un récord ni un número. Cada cifra que \
escribas en headline y narrative tiene que estar en los datos que te doy.
- No digas que la persona mejora o empeora: tienes una sola sesión.
- Si no se contó ninguna repetición, dilo y explica por qué con los motivos \
(blockers) que te doy. Si falta algo, di qué grabar la próxima vez.
- headline: una línea corta (máximo 70 caracteres).
- narrative: 2–4 frases sobre qué salió mejor y qué peor, citando números reales.
- nextSession: una recomendación concreta para la próxima grabación.

Devuelve SOLO un objeto JSON con las claves headline, narrative, nextSession."""

_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])")


def digest(payload: dict) -> dict:
    """What the model needs to write three sentences, and nothing else."""
    detected = payload.get("detected") or {}
    reps = []
    for r in payload.get("reps") or []:
        reps.append({
            "label": r.get("label"), "score": r.get("score"), "band": i18n.band(r.get("band")),
            "plausible": r.get("plausible"),
            "metrics": {i18n.localize_text(m.get("name")): i18n.localize_value(m.get("value"))
                        for m in r.get("metrics") or [] if m.get("name")},
            "faults": [f.get("name") for f in r.get("faults") or [] if f.get("name")],
            "problems": [i18n.localize_text(x) for x in (r.get("problems") or [])[:3]],
        })
    # Spanish going in, so the model has no English word to echo ("solid").
    return {
        "exercise": payload.get("exercise"),
        "movement": i18n.localize_text(detected.get("label") or payload.get("exercise")),
        "variant": (payload.get("variant") or {}).get("name"),
        "n_reps": payload.get("n_reps"), "n_candidates": payload.get("n_candidates"),
        "sessionScore": payload.get("sessionScore"),
        "sessionBand": i18n.band(payload.get("sessionBand")),
        "duration_s": payload.get("duration_s"),
        "blockers": [i18n.localize_text(b) for b in (payload.get("blockers") or [])[:5]],
        "reps": reps[:30],
    }


def _numbers_in(value) -> list[float]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        return [float(n.replace(",", ".")) for n in _NUMBER.findall(value)]
    if isinstance(value, dict):
        return [x for v in value.values() for x in _numbers_in(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _numbers_in(v)]
    return []


def _round_half_up(v: float, decimals: int) -> float:
    # Not round(): banker's rounding makes 12.5 -> 12, and truncation would let
    # a rep that ends at 12.5 s vouch for "12 reps".
    scale = 10 ** decimals
    return math.floor(v * scale + 0.5) / scale


def invented_numbers(text: str, facts: dict) -> list[str]:
    """Numbers in `text` that the digest does not contain at that precision.
    Ordinals up to the number of reps ("la 2.ª repetición") are allowed."""
    allowed = _numbers_in(facts)
    top = max(int(facts.get("n_candidates") or 0), int(facts.get("n_reps") or 0))
    out = []
    for raw in _NUMBER.findall(text or ""):
        x = float(raw.replace(",", "."))
        decimals = len(re.split(r"[.,]", raw)[1]) if re.search(r"[.,]", raw) else 0
        if decimals == 0 and 1 <= x <= top:
            continue
        if any(_round_half_up(v, decimals) == x for v in allowed):
            continue
        out.append(raw)
    return out


def _parse(text: str | None) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _judge(result, facts: dict) -> tuple[dict | None, str]:
    """(prose, "") when the reply may be used, else (None, why not)."""
    if not result.ok:
        return None, f"{result.model}: {result.error}"
    obj = _parse(result.text)
    if obj is None:
        return None, f"{result.model}: not_json"
    prose = {k: str(obj.get(k) or "").strip() for k in PROSE_KEYS}
    missing = [k for k, v in prose.items() if not v]
    if missing:
        return None, f"{result.model}: missing {','.join(missing)}"
    bad = invented_numbers(prose["headline"] + " " + prose["narrative"], facts)
    if bad:
        return None, f"{result.model}: invented_number: {', '.join(bad)}"
    return prose, ""


def _fallback(payload: dict) -> dict:
    headline, narrative = describe(payload)
    return {
        "headline": headline,
        "narrative": narrative,
        "nextSession": payload.get("nextSession")
        or "Cinco o seis repeticiones, una serie, el móvil fijo en un punto marcado, "
           "siempre desde el mismo lado y con la parte de arriba dentro del encuadre.",
    }


def write_prose(payload: dict) -> dict:
    """The model's judged prose, or why it was not used - the deferred half of
    `write_report` (docs/SPEED-PLAN.md B). The payload is the measured report;
    `process.finish_prose` applies the answer. One of:
      {"status": "done",     "prose": {headline, narrative, nextSession},
       "source": "llm:<model>"}
      {"status": "failed",   "reason": "..."}   # the call never produced prose
      {"status": "fallback", "reason": "..."}   # not_configured or rejected
    """
    if llm.config() is None:
        return {"status": "fallback", "reason": "not_configured"}
    facts = digest(payload)
    user = [{"role": "user", "content": "Datos de la serie:\n"
             + json.dumps(facts, ensure_ascii=False)}]
    reasons = []
    unanswered = False
    for model in dict.fromkeys((REPORT_MODEL, BACKUP_MODEL)):
        result = llm.complete(model, user, system=SYSTEM, json_mode=True, temperature=0.2)
        prose, why = _judge(result, facts)
        if prose is not None:
            return {"status": "done", "prose": prose, "source": f"llm:{result.model}"}
        unanswered = unanswered or not result.ok
        reasons.append(why)
        print(f"[barra] report rejected {why}", flush=True)
    # A call that never produced prose (transport, auth, quota) is not the
    # same signal as a reply that arrived and failed judgement.
    if unanswered:
        return {"status": "failed", "reason": "; ".join(reasons)}
    return {"status": "fallback", "reason": "; ".join(reasons)}


def fallback_report(payload: dict) -> dict:
    """The deterministic report: base keys plus the fixed Spanish prose.
    `measure_job` writes this immediately; `write_report` falls back to it."""
    base = {"sessions": payload.get("sessions") or [], "reps": payload.get("reps") or [],
            "blockers": payload.get("blockers") or []}
    return {**base, **_fallback(payload)}


def write_report(payload: dict) -> dict:
    """{headline, narrative, nextSession, sessions, reps, blockers,
    proseSource, proseRejected}. process_job carries every other measurement
    key through untouched."""
    out = write_prose(payload)
    if out["status"] == "done":
        return {**fallback_report(payload), **out["prose"], "proseSource": out["source"]}
    return {**fallback_report(payload), "proseSource": "fallback",
            "proseRejected": out["reason"]}
