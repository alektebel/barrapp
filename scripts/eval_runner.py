#!/usr/bin/env python
"""The eval runner: golden set, judge, gate - one command, CI-callable.

Runs the measurement core over the golden clips (cached keypoints by
default, so two runs differ only in code), grades the payloads against the
reviewed manifest, grades the prose against the reference check (and, when
a judge endpoint is configured, the rubric), and compares against a saved
baseline. Exit code 1 blocks the pipeline; that is the gate.

Modes:
  cached   posecache -> analyze_clip in this process. Extraction held fixed.
  fresh    process_job in an isolated subprocess per clip (a pose backend
           can take an interpreter down; the subprocess is the seatbelt).

Usage:
  python scripts/eval_runner.py --mode cached
  python scripts/eval_runner.py --save-baseline          # first run
  python scripts/eval_runner.py --mode cached --gate     # CI form

Outputs land in <out>/eval/<timestamp>-<mode>/:
  payloads/<stem>.json      the payload the phone would receive
  grade.json                golden grading, per clip and rollup
  judge.json                reference check (+ rubric scores when judged)
  gate.json                 baseline comparison and its verdict
  summary.txt               the one screen a human reads
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

sys.path.insert(0, str(ROOT / "scripts"))          # the existing runner
import evaluate_technique_pipeline as base  # noqa: E402  (worker + run helpers)

from barra.eval.golden import grade_run  # noqa: E402
from barra.eval.gate import compare_to_baseline  # noqa: E402

DEFAULT_OUT = ROOT / "out" / "eval"
MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"
GOLDEN_GLOBS = ("VID-*.mp4",)          # the reviewed root clips


def run_cached(clip: Path, exercise: str, trace_dir: Path) -> tuple[dict, dict]:
    """Delegates to the proven runner; same shape, same trace discipline."""
    return base.run_cached(clip, exercise, trace_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*", help="video files; default: golden VID-*.mp4")
    ap.add_argument("--mode", choices=("cached", "fresh"), default="cached")
    ap.add_argument("--exercise", default="auto")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--label", default="")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--save-baseline", action="store_true",
                    help="write grade.json as the new baseline (out/eval/baseline)")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 when a metric drops past tolerance vs baseline")
    args = ap.parse_args(argv)

    clips = [Path(c) for c in args.clips] or sorted(
        p for g in GOLDEN_GLOBS for p in ROOT.glob(g))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"{stamp}-{args.mode}{('-' + args.label) if args.label else ''}"
    (run_dir / "payloads").mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(exist_ok=True)

    results: dict[str, dict] = {}
    timing: list[dict] = []
    t0 = time.monotonic()
    for clip in clips:
        print(f"[{clip.name}] running ({args.mode})...", flush=True)
        clip_t0 = time.monotonic()
        try:
            if args.mode == "cached":
                payload, _tr = run_cached(clip, args.exercise, trace_dir)
            else:
                out_json = run_dir / "payloads" / f"{clip.stem}.json"
                worker = base.run_fresh_subprocess(
                    clip, args.exercise, out_json, trace_dir, vision=False)
                payload = json.loads(out_json.read_text()) if out_json.exists() else worker
        except Exception as exc:  # noqa: BLE001 - a failed clip is graded as one
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        wall = time.monotonic() - clip_t0
        results[clip.stem] = payload
        (run_dir / "payloads" / f"{clip.stem}.json").write_text(
            json.dumps(payload, indent=1, default=str) + "\n")
        rt = payload.get("_runtimeS") or {}
        timing.append({
            "clip": clip.name, "wallS": round(wall, 3),
            "analyzeS": rt.get("analyze"),
            "poseSource": rt.get("poseSource"),
            **({"error": payload["error"]} if "error" in payload else {}),
        })

    # ---- golden grading -------------------------------------------------
    grade = grade_run(results, args.manifest)
    (run_dir / "grade.json").write_text(json.dumps(grade, indent=1) + "\n")

    # ---- prose judging ---------------------------------------------------
    from barra.eval.judge import judge_writeup
    judged = {}
    for stem, payload in sorted(results.items()):
        prose = {k: payload.get(k) for k in ("headline", "narrative", "nextSession")
                 if payload.get(k)}
        if prose:
            judged[stem] = judge_writeup(payload, prose)
    (run_dir / "judge.json").write_text(json.dumps(judged, indent=1) + "\n")

    # ---- gate ------------------------------------------------------------
    baseline_path = args.out / "baseline" / "grade.json"
    verdict = compare_to_baseline(grade, baseline_path)
    verdict_dict = verdict.as_dict()
    if args.save_baseline:
        bdir = args.out / "baseline"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "grade.json").write_text(json.dumps(grade, indent=1) + "\n")
        verdict_dict["baselineSaved"] = str(bdir / "grade.json")
    (run_dir / "gate.json").write_text(json.dumps(verdict_dict, indent=1) + "\n")
    # ---- speed ------------------------------------------------------------
    from barra.eval.perf import timing_summary
    perf = timing_summary(timing)
    (run_dir / "perf.json").write_text(json.dumps(
        {"summary": perf, "perClip": timing}, indent=1) + "\n")
    w = perf["wallS"]
    lines = [f"eval run {run_dir.name}",
             f"  clips: {grade['clips']} ({grade['gradedClips']} graded), "
             f"{round(time.monotonic() - t0, 1)}s"]
    lines.append(f"  speed: wall mean {w['mean']}s median {w['median']}s "
                 f"p95 {w['p95']}s max {w['max']}s")
    if perf["byPoseSource"]:
        for src, row in perf["byPoseSource"].items():
            lines.append(f"    pose {src}: {row['clips']} clips, "
                         f"mean wall {row['meanWallS']}s")
    for s in perf["slowest"]:
        lines.append(f"    slow: {s['clip']} {s['wallS']}s ({s['poseSource']})")
    for kind, row in (grade.get("rollup") or {}).items():
        lines.append(f"  {kind:14s} {row['pass']}/{row['total']} = {row['rate']}")
    for r in grade.get("ungraded", []):
        lines.append(f"  ungraded: {r['clip']} - {r['why'][:80]}")
    for c in grade.get("failedChecks", []):
        lines.append(f"  FAIL {c['check']} on {c.get('clip', '?')}: {c}")
    for stem, j in judged.items():
        if not j["reference"]["ok"]:
            lines.append(f"  HALLUCINATION {stem}: "
                         f"{[i['number'] for i in j['reference']['invented']]}")
        elif j.get("judged"):
            lines.append(f"  judge {stem}: {j['verdict']} "
                         f"mean {j.get('meanScore')}")
    lines.append("  gate: " + ("BLOCKED" if verdict.blocked else
                              "pass" if not verdict.reasons else
                              "; ".join(verdict.reasons)[:120]))
    summary = "\n".join(lines) + "\n"
    (run_dir / "summary.txt").write_text(summary)
    print(summary)

    if args.gate and verdict.blocked:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
