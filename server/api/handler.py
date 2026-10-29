"""AWS Lambda entrypoints. Same JSON contract as local_server.py."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

import auth
import referral
import uploads

try:
    from pose_warmup import (finish_pose_runtime_warmup,
                             start_pose_runtime_warmup)
except ImportError:  # API-only deployment packages may omit the worker helper
    def start_pose_runtime_warmup():
        return None

    def finish_pose_runtime_warmup(_warmup):
        return {"ready": False, "outcome": "unavailable", "elapsedMs": 0,
                "waitMs": 0}

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lam = boto3.client("lambda")
table = ddb.Table(os.environ["JOBS_TABLE"])
feedback_table = ddb.Table(os.environ["FEEDBACK_TABLE"])
referrals_table = ddb.Table(os.environ["REFERRALS_TABLE"])
BUCKET = os.environ["VIDEO_BUCKET"]
WORKER = os.environ.get("WORKER_FUNCTION", "")


# The movements the pipeline can measure: the names in barra.movements.MOVEMENTS.
# Kept as a literal because this module must not import barra (numpy) at load;
# tests/test_declared_exercise.py fails if the two ever drift apart.
DECLARABLE_EXERCISES = frozenset({
    "squat", "muscle_up", "pull_up", "knee_raise", "dip", "push_up",
    "front_lever", "planche", "pistol_squat", "split_squat",
    "bulgarian_split_squat",
})


def declared_exercise(raw) -> str | None:
    """The exercise the athlete said it is: "auto" when they said nothing, the
    catalog name when they named one, None when the value is not a movement the
    pipeline knows. Separators are forgiving (`pull-up`, `pull up`)."""
    if raw is None:
        return "auto"
    if not isinstance(raw, str):
        return None
    key = "_".join(raw.strip().lower().replace("-", " ").replace("_", " ").split())
    if key in ("", "auto"):
        return "auto"
    return key if key in DECLARABLE_EXERCISES else None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_ddb(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,X-Device-Id,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }


def _resp(code: int, body: dict) -> dict:
    return {"statusCode": code, "headers": _headers(), "body": json.dumps(body, cls=_Enc)}


def _header(event, name: str) -> str:
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == name:
            return (value or "").strip()
    return ""


def _owner(event) -> str:
    """Who this request belongs to.

    A signed-in caller owns "u:<sub>"; anyone else owns their device id. Both
    are just strings in the `owner` column, which is what lets an anonymous
    install keep working after accounts exist and lets /v1/auth/claim move one
    to the other by rewriting the column.

    A bearer token that does not verify is an error, never a silent fall back
    to the device id - that would hand a stale session someone else's data.
    """
    bearer = _header(event, "authorization")
    if bearer.lower().startswith("bearer "):
        owner, _email = auth.identify(bearer[7:].strip())
        return owner
    return _header(event, "x-device-id")


def _public(item: dict | None) -> dict | None:
    if not item:
        return None
    out = {k: v for k, v in item.items() if k != "owner"}
    return out


def _item(job_id: str) -> dict | None:
    return table.get_item(Key={"id": job_id}).get("Item")


STALE_AFTER_MIN = 30
# Below this an "upload" is not a clip. The shortest real capture the
# phone produces is a couple of hundred KB; 8 KB only ever means a
# stream that ended before it started.
MIN_CLIP_BYTES = 8 * 1024


def _reap_stale(item: dict | None) -> dict | None:
    """A job stuck in queued/processing means the worker died before it could
    mark anything (broken image, killed container). Reap it lazily on read so
    the phone gets a real error and its Retry button works, instead of an
    eternal spinner.

    `created` counts as stuck too. It means the phone asked for a job and then
    never finished sending the clip - a dead upload. Left alone it is the
    quietest failure the pipeline has: not `done`, so /v1/history skips it,
    and the phone's queue has long since forgotten the work, so it shows up on
    no screen at all while still sitting in the table. Reaped, it at least
    reads as failed with a reason."""
    if not item or item.get("status") not in {"created", "queued", "processing"}:
        return item
    created = item.get("createdAt") or ""
    try:
        then = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return item
    age_min = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if age_min < STALE_AFTER_MIN:
        return item
    # Spanish here: the API zip has no barra.i18n (see sweeper._reason).
    reason = (
        "la subida del vídeo no llegó a terminar. Vuelve a intentarlo."
        if item.get("status") == "created"
        else "el análisis no llegó a empezar. Vuelve a intentarlo."
    )
    table.update_item(
        Key={"id": item["id"]},
        UpdateExpression="SET #s = :s, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "failed",
            ":e": "%s (atascado %d min)" % (reason, int(age_min)),
        },
    )
    uploads.record(item["id"], item.get("owner") or "", "reaped", reason,
                   level="error", previousStatus=item.get("status"),
                   ageMin=int(age_min))
    item = dict(item)
    item["status"] = "failed"
    item["error"] = reason
    return item


def _owned(item: dict | None, owner: str) -> bool:
    return bool(item and owner and item.get("owner") == owner)


def _job_upload_url(owner: str, job_id: str) -> str:
    """Mint a short-lived PUT capability for this owner's fixed job key."""
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": f"{owner}/{job_id}.mp4",
                "ContentType": "video/mp4"},
        ExpiresIn=3600,
    )


