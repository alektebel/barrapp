"""Run barra on one clip and return the JSON the phone renders."""
from __future__ import annotations

import math
import os
import sys
from datetime import date
from pathlib import Path

from deepseek import write_report
from vision import technique_note

from barra.frames import technique_artifacts

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


def process_job(job: dict, video_path: Path, on_stage=None) -> dict:
    """Measure one clip and return the payload the phone renders.

    `exercise` may be omitted or "auto": the clip is then classified from its
    own geometry rather than from what the athlete remembered to tap.

    Every job carries a trace id. It goes into the payload, so the phone can
    show it; into a JSON trace on disk, so the decision chain can be replayed
    with `barra explain --replay <id>`; and into the log line, so a user report
    maps to a specific run of a specific build.
    """
    def _stage(name: str) -> None:
        """A named heartbeat for the phone: the work list shows where the clip
        actually is, instead of a single undifferentiated 'processing'."""
        if on_stage is None:
            return
        try:
            on_stage(name)
        except Exception:  # noqa: BLE001 - a heartbeat never fails a job
            pass

    _stage("opening the clip")
    requested = (job.get("exercise") or "auto").strip() or "auto"
    trace = _new_trace(job, video_path, requested)
    metrics = analyze_clip(video_path, requested, session=job.get("session"),
                           trace=trace, on_stage=_stage)
    report = write_report(metrics)
    # The prose model owns exactly three keys. Everything else the UI draws -
    # the detected movement, the trim window, per-rep scores and traces - is
    # carried through untouched.
    #
    # Inverted on purpose: an allow-list of measurement keys has to be updated
    # every time one is added, and the failure mode is a field that silently
    # never reaches the phone. A deny-list of the three prose keys cannot drift.
    prose = {"headline", "narrative", "nextSession"}
    for key, value in metrics.items():
        if key not in prose:
            report[key] = value

    # The raw take is not the technique. Cut the working set out of the clip
    # and still every rep's turning point, then let a vision model - when one
    # is configured - study those artifacts and say what the geometry missed.
    # Both steps are best-effort; without a vision key nothing changes.
    artifacts_root = Path(os.environ.get(
        "BARRA_TRACE_DIR", str(BARRA_ROOT / "out" / "traces")))
    artifacts = technique_artifacts(video_path, report, artifacts_root,
                                    str(report.get("traceId") or job.get("id") or "job"))
    if trace is not None and (artifacts.clip or artifacts.stills):
        trace.step("technique artifacts", **artifacts.as_trace_data())
    note = technique_note(artifacts)
    if note is not None:
        report.update(note)
        report["proseSource"] = "vision"
    elif trace is not None and artifacts.stills:
        trace.step("vision pass skipped", reason="no vision endpoint configured")

    if trace is not None:
        report["traceId"] = trace.id
        report["provenance"] = _provenance()
        _write_trace(trace)
        print(f"[barra] job={job.get('id')} trace={trace.id} "
              f"exercise={report.get('exercise')} reps={report.get('n_reps')} "
              f"score={report.get('sessionScore')} "
              f"rejections={len(trace.rejections)} errors={len(trace.errors)}",
              flush=True)
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


def _write_trace(trace) -> None:
    """Traces live under BARRA_TRACE_DIR, or out/traces beside the code.

    Failing to write one must never fail the job: a debugging aid that can take
    down a measurement is worse than no debugging aid.
    """
    try:
        root = Path(os.environ.get("BARRA_TRACE_DIR", str(BARRA_ROOT / "out" / "traces")))
        trace.write(root / f"{trace.id}.json")
    except Exception as exc:  # noqa: BLE001
        print(f"[barra] could not write trace {trace.id}: {exc}", flush=True)


def _empty(exercise: str, blockers: list[str], **extra) -> dict:
    """A result the app can render when nothing could be measured.

    Every key the success path returns is present, because a client that has to
    ask whether a field exists ends up guessing what its absence means. A clip
    that produced nothing is a complete answer, not a partial one.
    """
    base = {
        "exercise": exercise,
        "detected": None,
        "n_reps": 0,
        "n_candidates": 0,
        "fps": 0.0,
        "duration_s": 0.0,
        "trim": None,
        "session": date.today().isoformat(),
        "sessionScore": None,
        "sessionBand": "unmeasured",
        "sessions": [],
        "reps": [],
        "blockers": blockers,
    }
    base.update(extra)
    return base


