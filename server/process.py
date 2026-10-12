"""Run barra on one clip and return the JSON the phone renders."""
from __future__ import annotations

import math
import os
import sys
from datetime import date

import numpy as np
from pathlib import Path

from barra import sentinel
from barra.i18n import localize_payload
from report import fallback_report, write_prose
from vision import technique_note, technique_second_opinion, count_from_clip

try:
    import llm
except ImportError:  # tests / local dev with `server/` on the path
    from api import llm

from barra.evidence import declared_view, estimate_view, rep_evidence
from barra.faults_taxonomy import classify_faults
from barra.holds import clip_failures, hold_attempts
from barra.recommend import recommend_for_payload
from barra.rules import (ASSESSMENT_VERSION, OBSERVED, assess,
                         normalise_variant, summarise)

from barra.frames import technique_artifacts
from barra.tracestore import put_trace

# This file lives at <repo>/server/process.py, so the repo is two parents up.
# It used to default to an absolute path from one developer's laptop, which
# meant that everywhere else the server wrote its traces to a directory the CLI
# does not read - `barra explain --replay <id>` could not find a single trace
# the server had written, which is the one thing that command exists to do.
# Code that can work out where it lives should not be guessing.
BARRA_ROOT = Path(os.environ.get("BARRA_ROOT") or Path(__file__).resolve().parent.parent)
if str(BARRA_ROOT) not in sys.path:
    sys.path.insert(0, str(BARRA_ROOT))

_METRIC_ORDER = [
    "transition_s",
    "concentric_s",
    "eccentric_s",
    "total_s",
    "tempo_ratio",
    "top_hold_s",
    "rom",
    "peak_height",
    "start_depth",
    "shoulder_asymmetry",
    "turn_asymmetry",
    "swing",
]


def _trace(signal, start: int, end: int, n: int = 48) -> list[float]:
    """A small, evenly-sampled copy of the rep's own trace, for the phone to
    draw. Downsampled here rather than on the device: the shape is the point,
    and 48 points carry it at any size a phone will draw it."""
    try:
        import numpy as np
    except ImportError:
        return []
    seg = np.asarray(signal[start:end + 1], dtype=float)
    if seg.size < 4:
        return []
    xs = np.linspace(0, seg.size - 1, n)
    ys = np.interp(xs, np.arange(seg.size), seg)
    return [round(float(v), 4) for v in ys]


