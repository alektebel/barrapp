"""Convierte la valoración humana en texto libre en datos comparables.

    .venv/bin/python tools/evalweb/structure.py [--model deepseek-v4-flash] [--force]

Lee data/eval/human_technique.jsonl (la última respuesta de cada sha256 gana) y
escribe data/eval/human_technique_structured.jsonl: movimiento real, si el clip
es una sola serie evaluable, el veredicto y cada fallo citado literalmente,
separado en observable o no, con la regla del pipeline que le corresponde si la
hay. El texto original no se toca; este fichero se regenera cuando haga falta.

Un modelo ligero (nan.builders) sólo organiza lo que el entrenador escribió:
no puede añadir fallos. Cada fallo lleva la cita exacta y se descarta si la cita
no aparece en el texto.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

from api import llm  # noqa: E402
from barra.movements import MOVEMENTS  # noqa: E402
from barra.rules import RULES  # noqa: E402

SRC = ROOT / "data/eval/human_technique.jsonl"
DST = ROOT / "data/eval/human_technique_structured.jsonl"
CACHE = ROOT / "out/evalweb/structured"
PROMPT_VERSION = "2"

# Familias de fallo, para comparar aunque no haya regla del pipeline.
CATEGORIES = {
    "rango": "recorrido incompleto o insuficiente (profundidad, barbilla bajo la barra)",
    "extension": "no extiende del todo (bloqueo arriba o colgado abajo)",
    "balanceo": "balanceo, kip o impulso con el cuerpo",
    "cadera": "posición de la cadera (hundida, picada, usada para impulsar)",
    "piernas": "piernas: rodillas flexionadas, piernas sin alinear o sin reclutar",
    "rodillas_dentro": "rodillas que se juntan o van hacia dentro",
    "core": "core o abdomen sin activar, falta de estabilidad del tronco",
    "escapulas": "retracción, depresión o postura escapular",
    "bajada": "bajada sin control o demasiado rápida",
    "transicion": "transición del muscle-up o del ejercicio",
    "agarre": "agarre: pulgares, agarre falso o semifalso",
    "cabeza": "cabeza o mirada (adelantada, mirando abajo)",
    "lumbar": "lumbar o retroversión pélvica (butt wink)",
    "incompleto": "no completa el ejercicio",
    "otro": "cualquier otro fallo",
}


def rule_catalog() -> str:
    lines = []
    for movement, rules in RULES.items():
        lines.append(f"{movement}: " + "; ".join(f"{r.id} ({r.name})" for r in rules))
    return "\n".join(lines)


SYSTEM = f"""Eres un asistente que ORGANIZA la valoración escrita por un entrenador de \
calistenia sobre un vídeo. No ves el vídeo. No añades, inventas ni corriges nada: \
sólo estructuras lo que el texto dice.

Devuelve un único objeto JSON con estas claves:
- "movement": id del catálogo si el ejercicio principal está en él, "other" si es \
otro ejercicio, "unknown" si el texto no dice qué ejercicio es. Catálogo: \
{", ".join(MOVEMENTS)}. Puede venir la carpeta del corpus como pista: úsala sólo \
para desambiguar ("plancha" en la carpeta planche es la planche de calistenia, no \
la plancha abdominal); si el texto describe otro ejercicio, manda el texto.
- "movementDesc": el ejercicio real en pocas palabras, en español.
- "singleSet": true si el vídeo es una sola serie de un solo ejercicio y una sola \
persona (varias repeticiones del mismo ejercicio siguen siendo una serie); false \
si es una compilación, varias personas, varias progresiones o ejercicios distintos.
- "startS": segundo en que empieza el ejercicio si el texto lo dice, si no null.
- "reps": número de repeticiones si el texto lo dice, si no null.
- "verdict": "clean" si el texto dice que la técnica es buena sin fallos concretos; \
"faults" si nombra al menos un fallo; "incomplete" si el ejercicio no se completa; \
"unassessable" SÓLO si el texto dice explícitamente que no se puede valorar. Que \
el ejercicio no esté en el catálogo o sea raro no lo hace "unassessable": si no \
nombra fallos es "clean".
- "faults": lista de fallos de técnica que el texto afirma. Cada uno: \
{{"quote": cita EXACTA y literal del texto, "category": una de {list(CATEGORIES)}, \
"ruleId": id de la regla del pipeline que mide exactamente eso o null, \
"observable": true si es un hecho visible en el vídeo (posición, recorrido, \
balanceo), false si es una causa o interpretación (falta de fuerza, \
activación muscular que no se ve), "hedged": true si el texto lo matiza \
("parece", "quizás", "un poco"), "timeS": segundo si el texto lo da, si no null}}.
- "advice": lista de consejos o ejercicios propuestos (citas literales).
- "context": lista de datos que no son técnica (peso estimado, material, objetivo \
del ejercicio).

