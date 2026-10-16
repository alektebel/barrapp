#!/usr/bin/env python3
"""Local API that matches the AWS contract. Phone on LAN: http://<lan-ip>:8080"""
from __future__ import annotations

import json
import re
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "bin" / "python"
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from process import measure_job  # noqa: E402
import referral  # noqa: E402

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
JOBS: dict[str, dict] = {}
FEEDBACK: dict[str, dict] = {}
POSE_WARMUPS: dict[str, object] = {}
# The same referral engine the Lambda runs, on the in-memory store. Sharing
# the module is what keeps a code redeemed on the LAN and on AWS the same
# program rather than two that drift.
REFERRALS = referral.MemoryStore()
LOCK = threading.Lock()
# The same floor handler.py applies: below this an "upload" is a stream
# that ended before it started, not a clip.
MIN_CLIP_BYTES = 8 * 1024


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


def _start_pose_warmup(job_id: str) -> None:
    """Overlap lazy pose-package imports with the incoming clip bytes."""
    try:
        from pose_warmup import start_pose_runtime_warmup

        warmup = start_pose_runtime_warmup()
    except Exception:  # noqa: BLE001 - an optimization must not fail upload
        return
    if warmup is not None:
        with LOCK:
            POSE_WARMUPS[job_id] = warmup


def _finish_pose_warmup(job_id: str) -> dict:
    with LOCK:
        warmup = POSE_WARMUPS.pop(job_id, None)
    try:
        from pose_warmup import finish_pose_runtime_warmup

        return finish_pose_runtime_warmup(warmup)
    except Exception as exc:  # noqa: BLE001 - preserve normal lazy import path
        return {"ready": False, "outcome": type(exc).__name__,
                "elapsedMs": 0, "waitMs": 0}


