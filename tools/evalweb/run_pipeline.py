"""Pasa por el pipeline de producción cada clip valorado a mano.

    .venv/bin/python tools/evalweb/run_pipeline.py [--api URL] [--force] [--jobs 4]

Sube cada clip de data/eval/human_technique_structured.jsonl como lo haría el
teléfono (ejercicio "auto", un dispositivo desechable), espera al resultado,
lo guarda en out/evalweb/pipeline/<sha256[:16]>.json y borra el trabajo. Un clip
ya guardado no se repite salvo con --force.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_pipeline as e2e  # noqa: E402

SRC = ROOT / "data/eval/human_technique_structured.jsonl"
OUT = ROOT / "out/evalweb/pipeline"


class Quiet(e2e.Report):
    """El Report de e2e, sin una línea por comprobación."""

    def ok(self, name, detail=""):
        self.rows.append((name, True, detail))

    def bad(self, name, detail=""):
        self.rows.append((name, False, detail))

    def check(self, name, cond, detail=""):
        (self.ok if cond else self.bad)(name, detail)
        return bool(cond)


def run(api: str, row: dict, budget: int) -> dict:
    clip = next((ROOT / p for p in row["paths"] if (ROOT / p).exists()), None)
    if clip is None:
        return {"error": "clip no encontrado"}
    rep, device = Quiet(), f"eval-{uuid.uuid4().hex[:12]}"
    status, created, _ = e2e.request("POST", f"{api}/v1/jobs", device=device,
                                     json_body={"exercise": "auto"})
    if status != 201:
        return {"error": f"crear trabajo: HTTP {status}"}
    job = created["id"]
    try:
        if not e2e.upload_clip(rep, api, device, job, clip):
            return {"error": "subida: " + "; ".join(n for n, ok, _ in rep.rows if not ok)}
        status, _, _ = e2e.request("POST", f"{api}/v1/jobs/{job}/submit",
                                   device=device, json_body={})
        if status != 202:
            return {"error": f"submit: HTTP {status}"}
        item = e2e.poll(rep, api, device, job, budget)
        return {"clip": str(clip.relative_to(ROOT)), "item": item} if item else {
            "error": f"sin resultado en {budget}s"}
    finally:
        try:
            e2e.request("DELETE", f"{api}/v1/jobs/{job}", device=device)
        except Exception:  # noqa: BLE001 - el trabajo caduca solo
            pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--budget", type=int, default=900)
    args = ap.parse_args()
    api = e2e.api_base(args.api)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in SRC.read_text(encoding="utf-8").splitlines() if line]
    def done(r):
        f = OUT / f"{r['sha256'][:16]}.json"
        return f.exists() and not json.loads(f.read_text(encoding="utf-8")).get("error")
    todo = [r for r in rows if args.force or not done(r)]
    print(f"{len(todo)} de {len(rows)} clips por pasar ({api})")

    def one(row):
        try:
            res = run(api, row, args.budget)
        except Exception as exc:  # noqa: BLE001 - un corte de red no para la tanda
            res = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        res["sha256"] = row["sha256"]
        (OUT / f"{row['sha256'][:16]}.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        item = res.get("item") or {}
        result = item.get("result") or {}
        print(f"  {row['paths'][0][-40:]:40} {res.get('error') or item.get('status')} "
              f"{result.get('exercise', '')} {result.get('n_reps', '')}", flush=True)

    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(one, todo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
