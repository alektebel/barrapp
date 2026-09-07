#!/usr/bin/env python3
"""One clip through the real pipeline, in a process of its own.

Run as a module (``python tools/debugweb/runner.py <spec.json>``) rather than
called in-process, and that is not incidental. A pose backend can fail in a way
this interpreter cannot survive: on the machine this was written on,
mediapipe's ``estimate()`` is SIGKILLed, which is not an exception and cannot
be caught - ``server/process.py`` says as much in a comment above its own
backend loop, and its try/except cannot help either. A debug server that dies
with the backend is a debug server that cannot tell you the backend died.

So each run is a subprocess writing its progress to a status file. A kill
becomes a returncode the parent reports, next to the stage it had reached.

Everything it produces goes where the rest of the project already puts it:
the trace to ``out/traces/<id>.json``, in the one format ``barra explain
--replay`` reads, and the payload beside it. Nothing here re-implements a
threshold or a decision - a debug tool that computes its own answer is
debugging itself.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))


def _write(status_path: Path, **fields) -> None:
    """Progress the parent can read. Written whole, then renamed, so the parent
    never reads a half-written file."""
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(fields))
    tmp.replace(status_path)


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    clip = Path(spec["clip"])
    status = Path(spec["status"])
    exercise = spec.get("exercise") or "auto"
    fresh = bool(spec.get("fresh"))
    backend = spec.get("backend") or ""

    state = {"state": "running", "stage": "starting", "clip": clip.name,
             "traceId": None, "error": None}
    _write(status, **state)

    def stage(name: str) -> None:
        state["stage"] = name
        _write(status, **state)

    try:
        from barra.config import PATHS
        from barra.posecache import load_or_estimate
        from barra.trace import Trace, new_id
        from process import analyze_clip

        tr = Trace(new_id(clip.name), clip.name,
                   source="debugweb", clip=str(clip),
                   exercise_requested=exercise)
        state["traceId"] = tr.id
        _write(status, **state)

        tr.stage("pose")
        stage("estimating the pose")
        order = [backend] if backend else None
        pose = load_or_estimate(clip, fresh=fresh, trace=tr, order=order,
                                write_cache=True)
        state["poseSource"] = pose.source
        _write(status, **state)

        payload = analyze_clip(clip, exercise=exercise,
                               session=date.today().isoformat(),
                               trace=tr, on_stage=stage, pose=pose)
        payload["traceId"] = tr.id

        traces = PATHS.o("traces")
        traces.mkdir(parents=True, exist_ok=True)
        tr.write(traces / f"{tr.id}.json")
        (traces / f"{tr.id}.payload.json").write_text(json.dumps(payload, indent=2))

        state.update(state="done", stage="done",
                     reps=payload.get("n_reps"),
                     exercise=payload.get("exercise"),
                     rejections=len(tr.rejections), errors=len(tr.errors))
        _write(status, **state)
        return 0
    except Exception as exc:  # noqa: BLE001 - the parent needs the reason, not a stack
        state.update(state="failed", error=f"{type(exc).__name__}: {exc}",
                     traceback=traceback.format_exc()[-2000:])
        _write(status, **state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