def _feedback(owner: str, body: dict) -> tuple[int, dict]:
    """A user's report from the field, with an optional clip.

    The message is the only required field; everything else - the trace id of
    a measurement that looked wrong, the job it belonged to, the app version -
    arrives when the app can supply it. A clip is optional and goes to the
    bucket under feedback/<owner>/<id>.mp4 via a presigned PUT, the same
    contract a job upload speaks, so the client needs no second code path.

    The row never expires; the clip expires with the bucket's 30-day rule.
    Feedback read late loses its video, never its text.
    """
    message = (body.get("message") or "").strip() if isinstance(body.get("message"), str) else ""
    if not message:
        return 400, {"error": "a message is required"}
    if len(message) > 5000:
        return 400, {"error": "the message is too long (5000 characters max)"}

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

    out = dict(item)
    if body.get("video"):
        key = f"feedback/{owner}/{feedback_id}.mp4"
        item["videoKey"] = key
        # No ContentType in the signing params: a presigned PUT that signs the
        # content type rejects every request whose header differs from it, and
        # clients cannot agree on what a clip's mime is. Unsigned headers are
        # free - the same reason the multipart presigns sign none.
        out["uploadUrl"] = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=3600,
        )
        out["uploadMethod"] = "PUT"
    feedback_table.put_item(Item=_to_ddb(item))
    out.pop("owner", None)
    return 201, out


