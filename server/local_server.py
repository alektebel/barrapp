#!/usr/bin/env python3
"""Local API that matches the AWS contract. Phone on LAN: http://<lan-ip>:8080"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "bin" / "python"
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

sys.path.insert(0, str(ROOT))

from process import process_job  # noqa: E402

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        example = ROOT / ".env.example"
        if example.exists():
            path.write_text(example.read_text())
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _dump(job: dict) -> dict:
    body = {
        "id": job["id"],
        "status": job["status"],
        "exercise": job["exercise"],
        "createdAt": job["createdAt"],
        "uploadUrl": f"/v1/jobs/{job['id']}/video",
        "uploadMethod": "PUT",
    }
    if job.get("result") is not None:
        body["result"] = job["result"]
    if job.get("error"):
        body["error"] = job["error"]
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("local-api: " + fmt % args + "\n")

    def _owner(self) -> str:
        return (self.headers.get("X-Device-Id") or "").strip()

    def _send(self, code: int, payload: dict | list | None = None) -> None:
        raw = json.dumps(payload if payload is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Device-Id,Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Device-Id,Authorization")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            return self._send(200, {"ok": True})
        owner = self._owner()
        if not owner:
            return self._send(401, {"error": "missing X-Device-Id"})
        if path == "/v1/jobs":
            with LOCK:
                jobs = [
                    _dump(j)
                    for j in sorted(JOBS.values(), key=lambda x: x["createdAt"], reverse=True)
                    if j.get("owner") == owner
                ]
            return self._send(200, {"jobs": jobs})
        if path == "/v1/history":
            with LOCK:
                history = [
                    {
                        "id": j["id"],
                        "createdAt": j["createdAt"],
                        "exercise": j["exercise"],
                        "result": j.get("result"),
                    }
                    for j in sorted(JOBS.values(), key=lambda x: x["createdAt"], reverse=True)
                    if j.get("owner") == owner and j.get("status") == "done"
                ]
            return self._send(200, {"history": history})
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "v1" and parts[1] == "jobs":
            with LOCK:
                job = JOBS.get(parts[2])
            if not job or job.get("owner") != owner:
                return self._send(404, {"error": "unknown job"})
            return self._send(200, _dump(job))
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        owner = self._owner()
        if not owner:
            return self._send(401, {"error": "missing X-Device-Id"})
        path = urlparse(self.path).path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid json"})

        if path == "/v1/jobs":
            job_id = uuid.uuid4().hex[:12]
            job = {
                "id": job_id,
                "owner": owner,
                "status": "created",
                # "auto" by default: the movement is detected from the clip, so a client
                # that omits the field does not get squat geometry applied to a
                # muscle-up, which produces numbers that look fine and mean nothing.
                "exercise": body.get("exercise") or "auto",
                "createdAt": _now(),
                "result": None,
                "error": None,
            }
            with LOCK:
                JOBS[job_id] = job
            return self._send(201, _dump(job))

        if path == "/v1/chat":
            from chat import chat

            return self._send(200, chat(body.get("messages") or []))

        if path.endswith("/submit") and path.startswith("/v1/jobs/"):
            job_id = path.split("/")[3]
            with LOCK:
                job = JOBS.get(job_id)
                if not job or job.get("owner") != owner:
                    return self._send(404, {"error": "unknown job"})
                job["status"] = "processing"
            threading.Thread(target=_run, args=(job_id,), daemon=True).start()
            return self._send(202, _dump(job))

        self._send(404, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802
        owner = self._owner()
        if not owner:
            return self._send(401, {"error": "missing X-Device-Id"})
        path = urlparse(self.path).path.rstrip("/")
        if not (path.startswith("/v1/jobs/") and path.endswith("/video")):
            return self._send(404, {"error": "not found"})
        job_id = path.split("/")[3]
        with LOCK:
            job = JOBS.get(job_id)
            if not job or job.get("owner") != owner:
                return self._send(404, {"error": "unknown job"})
        length = int(self.headers.get("Content-Length") or 0)
        dest = DATA / f"{job_id}.mp4"
        with dest.open("wb") as fh:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)
        with LOCK:
            JOBS[job_id]["status"] = "uploaded"
        self._send(200, {"ok": True, "id": job_id})

    def do_DELETE(self) -> None:  # noqa: N802
        owner = self._owner()
        if not owner:
            return self._send(401, {"error": "missing X-Device-Id"})
        path = urlparse(self.path).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        if not (len(parts) == 3 and parts[0] == "v1" and parts[1] == "jobs"):
            return self._send(404, {"error": "not found"})
        job_id = parts[2]
        with LOCK:
            job = JOBS.get(job_id)
            if not job or job.get("owner") != owner:
                return self._send(404, {"error": "unknown job"})
            JOBS.pop(job_id, None)
        video = DATA / f"{job_id}.mp4"
        if video.exists():
            video.unlink()
        self._send(200, {"ok": True, "id": job_id})


def _run(job_id: str) -> None:
    video = DATA / f"{job_id}.mp4"
    with LOCK:
        job = dict(JOBS[job_id])
    try:
        result = process_job(job, video)
        with LOCK:
            JOBS[job_id]["result"] = result
            JOBS[job_id]["exercise"] = result.get("exercise") or job.get("exercise")
            JOBS[job_id]["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = str(exc)


def main() -> None:
    _load_env()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"barrapp api on http://0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
