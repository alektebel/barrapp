"""`barra explain <video>` - the whole decision chain for one clip.

The point of this command is that it answers "why did it do that?" without
reading any code. It runs the same pipeline the server runs, with tracing on,
and prints every decision with the evidence and the threshold behind it:

    probe -> pose -> classify -> segment -> metrics -> quality -> payload

It writes the machine-readable trace beside the printout so two runs can be
diffed, which is how you find what a change actually altered.

Deliberately re-runs rather than reading a cached result. A trace of a run that
did not just happen is a trace of a different build, a different model, or a
different clip, and confusing the three is how debugging sessions get lost.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import schema as S
from .config import PATHS
from .trace import Trace, new_id


def explain(video: Path, exercise: str = "auto", show: str = "decisions",
            write: bool = True, fresh: bool = False) -> dict:
    from .classify import HUMAN, classify
    from .ingest import _clean_signal, probe_video, segment_reps_verbose
    from .metrics import MIN_REP_QUALITY, arm_reach, rep_metrics
    from .movements import resolve, tracking_signal
    from .pose import available_backends, get_backend
    from .quality import band, score_rep

    tr = Trace(new_id(video.name), video.name, exercise_requested=exercise)

    tr.stage("probe")
    info = probe_video(video)
    tr.step("container", **{k: v for k, v in info.items() if k != "ok"})
    if not info.get("ok"):
        tr.error("could not open the clip", reason=info.get("reason"))
        return _finish(tr, video, show, write, None)

    tr.stage("pose")
    # Pose is the slow step by an order of magnitude, and a debug loop you have
    # to wait 80 seconds for is a debug loop you stop using. Cached keypoints
    # are reused when they exist - and the trace says so, because a trace that
    # silently mixed a fresh run with an old pose would be worse than none.
    cached = PATHS.o(S.P_KEYPOINTS, f"{video.stem}.parquet")
    keypoints = None
    if cached.exists() and not fresh:
        import pandas as pd

        from .ingest import frame_to_keypoints
        keypoints = frame_to_keypoints(pd.read_parquet(cached))
        tr.step("keypoints reused from an earlier run", path=str(cached),
                written=cached.stat().st_mtime, frames=int(len(keypoints)),
                note="pass --fresh to re-run pose estimation")
        fps = info["fps"] or 30.0
    else:
        backends = available_backends()
        tr.step("backends available", backends=backends)
        if not backends:
            tr.error("no pose backend installed",
                     fix='pip install -e ".[mediapipe]" in the server venv')
            return _finish(tr, video, show, write, None)
        backend = get_backend(backends[0])
        model = getattr(backend, "model_path", None)
        tr.step("estimating", backend=backend.name,
                model=str(model) if model else None,
                model_bytes=Path(model).stat().st_size
                if model and Path(model).exists() else None)
        pose = backend.estimate(video)
        keypoints = pose.keypoints
        fps = pose.fps or info["fps"] or 30.0

    class _P:
        pass
    pose = _P()
    pose.keypoints = keypoints
    conf = pose.keypoints[:, S.ANALYSIS_IDX, 2]
    tr.step("keypoints", frames=int(len(pose.keypoints)), fps=float(fps),
            mean_confidence=float(conf.mean()),
            frames_above_0_6=int((conf.mean(axis=1) >= 0.6).sum()))

    detection = classify(pose.keypoints, tr, fps=fps)
    chosen = detection.exercise if exercise in ("", "auto", None) else exercise
    if chosen == "unknown":
        tr.error("no movement recognised, so nothing downstream can run")
        return _finish(tr, video, show, write, None)
    if exercise not in ("", "auto", None) and detection.exercise != exercise:
        tr.note("the named exercise disagrees with the detected one",
                named=exercise, detected=detection.exercise,
                detected_confidence=detection.confidence)

    movement = resolve(chosen)
    found, reasons = segment_reps_verbose(pose.keypoints, fps, movement, trace=tr)

    raw, sconf = tracking_signal(pose.keypoints, movement)
    signal, _ = _clean_signal(raw, sconf)
    arm = arm_reach(pose.keypoints)

    scores = []
    for i, (a, t, b) in enumerate(found):
        label = f"rep {i + 1}"
        m = rep_metrics(pose.keypoints, a, t, b, fps, movement, trace=tr, label=label)
        q = score_rep(m.values, arm, signal, a, t, plausible=m.plausible,
                      rep_quality=m.quality.get("rep", 0.0),
                      min_rep_quality=MIN_REP_QUALITY, trace=tr, label=label)
        scores.append(q.score)

    tr.stage("result")
    measured = [s for s in scores if s is not None]
    session = int(round(sum(measured) / len(measured))) if measured else None
    tr.decision("session", "mean of the reps that could be scored",
                exercise=movement.name, detected=HUMAN.get(detection.exercise),
                candidates=len(found), scored=len(measured),
                session_score=session, band=band(session))
    return _finish(tr, video, show, write, {
        "exercise": movement.name, "reps": len(found),
        "scored": len(measured), "sessionScore": session,
    })


def _finish(tr: Trace, video: Path, show: str, write: bool, summary: dict | None) -> dict:
    print(tr.render(show=show))
    out = None
    if write:
        out = tr.write(PATHS.o("traces", f"{tr.id}.json"))
        print(f"\n  trace written to {out}")
        print(f"  {len(tr.entries)} entries · {len(tr.rejections)} rejections · "
              f"{len(tr.errors)} errors")
    return {"traceId": tr.id, "trace": str(out) if out else None,
            "summary": summary, "rejections": len(tr.rejections)}


def replay(trace_id: str, show: str = "all") -> None:
    """Print a trace written by an earlier run, or by the server."""
    path = PATHS.o("traces", f"{trace_id}.json")
    if not path.exists():
        matches = sorted(PATHS.o("traces").glob(f"*{trace_id}*.json"))
        if not matches:
            raise SystemExit(
                f"no trace matching {trace_id!r} in {PATHS.o('traces')}. "
                "Run `barra explain <video>` first, or copy one off the server."
            )
        path = matches[-1]
    data = json.loads(path.read_text())
    keep = {"all": None, "decisions": {"decision", "reject", "error"},
            "problems": {"reject", "error"}}[show]
    print(f"trace {data['traceId']}  ·  {data['subject']}")
    if data.get("context"):
        print("  " + "  ".join(f"{k}={v}" for k, v in data["context"].items()))
    stage = None
    for e in data["entries"]:
        if keep is not None and e["kind"] not in keep:
            continue
        if e["stage"] != stage:
            stage = e["stage"]
            print(f"\n[{stage}]")
        mark = {"decision": "->", "reject": " x", "error": " !",
                "note": "  ", "step": "  "}[e["kind"]]
        print(f" {e['atMs']:>5}ms {mark} {e.get('message', '')}")
        for k, v in (e.get("data") or {}).items():
            if k in ("outcome", "what"):
                continue
            print(f"            {k} = {v}")


def recent(limit: int = 20) -> list[dict]:
    """List traces on disk, newest first."""
    rows = []
    for p in sorted(PATHS.o("traces").glob("*.json"), reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        rows.append({
            "traceId": d.get("traceId", p.stem),
            "subject": d.get("subject", ""),
            "rejections": d.get("counts", {}).get("reject", 0),
            "errors": d.get("counts", {}).get("error", 0),
            "durationMs": d.get("durationMs", 0),
        })
    return rows
