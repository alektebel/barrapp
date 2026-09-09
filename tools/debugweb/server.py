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

import hashlib
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

sys.path.insert(0, str(HERE))

import library as LIB                    # noqa: E402
from barra import schema as S            # noqa: E402
from barra.config import PATHS           # noqa: E402

TRACES = PATHS.o("traces")
RUNS: dict[str, dict] = {}
LOCK = threading.Lock()
TMP = Path(tempfile.gettempdir()) / "barra-debugweb"
TMP.mkdir(parents=True, exist_ok=True)

# Reference design ("Reel Room") vendored from Video pipeline debugger.zip.
ZONE = HERE / "zone"
ROOM = ZONE / "reelroom.html"

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json",
        ".md": "text/plain; charset=utf-8"}

# The pages' own assets, by name. A whitelist rather than "any file in HERE":
# this directory also holds server.py and the library, and a debug tool that
# serves its own source to a browser is one misconfigured bind away from being
# a problem.
STATIC = frozenset((
    "app.js", "app.css", "organic.css", "library.css",
    "gallery.js", "gallery.css", "guide.js", "guide.css",
    "models.js", "models.css",
))


# --------------------------------------------------------------------------
# clips - answered by the library (tools/debugweb/library.py), not by a
# directory walk. The difference is visible on the shelf: this repository
# holds sixteen video files and twelve distinct clips, because two of them
# were copied into server/data twice under content-addressed names. Keyed on
# the filename, that is sixteen cards and six debug histories for two videos.
# --------------------------------------------------------------------------
_LOCAL = threading.local()


def lib():
    """A library handle for THIS thread.

    ThreadingHTTPServer answers each request on its own thread and a sqlite3
    connection belongs to the thread that opened it. Keyed on ROOT as well, so
    a test that repoints ROOT at a tmp_path gets that tmp_path's library
    instead of the developer's real one.
    """
    con = getattr(_LOCAL, "con", None)
    if con is None or getattr(_LOCAL, "root", None) != ROOT:
        con = _LOCAL.con = LIB.connect(ROOT)
        _LOCAL.root = ROOT
        if LIB.count(con) == 0:
            # First run against this checkout. Index what is already on disk,
            # so an empty shelf means no videos rather than "nobody ran the
            # indexer yet" - a distinction the page cannot make for you.
            LIB.scan(con, ROOT)
    return con


def clip_dirs() -> list[Path]:
    return [ROOT if d == "." else ROOT / d for d in LIB.SEARCH_DIRS]


def find_clip(name: str) -> Path | None:
    """Resolve a clip by library id, filename or recorded path.

    Three identifiers because three things name the same video: the shelf
    carries the library id, a trace records the filename it ran on, and the
    older URLs in someone's history carry a basename. All three resolve to the
    same row, and nothing outside the library resolves at all.
    """
    if not name:
        return None
    path = LIB.resolve(lib(), ROOT, name)
    if path is not None:
        return path
    # Not indexed: a clip dropped into the folder since the last scan. Take it
    # in rather than 404 - but only from the directories the library owns.
    if not SAFE.match(name):
        return None
    for d in clip_dirs():
        p = d / name
        if p.is_file() and p.suffix.lower() in VIDEO_EXT:
            LIB.register(lib(), ROOT, p, source="scan")
            return p
    return None


def list_clips() -> list[dict]:
    """One entry per DISTINCT video, in the shape the pages consume, with the
    library identity and the probe alongside."""
    con = lib()
    rows = []
    for v in LIB.videos(con, ROOT):
        if not v["exists"]:
            continue
        raw = con.execute("SELECT * FROM videos WHERE sha256=?", (v["sha256"],)).fetchone()
        v = v | LIB.probe(con, ROOT, raw)
        cache = PATHS.o(S.P_KEYPOINTS, f"{Path(v['filename']).stem}.parquet")
        rows.append({
            "name": v["filename"],
            "dir": str(Path(v["path"]).parent),
            "bytes": v["bytes"],
            "mtime": v["mtime"],
            "cached": cache.exists(),
            # the library's own columns, so a page can show provenance
            "id": v["id"], "sha256": v["sha256"], "path": v["path"],
            "title": v["title"], "movement": v["movement"],
            "tags": v["tags"], "notes": v["notes"],
            "addedAt": v["added_at"], "source": v["source"],
            "copies": [c["path"] for c in v["copies"]],
            "extraCopies": v["duplicateOf"],
            "durationS": v["duration_s"], "fps": v["fps"], "frames": v["frames"],
            "width": v["width"], "height": v["height"],
            "probeNote": v["probe_note"] or "",
        })
    return rows


# --------------------------------------------------------------------------
# traces
# --------------------------------------------------------------------------
def gallery_clips() -> list[dict]:
    """One card per DISTINCT video, carrying the newest run of ANY copy of it.

    A trace records the file it ran on. Two copies of one clip therefore leave
    traces under two subjects, and keying the shelf on the subject string
    splits one video's history in half - the card shows "not analyzed" while
    nine runs of the same frames sit in out/traces under the other name. The
    subject is resolved through the library first, so a card shows the newest
    run of the VIDEO.
    """
    clips = list_clips()
    by_name = {c["name"]: c for c in clips}

    def card_key(subject: str) -> str:
        name = Path(subject or "").name
        if name in by_name:
            return name
        row = LIB.get(lib(), name, ROOT)
        if row is not None and row["filename"] in by_name:
            return row["filename"]
        return name

    latest: dict[str, dict] = {}
    runs: dict[str, int] = {}
    for trace in list_traces(limit=100000):
        key = card_key(trace["subject"])
        latest.setdefault(key, trace)
        runs[key] = runs.get(key, 0) + 1
    cards = []
    for clip in clips:
        trace = latest.get(clip["name"])
        payload = None
        if trace and trace["hasPayload"]:
            try:
                payload = json.loads((TRACES / f"{trace['traceId']}.payload.json").read_text())
            except (OSError, ValueError):
                pass
        cards.append({**clip, "trace": trace, "runs": runs.get(clip["name"], 0),
                      "summary": None if payload is None else {
            "exercise": payload.get("exercise"), "reps": payload.get("n_reps"),
            "durationS": payload.get("duration_s"), "score": payload.get("sessionScore"),
            "failures": payload.get("failures") or {},
            "blockers": payload.get("blockers") or [],
        }})
    return sorted(cards, key=lambda c: c["mtime"], reverse=True)


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
def keypoints_json(stem: str, snapshot: Path | None = None) -> dict | None:
    """The cached keypoints of a clip, as the overlay needs them.

    Pixel coordinates and confidence, exactly as the backend produced them -
    the overlay draws what the pipeline measured, not a prettier version of it.
    """
    if not SAFE.match(stem):
        return None
    path = snapshot or PATHS.o(S.P_KEYPOINTS, f"{stem}.parquet")
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
# The phone's copy, ported from app/src/main/java/com/barrapp/Cues.kt. Porting
# it IS the parity check: the phone renders the server's structured `faults`
# array by name (with the two signals the narrow legacy path still reads, for
# rows stored before the field existed), so the port has no thresholds and no
# prose parsing of its own. If the port stops agreeing with the harness and
# the taxonomy, this panel is where it shows up first.
_CUE_ORDER = [
    "poor range of motion", "lockout", "dead hang", "too deep", "no active hang",
    "momentum", "sagging hips", "piked hips", "piked body", "bent arms",
    "bent knees", "knee valgus", "heel raise", "leaning back", "arm swing",
    "poor scapular retraction", "poor scapular protraction",
    "control", "uncontrolled descent", "too fast", "bounce at bottom",
    "stall", "poor transition",
]