def _num(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(x):
        return ""
    return f"{x:.2f}"


def process_job(job: dict, video_path: Path, on_stage=None, pose=None) -> dict:
    """Measure one clip, then add the vision pass: the payload the phone renders.

    The two halves are `measure_job` and `add_vision`; the worker calls them
    separately so the measurement reaches the phone without waiting for the
    vision models (see tests/test_fast_result.py). Local tools call this.
    """
    report = measure_job(job, video_path, on_stage=on_stage, pose=pose,
                         vision_label=job.get("visionLabel"))
    return add_vision(job, video_path, report)


# The trace of a measured job, kept until its vision pass appends to it. Per
# container: a worker instance runs one job at a time.
_TRACES: dict[str, object] = {}


def _resolve_vote(vote):
    """The vision vote for fusion: a label, or a callable that produces one
    (the worker's localization, running alongside pose). A vote that fails is
    no vote - localization never fails a job."""
    if not callable(vote):
        return vote
    try:
        return vote()
    except Exception:  # noqa: BLE001
        return None


def _vision_configured() -> bool:
    try:
        from vision import _config
        return _config() is not None
    except Exception:  # noqa: BLE001
        return False


def _stager(on_stage):
    def _stage(name: str) -> None:
        """A named heartbeat for the phone: the work list shows where the clip
        actually is, instead of a single undifferentiated 'processing'."""
        if on_stage is None:
            return
        try:
            on_stage(name)
        except Exception:  # noqa: BLE001 - a heartbeat never fails a job
            pass
    return _stage


def _finish(trace, report: dict, job: dict, requested: str) -> dict:
    """Spanish, sentinel-checked, traced: what is written for the phone."""
    if trace is None:
        return localize_payload(report)
    report["traceId"] = trace.id
    report["provenance"] = _provenance()
    trace.stage("payload")
    report = localize_payload(report)
    sentinel.watch(trace, "payload", {"payload": report},
                   inputs={"job": job.get("id"), "requested": requested})
    if isinstance(report["provenance"], dict):
        report["provenance"]["poseBackendUsed"] = report.get("poseBackend")
    _write_trace(trace, str(job.get("id") or ""))
    return report


def measure_job(job: dict, video_path: Path, on_stage=None, pose=None,
                vision_label=None) -> dict:
    """The measurement and its report - everything the phone needs except the
    advisory vision note, which `add_vision` adds afterwards.

    `on_stage`, when given, receives a short human phrase at each step that
    can take time, for the phone's work list. `pose`, when given, is supplied to
    `analyze_clip` unchanged; the debugging tool uses it to reuse the keypoint
    cache while still running the production post-analysis path.
    `vision_label` is the vision model's name for the movement, or a callable
    that returns it when fusion asks (the worker locates in parallel).

    `exercise` may be omitted or "auto": the clip is then classified from its
    own geometry rather than from what the athlete remembered to tap.

    Every job carries a trace id. It goes into the payload, so the phone can
    show it; into a JSON trace, so the decision chain can be replayed with
    `barra explain --replay <id>`; and into the log line, so a user report
    maps to a specific run of a specific build.
    """
    _stage = _stager(on_stage)
    _stage("opening the clip")
    requested = (job.get("exercise") or "auto").strip() or "auto"
    trace = _new_trace(job, video_path, requested)
    def _visual_count():
        from pathlib import Path as _P
        root = _P(os.environ.get("BARRA_TRACE_DIR", str(BARRA_ROOT / "out" / "traces")))
        return count_from_clip(video_path, root / str(job.get("id") or "vision"))

    metrics = analyze_clip(video_path, requested, session=job.get("session"),
                           trace=trace, on_stage=_stage,
                           visual_count=_visual_count,
                           declared_bin=job.get("view"),
                           variant=job.get("variant"),
                           pose=pose,
                           vision_label=vision_label)
    # The model prose is OFF the critical path (docs/SPEED-PLAN.md B): the
    # result reaches the phone with the deterministic Spanish text and
    # `proseStatus: "pending"`, and `finish_prose` upgrades it afterwards,
    # exactly like `add_vision` does for the vision note. The prose model
    # owns exactly three keys; everything else the UI draws - the detected
    # movement, the trim window, per-rep scores and traces - is carried
    # through untouched from `metrics` below.
    pending = llm.config() is not None
    report = {**fallback_report(metrics),
              "proseStatus": "pending" if pending else "done",
              "proseSource": "fallback"}
    if not pending:
        report["proseRejected"] = "not_configured"
    # Inverted on purpose: an allow-list of measurement keys has to be updated
    # every time one is added, and the failure mode is a field that silently
    # never reaches the phone. A deny-list of the three prose keys cannot drift.
    prose = {"headline", "narrative", "nextSession"}
    for key, value in metrics.items():
        if key not in prose:
            report[key] = value
    report["visionStatus"] = "pending" if _vision_configured() else "skipped"

    report = _finish(trace, report, job, requested)
    if trace is not None:
        _TRACES[trace.id] = (trace, requested)
        print(f"[barra] job={job.get('id')} trace={trace.id} "
              f"exercise={report.get('exercise')} reps={report.get('n_reps')} "
              f"score={report.get('sessionScore')} "
              f"rejections={len(trace.rejections)} errors={len(trace.errors)}",
              flush=True)
    return report


def add_vision(job: dict, video_path: Path, report: dict) -> dict:
    """The advisory vision pass on a measured payload: technique note and
    second opinion. Never changes the movement, the count or a score, and
    never leaves `visionStatus` pending: done, skipped or failed."""
    report = dict(report)
    trace, requested = _TRACES.pop(str(report.get("traceId") or ""), (None, "auto"))
    if report.get("visionStatus") == "skipped":
        return report
    try:
        # The raw take is not the technique. Cut the working set out of the clip
        # and still every rep's turning point, then let a vision model study
        # those artifacts and say what the geometry missed.
        artifacts_root = Path(os.environ.get(
            "BARRA_TRACE_DIR", str(BARRA_ROOT / "out" / "traces")))
        artifacts = technique_artifacts(video_path, report, artifacts_root,
                                        str(report.get("traceId") or job.get("id") or "job"))
        if trace is not None:
            trace.stage("vision")
            if artifacts.clip or artifacts.stills:
                # The selected timestamps, reps and phases, so the request the
                # model saw can be rebuilt from the trace.
                trace.step("technique artifacts", **artifacts.as_trace_data())
        # The vision model is handed the measured report - movement, variant,
        # boundaries, per-rep checks and what could not be checked - not just
        # the pictures. Its observations come back validated against that
        # report and are kept as advisory, separately sourced rows.
        # The note and the second opinion are independent calls (124 s and
        # 21 s measured on 2026-10-11): run them at the same time. A second
        # opinion is only kept beside a note, as before.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            note_f = pool.submit(technique_note, artifacts, report)
            second_f = pool.submit(technique_second_opinion, artifacts)
            note = note_f.result()
            try:
                second = second_f.result()
            except Exception:  # noqa: BLE001 - a second opinion never sinks the note
                second = None
        if note is not None:
            # The report owns headline/narrative/nextSession; the vision
            # model's own prose is kept beside it, never over it (a real job's
            # headline became the model's paragraph about stills on 2026-10-11).
            prose_keys = ("headline", "narrative", "nextSession")
            report["visionNote"] = {k: note[k] for k in prose_keys if note.get(k)}
            report.update({k: v for k, v in note.items() if k not in prose_keys})
            if trace is not None:
                trace.step("vision observations",
                           kept=len(note.get("visionObservations") or []),
                           validation=note.get("visionValidation"),
                           movement=note.get("visionMovement"))
                if (note.get("visionMovement") or {}).get("review"):
                    trace.note("vision disagrees with the geometric movement label",
                               geometry=report.get("exercise"),
                               vision=note["visionMovement"].get("label"))
            # Key moment 2, second opinion: the same stills, a different
            # model, one word. A disagreement is worth more than either.
            if second is not None:
                report["visionVerdict"] = second
                if trace is not None:
                    trace.step("vision second opinion", verdict=second)
            report["visionStatus"] = "done"
        else:
            if trace is not None and artifacts.stills:
                from vision import skip_reason
                trace.step("vision pass skipped", reason=skip_reason())
            report["visionStatus"] = "skipped"
    except Exception as exc:  # noqa: BLE001 - advisory: the measurement stands
        report["visionStatus"] = "failed"
        if trace is not None:
            trace.error("vision pass failed", reason=str(exc)[:200])
    return _finish(trace, report, job, requested)


def finish_prose(job: dict, report: dict) -> dict:
    """The model prose, after the result (docs/SPEED-PLAN.md B): the sibling
    of `add_vision`, off the critical path. Asks the report model for the
    three prose keys, judges the reply by the same rules `write_report`
    applies, and only then replaces the fallback text. Whatever happens, the
    headline is never left empty, and `proseStatus` never stays pending:
    done, failed or fallback. Everything else in the payload is untouched.
    """
    report = dict(report)
    trace, requested = _TRACES.get(str(report.get("traceId") or ""), (None, "auto"))
    if report.get("proseStatus") != "pending":
        return report
    # What the model is offered: the measured payload, without the prose keys
    # it would echo and the statuses it must not see. `digest` picks what it
    # actually uses, exactly as `write_report` did from `metrics`.
    prose_keys = {"headline", "narrative", "nextSession", "proseStatus",
                  "proseSource", "proseRejected"}
    metrics = {k: v for k, v in report.items() if k not in prose_keys}
    try:
        out = write_prose(metrics)
        if out["status"] == "done":
            # Only the three prose keys move; a measured number cannot change
            # here because the judgement rejects prose with invented numbers.
            report.update(out["prose"])
            report["proseSource"] = out["source"]
            report["proseStatus"] = "done"
            report.pop("proseRejected", None)
        elif out["status"] == "fallback":
            # The fallback text already stands; record why the model's did not.
            report["proseSource"] = "fallback"
            report["proseStatus"] = "fallback"
            report["proseRejected"] = out["reason"]
        else:
            report["proseSource"] = "fallback"
            report["proseStatus"] = "failed"
            report["proseRejected"] = out["reason"]
        if trace is not None:
            trace.stage("prose")
            trace.step("model prose",
                       status=report["proseStatus"], source=report["proseSource"],
                       rejected=report.get("proseRejected"))
            # The same payload contract the measurement ran: Spanish prose,
            # no invented numbers, nothing missing.
            sentinel.watch(trace, "payload", {"payload": report},
                           inputs={"job": job.get("id"), "requested": requested})
            _write_trace(trace, str(job.get("id") or ""))
    except Exception as exc:  # noqa: BLE001 - advisory: the fallback stands
        report["proseSource"] = "fallback"
        report["proseStatus"] = "failed"
        report["proseRejected"] = str(exc)[:200]
        if trace is not None:
            trace.error("prose pass failed", reason=str(exc)[:200])
    return report


def _new_trace(job: dict, video_path: Path, requested: str):
    try:
        from barra.trace import Trace, new_id
    except ImportError:
        return None
    t = Trace(
        new_id(str(job.get("id", ""))),
        video_path.name,
        jobId=str(job.get("id", "")),
        exercise_requested=requested,
        session=job.get("session"),
        bytes=video_path.stat().st_size if video_path.exists() else 0,
    )
    t.stage("job")
    t.step("provenance", **_provenance())
    return t


def _provenance() -> dict:
    try:
        from barra.provenance import stamp

        return stamp()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"provenance unavailable: {exc}"}


