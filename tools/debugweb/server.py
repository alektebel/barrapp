#!/usr/bin/env python3
"""A browser you can point at the pipeline.

    python tools/debugweb/server.py        ->  http://127.0.0.1:8091

Every debug surface this project has is a text stream or a one-shot file:
`barra explain` prints ASCII, `barra/qc.py` writes an mp4 you open in a player,
and `server/local_server.py` answers JSON and nothing else. So nothing
correlates a trace with the frames it describes, and "why did this clip count
zero reps" is answered by reading numbers and imagining the video.

This serves the trace *on top of* the clip it came from: the skeleton over the
pixels, the tracking signal with the amplitude lines that decided which
turnarounds counted, and every rejection at the second it happened.

Three rules it holds to:

  * **It never computes an answer.** Every number shown is read out of a trace
    or a payload the pipeline produced. A debug tool with its own opinion is
    debugging itself.
  * **Runs happen in a subprocess.** A pose backend can take the interpreter
    down with it (mediapipe does exactly that here), and a server that dies
    with the backend cannot report that the backend died.
  * **Its output is the project's output.** Traces land in `out/traces/` in the
    one format `barra explain --replay` reads, so anything run here is
    replayable on the command line and diffable against a server trace.

Stdlib only, and 127.0.0.1 by default - unlike local_server.py, this one serves
local video files.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

VENV_PY = ROOT / ".venv" / "bin" / "python"
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

# barra.config.PATHS is rooted at $BARRA_ROOT, default "." - so `out/` means
# "out relative to wherever this was launched from". Pin it to the repo, or the
# server and the CLI would disagree about where traces live.
os.chdir(ROOT)

from barra import schema as S            # noqa: E402
from barra.config import PATHS           # noqa: E402

TRACES = PATHS.o("traces")
RUNS: dict[str, dict] = {}
LOCK = threading.Lock()
TMP = Path(tempfile.gettempdir()) / "barra-debugweb"
TMP.mkdir(parents=True, exist_ok=True)

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8"}


# --------------------------------------------------------------------------
# clips
# --------------------------------------------------------------------------
def clip_dirs() -> list[Path]:
    return [ROOT, ROOT / "data" / "videos", ROOT / "server" / "data"]


def find_clip(name: str) -> Path | None:
    """Resolve a clip by basename, inside the known directories only."""
    if not SAFE.match(name):
        return None
    for d in clip_dirs():
        p = d / name
        if p.is_file() and p.suffix.lower() in VIDEO_EXT:
            return p
    return None


def list_clips() -> list[dict]:
    seen: dict[str, dict] = {}
    for d in clip_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
                continue
            if p.name in seen:
                continue
            cache = PATHS.o(S.P_KEYPOINTS, f"{p.stem}.parquet")
            seen[p.name] = {
                "name": p.name,
                "dir": str(d.relative_to(ROOT)) or ".",
                "bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
                "cached": cache.exists(),
            }
    return list(seen.values())


# --------------------------------------------------------------------------
# traces
# --------------------------------------------------------------------------
def trace_path(trace_id: str) -> Path | None:
    if not SAFE.match(trace_id):
        return None
    p = TRACES / f"{trace_id}.json"
    if p.exists():
        return p
    matches = sorted(TRACES.glob(f"*{trace_id}*.json"))
    matches = [m for m in matches if not m.name.endswith(".payload.json")]
    return matches[-1] if matches else None


def list_traces(limit: int = 60) -> list[dict]:
    rows = []
    for p in sorted(TRACES.glob("*.json"), reverse=True):
        if p.name.endswith(".payload.json"):
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        counts = d.get("counts", {})
        rows.append({
            "traceId": d.get("traceId", p.stem),
            "subject": d.get("subject", ""),
            "rejections": counts.get("reject", 0),
            "errors": counts.get("error", 0),
            "decisions": counts.get("decision", 0),
            "durationMs": d.get("durationMs", 0),
            "mtime": p.stat().st_mtime,
            "hasPayload": (TRACES / f"{d.get('traceId', p.stem)}.payload.json").exists(),
        })
        if len(rows) >= limit:
            break
    return rows


# --------------------------------------------------------------------------
# keypoints
# --------------------------------------------------------------------------
def keypoints_json(stem: str) -> dict | None:
    """The cached keypoints of a clip, as the overlay needs them.

    Pixel coordinates and confidence, exactly as the backend produced them -
    the overlay draws what the pipeline measured, not a prettier version of it.
    """
    if not SAFE.match(stem):
        return None
    path = PATHS.o(S.P_KEYPOINTS, f"{stem}.parquet")
    if not path.exists():
        return None
    import pandas as pd

    from barra.ingest import frame_to_keypoints

    kp = frame_to_keypoints(pd.read_parquet(path))
    xy = [[[round(float(kp[t, j, 0]), 1), round(float(kp[t, j, 1]), 1),
            round(float(kp[t, j, 2]), 3)] for j in range(kp.shape[1])]
          for t in range(kp.shape[0])]
    return {
        "frames": int(kp.shape[0]),
        "joints": S.COCO17,
        "edges": [[S.KP_INDEX[a], S.KP_INDEX[b]] for a, b in S.SKELETON_EDGES],
        "analysis": S.ANALYSIS_IDX,
        "kp": xy,
    }


# --------------------------------------------------------------------------
# parity: the three implementations of "which faults does this rep have"
# --------------------------------------------------------------------------
# The phone's copy, ported from app/src/main/java/com/barrapp/Cues.kt:17-46.
# Porting it IS the parity check: if this drifts from the Kotlin, the panel
# stops measuring anything. The thresholds below are the Kotlin's literals,
# deliberately re-typed rather than imported, because that is the situation
# being measured - the phone re-derives faults from prose with its own numbers.
_KT_LOCKOUT = re.compile(r"lockout (\d+)% of full")
_KT_HANG = re.compile(r"hang (\d+)% of full")


def phone_faults(rep: dict) -> list[str]:
    faults: list[str] = []
    for a in rep.get("aside") or []:
        if a.get("name") == "swing" and (a.get("value") or 0) > 0.4:
            faults.append("momentum")
    for c in rep.get("components") or []:
        why = c.get("why") or ""
        if c.get("name") == "range":
            m = _KT_LOCKOUT.search(why)
            h = _KT_HANG.search(why)
            if m and int(m.group(1)) < 85:
                faults.append("lockout")
            if h and int(h.group(1)) < 75:
                faults.append("dead hang")
    for p in rep.get("penalties") or []:
        if p.get("name") == "control" and (p.get("value") or 0) > 0.0:
            faults.append("control")
    for c in rep.get("components") or []:
        if c.get("name") == "smoothness" and \
                "% of the ascent made no progress" in (c.get("why") or ""):
            faults.append("stall")
    return faults


def parity(trace_id: str) -> dict | None:
    p = TRACES / f"{trace_id}.payload.json"
    if not p.exists():
        return None
    from barra.faults import rep_faults as harness_faults

    payload = json.loads(p.read_text())
    rows = []
    for rep in payload.get("reps") or []:
        server = sorted(rep.get("failures") or [])
        harness = sorted(harness_faults(rep))
        phone = sorted(phone_faults(rep))
        rows.append({
            "label": rep.get("label"),
            "score": rep.get("score"),
            "server": server, "harness": harness, "phone": phone,
            "agree": server == harness == phone,
        })
    return {
        "traceId": trace_id,
        "track": payload.get("track"),
        "reps": rows,
        "disagreements": sum(0 if r["agree"] else 1 for r in rows),
        "note": ("server = faults_taxonomy.classify_failures (numeric, shipped as "
                 "reps[].failures); harness = barra/faults.py (regex over the "
                 "why-strings); phone = Cues.kt (regex over the why-strings, "
                 "thresholds re-hardcoded, and it ignores reps[].failures)"),
    }


# --------------------------------------------------------------------------
# fault spec: which measurement each fault reads, and the line it must clear
# --------------------------------------------------------------------------
# The thresholds are IMPORTED, never retyped, so this panel cannot drift from
# the code it describes. What is written out by hand is only the mapping from a
# fault name to the key its predicate reads - that mapping lives inside the
# predicate bodies in barra/faults_taxonomy.py and is not otherwise inspectable.
# If a predicate changes which key it reads, this table must follow it; the
# panel says so, rather than pretending the mapping is derived.
def fault_spec() -> dict:
    import barra.faults_taxonomy as F

    def r(fault, key, op, threshold):
        return {"fault": fault, "key": key, "op": op, "threshold": threshold}

    bar = [
        r("momentum", "swing", ">", F.SWING_TORSO),
        r("lockout", "lockout_pct", "<", F.LOCKOUT_MIN * 100),
        r("dead hang", "hang_pct", "<", F.HANG_MIN * 100),
        r("control", "tempo_ratio", "<", F.CONTROLLED_TEMPO),
        r("stall", "stalled_frac", ">=", 0.05),
        r("poor transition", "transition_s", ">", 0.60),
        r("bent arms", "arms_straight_frac", "<", 0.5),
    ]
    lever = [
        r("poor range of motion", "body_line_deg", "<", F.STRICT_HORIZONTAL),
        r("poor scapular retraction", "arms_straight_frac", "<", 0.6),
        r("bent knees", "legs_straight_frac", "<", 0.6),
        r("piked hips", "hip_pike_deg", "<", F.PIKE),
        r("momentum", "swing", ">", F.SWING_TORSO),
    ]
    planche = [dict(x, fault=("poor scapular protraction"
                              if x["fault"] == "poor scapular retraction"
                              else "piked body" if x["fault"] == "piked hips"
                              else x["fault"])) for x in lever]
    pistol = [
        r("poor range of motion", "pistol_depth", "<", F.PISTOL_DEPTH),
        r("knee valgus", "knee_valgus", ">", F.PISTOL_VALGUS),
        r("heel raise", "heel_raise", ">", 0.20),
        r("leaning back", "torso_lean", "<", -0.30),
        r("uncontrolled descent", "tempo_ratio", "<", F.CONTROLLED_TEMPO),
        r("arm swing", "swing", ">", F.SWING_TORSO),
    ]
    spec = {"muscle_up": bar, "front_lever": lever, "planche": planche,
            "pistol_squat": pistol}
    # classify_failures routes these four into muscle_up() - the bar rules -
    # which is finding C1 in feedback.md, and the reason a squat rep is worth
    # looking at in this panel at all.
    for track in ("pull_up", "dip", "push_up", "squat"):
        spec[track] = bar
    return {"spec": spec,
            "inherits_bar_rules": ["pull_up", "dip", "push_up", "squat"]}


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------
def start_run(clip: Path, exercise: str, fresh: bool, backend: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    status = TMP / f"{run_id}.status.json"
    spec = TMP / f"{run_id}.spec.json"
    spec.write_text(json.dumps({
        "clip": str(clip), "status": str(status),
        "exercise": exercise, "fresh": fresh, "backend": backend,
    }))
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "runner.py"), str(spec)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    with LOCK:
        RUNS[run_id] = {"proc": proc, "status": status, "clip": clip.name,
                        "started": time.time(), "log": []}

    def drain() -> None:
        for line in proc.stdout:                      # type: ignore[union-attr]
            with LOCK:
                RUNS[run_id]["log"].append(line.rstrip())
                RUNS[run_id]["log"] = RUNS[run_id]["log"][-200:]
        proc.wait()

    threading.Thread(target=drain, daemon=True).start()
    return run_id


def run_state(run_id: str) -> dict | None:
    with LOCK:
        run = RUNS.get(run_id)
        if run is None:
            return None
        log = list(run["log"])
    state: dict = {"runId": run_id, "clip": run["clip"], "state": "running",
                   "stage": "starting", "elapsed": round(time.time() - run["started"], 1)}
    if run["status"].exists():
        try:
            state.update(json.loads(run["status"].read_text()))
        except Exception:  # noqa: BLE001 - a half-written status is just "not yet"
            pass
    rc = run["proc"].poll()
    if rc is not None and state.get("state") == "running":
        # The process is gone but never wrote a terminal status: it was killed.
        # This is the case a thread could not have reported at all.
        state["state"] = "failed"
        state["error"] = (
            f"the run process died with code {rc}"
            + (" (SIGKILL - the pose backend took the interpreter down with it; "
               "try another backend)" if rc == -9 else "")
        )
    state["returncode"] = rc
    state["log"] = log[-40:]
    return state


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "barra-debugweb"
    # Keep-alive matters here: a browser scrubbing a video issues a burst of
    # range requests, and one TCP connection each makes seeking feel broken.
    # Safe because every response below sets an accurate Content-Length.
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str) -> None:
        path = HERE / name
        if not path.exists():
            return self._json(404, {"error": f"no {name}"})
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(path.suffix, "text/plain"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _video(self, name: str) -> None:
        """Serve the clip with Range support. Without it, seeking does not work
        in any browser, and a debug tool you cannot scrub is a poster frame."""
        clip = find_clip(name)
        if clip is None:
            return self._json(404, {"error": "no such clip"})
        size = clip.stat().st_size
        rng = self.headers.get("Range", "")
        start, end = 0, size - 1
        partial = False
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            partial = True
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:                                     # suffix range: last N bytes
                start = max(0, size - int(m.group(2)))
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with clip.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(262144, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return                            # the browser seeked away
                remaining -= len(chunk)

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query)

        if path == "/":
            return self._static("index.html")
        if path in ("/app.js", "/app.css"):
            return self._static(path.lstrip("/"))

        if path == "/api/clips":
            return self._json(200, {"clips": list_clips(),
                                    "backends": _backends()})
        if path == "/api/traces":
            return self._json(200, {"traces": list_traces()})
        if path == "/api/faultspec":
            return self._json(200, fault_spec())
        if path.startswith("/api/runs/"):
            state = run_state(path.rsplit("/", 1)[-1])
            return self._json(200 if state else 404, state or {"error": "no such run"})
        if path.startswith("/api/video/"):
            return self._video(path.split("/api/video/", 1)[1])
        if path.startswith("/api/keypoints/"):
            data = keypoints_json(path.rsplit("/", 1)[-1])
            return self._json(200 if data else 404,
                              data or {"error": "no cached keypoints for that clip"})
        if path.startswith("/api/parity/"):
            data = parity(path.rsplit("/", 1)[-1])
            return self._json(200 if data else 404,
                              data or {"error": "no payload stored for that trace"})
        if path.endswith("/payload") and path.startswith("/api/traces/"):
            tid = path.split("/api/traces/", 1)[1].rsplit("/", 1)[0]
            p = TRACES / f"{tid}.payload.json"
            if not SAFE.match(tid) or not p.exists():
                return self._json(404, {"error": "no payload for that trace"})
            return self._json(200, json.loads(p.read_text()))
        if path.startswith("/api/traces/"):
            p = trace_path(path.rsplit("/", 1)[-1])
            if p is None:
                return self._json(404, {"error": "no such trace"})
            return self._json(200, json.loads(p.read_text()))
        if path == "/api/diff":
            return self._diff(q.get("a", [""])[0], q.get("b", [""])[0])
        return self._json(404, {"error": "not found"})

    def _diff(self, a: str, b: str) -> None:
        import difflib

        from barra.trace import render

        pa, pb = trace_path(a), trace_path(b)
        if pa is None or pb is None:
            return self._json(404, {"error": "both a and b must name a trace"})
        # One renderer for live and replay - the invariant barra/trace.py:166
        # exists to protect. Rendering both sides through it means a diff shows
        # what changed in the run, not in the formatting.
        ta = render(json.loads(pa.read_text()), show="all").splitlines()
        tb = render(json.loads(pb.read_text()), show="all").splitlines()
        return self._json(200, {
            "a": pa.stem, "b": pb.stem,
            "diff": list(difflib.unified_diff(ta, tb, pa.stem, pb.stem, lineterm="", n=2)),
        })

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        if u.path.rstrip("/") != "/api/runs":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            return self._json(400, {"error": "bad json"})
        clip = find_clip(body.get("clip") or "")
        if clip is None:
            return self._json(400, {"error": "no such clip"})
        run_id = start_run(clip, body.get("exercise") or "auto",
                           bool(body.get("fresh")), body.get("backend") or "")
        return self._json(202, {"runId": run_id})


def _backends() -> list[str]:
    try:
        from barra.pose import available_backends

        return available_backends()
    except Exception:  # noqa: BLE001
        return []


def main() -> None:
    port = int(os.environ.get("PORT", "8091"))
    host = os.environ.get("HOST", "127.0.0.1")
    TRACES.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"barra debug  ->  http://{host}:{port}")
    print(f"  clips     {', '.join(str(d.relative_to(ROOT)) or '.' for d in clip_dirs())}")
    print(f"  traces    {TRACES}")
    print(f"  backends  {', '.join(_backends()) or 'none installed'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