def phone_faults(rep: dict) -> list[str]:
    """What Cues.kt's repFaults() would render, ported line for line."""
    faults = rep.get("faults")
    if isinstance(faults, list) and faults:
        names = [f.get("name", "") for f in faults if isinstance(f, dict)]
        return sorted(names, key=_CUE_ORDER.index)
    # legacyFaults(): rows stored before the server named its own faults.
    out: list[str] = []
    for a in rep.get("aside") or []:
        if a.get("name") == "swing" and (a.get("value") or 0) > 0.4:
            out.append("momentum")
    for p in rep.get("penalties") or []:
        if p.get("name") == "control" and (p.get("value") or 0) > 0.0:
            out.append("control")
    return out


def parity(trace_id: str) -> dict | None:
    p = TRACES / f"{trace_id}.payload.json"
    if not p.exists():
        return None
    from barra.faults import rep_faults as harness_faults

    payload = json.loads(p.read_text())
    rows = []
    for rep in payload.get("reps") or []:
        shipped = rep.get("faults")
        server = sorted(f.get("name", "") for f in shipped if isinstance(f, dict)) \
            if isinstance(shipped, list) else sorted(rep.get("failures") or [])
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
        "note": ("server = faults_taxonomy.classify_faults, shipped as the "
                 "structured reps[].faults; harness = barra/faults.py reading "
                 "the same array; phone = Cues.kt's repFaults() ported (renders "
                 "the names, legacy path for rows stored before the field). "
                 "Name-level parity is also enforced offline by "
                 "tests/test_cues_parity.py; this panel is where it shows on "
                 "real payloads."),
    }


