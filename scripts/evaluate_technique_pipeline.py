#!/usr/bin/env python
"""Deterministic evaluation runner for the technique pipeline.

Runs the REAL measurement path over a set of clips and writes everything a
reviewer needs into a fresh run directory - payloads, traces, a summary, the
diff against a saved baseline, provenance and every failure - without ever
touching the baseline or the annotations it compares against.

Modes:

  cached    barra.posecache -> server.process.analyze_clip, in this process.
            Extraction is held fixed, so two runs differ only in the code.
  fresh     server.process.process_job in an isolated subprocess per clip,
            pose estimated anew. A pose backend can take an interpreter down;
            that is why it is a subprocess.
  vision    fresh mode with a named vision endpoint required; validated
            responses are kept separately under vision/.

Usage:
  python scripts/evaluate_technique_pipeline.py --mode cached
  python scripts/evaluate_technique_pipeline.py --mode fresh VID-20260827-WA0010.mp4
  python scripts/evaluate_technique_pipeline.py --mode cached --baseline out/pipeline-improvement

Outputs land in <out>/<timestamp>-<mode>/ (default out/technique-eval/):
  payloads/<stem>.json      the payload the phone would receive
  traces/<traceId>.json     the decision chain, one per clip
  summary.json / .csv       per clip: movement, count, faults, checks, runtime
  diff-vs-baseline.json     what changed against <baseline>/<stem>-before.json
  metrics.json              against data/evaluation/sample_manifest.json
  manifest-audit.json       data/calisthenics/metadata.csv vs files present
  provenance.json           code, config, model
  failures.json             every clip that did not produce a payload, and why
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

DEFAULT_MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"
DEFAULT_BASELINE = ROOT / "out" / "pipeline-improvement"
DEFAULT_OUT = ROOT / "out" / "technique-eval"
CORPUS_METADATA = ROOT / "data" / "calisthenics" / "metadata.csv"


# ---------------------------------------------------------------------------
# one clip
# ---------------------------------------------------------------------------
def run_cached(clip: Path, exercise: str, trace_dir: Path) -> tuple[dict, dict]:
    """analyze_clip on cached keypoints. Returns (payload, trace dict)."""
    from barra.ingest import probe_video
    from barra.posecache import load_or_estimate
    from barra.trace import Trace, new_id
    from process import analyze_clip

    tr = Trace(new_id(clip.name), clip.name, source="evaluate-cached",
               clip=str(clip), exercise_requested=exercise)
    info = probe_video(clip)
    pose = load_or_estimate(clip, fresh=False, trace=tr, write_cache=False,
                            fallback_fps=float(info.get("fps") or 0.0))
    t0 = time.monotonic()
    payload = analyze_clip(clip, exercise=exercise, session="1970-01-01",
                           trace=tr, pose=pose)
    payload["_runtimeS"] = {"analyze": round(time.monotonic() - t0, 3),
                            "poseSource": pose.source}
    payload["traceId"] = tr.id
    tr.write(trace_dir / f"{tr.id}.json")
    return payload, tr.as_dict()


def run_fresh_subprocess(clip: Path, exercise: str, out_json: Path,
                         trace_dir: Path, vision: bool) -> dict:
    """process_job in its own interpreter; the payload comes back via a file."""
    env = dict(os.environ)
    env["BARRA_TRACE_DIR"] = str(trace_dir)
    env.setdefault("BARRA_ROOT", str(ROOT))
    if not vision:
        # A fresh-pose run must not spend money or time on a vision call the
        # mode did not ask for.
        for k in ("BARRA_VISION_BASE_URL", "BARRA_VISION_API_KEY",
                  "NAN_BASE_URL", "NAN_API_KEY"):
            env.pop(k, None)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker",
           str(clip), str(out_json), "--exercise", exercise]
    # A native pose library can be killed by a signal before Python sees an
    # exception, which the in-process fallback in barra.posecache cannot
    # catch. So the fallback lives here: a worker that dies by signal is run
    # again with the next backend pinned, and the payload says which one
    # produced the keypoints and that the first did not survive.
    attempts: list[str | None] = [env.get("BARRA_POSE_BACKEND") or None]
    if attempts[0] is None:
        try:
            from barra.pose import available_backends
            attempts += [b for b in available_backends()]
        except Exception:  # noqa: BLE001
            pass
    died: list[dict] = []
    t0 = time.monotonic()
    for backend in dict.fromkeys(attempts):
        if backend:
            env["BARRA_POSE_BACKEND"] = backend
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                              text=True, timeout=1800)
        if proc.returncode == 0 and out_json.exists():
            payload = json.loads(out_json.read_text())
            payload["_runtimeS"] = {"process_job": round(time.monotonic() - t0, 3),
                                    "poseSource": "fresh",
                                    "poseBackendPinned": backend,
                                    "poseBackendDied": died or None}
            return payload
        died.append({"backend": backend or "default order", "exit": proc.returncode,
                     "stderr": proc.stderr[-1500:]})
        if proc.returncode >= 0:
            break            # a Python-level failure: retrying a backend will not help
    return {"error": f"worker exit {died[-1]['exit']}", "attempts": died,
            "stdout": proc.stdout[-2000:],
            "runtimeS": round(time.monotonic() - t0, 3)}


def _worker(clip: Path, out_json: Path, exercise: str) -> int:
    from process import process_job

    job = {"id": f"eval-{clip.stem}", "exercise": exercise, "session": "1970-01-01"}
    payload = process_job(job, clip)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------
def summarise_payload(payload: dict) -> dict:
    reps = payload.get("reps") or []
    faults = Counter()
    unobservable = Counter()
    for rep in reps:
        for f in rep.get("faults") or []:
            faults[f.get("errorId") or f.get("name")] += 1
        for a in rep.get("assessments") or []:
            if a.get("status") == "unobservable":
                unobservable[a.get("errorId")] += 1
    return {
        "exercise": payload.get("exercise"),
        "detected": (payload.get("detected") or {}).get("exercise"),
        "variant": (payload.get("variant") or {}).get("name"),
        "nReps": payload.get("n_reps"),
        "nCandidates": payload.get("n_candidates"),
        "rescued": payload.get("rescued"),
        "countedBy": payload.get("countedBy"),
        "sessionScore": payload.get("sessionScore"),
        "repWindows": [[r.get("startS"), r.get("turnS"), r.get("endS")] for r in reps],
        "faults": dict(faults),
        "unobservable": dict(unobservable),
        "blockers": payload.get("blockers") or [],
        "measurementVersion": payload.get("measurementVersion"),
        "traceId": payload.get("traceId"),
        "runtimeS": payload.get("_runtimeS"),
    }


def diff_against_baseline(stem: str, payload: dict, baseline_dir: Path) -> dict | None:
    before_path = baseline_dir / f"{stem}-before.json"
    if not before_path.exists():
        return None
    before = json.loads(before_path.read_text())
    a, b = summarise_payload(before), summarise_payload(payload)

    def _windows(s):
        return [tuple(round(float(x), 2) for x in w) for w in s["repWindows"]]

    before_w, after_w = _windows(a), _windows(b)
    removed = [w for w in before_w if w not in after_w]
    added = [w for w in after_w if w not in before_w]
    fault_delta = {}
    for key in set(a["faults"]) | set(b["faults"]):
        if a["faults"].get(key, 0) != b["faults"].get(key, 0):
            fault_delta[key] = {"before": a["faults"].get(key, 0),
                                "after": b["faults"].get(key, 0)}
    # Fault names, too: the baseline predates errorIds, so its keys are names.
    names_before = Counter()
    for rep in before.get("reps") or []:
        for f in rep.get("failures") or []:
            names_before[f] += 1
    names_after = Counter()
    for rep in payload.get("reps") or []:
        for f in rep.get("failures") or []:
            names_after[f] += 1
    name_delta = {k: {"before": names_before.get(k, 0), "after": names_after.get(k, 0)}
                  for k in set(names_before) | set(names_after)
                  if names_before.get(k, 0) != names_after.get(k, 0)}
    return {
        "baseline": before_path.name,
        "detected": {"before": a["detected"], "after": b["detected"]},
        "nReps": {"before": a["nReps"], "after": b["nReps"]},
        "sessionScore": {"before": a["sessionScore"], "after": b["sessionScore"]},
        "repsRemoved": removed,
        "repsAdded": added,
        "faultNameDelta": name_delta,
        "changed": bool(removed or added or name_delta
                        or a["detected"] != b["detected"]
                        or a["nReps"] != b["nReps"]),
    }


def metrics_against_manifest(results: dict[str, dict], manifest: dict | None) -> dict:
    """Movement confusion, count error, forbidden faults and false retained
    reps against the reviewed manifest. Denominators are reported with every
    number; a class with no reviewed clip is inconclusive, not 100%."""
    if not manifest:
        return {"note": "no manifest supplied"}
    by_file = {c["file"]: c for c in manifest.get("clips", [])}
    confusion: dict[str, Counter] = {}
    count_errors = []
    forbidden_hits = []
    phase_scoped = []
    false_retained = []
    unobservable_hits = []
    n_movement = 0
    correct = 0
    for stem, payload in results.items():
        label = by_file.get(f"{stem}.mp4")
        if not label or "error" in payload:
            continue
        detected = (payload.get("detected") or {}).get("exercise") or payload.get("exercise")
        truth = label.get("movement")
        if truth is not None:
            n_movement += 1
            confusion.setdefault(truth, Counter())[detected] += 1
            correct += int(detected == truth)
        if label.get("reps") is not None and truth not in (None, "unknown"):
            count_errors.append({"clip": stem, "reviewed": label["reps"],
                                 "measured": payload.get("n_reps"),
                                 "error": (payload.get("n_reps") or 0) - label["reps"]})
        if label.get("reps") == 0:
            count_errors.append({"clip": stem, "reviewed": 0,
                                 "measured": payload.get("n_reps"),
                                 "error": payload.get("n_reps") or 0})
        reps = payload.get("reps") or []
        for f in label.get("forbidden") or []:
            n = sum(1 for r in reps for a in r.get("faults") or []
                    if a.get("errorId") == f["errorId"])
            forbidden_hits.append({"clip": stem, "errorId": f["errorId"],
                                   "repsFired": n, "repsTotal": len(reps)})
        for ps in label.get("phaseScoped") or []:
            rows = [a for r in reps for a in r.get("assessments") or []
                    if a.get("errorId") == ps["errorId"] and a.get("status") == "observed"]
            bad = [a for a in rows
                   if a.get("phase") != ps["phase"]
                   or (a.get("intervalS") and
                       (a["intervalS"][1] - a["intervalS"][0]) > ps.get("maxWindowS", 1e9))]
            phase_scoped.append({"clip": stem, "errorId": ps["errorId"],
                                 "phase": ps["phase"], "fired": len(rows),
                                 "outsidePhaseOrTooWide": len(bad), "ok": not bad})
        for nr in label.get("notReps") or []:
            lo, hi = nr["intervalS"]
            kept = [r for r in reps
                    if r.get("startS") is not None
                    and abs(float(r["startS"]) - lo) < 0.5 and abs(float(r["endS"]) - hi) < 0.5]
            false_retained.append({"clip": stem, "intervalS": [lo, hi],
                                   "retained": bool(kept)})
        for u in label.get("unobservable") or []:
            states = Counter(a.get("status") for r in reps
                             for a in r.get("assessments") or []
                             if a.get("errorId") == u["errorId"])
            unobservable_hits.append({"clip": stem, "errorId": u["errorId"],
                                      "statuses": dict(states)})
    per_class = {}
    for truth, row in confusion.items():
        tp = row.get(truth, 0)
        fn = sum(row.values()) - tp
        fp = sum(c.get(truth, 0) for t, c in confusion.items() if t != truth)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if prec is not None and rec is not None else None)
        per_class[truth] = {"support": tp + fn, "precision": prec, "recall": rec, "f1": f1,
                            "predicted": dict(row)}
    f1s = [v["f1"] for v in per_class.values() if v["f1"] is not None]
    return {
        "movement": {
            "reviewedClips": n_movement,
            "accuracy": (correct / n_movement) if n_movement else None,
            "macroF1": (sum(f1s) / len(f1s)) if f1s else None,
            "perClass": per_class,
            "note": "eight clips are a smoke test, not an evaluation; classes with "
                    "support 1 are inconclusive",
        },
        "segmentation": {
            "countErrors": count_errors,
            "meanAbsCountError": (sum(abs(c["error"]) for c in count_errors) / len(count_errors))
            if count_errors else None,
            "falseRetained": false_retained,
        },
        "errors": {
            "forbidden": forbidden_hits,
            "phaseScoped": phase_scoped,
            "unobservableExpected": unobservable_hits,
        },
    }


def audit_corpus(metadata: Path) -> dict:
    """metadata.csv against the files actually on disk."""
    if not metadata.exists():
        return {"present": False, "path": str(metadata)}
    rows = list(csv.DictReader(metadata.open()))
    base = metadata.parent
    missing, present = [], []
    by_trick: Counter = Counter()
    for r in rows:
        p = base / r.get("file", "")
        (present if p.exists() else missing).append(r.get("file"))
        if p.exists():
            by_trick[r.get("trick", "?")] += 1
    return {"present": True, "rows": len(rows), "filesPresent": len(present),
            "filesMissing": len(missing), "missing": missing[:50],
            "presentByMovement": dict(by_trick)}


def provenance() -> dict:
    try:
        from barra.provenance import stamp
        out = stamp()
    except Exception as exc:  # noqa: BLE001
        out = {"error": str(exc)}
    try:
        from barra.config import THRESHOLDS
        import dataclasses
        out["thresholds"] = dataclasses.asdict(THRESHOLDS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from barra.rules import RULES
        out["rules"] = {k: [r.as_dict() for r in v] for k, v in RULES.items()}
    except Exception:  # noqa: BLE001
        pass
    out["argv"] = sys.argv
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*", help="video files; default: <root>/VID-*.mp4")
    ap.add_argument("--mode", choices=("cached", "fresh", "vision"), default="cached")
    ap.add_argument("--exercise", default="auto")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--label", default="", help="suffix for the run directory")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                    help="directory of <stem>-before.json payloads to diff against")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--worker", nargs=2, metavar=("CLIP", "OUT_JSON"),
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.worker:
        return _worker(Path(args.worker[0]), Path(args.worker[1]), args.exercise)

    clips = [Path(c).resolve() for c in args.clips] or sorted(ROOT.glob("VID-*.mp4"))
    if not clips:
        print("no clips", file=sys.stderr)
        return 2
    if args.mode == "vision":
        from vision import _config
        if _config() is None:
            print("vision mode needs BARRA_VISION_BASE_URL / BARRA_VISION_API_KEY "
                  "(or NAN_*); none is configured. Not claiming a vision run.",
                  file=sys.stderr)
            return 3

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"{stamp}-{args.mode}{('-' + args.label) if args.label else ''}"
    if run_dir.exists():
        print(f"refusing to overwrite {run_dir}", file=sys.stderr)
        return 4
    payload_dir, trace_dir = run_dir / "payloads", run_dir / "traces"
    payload_dir.mkdir(parents=True)
    trace_dir.mkdir(parents=True)

    manifest = json.loads(args.manifest.read_text()) if args.manifest.exists() else None
    results: dict[str, dict] = {}
    failures: dict[str, dict] = {}
    summary: dict[str, dict] = {}
    diffs: dict[str, dict] = {}

    for clip in clips:
        stem = clip.stem
        print(f"[{args.mode}] {clip.name} ...", flush=True)
        try:
            if args.mode == "cached":
                payload, _ = run_cached(clip, args.exercise, trace_dir)
            else:
                payload = run_fresh_subprocess(clip, args.exercise,
                                               payload_dir / f"{stem}.json", trace_dir,
                                               vision=(args.mode == "vision"))
        except Exception as exc:  # noqa: BLE001 - one clip must not end the run
            payload = {"error": f"{type(exc).__name__}: {exc}"}
        if "error" in payload:
            failures[stem] = payload
            print(f"   ! {payload['error']}", flush=True)
            continue
        (payload_dir / f"{stem}.json").write_text(json.dumps(payload, indent=2, default=str))
        results[stem] = payload
        summary[stem] = summarise_payload(payload)
        d = diff_against_baseline(stem, payload, args.baseline) if args.baseline else None
        if d is not None:
            diffs[stem] = d
        s = summary[stem]
        print(f"   {s['detected']} reps={s['nReps']} faults={s['faults']} "
              f"{'CHANGED' if d and d['changed'] else ''}", flush=True)
        if args.mode == "vision":
            vis = {k: payload.get(k) for k in
                   ("visionObservations", "visionValidation", "visionMovement",
                    "visionVerdict", "proseSource")}
            (run_dir / "vision").mkdir(exist_ok=True)
            (run_dir / "vision" / f"{stem}.json").write_text(json.dumps(vis, indent=2))

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    with (run_dir / "summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["clip", "detected", "nReps", "nCandidates", "rescued",
                    "sessionScore", "faults", "unobservable", "traceId"])
        for stem, s in summary.items():
            w.writerow([stem, s["detected"], s["nReps"], s["nCandidates"], s["rescued"],
                        s["sessionScore"], json.dumps(s["faults"]),
                        json.dumps(s["unobservable"]), s["traceId"]])
    (run_dir / "diff-vs-baseline.json").write_text(json.dumps(diffs, indent=2))
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics_against_manifest(results, manifest), indent=2))
    (run_dir / "manifest-audit.json").write_text(json.dumps(audit_corpus(CORPUS_METADATA), indent=2))
    (run_dir / "provenance.json").write_text(json.dumps(provenance(), indent=2, default=str))
    (run_dir / "failures.json").write_text(json.dumps(failures, indent=2))
    print(f"\nrun written to {run_dir}")
    print(f"  {len(results)} payloads, {len(failures)} failures, "
          f"{sum(1 for d in diffs.values() if d['changed'])} changed vs baseline")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
