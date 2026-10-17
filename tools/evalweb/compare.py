"""Compara el pipeline con la valoración humana (hallazgo 7 de la auditoría).

    .venv/bin/python tools/evalweb/compare.py

Entradas: data/eval/human_technique_structured.jsonl (structure.py) y
out/evalweb/pipeline/*.json (run_pipeline.py). Salida: out/evalweb/report.json y
un resumen en la terminal.

Lo que se le enseña al atleta son los `topFixes` de una serie puntuada; una
serie sin puntuar no le enseña fallos (se abstiene). Un fallo humano con regla
cuenta como acierto si esa regla está en los topFixes, como omisión si la regla
se juzgó limpia, y como abstención si no se pudo juzgar. Un topFix sin fallo
humano es falsa alarma en un clip que el entrenador dio por limpio, y "no
mencionado" en uno con otros fallos (el texto libre no es exhaustivo).

Los clips WA00xx propios se usaron al desarrollar el pipeline: se informan
aparte, porque medir sobre lo ajustado infla el resultado.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from barra.movements import resolve_family  # noqa: E402

HUMAN = ROOT / "data/eval/human_technique_structured.jsonl"
PIPE = ROOT / "out/evalweb/pipeline"
OUT = ROOT / "out/evalweb/report.json"


# La etiqueta del pipeline fuera de catálogo es vocabulario abierto del modelo de
# visión ("ring_muscle_up"): se lleva a su familia con la misma tabla que usa el
# pipeline. Parientes que el entrenador y el modelo nombran distinto sin estar
# mal cuentan como acierto de familia.
KIN = {frozenset({"split_squat", "bulgarian_split_squat"})}


def family(label: str | None) -> str | None:
    found = resolve_family(label)
    return found.name if found else None


def is_dev(row: dict) -> bool:
    return any("VID-20260827-WA" in p for p in row["paths"])


def compare_clip(h: dict, p: dict) -> dict:
    item = p.get("item") or {}
    res = item.get("result") or {}
    pipe_mov = res.get("exercise")
    scored = res.get("sessionScore") is not None
    fixes = [f["errorId"] for f in res.get("topFixes") or []] if scored else []
    checks = {c["errorId"]: c for c in (res.get("assessment") or {}).get("checks") or []}
    out = {
        "sha256": h["sha256"], "clip": p.get("clip") or h["paths"][0], "dev": is_dev(h),
        "error": p.get("error") or (item.get("error") if item.get("status") != "done" else None),
        "humanMovement": h["movement"], "humanDesc": h["movementDesc"],
        "pipelineMovement": pipe_mov, "singleSet": h["singleSet"],
        "humanVerdict": h["verdict"], "rating": h["rating"],
        "humanReps": h["reps"], "pipelineReps": res.get("n_reps"),
        "countStatus": res.get("countStatus"), "scored": scored,
        "score": res.get("sessionScore"), "topFixes": fixes,
        "faults": [],
    }
    if out["error"]:
        return out
    fam = family(pipe_mov)
    out["pipelineFamily"] = fam
    if h["movement"] in ("other", "unknown"):
        out["movementMatch"] = None
    else:
        out["movementMatch"] = (h["movement"] == fam
                                or frozenset({h["movement"], fam}) in KIN)
    out["movementExact"] = h["movement"] == pipe_mov
    # Las reglas sólo son comparables si el pipeline juzgó ese movimiento.
    same = h["movement"] == pipe_mov
    human_rules = set()
    for f in h["faults"]:
        rule = f["ruleId"]
        if not f["observable"]:
            outcome = "no observable"
        elif not rule:
            outcome = "sin regla"
        elif not same:
            outcome = "movimiento distinto"
        elif not scored:
            outcome = "abstención (sin puntuar)"
        elif rule in fixes:
            outcome = "acierto"
        else:
            c = checks.get(rule) or {}
            if c.get("observed"):
                outcome = "medido pero no mostrado"
            elif c.get("notObserved"):
                outcome = "omisión"
            else:
                outcome = "abstención (no juzgable)"
        if rule:
            human_rules.add(rule)
        out["faults"].append({**f, "outcome": outcome})
    extra = [r for r in fixes if r not in human_rules]
    clean = h["verdict"] == "clean"
    out["falseAlarms"] = extra if (clean and same) else []
    out["wrongMovementFixes"] = fixes if (fixes and out["movementMatch"] is False) else []
    out["unmentioned"] = extra if (not clean and same) else []
    return out


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r["error"]]
    mv = [r for r in ok if r["movementMatch"] is not None]
    outcomes = Counter(f["outcome"] for r in ok for f in r["faults"])
    by_cat = Counter(f["category"] for r in ok for f in r["faults"]
                     if f["observable"] and not f["ruleId"])
    clean_same = [r for r in ok if r["humanVerdict"] == "clean" and r["movementExact"]]
    clean_scored = [r for r in clean_same if r["scored"]]
    reps = [r for r in ok if r["humanReps"] and r["movementMatch"]]
    off_catalog = [r for r in ok if r["humanMovement"] == "other"]
    return {
        "clips": len(rows), "errors": len(rows) - len(ok),
        "movement": {"judged": len(mv), "family": sum(r["movementMatch"] for r in mv),
                     "exactCatalog": sum(r["movementExact"] for r in mv)},
        "offCatalog": {"clips": len(off_catalog), "scoredAnyway": sum(
            r["scored"] for r in off_catalog)},
        "scored": sum(r["scored"] for r in ok),
        "faultOutcomes": dict(outcomes),
        "unmeasurableCategories": dict(by_cat.most_common()),
        "cleanClips": {"sameMovement": len(clean_same), "scored": len(clean_scored),
                       "withFalseAlarm": sum(bool(r["falseAlarms"]) for r in clean_scored),
                       "falseAlarms": sum(len(r["falseAlarms"]) for r in clean_scored)},
        "unmentionedFixes": sum(len(r["unmentioned"]) for r in ok),
        "scoredAsWrongMovement": sum(bool(r["wrongMovementFixes"]) or (
            r["scored"] and r["movementMatch"] is False) for r in ok),
        "repCount": {"judged": len(reps), "exact": sum(
            r["pipelineReps"] == r["humanReps"] for r in reps)},
    }


def main() -> int:
    humans = [json.loads(l) for l in HUMAN.read_text(encoding="utf-8").splitlines() if l]
    rows = []
    for h in humans:
        f = PIPE / f"{h['sha256'][:16]}.json"
        p = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {
            "error": "sin pasar por el pipeline"}
        rows.append(compare_clip(h, p))
    report = {
        "all": summarise(rows),
        "heldOut": summarise([r for r in rows if not r["dev"]]),
        "dev": summarise([r for r in rows if r["dev"]]),
        "clips": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("all", "heldOut", "dev")},
                     ensure_ascii=False, indent=1))
    print(f"\n{'clip':42} {'humano':22} {'pipeline':14} reps  punt  topFixes / resultado")
    for r in rows:
        if r["error"]:
            print(f"{r['clip'][-42:]:42} ERROR {r['error']}")
            continue
        print(f"{r['clip'][-42:]:42} {r['humanMovement'][:22]:22} "
              f"{str(r['pipelineMovement'])[:14]:14} {str(r['humanReps'] or '-'):>2}/"
              f"{str(r['pipelineReps']):<3} {str(r['score'] or '-'):>4}  "
              f"{','.join(x.split('.')[-1] for x in r['topFixes']) or '-'}")
        for f in r["faults"]:
            print(f"{'':46}· {f['outcome']:<26} {f['quote'][:50]}")
        for x in r["falseAlarms"]:
            print(f"{'':46}! falsa alarma {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