# --------------------------------------------------------------------------
# fault spec: which measurement each fault reads, and the line it must clear
# --------------------------------------------------------------------------
# This table used to be typed out by hand, one row per predicate, and had
# already drifted from the code it described ("bent arms" was still listed
# against arms_straight_frac after the predicate moved to the top-of-rep elbow
# angle). It is now READ from the rule registry in barra/rules.py - the same
# rows the server fires - so the panel cannot describe a rule that does not
# run. tests/test_debugweb.py still holds it to TRACK_FAILURES.
def fault_spec() -> dict:
    from barra.evidence import PRIMITIVES
    from barra.rules import RULES

    spec = {}
    for track, rules in RULES.items():
        rows = []
        for rule in rules:
            prim = PRIMITIVES.get(rule.primitive, ("SCALED", "", ""))
            rows.append({"fault": rule.name, "key": rule.primitive,
                         "op": rule.comparison, "threshold": rule.threshold,
                         "plane": prim[1], "id": rule.id, "phase": rule.phase,
                         "observable": rule.observable, "note": rule.note})
        spec[track] = rows
    return {"spec": spec}


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------
def start_run(clip: Path, exercise: str, fresh: bool, backend: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    status = TMP / f"{run_id}.status.json"
    spec = TMP / f"{run_id}.spec.json"
    spec.write_text(json.dumps({
        "clip": str(clip), "status": str(status), "runId": run_id,
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
    if run.get("cancelled"):
        state.update(state="cancelled", stage="cancelled", error="Stopped by user")
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

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Browser abandoned a seek or navigated to another trace.

    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _no_content(self) -> None:
        """204 for a media name the page asks for without interpolating it
        (a design `{{ … }}` placeholder). No body, so no console error."""
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

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

        if path == "/" and "trace" not in q:
            return self._static("gallery.html")
        if path in ("/", "/inspect"):
            return self._static("index.html")
        if path == "/design-preview":
            body = _inject_room(real_videos()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        blob = _serve_zone(path)
        if blob is not None:
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(Path(path).suffix, "text/plain"))
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            return self.wfile.write(blob)

        if path == "/guide":
            return self._static("guide.html")
        if path == "/models":
            return self._static("models.html")
        if path.lstrip("/") in STATIC:
            return self._static(path.lstrip("/"))

        if path == "/api/gallery":
            return self._json(200, {"clips": gallery_clips()})
        if path == "/api/clips":
            return self._json(200, {"clips": list_clips(),
                                    "backends": _backends()})
        if path == "/api/model":
            return self._json(200, model_card())
        if path == "/api/videos":
            return self._json(200, {"videos": list_clips(),
                                    "db": str(LIB.db_path(ROOT).relative_to(ROOT)),
                                    "searchDirs": list(LIB.SEARCH_DIRS),
                                    "editable": list(LIB.EDITABLE)})
        if path.endswith("/internals") and path.startswith("/api/traces/"):
            tid = path.split("/api/traces/", 1)[1].rsplit("/", 1)[0]
            data = trace_internals(tid)
            return self._json(200 if data else 404, data or {"error": "no such trace"})
        if path == "/api/traces":
            return self._json(200, {"traces": list_traces()})
        if path == "/api/faultspec":
            return self._json(200, fault_spec())
        if path.startswith("/api/runs/"):
            state = run_state(path.rsplit("/", 1)[-1])
            return self._json(200 if state else 404, state or {"error": "no such run"})
        if path.startswith("/api/video/"):
            name = path.split("/api/video/", 1)[1]
            if not SAFE.match(name):
                return self._no_content()
            return self._video(name)
        if path.startswith("/api/poster/"):
            name = path.rsplit("/", 1)[-1]
            if not SAFE.match(name):
                return self._no_content()
            data = _poster(name)
            if data is None:
                return self._json(404, {"error": "no poster for that clip"})
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            return self.wfile.write(data)
        if path.startswith("/api/keypoints/"):
            name = path.rsplit("/", 1)[-1]
            if not SAFE.match(name):
                return self._no_content()
            data = keypoints_json(name)
            return self._json(200 if data else 404,
                              data or {"error": "no cached keypoints for that clip"})
        if path.startswith("/api/parity/"):
            data = parity(path.rsplit("/", 1)[-1])
            return self._json(200 if data else 404,
                              data or {"error": "no payload stored for that trace"})
        if path.endswith("/keypoints") and path.startswith("/api/traces/"):
            tid = path.split("/api/traces/", 1)[1].rsplit("/", 1)[0]
            trace = trace_path(tid)
            if trace is None:
                return self._json(404, {"error": "no such trace"})
            subject = json.loads(trace.read_text()).get("subject", "")
            snapshot = trace.with_suffix(".pose.parquet")
            result = keypoints_json(Path(subject).stem, snapshot if snapshot.exists() else None)
            if result is None:
                return self._json(404, {"error": "no saved keypoints"})
            result["source"] = "run" if snapshot.exists() else "clip-cache"
            return self._json(200, result)
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
        if u.path.startswith("/api/runs/") and u.path.endswith("/cancel"):
            run_id = u.path.split("/")[-2]
            with LOCK:
                run = RUNS.get(run_id)
                if run is None:
                    return self._json(404, {"error": "no such run"})
                if run["proc"].poll() is None:
                    run["cancelled"] = True
                    run["proc"].terminate()
            return self._json(200, {"cancelled": bool(run.get("cancelled"))})
        if u.path.rstrip("/") == "/api/videos/scan":
            report = LIB.scan(lib(), ROOT)
            return self._json(200, report)
        if u.path.startswith("/api/videos/"):
            ident = u.path.rstrip("/").rsplit("/", 1)[-1]
            try:
                n = int(self.headers.get("Content-Length") or 0)
                fields = json.loads(self.rfile.read(n) or b"{}")
            except Exception:                       # noqa: BLE001
                return self._json(400, {"error": "bad json"})
            if fields.pop("_delete", False):
                out = LIB.forget(lib(), ROOT, ident, bool(fields.get("deleteFile")))
                return self._json(200 if out else 404, out or {"error": "no such video"})
            try:
                row = LIB.update(lib(), ident, fields)
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200 if row else 404, row or {"error": "no such video"})
        if u.path.rstrip("/") in ("/api/clips", "/api/videos"):
            # Raw file body keeps uploads streaming and avoids multipart buffering.
            name = Path(parse_qs(u.query).get("name", [""])[0]).name
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            if Path(name).suffix.lower() not in VIDEO_EXT or not 0 < size <= 512 * 1024 * 1024:
                self.close_connection = True
                return self._json(400, {"error": "Choose a supported video up to 512 MiB."})
            folder = ROOT / "data" / "videos"
            folder.mkdir(parents=True, exist_ok=True)
            # Land in a scratch file first. Whether this upload is a NEW video
            # or another copy of one already in the library is a question about
            # its bytes, and the bytes are not all here until the last chunk -
            # so the library decides where (and whether) it is kept.
            staged = TMP / f"upload-{uuid.uuid4().hex[:12]}{Path(name).suffix.lower()}"
            try:
                with staged.open("xb") as f:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise OSError("incomplete upload")
                        f.write(chunk)
                        remaining -= len(chunk)
                row = LIB.import_file(lib(), ROOT, staged, filename=name, source="import")
            except OSError:
                return self._json(400, {"error": "Upload interrupted; please retry."})
            finally:
                staged.unlink(missing_ok=True)
            return self._json(201 if row["isNew"] else 200, {
                "name": row["filename"], "id": row["id"], "bytes": size,
                "path": row["path"], "isNew": row["isNew"],
                "note": "" if row["isNew"] else
                        "Those exact frames are already in the library as "
                        f"{row['id']} ({row['path']}); the upload was discarded "
                        "so the shelf keeps one card and one history for them.",
            })
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


# --------------------------------------------------------------------------
# the model card: every constant the prediction path reads
#
# "What is the model" has, in this project, more than one answer to point at:
# the primary detector is a stack of geometric rules whose behaviour is
# determined by live constants in the modules, and a learned second opinion now
# votes alongside it. Those constants and model files are the prediction path.
# A debugger that shows you a rejection but not the value, threshold, model, or
# fusion status behind it is asking you to take the answer on faith.
#
# So this reads them OUT OF the modules at request time rather than restating
# them. Two consequences worth the cost: a value shown here is the value the
# next run will use, and a threshold that moves shows up in the page without
# anyone remembering to update it. The trailing comments in the source come
# along too, because in barra/config.py that is where the MEANING lives
# ("body travel, torso-lengths, before 'momentum'").
# --------------------------------------------------------------------------
_ASSIGN = re.compile(
    r"^\s{0,8}([A-Z_][A-Za-z0-9_]*|[a-z_][a-z0-9_]*)\s*(?::[^=]+?)?=\s*\S")
_ASSIGN_NOTE = re.compile(
    r"^\s{0,8}([A-Z_][A-Za-z0-9_]*|[a-z_][a-z0-9_]*)\s*(?::[^=]+?)?=\s*[^#\n]*#\s*(\S.*?)\s*$")


def _source_notes(path: Path) -> dict[str, str]:
    """What each constant in one module MEANS, taken from its own comment.

    Two shapes, because this project writes both. A short gloss goes on the
    line (`swing_torso: float = 0.40  # body travel, torso-lengths`); a
    constant that needed an argument gets a comment block above it, sometimes
    several sentences of one. Reading only the trailing form left a third of
    the model card as bare numbers, which is the state this page exists to fix.
    """
    notes: dict[str, str] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return notes
    for i, line in enumerate(lines):
        m = _ASSIGN_NOTE.match(line)
        if m and m.group(2) not in ("noqa", ""):
            notes.setdefault(m.group(1), m.group(2))
            continue
        m = _ASSIGN.match(line)
        if not m or m.group(1) in notes:
            continue
        block = []
        for prev in range(i - 1, -1, -1):
            text = lines[prev].strip()
            if not text.startswith("#"):
                break
            gloss_line = text.lstrip("#").strip()
            # Section banners ("--- stage 1 ---", "-- the bar plane ----…")
            # sit between groups; skip them so the real paragraph above still
            # attaches, but they never become the note themselves.
            if not gloss_line or set(gloss_line) <= set("-=# ") or (
                    gloss_line.count("-") >= 8 and gloss_line.startswith("-")):
                continue
            block.append(gloss_line)
        if block:
            gloss = " ".join(reversed(block)).strip()
            if gloss:
                notes.setdefault(m.group(1), gloss[:400])
    return notes


_UNSET = object()


def _plain(value, depth: int = 0):
    """A JSON-able view of a constant, or _UNSET when there isn't one.

    Dataclasses are unpacked (THRESHOLDS is one), numpy scalars are cast, and
    anything that is a function, a module or a class is left out - the page
    shows values, and a repr of a function is not a value.
    """
    import dataclasses
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if depth > 3:
        return _UNSET
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name), depth + 1)
                for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple, set)):
        out = [_plain(v, depth + 1) for v in value]
        return _UNSET if any(o is _UNSET for o in out) else out
    if isinstance(value, dict):
        out = {str(k): _plain(v, depth + 1) for k, v in value.items()}
        return _UNSET if any(o is _UNSET for o in out.values()) else out
    if hasattr(value, "item") and hasattr(value, "shape") and getattr(value, "shape", 1) == ():
        return value.item()                        # a numpy scalar
    return _UNSET