def _write_trace(trace, job_id: str = "") -> None:
    """Traces live under BARRA_TRACE_DIR, or out/traces beside the code - and,
    when TRACES_TABLE is set, in DynamoDB, one row per video analysis, so the
    decision chain survives the worker's ephemeral disk.

    Failing to write one must never fail the job: a debugging aid that can take
    down a measurement is worse than no debugging aid.
    """
    try:
        root = Path(os.environ.get("BARRA_TRACE_DIR", str(BARRA_ROOT / "out" / "traces")))
        trace.write(root / f"{trace.id}.json")
    except Exception as exc:  # noqa: BLE001
        print(f"[barra] could not write trace {trace.id}: {exc}", flush=True)
    try:
        store = put_trace(trace.as_dict(), trace.id, job_id)
        if store:
            print(f"[barra] trace {trace.id} stored in {store}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[barra] could not store trace {trace.id}: {exc}", flush=True)


def _measure_hold(pose, fps: float, movement, session: str | None,
                  detected: dict, tr, _stage, variant: dict | None = None) -> dict:
    """One clip of a lever or planche: measure the hold, not the reps.

    A hold is measured as one observation per attempt - sustain time, body
    line, and the failure types it shows. There is no 0-100 score; a hold's
    quality is its body line and its failures.
    """
    from barra.holds import clip_failures, hold_attempts

    variant = variant or normalise_variant(movement.name, None)
    _stage("measuring the hold")
    reps = hold_attempts(pose.keypoints, fps, movement, trace=tr,
                         variant=variant["name"])
    failures = clip_failures(reps)
    duration_s = round(len(pose.keypoints) / max(fps, 1.0), 2)

    trim = None
    if reps:
        pad = 0.6
        trim = {
            "startS": max(0.0, round(reps[0]["startS"] - pad, 2)),
            "endS": round(min(duration_s, reps[-1]["endS"] + pad), 2),
        }

    from barra.holds import hold_assessments
    from barra.fault_select import primary_from_assessments
    hold_rows = hold_assessments(reps)
    primary = primary_from_assessments(hold_rows, movement=movement.name)
    from barra.fault_select import top_fixes
    fixes = top_fixes(hold_rows, movement.name)
    rec = recommend_for_payload({"track": movement.name, "failures": failures})
    if primary and primary.get("name"):
        rec = recommend_for_payload({
            "track": movement.name,
            "failures": [primary["name"]] + [
                n for n in (failures or {}) if n != primary["name"]
            ],
        })
    checks = summarise(hold_rows)
    return {
        "exercise": movement.name,
        "track": movement.name,
        "detected": detected,
        "variant": variant,
        "failures": failures,
        "primaryFault": primary,
        # The three things to improve, most important first (docs/UX-PLAN.md).
        "topFixes": fixes,
        "recommendation": rec,
        "n_reps": len(reps),
        "n_candidates": len(reps),
        "reps": reps,
        "rescued": False,
        "countedBy": None,
        "consistency": None,
        "blockers": [],
        "fps": round(float(fps), 3),
        "duration_s": duration_s,
        "trim": trim,
        "session": session or date.today().isoformat(),
        "sessionScore": None,
        "sessionBand": "unmeasured",
        "measurementVersion": ASSESSMENT_VERSION,
        "assessment": checks,
        "sessions": [{"date": session or date.today().isoformat(),
                      "reps": len(reps), "note": "hold"}],
        "nextSession": (
            "Tres o cuatro mantenimientos, una serie, el móvil fijo en un punto "
            "marcado, siempre desde el mismo lado y con todo el cuerpo en el encuadre."
        ),
    }