class _ReferralStore:
    """The `referral` module's storage interface, over DynamoDB.

    `put_new` is a conditional insert rather than get-then-put: two taps on a
    flaky connection are how a redemption is normally attempted twice, and a
    check-then-write loses that race every time. `bump` uses ADD for the same
    reason - two redemptions racing must not read the same balance and write
    back the same number.
    """

    def __init__(self, table):
        self._t = table

    def get(self, key):
        return self._t.get_item(Key={"id": key}).get("Item")

    def put_new(self, item):
        try:
            self._t.put_item(Item=_to_ddb(item),
                             ConditionExpression=Attr("id").not_exists())
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                return False
            raise

    def delete(self, key):
        self._t.delete_item(Key={"id": key})

    def bump(self, key, adds, init):
        expr, names, values = _bump_expression(adds, init)
        resp = self._t.update_item(
            Key={"id": key}, UpdateExpression=expr,
            ExpressionAttributeNames=names, ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW")
        return resp.get("Attributes")


def _bump_expression(adds: dict, init: dict) -> tuple[str, dict, dict]:
    """The DynamoDB update that adds to a balance and defaults the rest.

    `ADD` initialises a missing number to zero, so only the non-added fields
    need an `if_not_exists` SET. Split out so the expression itself can be
    asserted: a malformed update here fails at runtime, on a redemption.
    """
    names = {f"#{k}": k for k in set(adds) | set(init)}
    setters = [k for k in init if k not in adds]
    clauses = []
    values = {}
    if setters:
        clauses.append("SET " + ", ".join(
            f"#{k} = if_not_exists(#{k}, :d_{k})" for k in setters))
        values.update({f":d_{k}": _to_ddb(init[k]) for k in setters})
    if adds:
        clauses.append("ADD " + ", ".join(f"#{k} :a_{k}" for k in adds))
        values.update({f":a_{k}": _to_ddb(v) for k, v in adds.items()})
    return " ".join(clauses), names, values


def _referral_store() -> _ReferralStore:
    return _ReferralStore(referrals_table)


def _referral(owner: str) -> tuple[int, dict]:
    return 200, referral.status(_referral_store(), owner)


def _redeem(owner: str, body: dict) -> tuple[int, dict]:
    code = body.get("code") if isinstance(body.get("code"), str) else ""
    return referral.redeem(_referral_store(), owner, code)


def _claim(owner: str, device_id: str) -> dict:
    """Move an anonymous install's finished sessions onto an account.

    Only `done` jobs move. An in-flight job's clip lives at
    `<owner>/<job>.mp4` in the bucket, and rewriting the owner would point the
    worker at a key that does not exist - so uploads in progress stay with the
    device and finish where they started. The history is what matters here,
    and the history is exactly the done ones.
    """
    if not device_id:
        return {"claimed": 0, "error": "no device id given"}
    if device_id.startswith("u:"):
        return {"claimed": 0, "error": "that is already an account"}
    resp = table.query(
        IndexName="owner-index",
        KeyConditionExpression=Key("owner").eq(device_id),
        FilterExpression=Attr("status").eq("done"),
    )
    moved = 0
    for item in resp.get("Items") or []:
        table.update_item(
            Key={"id": item["id"]},
            UpdateExpression="SET #o = :new, claimedFrom = :old",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={":new": owner, ":old": device_id},
            # Two phones racing the same claim must not double-count, and a
            # job someone else already owns must never move.
            ConditionExpression=Attr("owner").eq(device_id),
        )
        moved += 1
    return {"claimed": moved}


def api(event, _context):
    try:
        return _route(event)
    except auth.AuthError as err:
        return _resp(err.status, {"error": str(err)})


def _route(event):
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")
    path = event.get("rawPath") or event.get("path") or "/"
    owner = _owner(event)
    body = {}
    if event.get("body"):
        raw = event["body"]
        if event.get("isBase64Encoded"):
            import base64

            raw = base64.b64decode(raw).decode()
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return _resp(400, {"error": "invalid json"})

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": _headers(), "body": ""}

    if method == "GET" and path.rstrip("/") == "/health":
        return _resp(200, {"ok": True, "accounts": auth.configured()})

    # Signing up and signing in are the only calls that cannot already have an
    # identity, so they are routed before the check for one.
    if method == "POST" and path.rstrip("/").startswith("/v1/auth/"):
        action = path.rstrip("/").rsplit("/", 1)[-1]
        handler = {
            "signup": auth.signup,
            "confirm": auth.confirm,
            "resend": auth.resend,
            "login": auth.login,
            "refresh": auth.refresh,
            "forgot": auth.forgot,
            "reset": auth.reset,
        }.get(action)
        if handler:
            return _resp(200, handler(body))
        if action == "claim":
            if not owner.startswith("u:"):
                return _resp(401, {"error": "sign in first"})
            return _resp(200, _claim(owner, (body.get("deviceId") or "").strip()))
        return _resp(404, {"error": "not found"})

    if method in {"POST", "GET", "DELETE"} and path.rstrip("/") != "/health" and not owner:
        return _resp(401, {"error": "missing X-Device-Id"})

    if method == "GET" and path.rstrip("/") == "/v1/me":
        return _resp(200, {"owner": owner, "account": owner.startswith("u:")})

    if method == "POST" and path.rstrip("/") == "/v1/jobs":
        # A declared movement is checked HERE, before a credit is charged or a
        # row written: the pipeline resolves it with a function that raises
        # SystemExit on a name it does not know, which would sink the worker.
        exercise = declared_exercise(body.get("exercise"))
        if exercise is None:
            return _resp(400, {
                "error": "unknown exercise - send one of: auto, "
                         + ", ".join(sorted(DECLARABLE_EXERCISES)),
            })
        job_id = uuid.uuid4().hex[:12]
        item = {
            "id": job_id,
            "owner": owner,
            "status": "created",
            # See local_server.py: detection is the safer default.
            "exercise": exercise,
            "createdAt": _now(),
        }
        # Same contract as local_server.py: declared variant and camera side
        # travel with the job to process_job. DynamoDB rejects empty strings
        # in some item shapes, so absent stays absent.
        for key in ("variant", "view"):
            value = (body.get(key) or "").strip() if isinstance(body.get(key), str) else ""
            if value:
                item[key] = value
        # A clip costs a credit only where the deployment charges for clips.
        # Off by default, so a phone in the field never hits a wall it did not
        # have yesterday; on, the balance is what referrals are worth.
        allowed, credits = referral.charge(_referral_store(), owner)
        if not allowed:
            return _resp(402, {
                "error": "no measurements left - invite a friend to earn more",
                "credits": credits,
            })
        table.put_item(Item=item)
        upload = _job_upload_url(owner, job_id)
        uploads.record(job_id, owner, "job-created",
                       f"exercise={item['exercise']}",
                       variant=item.get("variant"), view=item.get("view"),
                       userAgent=_header(event, "user-agent")[:120])
        pub = _public(item)
        pub["uploadUrl"] = upload
        pub["uploadMethod"] = "PUT"
        return _resp(201, pub)

    if method == "GET" and path.rstrip("/") == "/v1/jobs":
        resp = table.query(
            IndexName="owner-index",
            KeyConditionExpression=Key("owner").eq(owner),
            ScanIndexForward=False,
        )
        # Reap here too, not only on the single-job read. A dead upload is
        # precisely the job nobody ever reads by id again - the phone dropped
        # the work from its queue long ago - so the list is the only place
        # left that can notice it and give it a reason.
        jobs = [_public(_reap_stale(i)) for i in resp.get("Items") or []]
        return _resp(200, {"jobs": jobs})

    if method == "GET" and path.rstrip("/") == "/v1/history":
        # The training history: the measurements of every finished job, keyed
        # by the device id, held for as long as the table exists. The clip
        # itself is not part of it - it expires from the bucket after 30 days,
        # and the copy a replay plays stays on the phone.
        resp = table.query(
            IndexName="owner-index",
            KeyConditionExpression=Key("owner").eq(owner),
            FilterExpression=Attr("status").eq("done"),
            ScanIndexForward=False,
        )
        history = [
            {
                "id": i["id"],
                "createdAt": i.get("createdAt", ""),
                "exercise": i.get("exercise", ""),
                "result": i.get("result"),
            }
            for i in resp.get("Items") or []
        ]
        return _resp(200, {"history": history})

    if method == "POST" and path.rstrip("/") == "/v1/chat":
        # The objectives intake. The model call and the key stay server-side;
        # the phone just passes the conversation and reads the reply.
        from chat import chat

        return _resp(200, chat(body.get("messages") or []))

    if method == "POST" and path.rstrip("/") == "/v1/feedback":
        code, payload = _feedback(owner, body)
        return _resp(code, payload)

    if method == "GET" and path.rstrip("/") == "/v1/referral":
        code, payload = _referral(owner)
        return _resp(code, payload)

    if method == "POST" and path.rstrip("/") == "/v1/referral/redeem":
        code, payload = _redeem(owner, body)
        return _resp(code, payload)

    parts = [p for p in path.split("/") if p]

    if method == "GET" and len(parts) == 3 and parts[0] == "v1" and parts[1] == "jobs":
        item = _reap_stale(_item(parts[2]))
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        return _resp(200, _public(item))

    if method == "DELETE" and len(parts) == 3 and parts[0] == "v1" and parts[1] == "jobs":
        job_id = parts[2]
        item = _item(job_id)
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        s3.delete_object(Bucket=BUCKET, Key=f"{owner}/{job_id}.mp4")
        # Deleting a session deletes every copy of its clip.
        s3.delete_object(Bucket=BUCKET, Key=ORIGINAL_KEY.format(owner=owner, job=job_id))
        table.delete_item(Key={"id": job_id})
        return _resp(200, {"ok": True, "id": job_id})

    if (method == "POST" and len(parts) == 4 and parts[0] == "v1"
            and parts[1] == "jobs" and parts[3] == "upload-url"):
        job_id = parts[2]
        item = _reap_stale(_item(job_id))
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        if item.get("status") != "created" or item.get("uploadId"):
            return _resp(409, {"error": "job is not waiting for a single-file upload"})
        return _resp(200, {"uploadUrl": _job_upload_url(owner, job_id),
                           "uploadMethod": "PUT"})

    # ---- resumable upload: S3 multipart, one presigned part at a time ----
    # A phone on mobile data does not lose a 40 MB clip because a train went
    # through a tunnel. Parts already uploaded are kept server-side; the
    # client re-asks only for the part URLs it has not finished.
    if method == "POST" and len(parts) == 5 and parts[0] == "v1" and parts[1] == "jobs" and parts[3] == "upload":
        item = _item(parts[2])
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        action = parts[4]
        if action == "start":
            if item.get("uploadId"):
                upload_id = item["uploadId"]
                uploads.record(parts[2], owner, "upload-resumed",
                               "the phone came back to an upload already in progress",
                               uploadId=upload_id)
            else:
                upload = s3.create_multipart_upload(
                    Bucket=BUCKET, Key=f"{owner}/{parts[2]}.mp4",
                    ContentType="video/mp4",
                )
                upload_id = upload["UploadId"]
                table.update_item(
                    Key={"id": parts[2]},
                    UpdateExpression="SET #u = :u",
                    ExpressionAttributeNames={"#u": "uploadId"},
                    ExpressionAttributeValues={":u": upload_id},
                )
                uploads.record(parts[2], owner, "upload-started", "",
                               uploadId=upload_id)
            return _resp(201, {"uploadId": upload_id, "partSize": 8 * 1024 * 1024})
        if action == "part":
            part_number = int((body or {}).get("partNumber") or 0)
            if part_number < 1 or part_number > 10000:
                return _resp(400, {"error": "bad partNumber"})
            upload_id = item.get("uploadId")
            if not upload_id:
                return _resp(409, {"error": "no upload in progress - start first"})
            url = s3.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": BUCKET, "Key": f"{owner}/{parts[2]}.mp4",
                    "UploadId": upload_id, "PartNumber": part_number,
                },
                ExpiresIn=3600,
            )
            uploads.record(parts[2], owner, "part-presigned", "",
                           partNumber=part_number)
            uploads.trim(parts[2])
            return _resp(200, {"url": url, "partNumber": part_number})
        if action == "complete":
            upload_id = item.get("uploadId")
            if not upload_id:
                return _resp(409, {"error": "no upload in progress"})
            s3parts = sorted(
                ({"ETag": p["etag"], "PartNumber": int(p["partNumber"])}
                 for p in (body or {}).get("parts") or []),
                key=lambda x: x["PartNumber"],
            )
            key = f"{owner}/{parts[2]}.mp4"
            try:
                s3.complete_multipart_upload(
                    Bucket=BUCKET, Key=key,
                    UploadId=upload_id, MultipartUpload={"Parts": s3parts},
                )
            except Exception as exc:  # noqa: BLE001
                uploads.record(parts[2], owner, "upload-failed", str(exc),
                               level="error", partCount=len(s3parts))
                return _resp(502, {"error": "the upload could not be assembled"})

            # S3 assembles whatever parts it is handed, and a client that
            # streamed nothing still gets a 200 and an object. A 17-byte .mp4
            # sat in this bucket from exactly that: the failure surfaced much
            # later, inside the worker, as a clip OpenCV could not open. Check
            # the size at the seam where it is still an upload problem.
            size = 0
            try:
                size = int(s3.head_object(Bucket=BUCKET, Key=key)["ContentLength"])
            except Exception as exc:  # noqa: BLE001 - unknown size is not a refusal
                uploads.record(parts[2], owner, "size-check-skipped", str(exc),
                               level="warn")
            if size and size < MIN_CLIP_BYTES:
                uploads.record(parts[2], owner, "upload-too-small",
                               f"{size} bytes assembled from {len(s3parts)} part(s)",
                               level="error", bytes=size)
                table.update_item(
                    Key={"id": parts[2]},
                    UpdateExpression="REMOVE #u SET #s = :s, #e = :e",
                    ExpressionAttributeNames={"#u": "uploadId", "#s": "status",
                                              "#e": "error"},
                    ExpressionAttributeValues={
                        ":s": "failed",
                        ":e": "the clip arrived empty or truncated. Retry.",
                    },
                )
                return _resp(400, {"error": "the clip arrived empty or truncated",
                                   "bytes": size})

            table.update_item(
                Key={"id": parts[2]},
                UpdateExpression="REMOVE #u SET #s = :s",
                ExpressionAttributeNames={"#u": "uploadId", "#s": "status"},
                ExpressionAttributeValues={":s": "uploaded"},
            )
            uploads.record(parts[2], owner, "upload-complete", "",
                           partCount=len(s3parts), bytes=size)
            return _resp(200, {"ok": True})
        if action == "abort":
            upload_id = item.get("uploadId")
            if upload_id:
                s3.abort_multipart_upload(
                    Bucket=BUCKET, Key=f"{owner}/{parts[2]}.mp4", UploadId=upload_id)
                table.update_item(
                    Key={"id": parts[2]},
                    UpdateExpression="REMOVE #u",
                    ExpressionAttributeNames={"#u": "uploadId"},
                )
                uploads.record(parts[2], owner, "upload-aborted",
                               "the client abandoned this upload", level="warn")
            return _resp(200, {"ok": True})

    # The phone's log of this upload, shipped as it happens. A dropped
    # connection, a retried part, a process the system killed: none of it is
    # visible from here, and all of it is what a "never finished uploading"
    # row needs to stop being a guess.
    if method == "POST" and len(parts) == 5 and parts[0] == "v1" \
            and parts[1] == "jobs" and parts[3] == "upload" and parts[4] == "event":
        item = _item(parts[2])
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        name = (body.get("event") or "client").strip()[:64]
        detail = (body.get("detail") or "")[:400]
        level = (body.get("level") or "info").strip().lower()
        if level not in {"info", "warn", "error"}:
            level = "info"
        stored = uploads.record(parts[2], owner, f"client:{name}", detail,
                                level=level,
                                partNumber=body.get("partNumber"),
                                attempt=body.get("attempt"))
        uploads.trim(parts[2])
        return _resp(202, {"ok": True, "stored": stored})

    if method == "POST" and len(parts) == 4 and parts[-1] == "submit":
        job_id = parts[2]
        item = _item(job_id)
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        try:
            uploaded = s3.head_object(
                Bucket=BUCKET, Key=f"{owner}/{job_id}.mp4")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return _resp(409, {"error": "the clip has not finished uploading"})
            return _resp(502, {"error": "the uploaded clip could not be verified"})
        except Exception:  # noqa: BLE001 - fail closed at the queue boundary
            return _resp(502, {"error": "the uploaded clip could not be verified"})
        size = int(uploaded.get("ContentLength") or 0)
        if size < MIN_CLIP_BYTES:
            return _resp(400, {"error": "the clip arrived empty or truncated",
                               "bytes": size})
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "queued"},
        )
        uploads.record(job_id, owner, "dispatch-started", "worker invoke requested")
        if WORKER:
            lam.invoke(
                FunctionName=WORKER,
                InvocationType="Event",
                Payload=json.dumps({"job_id": job_id, "owner": owner}).encode(),
            )
        else:
            worker({"job_id": job_id, "owner": owner}, None)
        uploads.record(job_id, owner, "dispatch-accepted",
                       "worker invoke accepted" if WORKER else "in-process worker returned")
        uploads.record(job_id, owner, "submitted",
                       "handed to the worker" if WORKER else "measured in-process")
        return _resp(202, _public(_item(job_id)) or {"id": job_id, "status": "queued"})

    return _resp(404, {"error": "not found"})