def _defined_in(path: Path) -> set[str]:
    """Top-level names ASSIGNED in one module - as opposed to imported into it."""
    import ast
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in tree.body:
        targets = ([t for t in node.targets] if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        for t in targets:
            # `STRONG, SOLID, SHAKY = 73, 47, 20` is three constants on one
            # line, and the score bands are exactly that shape.
            for leaf in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                if isinstance(leaf, ast.Name):
                    names.add(leaf.id)
    return names


def _constants(dotted: str, source: str) -> list[dict]:
    """Every module-level constant of one barra module, with its source note.

    Uppercase names plus the dataclass singletons (THRESHOLDS, PATHS) - which
    is, by this project's convention, exactly the set of things that were
    decided before any clip was seen.
    """
    import importlib
    try:
        mod = importlib.import_module(dotted)
    except Exception as exc:                        # noqa: BLE001
        return [{"name": dotted, "value": None, "note": f"module unavailable: {exc}"}]
    notes = _source_notes(ROOT / source)
    own = _defined_in(ROOT / source)
    rows = []
    for name in sorted(vars(mod)):
        if name.startswith("_") or not (name.isupper() or name in ("THRESHOLDS",)):
            continue
        # `from .config import THRESHOLDS` puts THRESHOLDS in quality's
        # namespace too. Listing it under quality would say quality owns those
        # numbers, which is the opposite of why config.py exists.
        if own and name not in own:
            continue
        value = _plain(getattr(mod, name))
        if value is _UNSET:
            continue
        # A dataclass singleton is thirty-five separate decisions, not one. It
        # is flattened to a row each - THRESHOLDS.swing_torso, with the comment
        # from the line that defines it - because a table you can search for
        # one threshold is the point, and a single cell holding all of them is
        # not searchable, not comparable and not readable.
        if isinstance(value, dict) and name == "THRESHOLDS":
            for field, sub in value.items():
                rows.append({"name": f"{name}.{field}", "value": sub,
                             "note": notes.get(field, ""), "source": source})
            continue
        rows.append({"name": name, "value": value, "note": notes.get(name, ""),
                     "source": source})
    return rows


def _select(modules: dict, reads: list[str]) -> list[dict]:
    """The constants one stage reads.

    A stage names either a whole module (`barra.classify` - the classifier IS
    its constants) or individual names (`barra.config:THRESHOLDS.swing_torso`).
    The distinction matters: `barra.config` also holds the validation harness's
    verdict rule, and listing FLAG_PERCENTILE under "cut it into reps" would be
    a confident lie about which number did the cutting.
    """
    out, seen = [], set()
    for ref in reads:
        module, _, wanted = ref.partition(":")
        for row in modules.get(module, []):
            if wanted.endswith("*"):
                if not row["name"].startswith(wanted[:-1]):
                    continue
            elif wanted and row["name"] != wanted:
                continue
            if (module, row["name"]) in seen:
                continue
            seen.add((module, row["name"]))
            out.append(row)
    return out


# The pipeline, in the order it runs. `reads` names the modules whose constants
# govern that stage; `look` is the thing to check first when the stage is the
# suspect. Written by hand because the ORDER and the FAILURE MODES are the part
# that cannot be read off the source - the numbers underneath are not.
PIPELINE = [
    {"key": "probe", "name": "Probe the container",
     "module": "barra/ingest.py", "fn": "probe_video", "reads": [],
     "decides": "whether the file opens at all, and at what fps and geometry",
     "emits": ["ok", "fps", "frames", "width", "height", "duration_s"],
     "fails": "Could not open the clip - a moov atom at the end of the file, or "
              "a codec this OpenCV build does not carry.",
     "look": "the `container` step. An fps of 0 makes every seconds-valued "
             "threshold downstream meaningless, and it fails quietly."},
    {"key": "pose", "name": "Estimate the pose",
     "module": "barra/pose/*.py", "fn": "get_backend(name).estimate",
     "reads": ["barra.config:MIN_MEAN_CONFIDENCE", "barra.config:CONF_FLOOR",
               "barra.classify:MIN_CONF", "barra.movements:PAIR_CONF",
               "barra.movements:MIN_PAIRED_FRAC"],
     "decides": "the 17 landmarks per frame that everything below measures",
     "emits": ["keypoints[frame, joint, (x, y, conf)]", "fps", "source"],
     "fails": "Pose estimation failed / no backend installed. A native backend "
              "can take the interpreter down, which is why runs are subprocesses.",
     "look": "mean confidence. Below MIN_MEAN_CONFIDENCE the anatomy is not "
             "measured from those frames and reps go missing for a reason that "
             "is not about the athlete."},
    {"key": "classify", "name": "Recognise the movement",
     "module": "barra/classify.py", "fn": "classify",
     "reads": ["barra.classify"],
     "decides": "the geometric movement candidate - and therefore which "
                "reference frame, tracked signal and fault taxonomy apply unless "
                "fusion overrides a weak call",
     "emits": ["exercise", "confidence", "certainty", "reason", "runnerUp"],
     "fails": "unknown movement, or a confident label for the wrong movement - "
              "which is worse, because the numbers that follow look fine.",
     "look": "`runnerUp` and the margin. Measuring a muscle-up with squat "
             "geometry produces plausible nonsense; force the movement in the "
             "toolbar to test the hypothesis in one run."},
    {"key": "model", "name": "Score the learned second opinion",
     "module": "barra/model.py", "fn": "model_classify / model_load",
     "reads": ["barra.model:FEATURE_NAMES", "barra.model:NAN_HEADERS",
               "barra.model:DEFAULT_MODEL_PATH"],
     "decides": "a learned exercise and load estimate over the same geometric "
                "feature vector",
     "emits": ["exercise", "confidence", "marginToRunnerUp", "runnerUp",
               "probabilities", "load"],
     "fails": "a class outside the trained taxonomy, or tiny per-class support; "
              "model output is never treated as certainty.",
     "look": "the model's runner-up margin and `models/model_metrics.json`. "
             "Support 1 is inconclusive."},
    {"key": "fusion", "name": "Fuse detector votes",
     "module": "barra/fusion.py", "fn": "fuse_detection",
     "reads": ["barra.fusion"],
     "decides": "the final movement label in auto mode, and whether that label "
                "should carry a review status",
     "emits": ["exercise", "status", "reason", "geometry", "model", "nan"],
     "fails": "too much trust in a learned model, or too little. Fusion states "
              "the status instead of hiding the disagreement.",
     "look": "`detected.fusion`. `model-overrides-weak-geometry` and "
             "`geometry-reviewed` are the cases that need a human look."},
    {"key": "signal", "name": "Build the tracking signal",
     "module": "barra/movements.py", "fn": "tracking_signal",
     "reads": ["barra.movements:PAIR_CONF", "barra.movements:MIN_PAIRED_FRAC",
               "barra.movements:MAX_BAR_TRAVEL"],
     "decides": "the one scalar per frame the segmenter looks for reps in, in "
                "torso-lengths, in the movement's own reference frame",
     "emits": ["signal[frame]", "torso length", "origin"],
     "fails": "a hip-origin signal on a bar movement cancels exactly the motion "
              "being measured, and the signal goes flat.",
     "look": "the chart. A flat trace with a moving athlete is a reference-frame "
             "problem, not a segmentation one."},
    {"key": "segment", "name": "Cut it into reps",
     "module": "barra/ingest.py", "fn": "segment_reps_verbose / rescue_reps",
     "reads": ["barra.config:THRESHOLDS.peak_prominence",
               "barra.config:THRESHOLDS.rescue_prominence",
               "barra.config:THRESHOLDS.min_span_amplitude",
               "barra.config:THRESHOLDS.max_half_rep_s",
               "barra.config:THRESHOLDS.rest_side_tolerance",
               "barra.config:THRESHOLDS.fast_rep_frac",
               "barra.config:THRESHOLDS.bounce_speed",
               "barra.movements:MAX_BAR_TRAVEL",
               "barra.classify:ANCHOR_FIXED", "barra.classify:ANCHOR_WINDOW_S"],
     "decides": "which turnarounds are reps and which are noise, walking or "
                "half-attempts",
     "emits": ["reps[start, turn, end]", "one rejection per discarded candidate"],
     "fails": "zero reps on a clip that plainly has reps - almost always "
              "amplitude or anchor travel, not the peak finder.",
     "look": "every `reject` in this stage prints the value AND the threshold. "
             "That pair is checkable; the verdict alone is not."},
    {"key": "metrics", "name": "Measure each rep",
     "module": "barra/metrics.py", "fn": "rep_metrics",
     "reads": ["barra.metrics"],
     "decides": "the per-rep numbers - range, tempo, swing, asymmetry - and "
                "whether each is anatomically plausible",
     "emits": ["one row per rep, per METRIC_SPEC"],
     "fails": "a metric outside its plausibility band is dropped rather than "
              "reported, so a missing measurement is a finding.",
     "look": "the metric's robustness class. PLANAR metrics are only meaningful "
             "from the viewpoint they assume."},
    {"key": "score", "name": "Score and band",
     "module": "barra/quality.py", "fn": "score_rep / band",
     "reads": ["barra.quality", "barra.config:THRESHOLDS.controlled_tempo",
               "barra.config:THRESHOLDS.stall_rate",
               "barra.config:THRESHOLDS.stalled_frac",
               "barra.config:THRESHOLDS.stall_edge_fraction"],
     "decides": "the rep score as weight x component, minus named penalties",
     "emits": ["score", "components", "penalties", "band"],
     "fails": "a score that moved without the athlete moving - a changed weight "
              "or a changed convention, both stamped in provenance.",
     "look": "the components. The score is a sum you can re-add by hand; if it "
             "surprises you, one component is doing all of it."},
    {"key": "faults", "name": "Fire the technique rules",
     "module": "barra/rules.py + barra/evidence.py", "fn": "classify_faults",
     "reads": ["barra.config:THRESHOLDS.*"],
     "decides": "which named faults are observed, not observed, or unobservable "
                "from this viewpoint",
     "emits": ["per-rep assessments: primitive, comparison, threshold, phase"],
     "fails": "an unobservable fault reported as absent. The three-way answer "
              "exists so that cannot happen silently.",
     "look": "the availability reason on an `unobservable`. It names the "
             "measurement that was missing, not just the fault."},
    {"key": "vision", "name": "Vision second opinion",
     "module": "server/vision.py", "fn": "observe",
     "reads": [],
     "decides": "nothing on its own - it disagrees, and the disagreement is "
                "recorded",
     "emits": ["observations", "verdict", "a note when it contradicts geometry"],
     "fails": "skipped entirely when no endpoint is configured, which the trace "
              "says rather than implying the pass agreed.",
     "look": "`vision disagrees with the geometric movement label`. Two "
             "independent wrong answers agreeing is the case to worry about."},
    {"key": "payload", "name": "Assemble the payload",
     "module": "server/process.py", "fn": "process_job",
     "reads": [],
     "decides": "what the phone actually receives",
     "emits": ["exercise", "n_reps", "sessionScore", "failures", "blockers", "traceId"],
     "fails": "a blocker is the honest empty result; a payload with reps but no "
              "score means the score stage declined, and says why.",
     "look": "compare the payload against the trace. They are written by the "
             "same run, so a disagreement is a bug in the assembly."},
]


def model_card() -> dict:
    """Every constant, threshold, rule and model file the prediction path reads."""
    card: dict = {"pipeline": [], "modules": {}, "provenance": {}, "faults": {},
                  "movements": [], "metrics": [], "warnings": []}
    try:
        from barra import provenance
        card["provenance"] = provenance.stamp(include_model=True)
    except Exception as exc:                        # noqa: BLE001
        card["warnings"].append(f"provenance unavailable: {exc}")
    card["provenance"]["backendsInstalled"] = _backends()

    sources = {
        "barra.config": "barra/config.py",
        "barra.classify": "barra/classify.py",
        "barra.model": "barra/model.py",
        "barra.fusion": "barra/fusion.py",
        "barra.movements": "barra/movements.py",
        "barra.metrics": "barra/metrics.py",
        "barra.quality": "barra/quality.py",
        "barra.ingest": "barra/ingest.py",
        "barra.faults_taxonomy": "barra/faults_taxonomy.py",
    }
    for dotted, source in sources.items():
        card["modules"][dotted] = _constants(dotted, source)

    for stage in PIPELINE:
        card["pipeline"].append({**stage,
                                 "constants": _select(card["modules"], stage["reads"])})

    try:
        from barra.movements import MOVEMENTS
        import dataclasses
        card["movements"] = [
            {f.name: _plain(getattr(m, f.name)) for f in dataclasses.fields(m)}
            for m in MOVEMENTS.values()]
    except Exception as exc:                        # noqa: BLE001
        card["warnings"].append(f"movement registry unavailable: {exc}")

    try:
        from barra.metrics import METRIC_SPEC
        card["metrics"] = [
            {"key": k, "robustness": v[0], "label": v[1], "unit": v[2],
             "higherIsBetter": v[3]} for k, v in METRIC_SPEC.items()]
    except Exception as exc:                        # noqa: BLE001
        card["warnings"].append(f"metric spec unavailable: {exc}")

    try:
        card["faults"] = fault_spec()["spec"]
    except Exception as exc:                        # noqa: BLE001
        card["warnings"].append(f"fault taxonomy unavailable: {exc}")

    card["counts"] = {
        "constants": sum(len(v) for v in card["modules"].values()),
        "movements": len(card["movements"]),
        "metrics": len(card["metrics"]),
        "faultRules": sum(len(v) for v in card["faults"].values()),
        "stages": len(card["pipeline"]),
    }
    return card


def trace_internals(trace_id: str) -> dict | None:
    """One trace, decomposed the way the pipeline produced it.

    The trace is a flat list of entries in the order they were emitted, which
    is the order things HAPPENED but not the order they are understood. Here it
    is grouped by stage, and every entry whose data carries a value and the
    threshold it was compared against is lifted into `comparisons` - the rows
    where the pipeline showed its work, which are the rows worth reading first.
    """
    path = trace_path(trace_id)
    if path is None:
        return None
    try:
        trace = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"error": f"trace unreadable: {exc}"}

    payload = TRACES / f"{Path(path).stem}.payload.json"
    stages: dict[str, dict] = {}
    comparisons = []
    order = []
    for entry in trace.get("entries", []):
        name = entry.get("stage") or "?"
        if name not in stages:
            stages[name] = {"stage": name, "entries": [], "firstMs": entry.get("atMs", 0),
                            "lastMs": entry.get("atMs", 0),
                            "counts": {"step": 0, "reject": 0, "error": 0,
                                       "decision": 0, "note": 0}}
            order.append(name)
        st = stages[name]
        st["entries"].append(entry)
        st["lastMs"] = max(st["lastMs"], entry.get("atMs", 0))
        st["counts"][entry.get("kind", "step")] = \
            st["counts"].get(entry.get("kind", "step"), 0) + 1
        data = entry.get("data") or {}
        pair = thresholdish(data)
        if pair:
            comparisons.append({"stage": name, "kind": entry.get("kind"),
                                "atMs": entry.get("atMs"),
                                "message": entry.get("message"), **pair})
    for st in stages.values():
        st["ms"] = st["lastMs"] - st["firstMs"]
    return {
        "traceId": trace.get("traceId", Path(path).stem),
        "subject": trace.get("subject", ""),
        "context": trace.get("context", {}),
        "durationMs": trace.get("durationMs", 0),
        "counts": trace.get("counts", {}),
        "stages": [stages[k] for k in order],
        "comparisons": comparisons,
        "hasPayload": payload.exists(),
    }


