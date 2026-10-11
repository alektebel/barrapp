"""The record of every upload try, and of every way one ended.

A job row says what a clip became. It says nothing about how it got there,
and for the uploads that never got there it says almost nothing at all: nine
rows in the jobs table read "the clip was never finished uploading", which is
the reaper's guess, not an observation. Whether those were a dead network, an
app the system killed mid-part, or a part S3 refused, nobody can tell - the
only log of the attempt lived on the phone, bounded to twelve works, and is
long gone.

So every step of an upload is written here instead: one row per job, an
append-only list of what happened and when, on the server, outliving the
phone's copy. The client ships its own view into the same row through
POST /v1/jobs/<id>/upload/event, so a pause on a train and the part that
resumed it sit in one ordered list.

Two rules this module keeps, both learned from the trace store:

  * Telemetry never fails the thing it watches. Every function swallows its
    own errors and returns a bool nobody has to check.
  * The list is bounded. A phone retrying a part on a bad connection can emit
    hundreds of events, and a DynamoDB item dies at 400 KB - a truncated log
    is a log, an item too large to write is not.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import boto3

# A resumable upload of a 120 MB clip is 15 parts. Allow for a bad network
# retrying most of them, and still stay far below the item limit.
MAX_EVENTS = 200
MAX_DETAIL_CHARS = 400
TTL_DAYS = 90

_ddb = boto3.resource("dynamodb")
_TABLE_NAME = os.environ.get("UPLOADS_TABLE", "").strip()
_table = _ddb.Table(_TABLE_NAME) if _TABLE_NAME else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(job_id: str, owner: str, event: str, detail: str = "",
           level: str = "info", **fields) -> bool:
    """Append one event to a job's upload log. Returns whether it was stored.

    The row is created on first write, so no caller has to know whether this
    job has been seen before. `fields` carries whatever the step knows -
    part numbers, byte counts, HTTP codes - and is stored as given.
    """
    if _table is None or not job_id:
        return False
    entry = {
        "at": _now(),
        "event": str(event)[:64],
        "level": str(level)[:16],
    }
    if detail:
        entry["detail"] = str(detail)[:MAX_DETAIL_CHARS]
    for key, value in fields.items():
        if value is None:
            continue
        entry[key] = str(value)[:MAX_DETAIL_CHARS] if isinstance(value, str) else value
    try:
        _table.update_item(
            Key={"jobId": job_id},
            UpdateExpression=(
                "SET #o = if_not_exists(#o, :owner), "
                "createdAt = if_not_exists(createdAt, :now), "
                "updatedAt = :now, #t = :ttl, "
                "events = list_append(if_not_exists(events, :empty), :one)"
            ),
            ExpressionAttributeNames={"#o": "owner", "#t": "ttl"},
            ExpressionAttributeValues={
                ":owner": owner or "",
                ":now": entry["at"],
                ":ttl": int(time.time()) + TTL_DAYS * 24 * 3600,
                ":empty": [],
                ":one": [_clean(entry)],
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 - telemetry never fails an upload
        print(f"[barra] could not record upload event {event} for {job_id}: {exc}",
              flush=True)
        return False


def _clean(entry: dict) -> dict:
    """DynamoDB rejects floats and empty strings. Neither is worth a failed
    write, so both are converted rather than refused."""
    from decimal import Decimal

    out = {}
    for key, value in entry.items():
        if isinstance(value, float):
            out[key] = Decimal(str(value))
        elif value == "":
            continue
        else:
            out[key] = value
    return out


def trim(job_id: str) -> None:
    """Keep the log bounded. Called after the events that can run away - a
    part upload above all - rather than on every write, because reading the
    row back to count it costs more than the write itself."""
    if _table is None or not job_id:
        return
    try:
        item = _table.get_item(Key={"jobId": job_id}).get("Item") or {}
        events = item.get("events") or []
        if len(events) <= MAX_EVENTS:
            return
        dropped = len(events) - MAX_EVENTS
        # Keep the beginning: the first events say how the upload was set up,
        # and that is what a later reader needs. Keep the end: that is how it
        # died. Drop the repetitive middle, and say so in the gap.
        head = events[: MAX_EVENTS // 4]
        tail = events[-(MAX_EVENTS - MAX_EVENTS // 4 - 1):]
        gap = {"at": _now(), "event": "log-trimmed", "level": "info",
               "detail": f"{dropped} event(s) dropped from the middle"}
        _table.update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET events = :e",
            ExpressionAttributeValues={":e": head + [gap] + tail},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[barra] could not trim the upload log for {job_id}: {exc}", flush=True)


def read(job_id: str) -> dict | None:
    if _table is None or not job_id:
        return None
    try:
        return _table.get_item(Key={"jobId": job_id}).get("Item")
    except Exception:  # noqa: BLE001
        return None