def _unsupported(chosen: str, detected: dict | None) -> dict:
    """A movement the classifier can name but the pipeline has no profile
    for. The blocker is a catalog code (barra/i18n.py renders it in Spanish);
    the raw SystemExit - a developer's list of known movements - never reaches
    the phone."""
    return _empty(chosen, [f"movement_unsupported:{chosen}"], detected=detected)


def _empty(exercise: str, blockers: list[str], **extra) -> dict:
    """A result the app can render when nothing could be measured.

    Every key the success path returns is present, because a client that has to
    ask whether a field exists ends up guessing what its absence means. A clip
    that produced nothing is a complete answer, not a partial one.
    """
    base = {
        "exercise": exercise,
        "detected": None,
        "variant": {"name": "unspecified", "source": "none"},
        "n_reps": 0,
        "n_candidates": 0,
        "fps": 0.0,
        "duration_s": 0.0,
        "trim": None,
        "session": date.today().isoformat(),
        "sessionScore": None,
        "sessionBand": "unmeasured",
        "measurementVersion": ASSESSMENT_VERSION,
        # No rep, so no check was made. An empty list under `checks` is the
        # statement that nothing was assessed, not that everything passed.
        "assessment": {"version": ASSESSMENT_VERSION, "checks": []},
        "topFixes": [],
        "sessions": [],
        "reps": [],
        "blockers": blockers,
    }
    base.update(extra)
    return base