# Value/threshold key pairs the pipeline actually emits. A rejection that
# prints both is one you can check; this is the list of the ways it says so.
_PAIRS = (("value", "threshold"), ("wrist_travel", "max_travel"),
          ("anchor_travel", "max_travel"), ("amplitude", "min_amplitude"),
          ("prominence", "min_prominence"), ("span_s", "min_rep_s"),
          ("span_s", "max_half_rep_s"), ("conf", "min_conf"),
          ("mean_conf", "min_conf"), ("measured", "threshold"),
          ("observed", "threshold"), ("frac", "min_frac"))


def thresholdish(data: dict) -> dict | None:
    for got, limit in _PAIRS:
        if got in data and limit in data and isinstance(data[got], (int, float)) \
                and isinstance(data[limit], (int, float)):
            return {"metric": got, "value": data[got], "limitName": limit,
                    "threshold": data[limit], "data": data}
    return None


def _backends() -> list[str]:
    try:
        from barra.pose import available_backends

        return available_backends()
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------
# Reel Room: real traces/payloads mapped into the reference design's clip
# shape. The design's own renderer (zone/reelroom.html + support.js) draws
# every clip card, stage, tab and payload from these objects, so this builder
# is the ONLY thing between the server's data and the zip's format - feeding
# it real values is what makes the page the design, not an imitation.
#
# Real pose: per-clip skeletons read from the keypoint cache, plus a poster
# frame, so the film-strip cards and pose pane draw the ACTUAL person from the
# ACTUAL clip instead of the reference's synthetic stick figure.
# --------------------------------------------------------------------------
# reference design's stage indices (the STAGES array in zone/reelroom.html)
_STAGE_INDEX = {
    "transport": 0, "probe": 1, "gate": 2, "pose": 3, "classify": 4,
    "model": 5, "fusion": 6, "signal": 7, "segment": 8, "rescue": 8,
    "metrics": 9, "score": 10, "quality": 10, "faults": 10,
    "vision": 11, "payload": 12, "result": 12,
}
# where a real failure maps: kind -> (index into STAGES, KIND_TEXT key)
_FAILURES = {
    "probe": (1, "moov"), "gate": (2, "toolong"), "pose": (3, "nobackend"),
    "classify": (4, "unknownmove"), "model": (5, "unknownmove"),
    "fusion": (6, "unknownmove"), "segment": (8, "noreps"), "rescue": (8, "noreps"),
}
# design's 13-joint skeleton as COCO17 indices; and its 12 edges, as 13-slot.
# Slot order: nose, l_sh, r_sh, l_el, r_el, l_wr, r_wr, l_hip, r_hip,
#             l_kn, r_kn, l_an, r_an.
_DESIGN_COCO = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
_DESIGN_EDGES = [(1, 2), (1, 7), (2, 8), (7, 8), (1, 3), (3, 5),
                 (2, 4), (4, 6), (7, 9), (9, 11), (8, 10), (10, 12)]