# The clip as uploaded, kept beside the trimmed copy for debugging.
ORIGINAL_KEY = "{owner}/{job}.original.mp4"


def _store_trimmed_clip(src: Path, owner: str, job_id: str, start_s: float,
                        end_s: float, duration_s: float | None = None,
                        rotate: int = 0) -> bool:
    """Cut the located window out of the clip and overwrite the stored object,
    after keeping the clip as uploaded at `ORIGINAL_KEY`.

    The original is kept for debugging, under the same 30-day lifecycle: a
    Bulgarian split squat whose ruler failed only because of the seconds
    before the set scored fine once trimmed, so the trimmed copy alone could
    not reproduce the bug (2026-10-18) - the clip had to be pulled off the
    phone.

    Best-effort by design: if there is no cutter, the cut fails, or the upload
    fails, the original stays in S3 and the job still succeeds. A localization
    that cannot be stored is not a reason to lose the measurement.

    `rotate=180` stores the clip the way up the measurement saw it: a clip the
    pipeline had to turn (it was filmed upside down) is replayed turned, so the
    skeleton drawn on it lands on the athlete.
    """
    try:
        from barra.frames import trim_clip
    except ImportError:
        return False
    margin = 1.0
    start = max(0.0, float(start_s) - margin)
    end = float(end_s) + margin
    if duration_s:
        end = min(end, float(duration_s))
    if end - start < 2.0:
        return False
    out = Path("/tmp") / f"{job_id}-exercise.mp4"
    # The normal path calls trim_clip exactly as before; `rotate` is only
    # passed when the clip has to be turned.
    if trim_clip(src, start, end, out, **({"rotate": rotate} if rotate else {})) is None:
        return False
    key = f"{owner}/{job_id}.mp4"
    try:
        # Server-side copy: no re-upload. If it fails, nothing is overwritten.
        s3.copy_object(Bucket=BUCKET, Key=ORIGINAL_KEY.format(owner=owner, job=job_id),
                       CopySource={"Bucket": BUCKET, "Key": key},
                       ContentType="video/mp4", MetadataDirective="REPLACE")
    except Exception:  # noqa: BLE001 - never trade the original for the cut
        return False
    try:
        s3.upload_file(str(out), BUCKET, f"{owner}/{job_id}.mp4",
                       ExtraArgs={"ContentType": "video/mp4"})
        return True
    except Exception:  # noqa: BLE001 - keep the original on any upload failure
        return False