def analyze_clip(video_path: Path, exercise: str = "auto",
                 session: str | None = None, trace=None, on_stage=None,
                 visual_count=None, pose=None,
                 declared_bin: str | None = None,
                 variant: str | None = None,
                 vision_label: str | None = None) -> dict:
    """Measure one clip. `on_stage`, when given, is called with a short human
    phrase at each step that can take real time, so a waiting phone can say
    where the work is. `visual_count`, when given, is the last resort for a
    count: a callable(list[Path]) -> int | None, asked only when every
    geometric pass found nothing. `pose`, when given, is keypoints already
    estimated for this clip (anything with `.keypoints` and `.fps`) and the
    backend loop is skipped - that is how the debug tool reuses the cache in
    barra/posecache.py instead of paying 78 seconds for a second opinion on
    frames that have not changed. `declared_bin` is the viewpoint the session
    row states (SAGITTAL / OBLIQUE / FRONTAL); given one, the planar faults
    trust it instead of the single-clip estimator. `variant` is the technique
    variant the athlete DECLARED (strict / kipping, full / tuck / straddle);
    it is never inferred from a posture, and rules written for a different
    standard are left out rather than fired. `vision_label` is an independent
    multimodal name for the movement (typically from locate_exercise); when
    auto-detecting it is the third vote in fuse_detection."""
    def _stage(name: str) -> None:
        if on_stage is None:
            return
        try:
            on_stage(name)
        except Exception:  # noqa: BLE001
            pass

    from barra.trace import NullTrace

    tr = trace if trace is not None else NullTrace()
    tr.stage("probe")
    if not video_path.exists() or video_path.stat().st_size == 0:
        tr.error("no video arrived at the server", path=str(video_path))
        return _empty(exercise, ["No video arrived at the server."])

    try:
        from barra.classify import HUMAN, classify
        from barra.ingest import _clean_signal, probe_video, segment_reps_verbose
        from barra.metrics import (METRIC_SPEC, MIN_REP_QUALITY, arm_reach,
                                   rep_metrics)
        from barra.movements import resolve, tracking_signal
        from barra.pose import available_backends, get_backend
        from barra.quality import band as qband
        from barra.quality import score_rep
    except ImportError as exc:
        return _empty(exercise, [
            f"barra is not importable on this host ({exc}). "
            "Use server/.venv (pip install -e ../barrapp[mediapipe])."
        ])

    if pose is not None:
        # Keypoints supplied by the caller. The trace records where they came
        # from: a run whose pose is implicit cannot answer "which model made
        # these numbers", which is the one question a replay must answer.
        tr.step("pose supplied by the caller",
                source=getattr(pose, "source", "caller"),
                frames=int(len(pose.keypoints)))

    backends = available_backends()
    if not backends and pose is None:
        return _empty(exercise, [
            "No pose backend installed. In server/.venv run: "
            "pip install -e ../barrapp[mediapipe]"
        ])

    # A backend can fail in ways this process cannot survive (a native library
    # that takes the interpreter down with it), so the order is decided BEFORE
    # the first frame: BARRA_POSE_BACKEND pins one, and the rest are tried in
    # registry order if the first estimate raises.
    requested = os.environ.get("BARRA_POSE_BACKEND", "").strip()
    if requested and pose is None:
        if requested not in backends:
            return _empty(exercise, [
                f"pose backend {requested!r} is not installed; have: {', '.join(backends)}"
            ])
        order = [requested] + [b for b in backends if b != requested]
    else:
        order = backends

    _stage("estimating the pose")
    info = probe_video(video_path)
    tr.step("container", **{k: v for k, v in info.items() if k != "ok"})
    sentinel.watch(tr, "probe", {"info": info},
                   inputs={"clip": video_path.name, "bytes": video_path.stat().st_size})
    if not info.get("ok"):
        tr.error("could not open the clip", reason=info.get("reason"))
        return _empty(exercise,
                      [f"Could not open the clip: {info.get('reason', 'unknown')}"])

    os.environ.setdefault("BARRA_POSE_MODEL", str(BARRA_ROOT / "models" / "pose_landmarker_heavy.task"))
    pose_error = None
    pose_backend = getattr(pose, "source", "caller") if pose is not None else None
    if pose is None:
        for name in order:
            try:
                pose = get_backend(name).estimate(video_path)
                pose_backend = name
                tr.step("pose backend", backend=name)
                break
            except Exception as exc:  # noqa: BLE001 - the next backend may still work
                pose_error = exc
                tr.reject("pose backend failed", backend=name, reason=str(exc)[:200])
    if pose is None:
        reason = str(pose_error) if pose_error else "unknown"
        return _empty(exercise, [f"Pose estimation failed: {reason}"])
    fps = pose.fps or info["fps"] or 30.0
    # A caller building a feature corpus may want the just-estimated keypoints
    # kept without running the whole pipeline twice. BARRA_WRITE_POSE=1 caches
    # them (barra/posecache.store writes the same schema `barra ingest` reads),
    # so a second pass can featurize them offline - and a POSED-but-unmeasured
    # clip contributes its keypoints to the model's training set even when the
    # geometric pass declined to count a rep.
    if os.environ.get("BARRA_WRITE_POSE") == "1":
        try:
            from pathlib import Path as _Path
            from barra.posecache import store as _store_pose
            weights = getattr(pose, "weights", None)
            tag = pose_backend or "pose"
            if weights:
                tag = f"{tag}:{_Path(str(weights)).name}"
            _store_pose(video_path, pose.keypoints, tag=tag)
        except Exception as _cue:  # noqa: BLE001 - caching must never fail the analysis
            tr.step("pose cache write skipped", reason=str(_cue))

    # Detect the movement from the clip itself. A movement the athlete named is
    # respected, but the detection still runs so the phone can say when the two
    # disagree - measuring a muscle-up with squat geometry produces numbers that
    # look fine and mean nothing.
    tr.step("keypoints", frames=int(len(pose.keypoints)), fps=float(fps),
            backend=pose_backend)
    sentinel.watch(tr, "pose", {"keypoints": pose.keypoints},
                   inputs={"backend": pose_backend, "fps": float(fps)}, fps=fps)
    _stage("recognising the movement")
    detection = classify(pose.keypoints, tr, fps=fps)
    detected = {
        "exercise": detection.exercise,
        "label": HUMAN.get(detection.exercise, detection.exercise),
        "confidence": round(float(detection.confidence), 2),
        # What that number is. It is a bounded distance from the measurement
        # that decided the label to the threshold it was compared against, not
        # a probability, and the phone renders it as one or the other on the
        # strength of this field rather than on a guess about the pipeline.
        "certainty": detection.certainty,
        "reason": detection.reason,
        "runnerUp": detection.runner_up,
    }
    sentinel.watch(tr, "detection", {"detected": detected},
                   inputs={"frames": int(len(pose.keypoints))})
    # The first learned model runs alongside the geometric classifier. It is a
    # second opinion, never a replacement: `detected` stays the interpretable,
    # verified answer, and `model` says what the model thinks and - with the
    # load estimate - what it thinks the athlete is carrying. When no trained
    # model is present (or it has no classes) this is null, and the phone says
    # nothing rather than improvise.
    model_out = None
    tr.stage("model")
    try:
        from barra.model import load_default, model_classify, model_load
        _model = load_default()
        if _model is not None and _model.classes:
            _feat = dict(getattr(detection, "features", None) or {})
            # The geometric detector's own feature dict is the narrow vector
            # its thresholds need. A model trained on the wider kinematic set
            # asks for names that dict has never held, and every one of them
            # arrives as the not-a-number sentinel - a model answering from a
            # third of its inputs, confidently, with nothing raising. So when
            # the loaded model wants more than the detector computed, compute
            # the rest from the same keypoints it already has.
            if any(n not in _feat for n in _model.feature_names):
                from barra.kinematics import full_features
                _feat = {**full_features(pose.keypoints, fps), **_feat}
            model_out = {
                "classification": model_classify(_model, _feat),
                "load": model_load(_model, _feat),
            }
    except Exception:  # noqa: BLE001 - a model failure must not sink the analysis
        model_out = None
    chosen = exercise
    if exercise in ("", "auto", None):
        fusion = None
        tr.stage("fusion")
        try:
            from barra.fusion import fuse_detection
            # locate_exercise already paid for a multimodal read of the clip;
            # reuse that name as the vision vote rather than making geometry
            # and the tiny pose model decide alone (0.556 → 0.817 measured).
            # A callable vote is the worker's localization, started alongside
            # pose; it is waited for here, where it is needed.
            vision_label = _resolve_vote(vision_label)
            fusion = fuse_detection(
                detected,
                (model_out or {}).get("classification"),
                nan_label=vision_label,
            )
            tr.step("fusion", **fusion)
            sentinel.watch(tr, "fusion", {"fusion": fusion},
                           inputs={"geometry": detected.get("exercise"),
                                   "model": ((model_out or {}).get("classification") or {}).get("exercise"),
                                   "vision": vision_label})
        except Exception as exc:  # noqa: BLE001 - fusion is an improvement, not a requirement
            tr.error("could not fuse detector votes", reason=str(exc)[:200])
        detected["fusion"] = fusion
        final = (fusion or {}).get("exercise") or detection.exercise
        if final == "unknown":
            return _empty("auto", [detection.reason], detected=detected,
                          duration_s=round(float(info.get("duration_s") or 0), 2))
        chosen = final
        if chosen != detection.exercise:
            detected["exercise"] = chosen
            detected["label"] = HUMAN.get(chosen, chosen)
            detected["reason"] = (fusion or {}).get("reason") or detected["reason"]
            detected["certainty"] = "detector-fusion"
            detected["runnerUp"] = detection.exercise if detection.exercise != "unknown" else detected.get("runnerUp")

    try:
        movement = resolve(chosen)
    except SystemExit:
        return _unsupported(chosen, detected)

    # The declared variant, labelled as declared - or unspecified. A variant
    # the movement does not define is not accepted, so a typo cannot switch
    # on the fault taxonomy of a different standard.
    variant_info = normalise_variant(movement.name, variant)
    tr.step("variant", **variant_info)

    # A front lever or planche is a hold, not a set of repetitions. The rep
    # segmenter counts turnarounds and would find nothing; measure the hold
    # instead - sustain time, body line, and the failure types it shows.
    if movement.is_hold:
        return _measure_hold(pose, fps, movement, session, detected, tr, _stage,
                             variant=variant_info)

    _stage("finding the reps")
    found, reasons = segment_reps_verbose(pose.keypoints, fps, movement, trace=tr)
    sentinel.watch(tr, "segments", {"found": found, "blockers": reasons},
                   subject=found, n_frames=int(len(pose.keypoints)),
                   inputs={"movement": movement.name, "fps": float(fps)})
    rescued = False
    if not found:
        from barra.ingest import rescue_reps
        _stage("trying the relaxed pass")
        found, rescue_note = rescue_reps(pose.keypoints, fps, movement, trace=tr)
        if found:
            rescued = True
            reasons = [
                f"the standard pass found nothing ({'; '.join(reasons[:2])}) — {rescue_note}"
            ]
            tr.note("rescue pass produced the count", standard_blockers=reasons)

    # The last resort for a count: when every geometric pass found nothing,
    # ask the configured vision models to count from stills of the clip. A
    # count from watching is weaker than one from measurement, and the report
    # says so - but it is an answer, where before there was only a blocker.
    # `visual_count` cuts its own stills, so barra stays free of server paths.
    vision_count = None
    if not found and visual_count is not None and detected.get("exercise") not in (
            None, "", "unknown"):
        _stage("counting from the frames")
        try:
            vision_count = visual_count()
        except Exception as exc:  # noqa: BLE001 - a fallback never fails a job
            tr.error("the vision count fell over", reason=str(exc)[:200])
            vision_count = None
        # A disagreement between the two models is a result, not a lower
        # bound: it is recorded, and no count is claimed from it.
        if vision_count is not None and (not vision_count.get("usable", True)
                                         or vision_count.get("reps") is None):
            tr.reject("vision count", vision_count.get("agreement", "unusable"),
                      models=vision_count.get("models"),
                      range=vision_count.get("range"))
            vision_count = None
        if vision_count is not None:
            tr.decision("vision count", "used the models' count",
                        reps=int(vision_count["reps"]),
                        range=vision_count.get("range"),
                        models=vision_count["models"])

    session = session or date.today().isoformat()
    raw_signal, sig_conf = tracking_signal(pose.keypoints, movement)
    signal, _valid = _clean_signal(raw_signal, sig_conf)
    arm = arm_reach(pose.keypoints)
    reps = []
    usable = 0
    extra_blockers: list[str] = []
    scores: list[int] = []
    # The joints, as timesteps: the tracked signal plus the wrist and hip
    # positions frame by frame, downsampled to a size a trace row can hold.
    # This is the raw evidence every later pass - a better segmenter, a vision
    # model, a replay - would need, stored beside the decisions that used it.
    def _series(idx_a: int, idx_b: int) -> dict:
        xa = pose.keypoints[:, idx_a, 0] + pose.keypoints[:, idx_b, 0]
        ya = pose.keypoints[:, idx_a, 1] + pose.keypoints[:, idx_b, 1]
        va = pose.keypoints[:, idx_a, 2] * pose.keypoints[:, idx_b, 2]
        step = max(1, len(xa) // 240)
        return {
            "t": [round(i / fps, 3) for i in range(0, len(xa), step)],
            "x": [round(float(v) / 2, 4) for v in xa[::step]],
            "y": [round(float(v) / 2, 4) for v in ya[::step]],
            "vis": [round(float(v), 3) for v in va[::step]],
        }

    try:
        coco = {"wrist_a": 9, "wrist_b": 10, "hip_a": 11, "hip_b": 12}
        tr.step("keypoint timesteps",
                fps=round(float(fps), 3),
                signal=[round(float(v), 4) for v in signal[::max(1, len(signal) // 240)]],
                wrist=_series(coco["wrist_a"], coco["wrist_b"]),
                hip=_series(coco["hip_a"], coco["hip_b"]))
    except Exception as exc:  # noqa: BLE001 - evidence must not fail the job
        tr.error("could not record the keypoint timesteps", reason=str(exc)[:200])

    # Where the camera stood, and whether that is knowable at all. Faults that
    # only exist in one plane - knee valgus is frontal, a sagging hip line
    # sagittal - are not fired from a viewpoint the estimator cannot pin down:
    # docs/FINDINGS.md measured a 10-degree azimuth change outweighing a
    # deliberately induced error, so a planar fault called from an unknown
    # angle is a coin flip with a number printed on it. A view declared on the
    # session row beats the estimate, because a person who wrote it down knows
    # where they put the tripod.
    view = declared_view(declared_bin) if declared_bin else estimate_view(pose.keypoints)
    tr.step("viewpoint", **view.as_dict())

    # The set's own median concentric, so "too fast" compares this athlete's
    # reps with each other rather than with a number someone chose. The lift
    # is whichever half of the rep the movement profile says it is.
    from barra.phases import ascent, ascent_signal, phases_as_dict, rep_phases
    concentrics = sorted(max(b - a, 1) / fps
                         for a, b in (ascent(movement, s, t, e) for s, t, e in found))
    median_concentric = (concentrics[len(concentrics) // 2] if concentrics else None)
    lift_signal = ascent_signal(signal, movement)

    _stage("scoring the reps")
    rep_amplitudes: list[float] = []
    rep_durations: list[float] = []
    per_rep_assessments = []
    for i, (start, turn, end) in enumerate(found):
        label = f"r{i + 1}"
        if 0 <= start < len(signal) and 0 <= turn < len(signal):
            rep_amplitudes.append(float(signal[turn] - min(signal[start], signal[end])))
        rep_durations.append((end - start) / fps)
        measured = rep_metrics(pose.keypoints, start, turn, end, fps, movement,
                               trace=tr, label=label)
        # The phases as measured - metrics narrows the muscle-up's transition
        # to the frames in the bar plane; the raw table has the whole lift.
        phases = measured.phases or rep_phases(movement, start, turn, end, fps)
        lines = []
        for key in _METRIC_ORDER:
            cls, mlabel, unit, _ = METRIC_SPEC[key]
            value = _num(measured.values.get(key))
            if not value:
                continue
            lines.append({"name": mlabel, "value": f"{value} {unit}", "class": cls, "key": key})
        plausible = measured.plausible and measured.quality.get("rep", 0) >= MIN_REP_QUALITY
        if plausible:
            usable += 1
        else:
            extra_blockers.extend(measured.problems)
        transition = next((m["value"] for m in lines if m["key"] == "transition_s"), "")
        total = next((m["value"] for m in lines if m["key"] == "total_s"), "")
        lift_a, lift_b = ascent(movement, start, turn, end)
        q = score_rep(
            measured.values, arm, lift_signal, lift_a, lift_b,
            plausible=measured.plausible,
            rep_quality=measured.quality.get("rep", 0.0),
            min_rep_quality=MIN_REP_QUALITY,
            trace=tr, label=label,
        )
        if q.score is not None:
            scores.append(q.score)
        # Classify the failure types this rep was measured to have, so the
        # phone can say WHAT was wrong rather than only how far from "perfect".
        ev = rep_evidence(measured.values, arm, signal, start, turn, end, fps,
                          movement, kp=pose.keypoints, view=view,
                          median_concentric_s=median_concentric, valid=_valid)
        # A rep whose pose is not physically possible, or that was barely
        # tracked, gets no fault labels - not because it was clean, but
        # because nothing about it can be asserted. The score was already
        # withheld on these; the faults used to fire regardless, which put an
        # authoritative label on a measurement the same code had just called
        # unusable.
        blocked = ""
        if not measured.plausible:
            blocked = "the pose estimate is not physically possible: " + \
                      "; ".join(measured.problems)
        elif measured.quality.get("rep", 0) < MIN_REP_QUALITY:
            blocked = (f"too little of the rep was tracked "
                       f"(quality {measured.quality.get('rep', 0):.2f} < {MIN_REP_QUALITY})")
        assessments = assess(movement.name, ev, variant_info["name"], blocked=blocked)
        per_rep_assessments.append(assessments)
        rep_faults = ([] if blocked else
                      classify_faults(movement.name, ev, variant_info["name"], fps))
        rep_failures = [f.name for f in rep_faults]
        assessment_rows = [a.as_dict(label, fps) for a in assessments]
        # The one decision in the chain that recorded no evidence. Every other
        # stage prints the number it measured next to the threshold it had to
        # clear (docs/DEBUGGING.md); the fault layer printed only its verdict,
        # so "why did it not say dead hang" had no answer in the trace. Now the
        # primitives it read are printed with their state and the phase window
        # they were read from, and every rule's verdict - observed, not
        # observed, or unobservable and why - is recorded beside them.
        tr.step(f"failure classification {label}",
                track=movement.name, variant=variant_info["name"],
                failures=rep_failures, blocked=blocked or None,
                faults=[f.as_dict() for f in rep_faults],
                evidence=ev.as_dict(), windows=ev.windows(fps),
                phases_s=phases_as_dict(phases, fps),
                assessments=assessment_rows,
                unmeasured=ev.unmeasured(),
                view_blocked=ev.view_blocked(), view=view.as_dict())
        reps.append({
            "session": session,
            "label": label,
            "rescued": rescued,
            "failures": rep_failures,
            # The structured contract the phone renders: each fired fault with
            # the value and the threshold that fired it, and, beside it, what
            # could not be looked at. Cues.kt used to recover these by regular
            # expression from human-readable prose, so a copy edit could switch
            # fault detection off on every device at once.
            "faults": [f.as_dict() for f in rep_faults],
            # Every applicable rule, with its verdict. `faults` is the
            # observed subset; this is the whole population it was drawn
            # from, so an empty fault list can be told from a blocked one.
            "assessments": assessment_rows,
            "phases": phases_as_dict(phases, fps),
            "assessmentBlocked": blocked or None,
            "unmeasured": ev.unmeasured(),
            "viewBlocked": ev.view_blocked(),
            "transition_s": transition.replace(" s", ""),
            "total_s": total.replace(" s", ""),
            "class": "INVARIANT",
            "metrics": lines,
            "plausible": plausible,
            "problems": list(measured.problems),
            "startS": round(start / fps, 2),
            "endS": round(end / fps, 2),
            "turnS": round(turn / fps, 2),
            "score": q.score,
            "band": qband(q.score),
            "scoreNote": q.note,
            # Whether EVERY graded component was measured. A rep scored on part
            # of its definition is weaker evidence than one scored on all of it,
            # and the progression standard depends on the difference.
            "complete": q.complete,
            "penalties": [
                {"name": name, "value": v["value"], "why": v["why"]}
                for name, v in q.penalties.items()
            ],
            "components": [
                {"name": name, "value": c["value"], "weight": c["weight"],
                 "why": c["why"]}
                for name, c in q.components.items()
            ],
            "aside": [
                {"name": name, "value": v["value"], "why": v["why"]}
                for name, v in q.context.items() if isinstance(v, dict)
            ],
            "trace": _trace(signal, start, end),
        })

    blockers = list(dict.fromkeys(reasons + extra_blockers))
    note = f"{len(found)} segmented, {usable} usable"
    if usable < 3:
        note += " — need 3 for a session median"

    # The trim the phone plays back: from the first rep's start to the last
    # rep's end, with a little air either side. Everything outside it is the
    # walk to the bar and the walk away, which is not the exercise.
    trim = None
    if found:
        pad = 0.6
        first, last = found[0][0], found[-1][2]
        trim = {
            "startS": max(0.0, round(first / fps - pad, 2)),
            "endS": round(min(info.get("duration_s") or last / fps,
                              last / fps + pad), 2),
        }

    session_score = int(round(sum(scores) / len(scores))) if scores else None

    # Deterministic quality of the SET, not the reps: how even were the
    # amplitudes and the tempos across it. A coefficient of variation needs
    # no units and no model - it is the plainest honest measure of control
    # there is, and the prose models are told to quote it when it is poor.
    consistency: dict = {}
    if len(rep_amplitudes) >= 2:
        amp = np.asarray(rep_amplitudes)
        consistency["amplitudeCV"] = round(float(amp.std() / max(amp.mean(), 1e-9)), 3)
    if len(rep_durations) >= 2:
        dur = np.asarray(rep_durations)
        consistency["tempoCV"] = round(float(dur.std() / max(dur.mean(), 1e-9)), 3)
    if consistency:
        tr.step("set consistency", **consistency)

    blockers_out = list(blockers)
    counted_by = None
    if vision_count is not None and not found:
        counted_by = "vision"
        blockers_out.append(
            f"the geometry could not time the reps, so two vision models "
            f"counted {vision_count['reps']} from stills of the clip "
            f"({vision_count['agreement']})")

    clip_faults = clip_failures(reps)
    from barra.fault_select import primary_from_assessments
    primary = primary_from_assessments(per_rep_assessments, movement=movement.name)
    from barra.fault_select import top_fixes
    fixes = top_fixes(per_rep_assessments, movement.name)
    rec = recommend_for_payload({"track": movement.name, "failures": clip_faults})
    if primary and primary.get("name"):
        # Prefer the measured primary cue over the static PRIORITY table when
        # recommending a fix - same fault the athlete is told about.
        rec = recommend_for_payload({
            "track": movement.name,
            "failures": [primary["name"]] + [
                n for n in (clip_faults or {}) if n != primary["name"]
            ],
        })
    checks = summarise(per_rep_assessments)
    tr.step("assessment summary", **checks)
    if primary:
        tr.step("primary fault", **primary)
    return {
        "exercise": movement.name,
        "track": movement.name,
        "detected": detected,
        "model": model_out,
        "variant": variant_info,
        "failures": clip_faults,
        "primaryFault": primary,
        # The three things to improve, most important first (docs/UX-PLAN.md).
        "topFixes": fixes,
        # Per errorId: reps observed / checked clean / could not be checked.
        # The clip-level counterpart of reps[].assessments; `failures` above
        # is its observed column only.
        "assessment": checks,
        "measurementVersion": ASSESSMENT_VERSION,
        # Which estimator made the keypoints. `provenance.poseModel` describes
        # the default model file, which is not the same thing once a backend
        # has fallen over and the next one produced the numbers.
        "poseBackend": pose_backend,
        "recommendation": rec,
        "n_reps": usable if found else (vision_count["reps"] if vision_count else 0),
        "n_candidates": len(found),
        "rescued": rescued,
        "countedBy": counted_by,
        "consistency": consistency or None,
        "view": view.as_dict(),
        "fps": round(float(fps), 3),
        "duration_s": round(float(info.get("duration_s") or 0), 2),
        "trim": trim,
        "session": session,
        "sessionScore": session_score,
        "sessionBand": qband(session_score),
        "sessions": [{"date": session, "reps": usable, "note": note}],
        "reps": reps,
        # blockers_out, not blockers: the key was written twice in this literal
        # and the second one won, so the "the geometry could not time the reps,
        # so two vision models counted N" line was built and then dropped on
        # every clip that needed it.
        "blockers": blockers_out,
        "nextSession": (
            "Cinco o seis repeticiones, una serie, el móvil fijo en un punto marcado, "
            "siempre desde el mismo lado y con la parte de arriba dentro del encuadre."
        ),
    }
