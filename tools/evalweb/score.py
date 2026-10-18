"""Una nota de 1 a 100 para el algoritmo oficial, contra la valoración humana.

    .venv/bin/python tools/evalweb/score.py            # tras compare.py

Lee out/evalweb/report.json (compare.py) y escribe out/evalweb/score.json.

La nota es la media ponderada de siete partes, cada una de 0 a 1 y medida sobre
los clips donde tiene sentido. Cada parte es algo que el atleta nota:

  movimiento    ¿reconoce el ejercicio? (clips de catálogo, familia)          20
  responde      ¿puntúa una serie de catálogo bien grabada? (no se abstiene)  10
  se_abstiene   ¿no puntúa lo que no es de catálogo?                          10
  reps          ¿cuenta bien las reps? (exactas = 1, a ±1 = 0,5)              15
  sin_falsas    ¿una serie limpia sale sin fallos inventados?                 20
  acierta       ¿ve los fallos que el humano señala y que tiene regla?        10
  nota          ¿su nota ordena las series como la nota 1–5 del humano?       15
                (Spearman, llevado de [-1, 1] a [0, 1])

Una parte sin clips suficientes (< 5) no cuenta y su peso se reparte. Cada
parte lleva su n: con muestras así, ±10 puntos son ruido, y la nota sirve
para comparar versiones del algoritmo sobre los mismos clips, no como verdad
absoluta. Lo que el texto libre no menciona no cuenta como error ni acierto:
un comentario no es una lista exhaustiva.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "out/evalweb/report.json"
OUT = ROOT / "out/evalweb/score.json"
HUMAN = ROOT / "data/eval/human_technique_structured.jsonl"

WEIGHTS = {"movimiento": 20, "responde": 10, "se_abstiene": 10, "reps": 15,
           "sin_falsas": 20, "acierta": 10, "nota": 15}
MIN_N = 5


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def parts(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r["error"]]
    catalog = [r for r in ok if r["movementMatch"] is not None]
    single = [r for r in catalog if r["singleSet"]]
    other = [r for r in ok if r["humanMovement"] == "other"]
    out = {}

    out["movimiento"] = (sum(r["movementMatch"] for r in catalog), len(catalog))
    good = [r for r in single if r["movementMatch"] and r["humanVerdict"] != "unassessable"]
    out["responde"] = (sum(r["scored"] for r in good), len(good))
    out["se_abstiene"] = (sum(not r["scored"] for r in other), len(other))

    reps = [r for r in single if r["humanReps"] and r["movementMatch"]]
    out["reps"] = (sum(1.0 if r["pipelineReps"] == r["humanReps"] else
                       0.5 if r["pipelineReps"] is not None
                       and abs(r["pipelineReps"] - r["humanReps"]) <= 1 else 0.0
                       for r in reps), len(reps))

    clean = [r for r in ok if r["humanVerdict"] == "clean" and r["movementExact"] and r["scored"]]
    out["sin_falsas"] = (sum(not r["falseAlarms"] for r in clean), len(clean))

    judged = [f for r in ok for f in r["faults"]
              if f["outcome"] in ("acierto", "omisión", "medido pero no mostrado")]
    out["acierta"] = (sum(f["outcome"] == "acierto" for f in judged), len(judged))

    pairs = [(r["rating"], r["score"]) for r in ok
             if r["scored"] and r["rating"] and r["movementMatch"]]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    out["nota"] = (((rho + 1) / 2) * len(pairs) if rho is not None else 0.0, len(pairs))
    out["_rho"] = rho
    return out


def score(rows: list[dict]) -> dict:
    p = parts(rows)
    rho = p.pop("_rho")
    table, total, wsum = {}, 0.0, 0.0
    for k, w in WEIGHTS.items():
        hit, n = p[k]
        frac = hit / n if n else None
        counted = n >= MIN_N
        table[k] = {"valor": None if frac is None else round(frac, 3), "n": n,
                    "peso": w, "cuenta": counted}
        if counted:
            total += w * frac
            wsum += w
    nota = round(100 * total / wsum) if wsum else None
    table["nota"]["spearman"] = None if rho is None else round(rho, 3)
    return {"nota": max(1, nota) if nota is not None else None, "partes": table}


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = report["clips"]
    res = {"todos": score(rows),
           "fuera_de_desarrollo": score([r for r in rows if not r["dev"]]),
           "clips": len(rows)}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for name in ("todos", "fuera_de_desarrollo"):
        s = res[name]
        print(f"\n{name}: NOTA {s['nota']}/100")
        for k, v in s["partes"].items():
            val = "—" if v["valor"] is None else f"{100 * v['valor']:.0f}"
            extra = f"  ρ={v['spearman']}" if "spearman" in v else ""
            print(f"  {k:12} {val:>4}  (n={v['n']}, peso {v['peso']}"
                  f"{'' if v['cuenta'] else ', no cuenta: pocos clips'}){extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