Categorías: {json.dumps(CATEGORIES, ensure_ascii=False)}

Reglas del pipeline (usa ruleId sólo si el movimiento coincide y la regla mide \
ese hecho; si dudas, null):
{rule_catalog()}

Elogios ("buena retracción escapular") NO son fallos. Un consejo no es un fallo \
salvo que el texto afirme el defecto."""


def latest_answers() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["sha256"]] = row
    return out


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def clean(parsed: dict, feedback: str) -> dict:
    """Sólo lo que el texto respalda: un fallo cuya cita no está en el texto se
    quita, y una regla que no existe para ese movimiento se anula."""
    text = _norm(feedback)
    movement = parsed.get("movement")
    if movement not in MOVEMENTS and movement != "unknown":
        movement = "other"
    rule_ids = {r.id for r in RULES.get(movement, ())}
    faults, dropped = [], []
    for f in parsed.get("faults") or []:
        if not isinstance(f, dict):
            continue
        quote = str(f.get("quote") or "").strip()
        if not quote or _norm(quote) not in text:
            dropped.append(quote)
            continue
        category = f.get("category") if f.get("category") in CATEGORIES else "otro"
        rule = f.get("ruleId") if f.get("ruleId") in rule_ids else None
        faults.append({
            "quote": quote, "category": category, "ruleId": rule,
            "observable": bool(f.get("observable")), "hedged": bool(f.get("hedged")),
            "timeS": f.get("timeS") if isinstance(f.get("timeS"), (int, float)) else None,
        })
    verdict = parsed.get("verdict")
    if verdict not in {"clean", "faults", "incomplete", "unassessable"}:
        verdict = "faults" if faults else "clean"
    if verdict == "clean" and faults:
        verdict = "faults"
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return {
        "movement": movement,
        "movementDesc": str(parsed.get("movementDesc") or ""),
        "singleSet": bool(parsed.get("singleSet")),
        "startS": num(parsed.get("startS")),
        "reps": num(parsed.get("reps")),
        "verdict": verdict,
        "faults": faults,
        "advice": [str(a) for a in parsed.get("advice") or []],
        "context": [str(c) for c in parsed.get("context") or []],
        "droppedQuotes": dropped,
    }


def structure(row: dict, model: str, force: bool) -> dict:
    feedback = row.get("feedback") or ""
    key = hashlib.sha256(
        f"{PROMPT_VERSION}|{model}|{SYSTEM}|{row.get('movementFolder')}|{feedback}".encode()).hexdigest()[:16]
    cache = CACHE / f"{row['sha256'][:16]}-{key}.json"
    if cache.exists() and not force:
        parsed = json.loads(cache.read_text(encoding="utf-8"))
    else:
        parsed = None
        for attempt in range(5):
            if attempt:
                time.sleep(5 * attempt)     # 429: nan limita las peticiones en paralelo
            folder = row.get("movementFolder") or ""
            hint = f"Carpeta del corpus (puede estar mal): {folder}\n\n" if folder in MOVEMENTS else ""
            res = llm.complete(model, [{"role": "user", "content": hint + feedback}],
                               system=SYSTEM, json_mode=True, temperature=0.0)
            try:
                parsed = json.loads(res.text or "")
                break
            except (json.JSONDecodeError, TypeError):
                continue
        if parsed is None:
            raise RuntimeError(f"{row['sha256'][:12]}: sin JSON ({llm.last_error()})")
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=1), encoding="utf-8")
    out = clean(parsed, feedback)
    if row.get("unassessable"):
        out["verdict"] = "unassessable"
    return {
        "sha256": row["sha256"], "paths": row.get("paths", []),
        "rating": row.get("rating"), "feedback": feedback,
        "savedAt": row.get("savedAt"), "model": model, "promptVersion": PROMPT_VERSION,
        **out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--force", action="store_true", help="ignora la caché")
    ap.add_argument("--jobs", type=int, default=3)
    args = ap.parse_args()
    rows = [r for r in latest_answers().values() if (r.get("feedback") or "").strip()
            or r.get("unassessable")]
    with ThreadPoolExecutor(args.jobs) as ex:
        results = list(ex.map(lambda r: structure(r, args.model, args.force), rows))
    results.sort(key=lambda r: r.get("savedAt") or "")
    DST.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results),
                   encoding="utf-8")
    faults = [f for r in results for f in r["faults"]]
    dropped = sum(len(r["droppedQuotes"]) for r in results)
    print(f"{len(results)} clips → {DST.relative_to(ROOT)}; {len(faults)} fallos "
          f"({sum(f['observable'] for f in faults)} observables, "
          f"{sum(bool(f['ruleId']) for f in faults)} con regla); "
          f"{dropped} citas descartadas por no estar en el texto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