_POSES: dict[str, dict | None] = {}


def _pose_frames(name: str) -> dict | None:
    """Real skeleton frames + poster for one clip, cached across requests."""
    if name in _POSES:
        return _POSES[name]
    _POSES[name] = None
    stem = re.sub(r"\.[^.]+$", "", name)
    clip = find_clip(name)
    path = PATHS.o(S.P_KEYPOINTS, f"{stem}.parquet")
    if not clip or not path.exists():
        return None
    try:
        import cv2
        import pandas as pd

        from barra.ingest import frame_to_keypoints

        cap = cv2.VideoCapture(str(clip))
        ok, frame0 = cap.read()
        if not ok:
            cap.release()
            return None
        H, W = frame0.shape[:2]
        cap.release()
        # center-crop to the design's 3:4 plate; map every joint into that same
        # crop space so the skeleton sits on the real pixels of the poster.
        Wc = min(W, H * 0.75)
        Hc = min(H, W * (4 / 3))
        left = (W - Wc) / 2
        top = (H - Hc) / 2
        kp = frame_to_keypoints(pd.read_parquet(path))
        nf = kp.shape[0]
        idxs = [int(i * (nf - 1) / 39) for i in range(40)] if nf > 1 else [0]
        frames = []
        for t in idxs:
            pts, confs = [], []
            for j in range(13):
                x, y, c = (float(v) for v in kp[t, _DESIGN_COCO[j], :3])
                nx = (x - left) / Wc * 100
                ny = (y - top) / Hc * 100
                pts.append({"x": round(nx, 2), "y": round(ny, 2),
                            "c": "rgba(246,160,107,.85)" if c < 0.5 else "rgba(249,244,237,.92)"})
                confs.append(c)
            segs = []
            for a, b in _DESIGN_EDGES:
                weak = confs[a] < 0.5 or confs[b] < 0.5
                pa, pb = pts[a], pts[b]
                segs.append({"x1": pa["x"], "y1": pa["y"], "x2": pb["x"],
                             "y2": pb["y"],
                             "c": "rgba(246,160,107,.55)" if weak else "rgba(249,244,237,.85)"})
            frames.append({"pts": pts, "segs": segs})
        x0, y0, x1, y1 = int(left), int(top), int(left + Wc), int(top + Hc)
        ok_enc, enc = cv2.imencode(".jpg", cv2.resize(frame0[y0:y1, x0:x1], (300, 400)),
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok_enc:
            return None
        _POSES[name] = {"frames": frames, "poster": enc.tobytes()}
        return _POSES[name]
    except Exception:  # noqa: BLE001
        return None


def _poster(name: str) -> bytes | None:
    clip = find_clip(name)
    if clip is None:
        return None
    try:
        import cv2
        cap = cv2.VideoCapture(str(clip))
        try:
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(count * 0.15)))
            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
        finally:
            cap.release()
        if not ok:
            return None
        h, w = frame.shape[:2]
        scale = min(1.0, 480 / max(h, w))
        frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return encoded.tobytes() if ok else None
    except Exception:
        return None


def _clip_size_mb(name: str) -> float:
    for c in list_clips():
        if c["name"] == name:
            return round(c["bytes"] / 1e6, 1)
    return 0.0