def _set_stage(job_id: str, owner: str, name: str,
               timings: list[dict[str, int | str]] | None = None) -> None:
    """Where the job is. `stage` stays the English phrase the installed app
    matches on; `stageCode` is stable and `stageText` is what to show.

    When called by the worker, record the two synchronous writes separately in
    memory. The worker emits this diagnostic after persisting the first result,
    so measuring stage telemetry does not add another write to the measured
    critical path.
    """
    code, text = _i18n_stage(name)
    table_started_ns = time.perf_counter_ns()
    table.update_item(
        Key={"id": job_id},
        UpdateExpression="SET #st = :st, #sc = :sc, #sx = :sx",
        ExpressionAttributeNames={"#st": "stage", "#sc": "stageCode", "#sx": "stageText"},
        ExpressionAttributeValues={":st": name, ":sc": code, ":sx": text},
    )
    table_us = (time.perf_counter_ns() - table_started_ns) // 1000
    log_started_ns = time.perf_counter_ns()
    uploads.record(job_id, owner, "stage", name)
    log_us = (time.perf_counter_ns() - log_started_ns) // 1000
    if timings is not None:
        timings.append({"name": name, "tableUs": table_us, "uploadLogUs": log_us,
                        "totalUs": table_us + log_us})


def _i18n_stage(name: str) -> tuple[str, str]:
    try:
        from barra.i18n import stage
    except ImportError:  # the API zip has no barra; only the worker sets stages
        return "stage.other", name
    return stage(name)


