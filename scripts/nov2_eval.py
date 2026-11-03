#!/usr/bin/env python
"""Re-run the 2026-11-02 missclass clips and print what each one got.

    python scripts/nov2_eval.py [--clips-dir /tmp/barra-nov2] [--strict] [--vision]

Default is geometry+model only (vision keys cleared). With --vision the
movement-tree vote is allowed when NAN_API_KEY is set.

Exit 0 always unless --strict, which exits 1 when any clip's exercise differs
from ground truth.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

# Ground truth for the Nov 2 jobs. There is no L-sit in any of these clips.
GROUND = {
    "a038d832f870": "dip",              # weighted dips → measure as dip
    "a9884573d367": "dip",
    "93ebbf6e4894": "front_lever_pull_up",
    "cc61dc871b9d": "inverted_curl",
    "31e6fc884110": "knee_raise",       # hanging leg raise, not L-sit
}


def _unwrap_ddb(value):
    if not isinstance(value, dict):
        return value
    if "S" in value:
        return value["S"]
    if "N" in value:
        return float(value["N"])
    if "BOOL" in value:
        return value["BOOL"]
    if "NULL" in value:
        return None
    if "M" in value:
        return {k: _unwrap_ddb(v) for k, v in value["M"].items()}
    if "L" in value:
        return [_unwrap_ddb(v) for v in value["L"]]
    return value


def _job_from_sidecar(sidecar: Path, job_id: str) -> dict:
    raw = json.loads(sidecar.read_text())
    item = raw.get("Item") or raw
    job = {k: _unwrap_ddb(v) for k, v in item.items()}
    job["id"] = job_id
    job["exercise"] = "auto"
    return job


def _run_one(job_id: str, clips_dir: Path, *, vision: bool) -> dict:
    from process import measure_job

    video = clips_dir / f"{job_id}.mp4"
    if not video.is_file():
        raise FileNotFoundError(video)
    sidecar = clips_dir / f"{job_id}.json"
    job = (_job_from_sidecar(sidecar, job_id) if sidecar.is_file()
           else {"id": job_id, "exercise": "auto"})
    vision_label = None
    if vision:
        def vision_label():
            from vision import name_movement
            return name_movement(video, Path("/tmp") / f"{job_id}-nov2-vote")
    report = measure_job(job, video, vision_label=vision_label)
    det = report.get("detected") or {}
    fus = det.get("fusion") or {}
    ground = det.get("classificationGrounding") or {}
    conf = (report.get("classificationConfidence")
            or det.get("classificationConfidence") or {})
    got = report.get("exercise") or det.get("exercise") or "unknown"
    want = GROUND[job_id]
    return {
        "job": job_id,
        "want": want,
        "got": got,
        "ok": got == want,
        "n_reps": report.get("n_reps"),
        "countStatus": report.get("countStatus"),
        "confidence": conf.get("value"),
        "band": conf.get("band"),
        "kind": conf.get("kind"),
        "clientNamesExercise": bool(
            report.get("clientNamesExercise")
            or ground.get("clientNamesExercise")
            or conf.get("clientNamesExercise")),
        "detectedLabel": ground.get("detectedLabel") or fus.get("exercise"),
        "fusionStatus": fus.get("status") or ground.get("fusionStatus"),
        "blockers": report.get("blockers") or [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clips-dir", type=Path, default=Path("/tmp/barra-nov2"))
    ap.add_argument("--out", type=Path, default=Path("/tmp/barra-nov2/eval.json"))
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any clip misses ground truth")
    ap.add_argument("--vision", action="store_true",
                    help="allow the movement-tree vision vote")
    args = ap.parse_args()

    if not args.vision:
        for k in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY"):
            os.environ.pop(k, None)
        os.environ["NAN_BASE_URL"] = ""

    rows = []
    print(f"{'job':12} {'want':22} {'got':22} {'conf':6} "
          f"{'client':6} {'fusion':16} ok")
    for job_id in GROUND:
        row = _run_one(job_id, args.clips_dir, vision=args.vision)
        rows.append(row)
        print(f"{row['job']:12} {row['want']:22} {row['got']:22} "
              f"{(row['confidence'] if row['confidence'] is not None else -1):6.3f} "
              f"{str(row['clientNamesExercise']):6} "
              f"{(row['fusionStatus'] or '-'):16} "
              f"{'OK' if row['ok'] else 'MISS'}")
        if row.get("detectedLabel") == "l_sit":
            print(f"  !! detectedLabel is l_sit (forbidden for this set)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2))
    print(f"wrote {args.out}")

    if args.strict and any(not r["ok"] for r in rows):
        return 1
    if any((r.get("detectedLabel") == "l_sit") for r in rows):
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
