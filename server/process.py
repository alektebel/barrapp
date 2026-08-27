"""Run barra on one clip and return the JSON the phone renders."""
from __future__ import annotations

import math
import os
import sys
from datetime import date
from pathlib import Path

from deepseek import write_report

BARRA_ROOT = Path(os.environ.get("BARRA_ROOT", "/home/diegeo/Development/dev/barrapp"))
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


def _num(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(x):
        return ""
    return f"{x:.2f}"


def process_job(job: dict, video_path: Path) -> dict:
    metrics = analyze_clip(video_path, job.get("exercise") or "muscle_up")
    return write_report(metrics)


def analyze_clip(video_path: Path, exercise: str = "muscle_up") -> dict:
    if not video_path.exists() or video_path.stat().st_size == 0:
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": ["No video arrived at the server."],
        }

    try:
        from barra.ingest import probe_video, segment_reps_verbose
        from barra.metrics import METRIC_SPEC, MIN_REP_QUALITY, rep_metrics
        from barra.movements import resolve
        from barra.pose import available_backends, get_backend
    except ImportError as exc:
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": [
                f"barra is not importable on this host ({exc}). "
                "Use server/.venv (pip install -e ../barrapp[mediapipe])."
            ],
        }

    backends = available_backends()
    if not backends:
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": [
                "No pose backend installed. In server/.venv run: "
                "pip install -e ../barrapp[mediapipe]"
            ],
        }

    info = probe_video(video_path)
    if not info.get("ok"):
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": [f"Could not open the clip: {info.get('reason', 'unknown')}"],
        }

    os.environ.setdefault("BARRA_POSE_MODEL", str(BARRA_ROOT / "models" / "pose_landmarker_heavy.task"))
    try:
        pose = get_backend(backends[0]).estimate(video_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": [f"Pose estimation failed: {exc}"],
        }
    fps = pose.fps or info["fps"] or 30.0
    try:
        movement = resolve(exercise)
    except SystemExit as exc:
        return {
            "exercise": exercise,
            "n_reps": 0,
            "sessions": [],
            "reps": [],
            "blockers": [str(exc)],
        }
    found, reasons = segment_reps_verbose(pose.keypoints, fps, movement)

    session = date.today().isoformat()
    reps = []
    usable = 0
    extra_blockers: list[str] = []
    for i, (start, turn, end) in enumerate(found):
        measured = rep_metrics(pose.keypoints, start, turn, end, fps, movement)
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
        reps.append({
            "session": session,
            "label": f"r{i + 1}",
            "transition_s": transition.replace(" s", ""),
            "total_s": total.replace(" s", ""),
            "class": "INVARIANT",
            "metrics": lines,
            "plausible": plausible,
            "problems": list(measured.problems),
        })

    blockers = list(dict.fromkeys(reasons + extra_blockers))
    note = f"{len(found)} segmented, {usable} usable"
    if usable < 3:
        note += " — need 3 for a session median"
    return {
        "exercise": movement.name,
        "n_reps": usable,
        "n_candidates": len(found),
        "fps": round(float(fps), 3),
        "duration_s": round(float(info.get("duration_s") or 0), 2),
        "sessions": [{"date": session, "reps": usable, "note": note}],
        "reps": reps,
        "blockers": blockers,
        "nextSession": (
            "Five or six reps, one set, tripod on a marked spot, same side every time, "
            "lockout in frame, trimmed to the working set."
        ),
    }