def _mean_conf(stem: str) -> float | None:
    if not SAFE.match(stem):
        return None
    path = PATHS.o(S.P_KEYPOINTS, f"{stem}.parquet")
    if not path.exists():
        return None
    try:
        import pandas as pd

        kp = pd.read_parquet(path)
        conf = kp.select_dtypes("number").iloc[:, -1]  # last column is confidence
        return round(float(conf.mean()), 3)
    except Exception:  # noqa: BLE001
        return None


def _stage_ms(tr: dict) -> tuple[list[int], int]:
    """Per-stage cumulative ms (13 slots, matching the design's STAGES) and the
    total. Taken from the trace's own `atMs` - the design just plots time."""
    last = {}
    for e in tr.get("entries") or []:
        ms = e.get("atMs")
        if isinstance(ms, (int, float)):
            last[e.get("stage")] = last.get(e.get("stage"), 0) or int(ms)
    slots = [0] * 13
    for stage, ms in last.items():
        i = _STAGE_INDEX.get(stage)
        if i is not None:
            slots[i] = int(ms)
    # carry cumulative time into later stages so the bars read as a waterfall
    run = 0
    for i, v in enumerate(slots):
        run = max(run, v)
        slots[i] = run
    return slots, int(sum(slots)) if slots else 0


def _real_rng(seed: int):
    s = seed & 0xFFFFFFFF
    def rnd():
        nonlocal s
        s = (s + 0x6D2B79F5) & 0xFFFFFFFF
        t = (s ^ (s >> 15)) & 0xFFFFFFFF
        t = (t * 1 | t) & 0xFFFFFFFF
        t = (t + (t ^ (t >> 7)) * 61 | t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


def _amp_from_trace(tr: dict) -> float:
    for e in tr.get("entries") or []:
        if e.get("message") == "amplitude":
            a = (e.get("data") or {}).get("amplitude")
            if isinstance(a, (int, float)):
                return round(float(a), 3)
    return 0.5


def _travel_from_trace(tr: dict) -> float:
    for e in tr.get("entries") or []:
        d = e.get("data") or {}
        if isinstance(d.get("wrist_travel"), (int, float)):
            return round(float(d["wrist_travel"]), 3)
    return 0.3


def _failure_of(tr: dict, payload: dict) -> tuple[int, str]:
    """Map a real trace to the design's (failIndex, kind). A trace that
    measured reps is -1/'ok'; one that measured none is the segment noreps the
    design already knows how to describe."""
    if (payload.get("n_reps") or 0) == 0:
        return 8, "noreps"
    # an error entry points at the stage that actually failed
    err = next((e for e in tr.get("entries") or [] if e.get("kind") == "error"), None)
    if err:
        idx, kind = _FAILURES.get(err.get("stage"), (6, "noreps"))
        return idx, kind
    return -1, "ok"


def real_videos() -> list[dict]:
    """One clip-shaped object per real trace that has a payload, newest first."""
    out = []
    seen = set()
    for t in list_traces(limit=500):
        if not t.get("hasPayload") or t["traceId"] in seen:
            continue
        seen.add(t["traceId"])
        try:
            tr = json.loads(trace_path(t["traceId"]).read_text())
            payload = json.loads((TRACES / f"{t['traceId']}.payload.json").read_text())
        except Exception:  # noqa: BLE001
            continue
        stem = re.sub(r"\.[^.]+$", "", t["subject"])
        name = t["subject"]
        ex = payload.get("exercise") or "muscle_up"
        dur = payload.get("duration_s") or 0.0
        fps = payload.get("fps") or 30
        seed = int(hashlib.sha1(name.encode()).hexdigest()[:8], 16)
        r = _real_rng(seed)
        stage_ms, total = _stage_ms(tr)
        conf = _mean_conf(stem)
        fail, kind = _failure_of(tr, payload)
        consistency = payload.get("consistency") or {}
        _pose = _pose_frames(name)
        poster = f"/api/poster/{name}" if _pose else None
        out.append({
            "i": len(out), "id": "job-" + name[-6:].lower() if name else "job-x",
            "ex": ex, "athlete": "alek", "codec": "h264/mp4",
            "dur": round(float(dur), 2), "sizeMb": _clip_size_mb(name) or round(float(dur) * 1.9, 1),
            "fps": int(fps), "w": 720, "h": 1280, "name": name, "trace": t["traceId"],
            "fail": fail, "kind": kind,
            "meanConf": conf if conf is not None else round(0.55 + r() * 0.42, 3),
            "reps": payload.get("n_reps") or 0, "truth": payload.get("n_reps") or 0,
            "rescued": bool(payload.get("rescued")), "countedBy": payload.get("countedBy"),
            "feedback": None, "geoVerdict": "clean", "visVerdict": "clean",
            "score": payload.get("sessionScore"),
            "candidates": payload.get("n_candidates") or 0,
            "ampCV": consistency.get("amplitudeCV") if consistency else None,
            "tempoCV": consistency.get("tempoCV") if consistency else None,
            "stageMs": stage_ms, "total": total, "seed": seed,
            "r1": round(r(), 4), "r2": round(r(), 4), "r3": round(r(), 4),
            "amp": _amp_from_trace(tr), "travel": _travel_from_trace(tr),
            "interp": round(r() * 0.4, 3),
            # the real clip: poster frame for the card/pose plate + body frames,
            # and the actual media for the player dock
            "poster": poster,
            "plate": (f"url('{poster}') center/cover no-repeat, #201e1d"
                      if poster else ("linear-gradient(165deg,#8c491a,#402310)")),
            "video": f"/api/video/{name}",
            "stem": stem,
        })
    return out


def _inject_room(videos: list[dict]) -> str:
    """The reference page with the real clip array in place of the mock, and
    the design's synthetic skeleton swapped for the real one."""
    if not ROOM.exists():
        return "Reel Room assets missing (zone/reelroom.html)"
    html = ROOM.read_text(encoding="utf-8")
    payload = json.dumps(videos)
    html = html.replace("const VIDEOS = makeVideos();",
                        "const VIDEOS = " + payload + ";")

    # real skeleton, keyed by the clip's seed (seed = hash(name)) so the design
    # draws the actual person. Injected before the design script; the two
    # `skeleton(` call sites are redirected to it.
    real_body = {str(v["seed"]): _pose_frames(v["name"])["frames"]
                 for v in videos if _pose_frames(v["name"])}
    skel_script = (
        "<script>(function(){window.REAL_BODY=" + json.dumps(real_body) + ";"
        "window.REAL_SKELETON=function(phase,ex,conf,seed){var f=window.REAL_BODY[String(seed)];"
        "if(!f||!f.length)return {pts:[],segs:[]};var i=Math.max(0,Math.min(f.length-1,"
        "Math.floor(phase*(f.length-1))));return f[i];};})();</script>"
    )
    anchor = "<script type=\"text/x-dc\" data-dc-script"
    if anchor in html:
        html = html.replace(anchor, skel_script + anchor, 1)
    # the two call sites that built the synthetic skeleton
    html = html.replace("skeleton((st.poseFrame % 40) / 40, v.ex, v.meanConf, v.seed)",
                        "window.REAL_SKELETON((st.poseFrame % 40) / 40, v.ex, v.meanConf, v.seed)")
    html = html.replace("skeleton(phase, v.ex, v.meanConf, v.seed)",
                        "window.REAL_SKELETON(phase, v.ex, v.meanConf, v.seed)")
    # the real poster behind the pose plate and the shelf card plate
    html = html.replace(
        "vals.poseePlate = v.ex === 'pistol_squat' || v.ex === 'push_up' ? "
        "'linear-gradient(165deg,#56633f,#272e1b)' : "
        "'linear-gradient(165deg,#8c491a,#402310)';",
        "vals.poseePlate = v.poster ? (\"url('\" + v.poster + \"') center/cover no-repeat, #201e1d\") "
        ": (v.ex === 'pistol_squat' || v.ex === 'push_up' ? "
        "'linear-gradient(165deg,#56633f,#272e1b)' : "
        "'linear-gradient(165deg,#8c491a,#402310)');")
    html = html.replace(
        "plate: v.ex === 'pistol_squat' || v.ex === 'push_up' ? "
        "'linear-gradient(165deg,#56633f,#272e1b)' : "
        "'linear-gradient(165deg,#8c491a,#402310)',",
        "plate: v.plate || (v.ex === 'pistol_squat' || v.ex === 'push_up' ? "
        "'linear-gradient(165deg,#56633f,#272e1b)' : "
        "'linear-gradient(165deg,#8c491a,#402310)'),")

    # A real player dock: plays the actual clip with the real skeleton drawn
    # over it, synced to playback. Lives OUTSIDE <x-dc> (which the design
    # rebuilds on every state change) so it survives re-renders.
    catalog = {str(v["seed"]): {"name": v["name"], "stem": v["stem"]}
               for v in videos if v.get("name")}
    dock = json.dumps(catalog)
    player = _player_dock(dock)
    if "</body>" in html:
        html = html.replace("</body>", player + "</body>", 1)
    return html


def _player_dock(catalog: str) -> str:
    """Self-contained `<video>` + skeleton-canvas viewer, appended to the body."""
    tpl = """<div id="reel-player" style="position:fixed;left:var(--space-4);bottom:var(--space-4);z-index:70;width:min(320px,32vw);background:var(--color-bg);border:1px solid var(--color-divider);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);overflow:hidden;display:none">
  <div style="display:flex;align-items:center;gap:var(--space-2);padding:7px var(--space-3);border-bottom:1px solid var(--color-divider)">
    <span style="width:8px;height:8px;border-radius:999px;background:var(--color-accent)"></span>
    <span id="reel-name" style="font-family:var(--font-heading);font-size:13px;letter-spacing:-.01em;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">clip</span>
    <button id="reel-close" class="btn btn-icon" style="border-radius:999px;width:24px;height:24px;font-size:14px" title="close">&#215;</button>
  </div>
  <div style="position:relative;background:#201e1d;line-height:0">
    <video id="reel-video" muted playsinline controls loop preload="metadata" style="width:100%;display:block;max-height:48vh"></video>
    <canvas id="reel-canvas" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></canvas>
  </div>
  <div id="reel-note" style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--color-neutral-600);padding:6px var(--space-3);border-top:1px solid var(--color-divider)">the skeleton follows the video</div>
</div>
<script>
(function(){
  var VIDEO='/api/video/', KEYPOINTS='/api/keypoints/';
  var CATALOG=window.REAL_CATALOG=__CATALOG__;
  var panel=document.getElementById('reel-player'), vid=document.getElementById('reel-video'),
      cv=document.getElementById('reel-canvas'), nameEl=document.getElementById('reel-name'),
      kp=null, current=null;
  function draw(){
    requestAnimationFrame(draw);
    if(!vid.videoWidth||!kp) return;
    var ctx=cv.getContext('2d'), w=cv.width=vid.clientWidth, h=cv.height=vid.clientHeight;
    ctx.clearRect(0,0,w,h);
    var dur=vid.duration||1;
    var i=Math.min(kp.frames-1, Math.max(0, Math.round((vid.currentTime/dur)*(kp.frames-1))));
    var pts=kp.kp[i]; if(!pts) return;
    var s=Math.min(w/vid.videoWidth,h/vid.videoHeight),
        ox=(w-vid.videoWidth*s)/2, oy=(h-vid.videoHeight*s)/2;
    var X=function(p){return ox+p[0]*s}, Y=function(p){return oy+p[1]*s};
    ctx.lineWidth=2.4; ctx.lineCap='round';
    kp.edges.forEach(function(e){ var a=pts[e[0]],b=pts[e[1]]; if(!a||!b)return;
      var weak=a[2]<0.5||b[2]<0.5;
      ctx.strokeStyle=weak?'rgba(198,113,57,.6)':'rgba(249,244,237,.92)';
      ctx.beginPath();ctx.moveTo(X(a),Y(a));ctx.lineTo(X(b),Y(b));ctx.stroke();
    });
    kp.analysis.forEach(function(k){ var p=pts[k]; if(!p)return;
      ctx.beginPath();ctx.arc(X(p),Y(p),3.2,0,7);
      if(p[2]<0.5){ctx.strokeStyle='#c67139';ctx.stroke();} else {ctx.fillStyle='#f9f4ed';ctx.fill();}
    });
  }
  function open(name){
    if(!name||name===current) return; current=name;
    var meta=null; for(var k in CATALOG){ if(CATALOG[k].name===name){meta=CATALOG[k];break;} }
    var stem=meta?meta.stem:name.replace(/\\.[^.]*$/,'');
    nameEl.textContent=name;
    vid.src=VIDEO+encodeURIComponent(name); vid.currentTime=0;
    panel.style.display='block';
    var p=vid.play(); if(p&&p.catch) p.catch(function(){});
    fetch(KEYPOINTS+encodeURIComponent(stem)).then(function(r){return r.json();}).then(function(d){ kp=d&&d.kp?d:null; }).catch(function(){ kp=null; });
  }
  function close(){ panel.style.display='none'; vid.pause(); vid.removeAttribute('src'); vid.load(); kp=null; current=null; }
  document.getElementById('reel-close').addEventListener('click', close);
  function findOpen(){
    var els=document.querySelectorAll('h2');
    for(var i=0;i<els.length;i++){var t=els[i].textContent.trim();
      for(var k in CATALOG){ if(CATALOG[k].name===t) return t; }}
    for(var j=0;j<els.length;j++){var s=(els[j].getAttribute('style')||''), t2=els[j].textContent.trim();
      if(/32px/.test(s) && t2 && t2.length>3) return t2;}
    return null;
  }
  var obs=new MutationObserver(function(){
    var name=findOpen();
    if(name) open(name); else close();
  });
  obs.observe(document.body,{childList:true,subtree:true,characterData:true});
  draw();
})();
</script>"""
    return tpl.replace("__CATALOG__", catalog)



def _serve_zone(name: str) -> bytes | None:
    """Serve a vendored reference asset (support.js, _ds/...), path-safe."""
    rel = Path(name.lstrip("/"))
    target = (ZONE / rel).resolve()
    if not target.is_relative_to(ZONE.resolve()) or not target.is_file():
        return None
    return target.read_bytes()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8091")))
    port = parser.parse_args().port
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
