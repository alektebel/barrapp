"""The scheduled pass that finishes what the phone abandoned.

Reaping used to happen only when someone read a job: `_reap_stale` in
handler.py turns a stuck row into a failure on the way out of GET /v1/jobs.
That works for a job the phone is still asking about, and not at all for the
one it is not - and the abandoned upload is precisely the job nobody reads
again, because the phone dropped the work from its queue hours ago. Eight rows
sat in `created` and `queued` in the live table for a week for exactly this
reason: nothing was ever going to look at them.

So the reaping runs on a clock as well, and it does the two things a read
could never do:

  * aborts the multipart upload the abandoned job left behind. S3 keeps the
    parts of an unfinished upload forever, invisible to ListObjects and
    untouched by the bucket's expiry rule - six of them had been accruing
    storage since the day they were started.
  * writes why, into the upload log, so an abandoned clip stops being a row
    with a guess in its error field.

Idempotent on purpose: it runs every fifteen minutes and must be safe to run
twice on the same minute, so every write is conditioned on the state it
expects to find.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Attr

import uploads

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["JOBS_TABLE"])
BUCKET = os.environ["VIDEO_BUCKET"]

# The same window handler.py reaps on, so a job does not read as failed in one
# place and pending in the other.
STALE_AFTER_MIN = 30
# A multipart upload older than this has no client still working on it: the
# phone's own resume gives up long before, and the presigned part urls it
# would need expire after an hour.
MPU_STALE_AFTER_H = 6

STUCK = {"created", "queued", "processing"}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_min(stamp: str) -> float | None:
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 60


def _reason(status: str, age_min: float) -> str:
    base = {
        "created": "the clip was never finished uploading",
        "queued": "the worker never picked this up",
        "processing": "the worker died while measuring this",
    }.get(status, "this job never reached a terminal state")
    return f"{base} (stuck for {int(age_min)} min). Retry."


def reap_jobs() -> list[dict]:
    """Fail every job that has been stuck past the window. Returns what it
    touched, which is what the invocation's log line is built from."""
    reaped = []
    kwargs = {"FilterExpression": Attr("status").is_in(list(STUCK))}
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items") or []:
            status = item.get("status")
            # Checked here as well as in the FilterExpression, and not out of
            # caution: the filter is the only thing standing between this
            # sweep and marking a finished measurement failed, and a filter
            # that is dropped or mistyped fails open. The status is right
            # here in the item; there is no reason to take the query's word.
            if status not in STUCK:
                continue
            age = _age_min(item.get("createdAt") or "")
            if age is None or age < STALE_AFTER_MIN:
                continue
            job_id = item["id"]
            owner = item.get("owner") or ""
            reason = _reason(status, age)
            try:
                table.update_item(
                    Key={"id": job_id},
                    UpdateExpression="SET #s = :failed, #e = :err, reapedAt = :now",
                    ExpressionAttributeNames={"#s": "status", "#e": "error"},
                    ExpressionAttributeValues={
                        ":failed": "failed",
                        ":err": reason,
                        ":now": _stamp(),
                    },
                    # Two sweeps overlapping, or a worker finishing between the
                    # scan and this write, must not overwrite a real result.
                    ConditionExpression=Attr("status").eq(status),
                )
            except Exception:  # noqa: BLE001 - it moved on; that is the good case
                continue
            uploads.record(job_id, owner, "reaped", reason, level="error",
                           previousStatus=status, ageMin=int(age))
            reaped.append({"id": job_id, "was": status, "ageMin": int(age)})
        token = resp.get("LastEvaluatedKey")
        if not token:
            return reaped
        kwargs["ExclusiveStartKey"] = token


def abort_stale_uploads() -> list[dict]:
    """Abort the multipart uploads nobody is going to finish.

    An unfinished upload is billed and invisible: it does not appear in
    ListObjects, and the bucket's 30-day expiry rule does not apply to it. The
    lifecycle rule added alongside this function is the belt; this is the
    braces, and it is the half that can say which job it belonged to.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MPU_STALE_AFTER_H)
    aborted = []
    paginator = s3.get_paginator("list_multipart_uploads")
    for page in paginator.paginate(Bucket=BUCKET):
        for upload in page.get("Uploads") or []:
            if upload["Initiated"] > cutoff:
                continue
            key = upload["Key"]
            try:
                s3.abort_multipart_upload(
                    Bucket=BUCKET, Key=key, UploadId=upload["UploadId"])
            except Exception as exc:  # noqa: BLE001
                print(f"[barra] could not abort {key}: {exc}", flush=True)
                continue
            # The key is "<owner>/<job>.mp4"; that is the only place the job
            # id survives once the row has been deleted.
            owner, _, name = key.partition("/")
            job_id = name.removesuffix(".mp4")
            uploads.record(job_id, owner, "upload-abandoned",
                           f"the multipart upload was abandoned and has been aborted "
                           f"({upload['Initiated'].isoformat()})",
                           level="error", key=key)
            aborted.append({"key": key, "initiated": upload["Initiated"].isoformat()})
    return aborted


def sweep(_event=None, _context=None) -> dict:
    # The two halves are independent, and one falling over must not discard
    # the other's work. The first run of this function in the live stack died
    # on a missing s3:ListBucketMultipartUploads and reported nothing at all,
    # even though the reap before it had already succeeded.
    reaped: list[dict] = []
    aborted: list[dict] = []
    trouble: list[str] = []
    try:
        reaped = reap_jobs()
    except Exception as exc:  # noqa: BLE001
        trouble.append(f"reap failed: {exc}")
    try:
        aborted = abort_stale_uploads()
    except Exception as exc:  # noqa: BLE001
        trouble.append(f"abort failed: {exc}")
    for line in trouble:
        print(f"[barra] sweep: {line}", flush=True)
    print(f"[barra] sweep: reaped {len(reaped)} job(s), "
          f"aborted {len(aborted)} abandoned upload(s)", flush=True)
    for row in reaped:
        print(f"[barra]   reaped {row['id']} ({row['was']}, {row['ageMin']} min)", flush=True)
    for row in aborted:
        print(f"[barra]   aborted {row['key']} (started {row['initiated']})", flush=True)
    out = {"reaped": len(reaped), "aborted": len(aborted)}
    if trouble:
        # Surfaced in the return value as well as the log, so a manual invoke
        # shows the problem instead of a reassuring pair of zeros.
        out["errors"] = trouble
    return out
