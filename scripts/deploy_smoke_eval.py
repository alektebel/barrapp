#!/usr/bin/env python3
"""Post-deploy eval: one golden clip through the REAL deployed pipeline.

The repo-side eval (tests, golden gate) proves the code; this proves the
DEPLOYMENT - image, Lambda config, S3, DynamoDB, the whole chain - by
uploading a reviewed clip through the deployed API's own contract
(POST /v1/jobs -> presigned PUT -> poll -> payload) and grading the
payload with the same barra.eval.golden layer that gates the repo.

CI calls it after `sam deploy`; it is also runnable by hand:

  python scripts/deploy_smoke_eval.py \
      --api https://<api-id>.execute-api.eu-west-1.amazonaws.com \
      --clip VID-20260827-WA0010.mp4 --exercise auto

Exit 1 = deployment broken or produced a graded failure. The grading is
strict for what the deployment controls (did the job complete, did the
pipeline run at all) and honest about what it does not (a vision-model
observation never overrides geometry; the movement check uses the same
reviewed manifest as the repo gate).
"""
from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.eval.golden import grade_payload  # noqa: E402

MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"
DEVICE = "cicd-smoke-device"
POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 5.0


def _call(url: str, method: str = "GET", data: bytes | None = None,
          headers: dict | None = None, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def run_job(api: str, clip: Path, exercise: str) -> dict:
    """The phone's exact flow: create job, PUT the clip, poll to done."""

    # POST /v1/jobs needs only X-Device-Id (anonymous is a supported state).
    status, body = _call(f"{api.rstrip('/')}/v1/jobs", "POST",
                         json.dumps({"exercise": exercise}).encode(),
                         {"X-Device-Id": DEVICE, "Content-Type": "application/json"})
    if status != 201:
        raise SystemExit(f"job creation failed: HTTP {status}: {body[:200]}")
    job = json.loads(body)
    job_id = job["id"]
    print(f"job {job_id} created; uploading {clip.name} "
          f"({clip.stat().st_size // 1024} KB)")

    upload = job["uploadUrl"]
    if upload.startswith("/"):
        upload = api.rstrip("/") + upload     # local server returns a path
    # The upload URL must carry the SAME device identity that created the
    # job: the local server (and the deployed API's auth check) reject an
    # upload whose owner does not match, and the rejection happens before
    # the body is read, which urllib reports as a confusing broken pipe.
    parsed = urllib.parse.urlparse(upload)
    conn = http.client.HTTPConnection(parsed.netloc, timeout=120)
    conn.request("PUT", parsed.path or "/", clip.read_bytes(),
                 {"Content-Type": "video/mp4", "X-Device-Id": DEVICE})
    resp = conn.getresponse()
    status, body = resp.status, resp.read()
    conn.close()

    # The deployed contract needs an explicit submit; the presigned PUT to
    # S3 does not reach the worker by itself.
    status, body = _call(f"{api.rstrip('/')}/v1/jobs/{job_id}/submit", "POST",
                         b"{}", {"X-Device-Id": DEVICE,
                                 "Content-Type": "application/json"})
    if status != 202:
        raise SystemExit(f"submit failed: HTTP {status}: {body[:200]}")
    print("job submitted to the worker")

    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        status, body = _call(f"{api.rstrip('/')}/v1/jobs/{job_id}",
                             headers={"X-Device-Id": DEVICE})
        job = json.loads(body)
        stage = job.get("stage") or job.get("status")
        if job.get("status") == "done":
            print(f"job done (stage trace: {stage})")
            return job.get("result") or {}
        if job.get("status") in ("failed", "error"):
            raise SystemExit(f"job failed: {job.get('error')}")
        print(f"  ... {stage}")
        time.sleep(POLL_INTERVAL_S)
    raise SystemExit(f"job {job_id} did not finish in {POLL_TIMEOUT_S}s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", required=True, help="deployed API base URL")
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--exercise", default="auto")
    args = ap.parse_args(argv)
    if not args.clip.exists():
        raise SystemExit(f"no such clip: {args.clip}")

    result = run_job(args.api, args.clip, args.exercise)
    if not result:
        raise SystemExit("job completed with an empty result - pipeline broken")

    # Grade with the same layer the repo gate uses. The deployment cannot
    # change what the correct movement is, so the manifest applies as-is.
    manifest = json.loads(MANIFEST.read_text())
    stem = args.clip.stem
    report = grade_payload(stem, result, manifest)
    print(f"\ngraded {stem}: {len(report.passed())} passed, "
          f"{len(report.failed())} failed")
    for c in report.failed():
        print(f"  FAIL {c['check']}: {c}")

    detected = (result.get("detected") or {}).get("exercise") or result.get("exercise")
    n_reps = result.get("n_reps")
    print(f"deployed pipeline said: exercise={detected} n_reps={n_reps} "
          f"score={result.get('sessionScore')}")
    if not report.graded:
        print(f"not graded: {report.why} (deployment smoke still passed)")
        return 0
    return 1 if report.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