def _spanish_error(text: str) -> str:
    """A job's error as the phone shows it. The English original stays in
    the trace and the upload log."""
    try:
        from barra.i18n import localize_text
    except ImportError:
        return text
    return localize_text(text)


def _write_result(job_id: str, result: dict) -> None:
    table.update_item(
        Key={"id": job_id},
        UpdateExpression="SET #s = :s, #r = :r",
        ExpressionAttributeNames={"#s": "status", "#r": "result"},
        ExpressionAttributeValues={":s": "done", ":r": _to_ddb(result)},
    )


def worker(event, _context):
    job_id = event["job_id"]
    owner = event.get("owner") or (_item(job_id) or {}).get("owner") or ""
    dest = Path("/tmp") / f"{job_id}.mp4"
    worker_entry = time.perf_counter()
    uploads.record(job_id, owner, "worker-entry", "worker handler entered")

    def _fail(exc: Exception) -> None:
        # Any death inside this handler must land on the job record, not in a
        # log stream nobody reads. An async invoke that dies at import time
        # used to leave the clip queued forever while the phone showed a
        # spinner no one would ever answer.
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s, #e = :e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": "failed", ":e": _spanish_error(str(exc))},
        )
        try:
            from barra.tracestore import put_failure
            put_failure(job_id, "worker", str(exc))
        except Exception:  # noqa: BLE001
            pass
        uploads.record(job_id, owner, "worker-failed", str(exc), level="error")

    try:
        # Inside the try on purpose: a broken image (missing module, bad
        # dependency) must fail the job, not crash before the first update.
        import process  # noqa: F401
        uploads.record(job_id, owner, "worker-ready", "process module imported",
                       importMs=round((time.perf_counter() - worker_entry) * 1000))

        stage_write_timings: list[dict[str, int | str]] = []

        def _stage(name: str) -> None:
            _set_stage(job_id, owner, name, timings=stage_write_timings)

        _stage("receiving the clip")
        # When Ultralytics is the configured pose backend, import its Python
        # runtime while S3 delivers the clip. This is a no-op for MediaPipe.
        # Model construction stays in the measured pose path.
        pose_warmup = start_pose_runtime_warmup()
        download_started_ns = time.perf_counter_ns()
        try:
            s3.download_file(BUCKET, f"{owner}/{job_id}.mp4", str(dest))
        finally:
            pose_warmup_timing = finish_pose_runtime_warmup(pose_warmup)
        clip_download_us = (time.perf_counter_ns() - download_started_ns) // 1000
        if not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError("the clip never arrived in storage")
        item = _item(job_id) or {"id": job_id, "exercise": "muscle_up"}
        processing_write_started_ns = time.perf_counter_ns()
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "processing"},
        )
        processing_write_us = (time.perf_counter_ns() - processing_write_started_ns) // 1000

        # Locate the exercise ALONGSIDE the pose, not before it: the vision call
        # took 57 s of a 375 s job on 2026-10-11, and pose (128 s) does not need
        # it. Fusion uses the vote only if localization finished during pose;
        # it never extends the first-result critical path. The measurement runs
        # on the FULL clip:
        # every reported timestamp is in the source video's time, and the
        # phone seeks its own local copy with them. Localization decides what
        # is kept, not what is measured.
        from concurrent.futures import ThreadPoolExecutor
        from process import add_vision, measure_job

        _stage("locating the exercise")
        pool = ThreadPoolExecutor(max_workers=1)
        localization_timing = {
            "startNs": None, "endNs": None, "outcome": "not-finished",
            "fusionWaitMs": None, "fusionOutcome": "not-awaited",
        }
        localization_timing_lock = threading.Lock()

        def _locate():
            started_ns = time.perf_counter_ns()
            with localization_timing_lock:
                localization_timing["startNs"] = started_ns
            try:
                from vision import locate_exercise
                located = locate_exercise(dest, Path("/tmp") / f"{job_id}-locate",
                                           item.get("exercise"))
                outcome = "usable" if located and located.get("usable") else "no-window"
                return located
            except Exception:  # noqa: BLE001 - localization never fails a job
                outcome = "error"
                return None
            finally:
                with localization_timing_lock:
                    localization_timing["endNs"] = time.perf_counter_ns()
                    localization_timing["outcome"] = outcome

        located_future = pool.submit(_locate)

        def _vision_vote(wait_s: float = 0.0):
            started_ns = time.perf_counter_ns()
            try:
                # Localization overlaps pose. Fusion waits for a late vote only
                # when geometry and the model disagree (process.py
                # VISION_VOTE_WAIT_S): then the vote decides the movement.
                located = located_future.result(timeout=wait_s)
                label = (located or {}).get("exercise") or None
                if label and str(label).lower() not in ("none", "unknown", ""):
                    outcome = "ready"
                    return label
                outcome = "no-vote"
                return None
            except Exception as exc:
                outcome = "timeout" if isinstance(exc, TimeoutError) else "error"
                raise
            finally:
                with localization_timing_lock:
                    localization_timing["fusionWaitMs"] = round(
                        (time.perf_counter_ns() - started_ns) / 1_000_000)
                    localization_timing["fusionOutcome"] = outcome

        def _vision_window():
            # Only a window already in hand: fusion has had its wait by the
            # time reps are counted, and counting never waits on vision.
            if not located_future.done():
                return None
            located = located_future.result() or {}
            if not located.get("usable") or located.get("startS") is None:
                return None
            return float(located["startS"]), float(located["endS"])

        result = measure_job(item, dest, on_stage=_stage, vision_label=_vision_vote,
                             vision_window=_vision_window)
        # A clip the pipeline had to turn (filmed upside down) is stored turned.
        rotate = int((result.get("orientation") or {}).get("rotatedBy") or 0)

        # The measurement reaches the phone now. Cutting and re-uploading the
        # stored clip (~44 s on 2026-10-11), the model prose (~10-15 s,
        # docs/SPEED-PLAN.md B) and the advisory vision note come after it.
        result_write_started_ns = time.perf_counter_ns()
        _write_result(job_id, result)
        result_write_us = (time.perf_counter_ns() - result_write_started_ns) // 1000
        result_persisted_ns = time.perf_counter_ns()
        with localization_timing_lock:
            timing_snapshot = dict(localization_timing)
        locator_end_ns = timing_snapshot["endNs"]
        locator_before_result = (
            locator_end_ns is not None and locator_end_ns <= result_persisted_ns
        )
        uploads.record(
            job_id, owner, "worker-timing", "localization/fusion at first result",
            fusionWaitMs=timing_snapshot["fusionWaitMs"],
            fusionOutcome=timing_snapshot["fusionOutcome"],
            locatorMsAtResult=(round((locator_end_ns - timing_snapshot["startNs"])
                                     / 1_000_000)
                               if locator_before_result else None),
            locatorCompleteAtResult=locator_before_result,
            stageWriteCount=len(stage_write_timings),
            stageTableUs=sum(row["tableUs"] for row in stage_write_timings),
            stageUploadLogUs=sum(row["uploadLogUs"] for row in stage_write_timings),
            stageTotalUs=sum(row["totalUs"] for row in stage_write_timings),
            stageSlowestName=(max(stage_write_timings,
                                  key=lambda row: row["totalUs"])["name"]
                              if stage_write_timings else None),
            stageSlowestUs=(max(row["totalUs"] for row in stage_write_timings)
                            if stage_write_timings else None),
            clipDownloadUs=clip_download_us,
            poseWarmupOutcome=pose_warmup_timing["outcome"],
            poseWarmupElapsedMs=pose_warmup_timing["elapsedMs"],
            poseWarmupWaitMs=pose_warmup_timing["waitMs"],
            processingStateWriteUs=processing_write_us,
            resultWriteUs=result_write_us,
        )
        uploads.record(job_id, owner, "done",
                       f"{result.get('exercise', '?')}, {result.get('n_reps', 0)} rep(s)")

        post_result_wait_ns = time.perf_counter_ns()
        try:
            located = located_future.result(timeout=300)
        except Exception:  # noqa: BLE001
            located = None
        post_result_wait_ms = round(
            (time.perf_counter_ns() - post_result_wait_ns) / 1_000_000)
        with localization_timing_lock:
            locator_start_ns = localization_timing["startNs"]
            locator_end_ns = localization_timing["endNs"]
            locator_outcome = localization_timing["outcome"]
        uploads.record(
            job_id, owner, "locator-finished", locator_outcome,
            durationMs=(round((locator_end_ns - locator_start_ns) / 1_000_000)
                        if locator_start_ns is not None and locator_end_ns is not None
                        else None),
            resultPersisted=True,
            postResultWaitMs=post_result_wait_ms,
            usable=bool(located and located.get("usable")),
        )
        pool.shutdown(wait=False)
        localization = None
        if located and located.get("usable"):
            loc = dict(located)
            loc["source"] = "vision"
            loc["trimmed"] = _store_trimmed_clip(
                dest, owner, job_id, located["startS"], located["endS"],
                located.get("durationS"), rotate=rotate)
            localization = loc
        # Vision unavailable or it found no window: fall back to the geometric
        # working set the measurement already computed.
        if localization is None:
            trim = result.get("trim") or {}
            s, e = trim.get("startS"), trim.get("endS")
            if s is not None and e is not None and e > s:
                if _store_trimmed_clip(dest, owner, job_id, s, e,
                                       result.get("duration_s"), rotate=rotate):
                    localization = {"source": "geometry", "startS": s, "endS": e,
                                    "durationS": result.get("duration_s"),
                                    "trimmed": True}
        if localization is not None:
            result["localization"] = localization
            print(f"[barra] stored clip localized by {localization.get('source')} "
                  f"{localization.get('startS')}-{localization.get('endS')}s "
                  f"trimmed={localization.get('trimmed')}", flush=True)
        elif rotate and result.get("duration_s"):
            # Nothing to cut, but the measurement saw the clip turned: store
            # the whole clip turned too.
            turned = _store_trimmed_clip(dest, owner, job_id, 0.0,
                                         result["duration_s"],
                                         result["duration_s"], rotate=rotate)
            print(f"[barra] stored the whole clip turned {rotate} degrees: {turned}",
                  flush=True)
        else:
            print("[barra] localization skipped; storing the raw clip", flush=True)

        if result.get("visionStatus") == "pending":
            try:
                result = add_vision(item, dest, result)
            except Exception as exc:  # noqa: BLE001 - the measurement stands
                result = {**result, "visionStatus": "failed"}
                print(f"[barra] vision pass failed: {exc}", flush=True)
            uploads.record(job_id, owner, "vision", result.get("visionStatus", ""))

        # The model prose, like the vision note: after the result, judged,
        # the fallback text standing until a good reply replaces it.
        from process import finish_prose
        if result.get("proseStatus") == "pending":
            try:
                result = finish_prose(item, result)
            except Exception as exc:  # noqa: BLE001 - the fallback text stands
                result = {**result, "proseStatus": "failed"}
                print(f"[barra] prose pass failed: {exc}", flush=True)
            uploads.record(job_id, owner, "prose", result.get("proseStatus", ""))
        _write_result(job_id, result)
        uploads.trim(job_id)
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
    return {"ok": True}