def analyze_clip(video_path: Path, exercise: str = "auto",
                 session: str | None = None, trace=None, on_stage=None) -> dict:
    """Measure one clip. `on_stage`, when given, is called with a short human
    phrase at each step that can take real time, so a waiting phone can say
    where the work is."""
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

    backends = available_backends()
    if not backends:
        return _empty(exercise, [
            "No pose backend installed. In server/.venv run: "
            "pip install -e ../barrapp[mediapipe]"
        ])

    # A backend can fail in ways this process cannot survive (a native library
    # that takes the interpreter down with it), so the order is decided BEFORE
    # the first frame: BARRA_POSE_BACKEND pins one, and the rest are tried in
    # registry order if the first estimate raises.
    requested = os.environ.get("BARRA_POSE_BACKEND", "").strip()
    if requested:
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
    if not info.get("ok"):
        tr.error("could not open the clip", reason=info.get("reason"))
        return _empty(exercise,
                      [f"Could not open the clip: {info.get('reason', 'unknown')}"])

    os.environ.setdefault("BARRA_POSE_MODEL", str(BARRA_ROOT / "models" / "pose_landmarker_heavy.task"))
    pose = None
    pose_error = None
    for name in order:
        try:
            pose = get_backend(name).estimate(video_path)
            tr.step("pose backend", backend=name)
            break
        except Exception as exc:  # noqa: BLE001 - the next backend may still work
            pose_error = exc
            tr.reject("pose backend failed", backend=name, reason=str(exc)[:200])
    if pose is None:
        reason = str(pose_error) if pose_error else "unknown"
        return _empty(exercise, [f"Pose estimation failed: {reason}"])
    fps = pose.fps or info["fps"] or 30.0

    # Detect the movement from the clip itself. A movement the athlete named is
    # respected, but the detection still runs so the phone can say when the two
    # disagree - measuring a muscle-up with squat geometry produces numbers that
    # look fine and mean nothing.
    tr.step("keypoints", frames=int(len(pose.keypoints)), fps=float(fps))
    _stage("recognising the movement")
    detection = classify(pose.keypoints, tr, fps=fps)
    detected = {
        "exercise": detection.exercise,
        "label": HUMAN.get(detection.exercise, detection.exercise),
        "confidence": round(float(detection.confidence), 2),
        "reason": detection.reason,
        "runnerUp": detection.runner_up,
    }
    chosen = exercise
    if exercise in ("", "auto", None):
        if detection.exercise == "unknown":
            return _empty("auto", [detection.reason], detected=detected,
                          duration_s=round(float(info.get("duration_s") or 0), 2))
        chosen = detection.exercise

    try:
        movement = resolve(chosen)
    except SystemExit as exc:
        return _empty(chosen, [str(exc)], detected=detected)

    _stage("finding the reps")
    found, reasons = segment_reps_verbose(pose.keypoints, fps, movement, trace=tr)

    session = session or date.today().isoformat()
    raw_signal, sig_conf = tracking_signal(pose.keypoints, movement)
    signal, _valid = _clean_signal(raw_signal, sig_conf)
    arm = arm_reach(pose.keypoints)
    reps = []
    usable = 0
    extra_blockers: list[str] = []
    scores: list[int] = []
    _stage("scoring the reps")
    for i, (start, turn, end) in enumerate(found):
        measured = rep_metrics(pose.keypoints, start, turn, end, fps, movement,
                               trace=tr, label=f"r{i + 1}")
        lines = []
        for key in _METRIC_ORDER:
            cls, label, unit, _ = METRIC_SPEC[key]
            value = _num(measured.values.get(key))
            if not value:
                continue
            lines.append({"name": label, "value": f"{value} {unit}", "class": cls, "key": key})
        plausible = measured.plausible and measured.quality.get("rep", 0) >= MIN_REP_QUALITY
        if plausible:
            usable += 1
        else:
            extra_blockers.extend(measured.problems)
        transition = next((m["value"] for m in lines if m["key"] == "transition_s"), "")
        total = next((m["value"] for m in lines if m["key"] == "total_s"), "")
        q = score_rep(
            measured.values, arm, signal, start, turn,
            plausible=measured.plausible,
            rep_quality=measured.quality.get("rep", 0.0),
            min_rep_quality=MIN_REP_QUALITY,
            trace=tr, label=f"r{i + 1}",
        )
        if q.score is not None:
            scores.append(q.score)
        reps.append({
            "session": session,
            "label": f"r{i + 1}",
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
    return {
        "exercise": movement.name,
        "detected": detected,
        "n_reps": usable,
        "n_candidates": len(found),
        "fps": round(float(fps), 3),
        "duration_s": round(float(info.get("duration_s") or 0), 2),
        "trim": trim,
        "session": session,
        "sessionScore": session_score,
        "sessionBand": qband(session_score),
        "sessions": [{"date": session, "reps": usable, "note": note}],
        "reps": reps,
        "blockers": blockers,
        "nextSession": (
            "Five or six reps, one set, tripod on a marked spot, same side every time, "
            "lockout in frame, trimmed to the working set."
        ),
    }
