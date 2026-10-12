"""Where a production job's time went.

    python scripts/job_timing.py <job_id>          # needs AWS credentials
    python scripts/job_timing.py --fixture tests/fixtures/job_timing_31103ccedfc3.json

Reads the job's upload log (the phone's and the worker's events, with wall
clock times) and its trace (the worker's steps, in ms from the start of the
measurement), aligns the two on the "opening the clip" stage, and prints each
stage's duration. These are server timings: `done` proves persistence, not
phone receipt/render. A client monotonic trace is needed for the <15 s gate.
Old event logs only have whole seconds; retaining precision does not recover
milliseconds that were never recorded. Nested/overlapping stages must not be
summed. docs/SPEED-PLAN.md measures every step with this.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _t(stamp: str) -> datetime:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _first(events: list[dict], event: str, detail: str | None = None) -> datetime | None:
    return min((_t(e["at"]) for e in events
                if e.get("event") == event and
                (detail is None or e.get("detail") == detail)), default=None)


def _trace_ms(trace: dict, message: str, stage: str | None = None) -> int | None:
    for e in trace.get("entries", []):
        if e.get("message") == message and (stage is None or e.get("stage") == stage):
            return int(e["atMs"])
    return None


def durations(uploads: list[dict], trace: dict | None) -> dict[str, float]:
    """Seconds per stage. Stages whose events are missing are left out."""
    out: dict[str, float] = {}
    created = _first(uploads, "job-created")
    started = _first(uploads, "upload-started")
    complete = _first(uploads, "upload-complete")
    submitted = _first(uploads, "submitted")
    receiving = _first(uploads, "stage", "receiving the clip")
    opening = _first(uploads, "stage", "opening the clip")
    done = _first(uploads, "done")
    vision = _first(uploads, "vision")
    prose = _first(uploads, "prose")

    if started and complete:
        out["upload"] = (complete - started).total_seconds()
    if complete and submitted:
        out["submit"] = (submitted - complete).total_seconds()
    if submitted and receiving:
        out["queue"] = (receiving - submitted).total_seconds()
    if receiving and opening:
        out["download+dispatch"] = (opening - receiving).total_seconds()
    if trace:
        pose_end = _trace_ms(trace, "pose backend")
        probe = _trace_ms(trace, "entered probe")
        payload = _trace_ms(trace, "entered payload")
        if probe is not None and pose_end is not None:
            out["pose"] = (pose_end - probe) / 1000
        if pose_end is not None and payload is not None:
            out["measure+report"] = (payload - pose_end) / 1000
        fusion_start = _trace_ms(trace, "entered fusion", "fusion")
        fusion_end = _trace_ms(trace, "fusion", "fusion")
        if fusion_start is not None and fusion_end is not None:
            out["fusion (includes vision wait)"] = (fusion_end - fusion_start) / 1000
        # The trace starts at "opening the clip"; done is a wall-clock event.
        if opening and done and payload is not None:
            out["after payload, before done"] = (
                (done - opening).total_seconds() - payload / 1000)
    if complete and done:
        out["upload end -> result"] = (done - complete).total_seconds()
    if started and done:
        out["upload start -> server result"] = (done - started).total_seconds()
    if done and vision:
        out["vision (after result)"] = (vision - done).total_seconds()
    if done and prose:
        out["prose (after result)"] = (prose - done).total_seconds()
    end = max((stamp for stamp in (done, vision, prose) if stamp is not None), default=None)
    if created and end:
        out["total"] = (end - created).total_seconds()
    return out


def table(d: dict[str, float]) -> str:
    width = max(len(k) for k in d) if d else 0
    return "\n".join(f"{k:<{width}}  {v:>9.3f} s" for k, v in d.items())


def fetch(job_id: str) -> tuple[list[dict], dict | None]:
    import boto3

    ddb = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-1"))
    up = ddb.get_item(TableName=os.environ.get("UPLOADS_TABLE", "sam-app-UploadsTable-1TBZME1NCIWR9"),
                      Key={"jobId": {"S": job_id}}).get("Item") or {}
    events = [{k: list(v.values())[0] for k, v in e["M"].items()}
              for e in up.get("events", {}).get("L", [])]
    job = ddb.get_item(TableName=os.environ.get("JOBS_TABLE", "sam-app-JobsTable-12EQEZ1EM3YR7"),
                       Key={"id": {"S": job_id}}).get("Item") or {}
    trace_id = job.get("result", {}).get("M", {}).get("traceId", {}).get("S")
    trace = None
    if trace_id:
        tr = ddb.get_item(TableName=os.environ.get("TRACES_TABLE", "sam-app-TracesTable-1R6026Z7HAU29"),
                          Key={"traceId": {"S": trace_id}}).get("Item")
        if tr:
            trace = json.loads(tr["payload"]["S"])
    return events, trace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id", nargs="?")
    ap.add_argument("--fixture", type=Path, help="replay a saved uploads/trace JSON, offline")
    a = ap.parse_args()
    if bool(a.job_id) == bool(a.fixture):
        ap.error("provide either job_id or --fixture")
    if a.fixture:
        saved = json.loads(a.fixture.read_text())
        events, trace = saved["uploads"], saved.get("trace")
    else:
        events, trace = fetch(a.job_id)
    print(table(durations(events, trace)))
    print("Server persistence only; phone rendering is not measured. "
          "Stages can overlap; whole-second source timestamps remain coarse.")


if __name__ == "__main__":
    main()
