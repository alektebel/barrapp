"""Where a job's decision chain is kept after the run.

Locally the trace JSON on disk is the store. On AWS the worker's disk is
ephemeral, so the trace goes to a DynamoDB table instead: one row per video
analysis, holding the whole decision chain, the keypoint timesteps, and the
artifacts' names. This is the log a user report is answered from - "it said
it couldn't count any reps" becomes a queryable record of exactly what the
pipeline saw, stage by stage, for that clip.

Failing to store a trace must never fail a job. Every path here returns the
store it used, or None, and swallows its own errors.
"""
from __future__ import annotations

import json
import os
import time

# DynamoDB item limit is 400 KB; the trace is downsampled upstream, but a
# pathological clip should still not break the write.
MAX_PAYLOAD_CHARS = 350_000
TTL_DAYS = 90


def put_trace(record: dict, trace_id: str, job_id: str = "") -> str | None:
    """Store one trace record. Returns 'dynamodb' or None (disk is handled by
    the caller, which already knows where its files go)."""
    table = os.environ.get("TRACES_TABLE", "").strip()
    if not table:
        return None
    try:
        import boto3

        payload = json.dumps(record, default=str)[:MAX_PAYLOAD_CHARS]
        ttl = int(time.time()) + TTL_DAYS * 24 * 3600
        boto3.client("dynamodb").put_item(
            TableName=table,
            Item={
                "traceId": {"S": trace_id},
                "jobId": {"S": job_id or trace_id},
                "createdAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "ttl": {"N": str(ttl)},
                "payload": {"S": payload},
            },
        )
        return "dynamodb"
    except Exception as exc:  # noqa: BLE001
        print(f"[barra] could not store trace {trace_id}: {exc}", flush=True)
        return None


def put_failure(job_id: str, stage: str, error: str) -> str | None:
    """A record for a job that died before it had a trace of its own."""
    table = os.environ.get("TRACES_TABLE", "").strip()
    if not table:
        return None
    return put_trace(
        {"jobId": job_id, "stage": stage, "error": error,
         "kind": "worker-failure"}, f"failure-{job_id}", job_id)
