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
summed. New worker events also expose stage telemetry-write, clip-download,
processing-status and first-result persistence durations. docs/SPEED-PLAN.md
measures every step with this.
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


def _last_event(events: list[dict], event: str) -> dict | None:
    return next((e for e in reversed(events) if e.get("event") == event), None)


def _seconds_ms(value) -> float | None:
    try:
        return float(value) / 1000
    except (TypeError, ValueError):
        return None


def _seconds_us(value) -> float | None:
    try:
        return float(value) / 1_000_000
    except (TypeError, ValueError):
        return None


def _trace_ms(trace: dict, message: str, stage: str | None = None) -> int | None:
    for e in trace.get("entries", []):
        if e.get("message") == message and (stage is None or e.get("stage") == stage):
            return int(e["atMs"])
    return None


def _trace_data(trace: dict, message: str) -> dict | None:
    for entry in trace.get("entries", []):
        if entry.get("message") == message:
            data = entry.get("data")
            return data if isinstance(data, dict) else None
    return None


def _elapsed(start: datetime | None, end: datetime | None) -> float | None:
    """Wall-clock diagnostic interval; omit missing or clock-inverted pairs."""
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def durations(uploads: list[dict], trace: dict | None) -> dict[str, float]:
    """Seconds per stage. Stages whose events are missing are left out."""
    out: dict[str, float] = {}
    created = _first(uploads, "job-created")
    started = _first(uploads, "upload-started")
    complete = _first(uploads, "upload-complete")
    submitted = _first(uploads, "submitted")
    dispatch_started = _first(uploads, "dispatch-started")
    dispatch_accepted = _first(uploads, "dispatch-accepted")
    worker_entry = _first(uploads, "worker-entry")
    worker_ready = _first(uploads, "worker-ready")
    receiving = _first(uploads, "stage", "receiving the clip")
    opening = _first(uploads, "stage", "opening the clip")
    done = _first(uploads, "done")
    vision = _first(uploads, "vision")
    prose = _first(uploads, "prose")

    if started and complete:
        out["upload"] = (complete - started).total_seconds()
    if complete and submitted:
        out["submit"] = (submitted - complete).total_seconds()
    for label, start, end in (
        ("worker dispatch request", dispatch_started, dispatch_accepted),
        ("accepted -> worker entry", dispatch_accepted, worker_entry),
        ("worker handler -> imports ready", worker_entry, worker_ready),
    ):
        duration = _elapsed(start, end)
        if duration is not None:
            out[label] = duration
    worker_timing = _last_event(uploads, "worker-timing")
    if worker_timing:
        wait = _seconds_ms(worker_timing.get("fusionWaitMs"))
        if wait is not None:
            out["fusion vision wait"] = wait
        locate_before = _seconds_ms(worker_timing.get("locatorMsAtResult"))
        if locate_before is not None:
            out["locator before result"] = locate_before
        for field, label in (("stageTableUs", "stage table writes"),
                             ("stageUploadLogUs", "stage upload-log writes"),
                             ("stageTotalUs", "stage telemetry writes"),
                             ("stageSlowestUs", "slowest stage telemetry write"),
                             ("clipDownloadUs", "clip download"),
                             ("processingStateWriteUs", "processing status write"),
                             ("resultWriteUs", "first result write")):
            value = _seconds_us(worker_timing.get(field))
            if value is not None:
                out[label] = value
    locator = _last_event(uploads, "locator-finished")
    if locator:
        duration = _seconds_ms(locator.get("durationMs"))
        if duration is not None:
            out["locator"] = duration
        after_result = _seconds_ms(locator.get("postResultWaitMs"))
        if locator.get("resultPersisted") and after_result is not None:
            out["locator after result wait"] = after_result
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
        count_rescue = _trace_data(trace, "visual count rescue")
        if count_rescue is not None:
            duration = _seconds_ms(count_rescue.get("durationMs"))
            if duration is not None:
                out["visual count rescue"] = duration
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