def _dump(job: dict) -> dict:
    body = {
        "id": job["id"],
        "status": job["status"],
        "exercise": job["exercise"],
        "createdAt": job["createdAt"],
        "uploadUrl": f"/v1/jobs/{job['id']}/video",
        "uploadMethod": "PUT",
    }
    if job.get("stage"):
        body["stage"] = job["stage"]
    if job.get("result") is not None:
        body["result"] = job["result"]
    if job.get("error"):
        body["error"] = job["error"]
    if job.get("resultReadyAtEpochMs") is not None:
        body["resultReadyAtEpochMs"] = job["resultReadyAtEpochMs"]
        body["serverMeasurementMs"] = job.get("serverMeasurementMs")
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        # Millisecond wall time makes each phone poll response alignable with
        # resultReadyAtEpochMs in the response payload.
        sys.stderr.write(f"{int(time.time() * 1000)} local-api: "
                         + fmt % args + "\n")

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
        if path == "/v1/referral":
            return self._send(200, referral.status(REFERRALS, owner))
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
                # Declared, never inferred: the technique variant (strict /
                # kipping / tuck ...) selects which checks apply, and the camera
                # side overrides the estimated view. process_job validates
                # both; an unknown variant is reported back as unspecified.
                "variant": (body.get("variant") or "").strip() or None,
                "view": (body.get("view") or "").strip() or None,
                "createdAt": _now(),
                "result": None,
                "error": None,
            }
            allowed, credits = referral.charge(REFERRALS, owner)
            if not allowed:
                return self._send(402, {
                    "error": "no measurements left - invite a friend to earn more",
                    "credits": credits,
                })
            with LOCK:
                JOBS[job_id] = job
            return self._send(201, _dump(job))
        if path == "/v1/chat":
            from chat import chat

            return self._send(200, chat(body.get("messages") or []))

        if path == "/v1/referral/redeem":
            code = body.get("code") if isinstance(body.get("code"), str) else ""
            status, payload = referral.redeem(REFERRALS, owner, code)
            return self._send(status, payload)

        if path == "/v1/feedback":
            message = (body.get("message") or "").strip() if isinstance(body.get("message"), str) else ""
            if not message:
                return self._send(400, {"error": "a message is required"})
            if len(message) > 5000:
                return self._send(400, {"error": "the message is too long (5000 characters max)"})
            feedback_id = uuid.uuid4().hex[:12]
            item = {
                "id": feedback_id,
                "owner": owner,
                "message": message,
                "status": "new",
                "createdAt": _now(),
            }
            for key, limit in (("traceId", 64), ("jobId", 64), ("appVersion", 80)):
                value = (body.get(key) or "").strip() if isinstance(body.get(key), str) else ""
                if value and len(value) <= limit:
                    item[key] = value
            out = {k: v for k, v in item.items() if k != "owner"}
            if body.get("video"):
                item["videoKey"] = f"feedback/{owner}/{feedback_id}.mp4"
                out["uploadUrl"] = f"/v1/feedback/{feedback_id}/video"
                out["uploadMethod"] = "PUT"
            with LOCK:
                FEEDBACK[feedback_id] = item
            return self._send(201, out)

        parts = [p for p in path.split("/") if p]
        if (len(parts) == 5 and parts[0] == "v1" and parts[1] == "jobs"
                and parts[3] == "upload"):
            return self.do_POST_upload(parts, body, owner)

        if (len(parts) == 4 and parts[0] == "v1"
                and parts[1] == "jobs" and parts[3] == "upload-url"):
            job_id = parts[2]
            with LOCK:
                job = JOBS.get(job_id)
                if not job or job.get("owner") != owner:
                    return self._send(404, {"error": "unknown job"})
                if job.get("status") != "created" or job.get("uploadId"):
                    return self._send(409, {
                        "error": "job is not waiting for a single-file upload"})
            return self._send(200, {
                "uploadUrl": f"/v1/jobs/{job_id}/video",
                "uploadMethod": "PUT",
            })

        if path.endswith("/submit") and path.startswith("/v1/jobs/"):
            job_id = path.split("/")[3]
            with LOCK:
                job = JOBS.get(job_id)
                if not job or job.get("owner") != owner:
                    return self._send(404, {"error": "unknown job"})
                video = DATA / f"{job_id}.mp4"
                if not video.is_file() or video.stat().st_size < MIN_CLIP_BYTES:
                    return self._send(409, {
                        "error": "the clip has not finished uploading"})
                job["status"] = "processing"
            threading.Thread(target=_run, args=(job_id,), daemon=True).start()
            return self._send(202, _dump(job))

        self._send(404, {"error": "not found"})

    # ---- resumable upload, same contract as the AWS API, parts on disk ----
    def _part_dir(self, job_id: str) -> Path:
        d = DATA / f"{job_id}.parts"
        d.mkdir(exist_ok=True)
        return d

    def do_POST_upload(self, parts: list[str], body: dict, owner: str) -> None:
        job_id = parts[2]
        action = parts[4]
        with LOCK:
            job = JOBS.get(job_id)
        if not job or job.get("owner") != owner:
            return self._send(404, {"error": "unknown job"})
        if action == "start":
            with LOCK:
                upload_id = JOBS[job_id].setdefault("uploadId", uuid.uuid4().hex)
            self._part_dir(job_id)
            return self._send(201, {"uploadId": upload_id, "partSize": 8 * 1024 * 1024})
        if action == "part":
            upload_id = JOBS.get(job_id, {}).get("uploadId")
            if not upload_id:
                return self._send(409, {"error": "no upload in progress - start first"})
            part_number = int((body or {}).get("partNumber") or 0)
            return self._send(200, {
                "url": f"/v1/jobs/{job_id}/video/part/{part_number}",
                "partNumber": part_number,
            })
        if action == "complete":
            if not JOBS.get(job_id, {}).get("uploadId"):
                return self._send(409, {"error": "no upload in progress"})
            dest = DATA / f"{job_id}.mp4"
            part_dir = self._part_dir(job_id)
            got = sorted(
                int(p["partNumber"]) for p in (body or {}).get("parts") or [])
            with dest.open("wb") as out:
                for n in got:
                    part = part_dir / f"{n:05d}"
                    with part.open("rb") as fh:
                        while True:
                            chunk = fh.read(1 << 20)
                            if not chunk:
                                break
                            out.write(chunk)
            for part in part_dir.glob("*"):
                part.unlink()
            part_dir.rmdir()
            size = dest.stat().st_size if dest.exists() else 0
            if size < MIN_CLIP_BYTES:
                with LOCK:
                    JOBS[job_id]["status"] = "failed"
                    JOBS[job_id]["error"] = "the clip arrived empty or truncated. Retry."
                    JOBS[job_id].pop("uploadId", None)
                return self._send(400, {"error": "the clip arrived empty or truncated",
                                        "bytes": size})
            with LOCK:
                JOBS[job_id]["status"] = "uploaded"
                JOBS[job_id].pop("uploadId", None)
            return self._send(200, {"ok": True})
        if action == "event":
            # Parity with the deployed API, which keeps an UploadsTable row
            # per job. There is no such table here, so the phone's line goes
            # to the console - which is where a LAN test is being watched
            # from anyway, and is enough to stop the client seeing a 404 on
            # every event it ships.
            print(f"[upload {job_id}] {(body or {}).get('level', 'info')}: "
                  f"{(body or {}).get('event', 'client')} "
                  f"{(body or {}).get('detail', '')}".rstrip(), flush=True)
            return self._send(202, {"ok": True, "stored": False})
        if action == "abort":
            part_dir = self._part_dir(job_id)
            for part in part_dir.glob("*"):
                part.unlink()
            with LOCK:
                JOBS.get(job_id, {}).pop("uploadId", None)
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_PUT(self) -> None:  # noqa: N802
        owner = self._owner()
        if not owner:
            return self._send(401, {"error": "missing X-Device-Id"})
        path = urlparse(self.path).path.rstrip("/")
        m = re.fullmatch(r"/v1/jobs/([0-9a-f]+)/video/part/(\d+)", path)
        if m:
            job_id, n = m.group(1), int(m.group(2))
            with LOCK:
                job = JOBS.get(job_id)
            if not job or job.get("owner") != owner:
                return self._send(404, {"error": "unknown job"})
            _start_pose_warmup(job_id)
            length = int(self.headers.get("Content-Length") or 0)
            part = self._part_dir(job_id) / f"{n:05d}"
            with part.open("wb") as fh:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            self._send(200, {"ok": True, "partNumber": n,
                             "etag": f'"{n:05d}"'})
            return
        # A feedback clip lands on the same presigned-PUT contract as a job
        # upload, so the phone needs no second code path. On AWS that PUT goes
        # straight to S3; here it has to be a real route, or attaching a clip
        # to feedback works in production and 404s on the LAN.
        m = re.fullmatch(r"/v1/feedback/([0-9a-f]+)/video", path)
        if m:
            feedback_id = m.group(1)
            with LOCK:
                item = FEEDBACK.get(feedback_id)
            if not item or item.get("owner") != owner:
                return self._send(404, {"error": "unknown feedback"})
            length = int(self.headers.get("Content-Length") or 0)
            dest = DATA / f"feedback-{feedback_id}.mp4"
            with dest.open("wb") as fh:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            with LOCK:
                item["videoBytes"] = dest.stat().st_size
            self._send(200, {"ok": True, "id": feedback_id})
            return
        if not (path.startswith("/v1/jobs/") and path.endswith("/video")):
            return self._send(404, {"error": "not found"})
        job_id = path.split("/")[3]
        with LOCK:
            job = JOBS.get(job_id)
            if not job or job.get("owner") != owner:
                return self._send(404, {"error": "unknown job"})
        _start_pose_warmup(job_id)
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
        if remaining > 0 or dest.stat().st_size < MIN_CLIP_BYTES:
            dest.unlink(missing_ok=True)
            return self._send(400, {"error": "the clip arrived empty or truncated"})
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
    worker_started_ns = time.perf_counter_ns()

    def stage(name: str) -> None:
        with LOCK:
            JOBS[job_id]["stage"] = name

    first_result_written = False
    locator_pool = None
    pose_warmup_timing = {"ready": False, "outcome": "not-started",
                          "elapsedMs": 0, "waitMs": 0}
    try:
        pose_warmup_timing = _finish_pose_warmup(job_id)
        # Classification localization can overlap pose, but a late vote must
        # never hold the first measured result. This mirrors handler.worker.
        def _locate():
            try:
                from vision import locate_exercise
                return locate_exercise(video, DATA / f"{job_id}-locate",
                                       job.get("exercise"))
            except Exception:  # noqa: BLE001 - localization is advisory
                return None

        locator_pool = ThreadPoolExecutor(max_workers=1)
        located_future = locator_pool.submit(_locate)

        def _vision_vote(wait_s: float = 0.0):
            try:
                located = located_future.result(timeout=wait_s)
                label = (located or {}).get("exercise") or None
                return label if str(label or "").lower() not in (
                    "none", "unknown", "") else None
            except Exception:  # noqa: BLE001 - a late vote is not required
                return None

        result = measure_job(job, video, on_stage=stage,
                             vision_label=_vision_vote)
        result_ready_epoch_ms = int(time.time() * 1000)
        server_measurement_ms = round(
            (time.perf_counter_ns() - worker_started_ns) / 1_000_000)
        with LOCK:
            JOBS[job_id]["result"] = result
            JOBS[job_id]["exercise"] = result.get("exercise") or job.get("exercise")
            JOBS[job_id]["status"] = "done"
            JOBS[job_id]["resultReadyAtEpochMs"] = result_ready_epoch_ms
            JOBS[job_id]["serverMeasurementMs"] = server_measurement_ms
        first_result_written = True
        print(f"local-api: job={job_id} event=first-result "
              f"serverMeasurementMs={server_measurement_ms} "
              f"poseWarmup={pose_warmup_timing['outcome']} "
              f"poseWarmupElapsedMs={pose_warmup_timing['elapsedMs']} "
              f"poseWarmupWaitMs={pose_warmup_timing['waitMs']} "
              f"resultReadyAtEpochMs={result_ready_epoch_ms}", flush=True)

        # Everything below is enrichment or replay storage. The phone already
        # has the measured payload, so these operations cannot delay its result.
        try:
            located = located_future.result(timeout=300)
        except Exception:  # noqa: BLE001 - localization never fails a result
            located = None
        locator_pool.shutdown(wait=False)
        localization = None
        if located and located.get("usable"):
            localization = dict(located)
            localization["source"] = "vision"
        from barra.frames import trim_clip

        if localization is None:
            t = result.get("trim") or {}
            if t.get("startS") is not None and t.get("endS") is not None:
                localization = {"source": "geometry", "startS": t["startS"],
                                "endS": t["endS"], "durationS": result.get("duration_s")}
        if localization and localization.get("startS") is not None:
            margin = 1.0
            start = max(0.0, float(localization["startS"]) - margin)
            end = float(localization["endS"]) + margin
            dur = localization.get("durationS") or result.get("duration_s")
            if dur:
                end = min(end, float(dur))
            cut = trim_clip(video, start, end, DATA / f"{job_id}-exercise.mp4")
            if cut is not None:
                cut.replace(video)
                localization["trimmed"] = True
        if localization is not None:
            result["localization"] = localization
        if result.get("visionStatus") == "pending":
            from process import add_vision
            result = add_vision(job, video, result)
        if result.get("proseStatus") == "pending":
            from process import finish_prose
            result = finish_prose(job, result)
        with LOCK:
            JOBS[job_id]["result"] = result
    except Exception as exc:  # noqa: BLE001
        if locator_pool is not None:
            locator_pool.shutdown(wait=False)
        if first_result_written:
            print(f"local-api: job={job_id} post-result enrichment failed: {exc}",
                  flush=True)
        else:
            with LOCK:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = str(exc)


def main() -> None:
    _load_env()
    port = int(os.environ.get("PORT", "8080"))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as exc:
        # The usual cause is another dev server squatting the port (a frontend
        # on 8080, for instance), which read as "the backend is broken".
        raise SystemExit(
            f"barrapp api cannot bind port {port} ({exc}). Something else is "
            f"listening on it - stop that process, or run me with: PORT={port + 1} "
            f"python server/local_server.py")
    print(f"barrapp api on http://0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
