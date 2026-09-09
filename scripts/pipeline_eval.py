#!/usr/bin/env python
"""Run every scraped clip through the measurement pipeline and keep the whole
decision chain, so misclassifications are explained, not just counted.

This is the "debugging pipeline" made queryable. For each clip it:

   1. estimates the pose (Ultralytics by default, or BARRA_POSE_BACKEND/--backends;
     cached keypoints are reused per model tag when available),
  2. runs the real measurement path (server.process.analyze_clip) on that pose
     and keeps the payload (detected movement, reps, faults, score, trim,
     recommendation) and the decision-chain trace (every stage, every gate),
  3. featurises the keypoints and scores with the learned model, and records
     the model's class and load estimate,
  4. cuts stills through the rep windows and asks the nan.builders multimodal
     model what exercise it sees - an INDEPENDENT label from the pixels - so a
     pipeline misclassification can be checked against what a vision model saw,
     not against a guess about the pipeline,
  5. stores one row per clip in a DynamoDB table (the intermediate state, the
     program/commit/python, the pose backend, the model and its version, the
     nan verdict) and the full trace in the TRACES_TABLE,
  6. writes payloads, traces, features and stills under out/pipeline-eval/ so
     the existing debugg tool can replay any single run.

Nothing here mutates a baseline or the reviewed manifest. It produces data for
the misclassification report and, from the cached keypoints, a training set for
the model.

Usage:
  python scripts/pipeline_eval.py                          # whole corpus, cached
  python scripts/pipeline_eval.py --tricks squat,push_up --per-trick 5
  python scripts/pipeline_eval.py --clips data/calisthenics/videos/squat/*.mp4
  python scripts/pipeline_eval.py --no-nan                  # skip the vision pass
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

import barra.schema as S
from barra.classify import features as classify_features
from barra.frames import technique_artifacts
from barra.fusion import fuse_detection
from barra.ingest import probe_video
from barra.model import (FEATURE_NAMES, load_default, model_classify,
                         model_load, vector_from_dict)
from barra.movements import MOVEMENTS
from barra.posecache import cache_path, load_or_estimate
from barra.trace import Trace, new_id
from barra.tracestore import put_failure, put_trace
from process import analyze_clip

METADATA = ROOT / "data" / "calisthenics" / "metadata.csv"
OUT = ROOT / "out" / "pipeline-eval"
EVAL_TABLE = os.environ.get("EVAL_TABLE", "barra-pipeline-eval")
TRACES_TABLE = os.environ.get("TRACES_TABLE", "sam-app-TracesTable-1R6026Z7HAU29")

MAX_NAN_STILLS = 3

# A movement the pipeline recognises; anything else is a clip the geometry
# should abstain on (or misclassify, which is exactly what we want to find).
KNOWN = set(MOVEMENTS)


def _slug(value: str) -> str:
    out = []
    for ch in str(value):
        out.append(ch if ch.isalnum() or ch in "-_." else "_")
    return "".join(out).strip("_") or "pose"


def _alias_ok(a: str, b: str) -> bool:
    """Whether two exercise labels denote the same movement (alias aware)."""
    if not a or not b or a == "unknown" or b == "unknown":
        return False
    try:
        from barra.movements import resolve
        return resolve(a).name == resolve(b).name
    except SystemExit:
        return a == b


def nan_label(paths: list[Path], base_url: str, key: str, model: str) -> dict:
    """Ask the multimodal model what exercise a clip shows, from up to 3 stills."""
    import base64
    import urllib.request
    import urllib.error

    uris = []
    for p in paths:
        try:
            uris.append("data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode())
        except OSError:
            continue
    if not uris:
        return {"ok": False, "label": "", "reason": "no stills"}
    moved = ", ".join(sorted(m.replace("_", " ") for m in MOVEMENTS))
    system = ("You identify the exercise in stills from one gym clip. Answer with "
              "one JSON object: {\"exercise\": \"<short label>\", \"gym\": true/false, "
              "note: \"one sentence\"}. The movement may be one of: " + moved +
              " or any other common gym exercise (bench press, deadlift, row, curl, "
              "machine, etc.). 'gym' is false if it is not recognisable as an exercise.")
    user = ("What exercise is this? Reply with the JSON object only.")
    content = [{"type": "text", "text": user}]
    content += [{"type": "image_url", "image_url": {"url": u}} for u in uris]
    body = json.dumps({"model": model, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": content}],
        "temperature": 0.1}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "barrapp-eval/1.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode())
        text = d["choices"][0]["message"]["content"] or ""
        start, end = text.find("{"), text.rfind("}")
        obj = json.loads(text[start:end + 1]) if start >= 0 and end > start else {}
        return {"ok": True, "label": str(obj.get("exercise") or "").strip(),
                "gym": bool(obj.get("gym")), "note": str(obj.get("note") or "")[:120],
                "raw": text[:200]}
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError,
            TimeoutError) as exc:
        return {"ok": False, "label": "", "reason": f"{type(exc).__name__}: {exc}"}


def _nan_config():
    base = (os.environ.get("BARRA_VISION_BASE_URL")
            or os.environ.get("NAN_BASE_URL") or "https://api.nan.builders/v1")
    key = os.environ.get("BARRA_VISION_API_KEY") or os.environ.get("NAN_API_KEY") or ""
    model = os.environ.get("BARRA_VISION_MODEL", "glm5.3-flash")
    return base, key, model


def stills_for(clip: Path, payload: dict, out_dir: Path) -> list[Path]:
    """Three stills across the working set when the geometry found reps,
    otherwise across the whole clip - so a misclassified/unrecognised clip still
    gets a nan label."""
    from barra.frames import grab_stills
    trim = payload.get("trim") or {}
    start_s = float(trim.get("startS") or 0.0)
    end_s = float(trim.get("endS") or 0.0)
    reps = [r for r in payload.get("reps") or [] if isinstance(r, dict)]
    if end_s > start_s and reps:
        t = end_s - start_s
        moments = [start_s + t * f for f in (0.1, 0.5, 0.9)]
    else:
        dur = float(payload.get("duration_s") or 0.0)
        if dur <= 0:
            return []
        moments = [dur * f for f in (0.15, 0.5, 0.85)]
    return grab_stills(clip, moments[:MAX_NAN_STILLS], out_dir, prefix="step")[:MAX_NAN_STILLS]


# The remote store for the per-clip evaluation row: "astra" (default when Astra
# is configured), "dynamodb" (legacy), or "local" (skip the remote row; the
# artifact dir on disk is still written). Selected by --store.
STORE = os.environ.get("EVAL_STORE", "").strip()


def _put_dynamodb(clip_key: str, item: dict):
    """The legacy DynamoDB row. Scalars stay strings; composite values become
    short JSON so the intermediate state is queryable without the artifact dir."""
    import boto3
    flat: dict = {}
    for k, v in item.items():
        if isinstance(v, (bool, int, float)) and v != "":
            flat[k] = {"S": str(v)}
        elif isinstance(v, str):
            if v:
                flat[k] = {"S": v}
        elif isinstance(v, (list, dict)):
            flat[k] = {"S": json.dumps(v, default=str)[:2500]}
    flat.setdefault("trick", {"S": item.get("trick", "")})
    boto3.client("dynamodb").put_item(
        TableName=EVAL_TABLE, Item={"clip": {"S": clip_key}, **flat})


def _put(clip_key: str, item: dict):
    """Route one evaluation row to the selected store.

    Astra is the primary store: the row is written as a single document (native
    JSON types, not DynamoDB-typed), keyed by a deterministic `_id` so a re-run
    of the same clip and pose backend never duplicates. Falls back to the local
    artifact dir when no remote store is configured or the write fails.
    """
    from barra.astra_store import AstraStore, configured as _astra_configured
    which = STORE or ("astra" if _astra_configured() else "local")
    backend = str(item.get("poseBackend") or "").strip()
    if which == "astra" and _astra_configured():
        base = item.get("traceId") or item.get("_id") or clip_key
        doc = {**item, "clip": clip_key,
               "evaluationId": f"{backend}:{base}" if backend else base}
        AstraStore().put_evaluation(doc)
        return
    if which in ("", "dynamodb"):
        try:
            _put_dynamodb(clip_key, item)
        except Exception as exc:  # noqa: BLE001 - remote write must not sink the run
            print(f"   ! dynamodb put failed: {exc}", flush=True)
        return


def _summarize(results: dict[str, dict]) -> dict:
    total = len(results)
    correct = sum(1 for r in results.values() if r.get("correct"))
    fusion_correct = sum(1 for r in results.values() if r.get("fusionCorrect"))
    model_correct = sum(1 for r in results.values() if r.get("modelCorrect"))
    nan_correct = sum(1 for r in results.values() if r.get("nanCorrect"))
    abstained = sum(1 for r in results.values()
                    if not r.get("correct") and not r.get("error")
                    and r.get("detected") in ("", "unknown"))
    misclassified = sum(1 for r in results.values()
                        if not r.get("correct") and not r.get("error")
                        and r.get("detected") not in ("", "unknown"))
    errors = sum(1 for r in results.values() if r.get("error"))
    nan_count = sum(1 for r in results.values() if r.get("nanOk"))
    nan_agree = sum(1 for r in results.values() if r.get("nanAgreesWithGeometry"))
    by_trick: dict[str, Counter] = {}
    for r in results.values():
        t = r.get("trick", "?")
        v = "correct" if r.get("correct") else (
            "error" if r.get("error") else ("abstained" if r.get("detected") in ("", "unknown")
                                            else "misclassified"))
        by_trick.setdefault(t, Counter())[v] += 1
    return {
        "total": total,
        "correct": correct,
        "fusionCorrect": fusion_correct,
        "modelCorrect": model_correct,
        "nanCorrect": nan_correct,
        "abstained": abstained,
        "misclassified": misclassified,
        "errors": errors,
        "accuracy": round(correct / total, 3) if total else None,
        "fusionAccuracy": round(fusion_correct / total, 3) if total else None,
        "modelAccuracy": round(model_correct / total, 3) if total else None,
        "nanReviewed": nan_count,
        "nanAgreesWithGeometry": nan_agree,
        "perTrick": {k: dict(v) for k, v in by_trick.items()},
    }


def run_one(clip: Path, trick: str, out_dir: Path, do_nan: bool,
            nan_cfg, model, meta: dict, backend: str = "ultralytics",
            cache_tag: str | None = None) -> dict:
    """One clip through the full pipeline. Returns the record, or a failure row."""
    record = {"trick": trick, "file": str(clip.relative_to(ROOT))}
    t_start = time.monotonic()
    # ---- 1. pose -----------------------------------------------------------
    try:
        info = probe_video(clip)
        probe_fps = float(info.get("fps") or 0.0) or 30.0
        pose = load_or_estimate(
            clip,
            order=[backend],
            write_cache=os.environ.get("BARRA_WRITE_POSE") == "1",
            fallback_fps=probe_fps,
            cache_tag=backend if cache_tag is None else cache_tag,
        )
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        record.update({"poseBackend": backend,
                       "error": f"pose: {type(exc).__name__}: {exc}",
                       "detected": "", "nanLabel": "", "correct": False})
        return record
    fps = float(getattr(pose, "fps", 0) or 0.0) or probe_fps
    record["poseBackend"] = backend
    record["poseSource"] = getattr(pose, "source", backend)
    record["poseFrames"] = int(len(pose.keypoints))

    # ---- 2. measure --------------------------------------------------------
    tr = Trace(new_id(clip.name), clip.name, source="pipeline-eval",
               clip=str(clip), exercise_requested="auto")
    try:
        payload = analyze_clip(clip, exercise="auto", session="eval",
                               trace=tr, pose=pose)
    except Exception as exc:  # noqa: BLE001
        record.update({"error": f"measure: {type(exc).__name__}: {exc}",
                       "detected": "", "nanLabel": "", "correct": False})
        return record
    payload["_traceId"] = tr.id
    payload["_runtimeS"] = {"eval": round(time.monotonic() - t_start, 2)}
    record["traceId"] = tr.id
    record["detected"] = (payload.get("detected") or {}).get("exercise") or ""
    record["label"] = (payload.get("detected") or {}).get("label") or record["detected"]
    record["nReps"] = payload.get("n_reps") or 0
    record["faults"] = payload.get("failures") or []
    record["score"] = payload.get("sessionScore")
    record["trim"] = payload.get("trim") or {}
    record["durationS"] = round(float(payload.get("duration_s") or 0), 2)
    record["variants"] = bool(payload.get("sessions") or [])

    # ---- 3. learned model ---------------------------------------------------
    feat = vector_from_dict(classify_features(pose.keypoints, fps))
    record["features"] = [None if not np.isfinite(x) else round(float(x), 4)
                          for x in feat]
    if model is not None and model.classes:
        mdl = model_classify(model, {f: v for f, v in zip(FEATURE_NAMES, feat)})
        ld = model_load(model, {f: v for f, v in zip(FEATURE_NAMES, feat)})
        record["modelClass"] = mdl["exercise"]
        record["modelConfidence"] = mdl["confidence"]
        record["modelMargin"] = mdl.get("marginToRunnerUp")
        record["modelVersion"] = model.version
        record["loadKg"] = ld["kg"]
        record["loadEstimated"] = ld["estimated"]
        record["modelCorrect"] = _alias_ok(record["modelClass"], trick)

    # ---- 4. write artifacts + trace ----------------------------------------
    clip_out = out_dir / tr.id
    clip_out.mkdir(parents=True, exist_ok=True)
    (clip_out / "payload.json").write_text(json.dumps(payload, indent=2, default=str))
    try:
        tr.write(clip_out / "trace.json")
    except Exception:  # noqa: BLE001
        pass
    (clip_out / "features.json").write_text(
        json.dumps({"features": [None if not np.isfinite(x) else round(float(x), 4)
                                 for x in feat]}))

    # ---- 5. nan multimodal label -------------------------------------------
    if do_nan and nan_cfg[1]:
        base_url, key, nmodel = nan_cfg
        stills = stills_for(clip, payload, clip_out / "stills")
        # also the framed technique stills, for a richer look when available
        technique_artifacts(clip, payload, out_dir, tr.id)
        nan = nan_label(stills, base_url, key, nmodel)
        record["nanLabel"] = nan.get("label", "")
        record["nanModel"] = nmodel
        record["nanNote"] = nan.get("note", "")
        record["nanOk"] = bool(nan.get("ok"))
        record["nStills"] = len(stills)
        record["nanCorrect"] = _alias_ok(record["nanLabel"], trick)
        # if the geometry recognised it, ask the technique pass whether it agrees
        if record["detected"] and nan.get("ok"):
            record["nanAgreesWithGeometry"] = _alias_ok(
                record["nanLabel"], record["detected"])

    fusion = fuse_detection(
        payload.get("detected") or {},
        (payload.get("model") or {}).get("classification"),
        record["nanLabel"] if record.get("nanOk") else None,
    )
    record["fusionLabel"] = fusion.get("exercise")
    record["fusionStatus"] = fusion.get("status")
    record["fusionReason"] = fusion.get("reason")
    record["fusionCorrect"] = _alias_ok(str(fusion.get("exercise") or ""), trick)

    # ---- 6. store ----------------------------------------------------------
    record["barra"] = meta.get("barra", "")
    record["commit"] = meta.get("commit", "")
    record["python"] = meta.get("python", "")
    record["modelVersion"] = record.get("modelVersion", "")
    record["runtimeS"] = round(time.monotonic() - t_start, 2)
    record["createdAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record["correct"] = _alias_ok(record["detected"], record["trick"])
    record["expected"] = record["trick"]
    try:
        _put(f"{record['trick']}/{clip.name}", record)
    except Exception as exc:  # noqa: BLE001
        print(f"   ! ddb put failed: {exc}", flush=True)
    put_trace(tr.as_dict() if hasattr(tr, "as_dict") else {},
              tr.id, job_id=record["trick"] + "/" + clip.name)
    return record


def provenance() -> dict:
    try:
        import barra  # noqa: F401
        from barra.provenance import stamp
        s = stamp()
        return {"barra": s.get("barra", ""), "commit": s.get("commit", ""),
                "python": s.get("python", "")}
    except Exception as exc:  # noqa: BLE001
        return {"barra": "", "commit": "", "python": str(exc)}


def build_corpus(tricks: str | None, per_trick: int | None,
                 clips: list[str] | None, cached_only: bool = False) -> list[tuple[Path, str]]:
    if clips:
        return [(Path(c).resolve(), c.split("/")[-2]) for c in clips]
    want = {t.strip() for t in (tricks or "").split(",") if t.strip()} or None
    rows: list[tuple[Path, str]] = []
    by_class: dict[str, list[Path]] = {}
    if METADATA.exists():
        with METADATA.open() as f:
            for r in csv.DictReader(f):
                trick = r.get("trick", "")
                if want and trick not in want:
                    continue
                p = METADATA.parent / r.get("file", "")
                if p.exists():
                    by_class.setdefault(trick, []).append(p)
    for trick, paths in by_class.items():
        if cached_only:
            paths = [p for p in paths if cache_path(p).exists()]
        if per_trick:
            paths = paths[:per_trick]
        for p in paths:
            rows.append((p.resolve(), trick))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tricks", default="")
    ap.add_argument("--per-trick", type=int, default=0)
    ap.add_argument("--clips", nargs="*")
    ap.add_argument("--no-nan", action="store_true")
    ap.add_argument("--cached-only", action="store_true",
                    help="evaluate only clips whose keypoints are already cached")
    ap.add_argument("--pose-backend", default="",
                    help="pose backend for the run; defaults to BARRA_POSE_BACKEND "
                         "or ultralytics")
    ap.add_argument("--backends", default="",
                    help="comma-separated pose backends to sweep; when set, each "
                        "backend gets its own artifact/report slice")
    ap.add_argument("--store", choices=("astra", "dynamodb", "local"), default="",
                    help="where the per-clip eval row is written; 'astra' is the "
                         "primary store, 'dynamodb' the legacy path, 'local' skips "
                         "the remote row. Default: astra when configured, else local.")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--report", type=Path, default=OUT / "report.json")
    args = ap.parse_args(argv)

    global STORE
    if args.store:
        STORE = args.store.lower()

    default_backend = (args.pose_backend or os.environ.get("BARRA_POSE_BACKEND", "")
                       or "ultralytics").strip()
    backends = ([b.strip() for b in args.backends.split(",") if b.strip()]
                if args.backends else [default_backend])
    corpus = build_corpus(args.tricks, args.per_trick or None, args.clips,
                          cached_only=args.cached_only)
    if not corpus:
        print("no clips to evaluate", file=sys.stderr)
        return 2
    nan_cfg = _nan_config() if not args.no_nan else ("", "", "")
    model = load_default()
    meta = provenance()

    all_results: dict[str, dict] = {}
    backend_reports: dict[str, dict] = {}
    for backend in backends:
        out_dir = args.out if len(backends) == 1 else args.out / _slug(backend)
        results: dict[str, dict] = {}
        for i, (clip, trick) in enumerate(corpus, 1):
            print(f"[{backend} {i}/{len(corpus)}] {clip.relative_to(ROOT)} ...", flush=True)
            rec = run_one(clip, trick, out_dir, not args.no_nan, nan_cfg, model,
                          meta, backend=backend,
                          cache_tag=("" if len(backends) == 1 else backend))
            results[f"{trick}/{clip.name}"] = rec
            err = rec.get("error", "")
            print(f"   expected={trick:22s} detected={rec.get('detected',''):22s} "
                  f"model={rec.get('modelClass',''):16s} "
                  f"fusion={rec.get('fusionLabel',''):16s} "
                  f"nan={rec.get('nanLabel','')[:24]!r}"
                  f"{'  ERR ' + err[:40] if err else ''}", flush=True)

        summary = _summarize(results)
        backend_reports[backend] = summary
        args.report.parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
        if len(backends) == 1:
            report = {"backend": backend, "program": meta, **summary}
            args.report.write_text(json.dumps(report, indent=2, default=str))
            print(f"   report -> {args.report}")
        print(f"\n== {backend} {summary['total']} clips | geometry {summary['correct']} | "
              f"fusion {summary['fusionCorrect']} | model {summary['modelCorrect']} | "
              f"abstained {summary['abstained']} | errors {summary['errors']}")

    all_results = {b: r for b, r in backend_reports.items()}
    combined = {
        "backends": backends,
        "program": meta,
        "perBackend": all_results,
        "selected": max(all_results.values(), key=lambda s: (s.get("fusionCorrect", 0),
                                                             s.get("correct", 0)))
        if all_results else {},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(combined, indent=2, default=str))
    print(f"   combined report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
