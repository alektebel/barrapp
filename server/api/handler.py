"""AWS Lambda entrypoints. Same JSON contract as local_server.py."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr, Key

import auth

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lam = boto3.client("lambda")
table = ddb.Table(os.environ["JOBS_TABLE"])
feedback_table = ddb.Table(os.environ["FEEDBACK_TABLE"])
BUCKET = os.environ["VIDEO_BUCKET"]
WORKER = os.environ.get("WORKER_FUNCTION", "")


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
    reason = (
        "the clip was never finished uploading. Retry."
        if item.get("status") == "created"
        else "the worker never picked this up. Retry."
    )
    table.update_item(
        Key={"id": item["id"]},
        UpdateExpression="SET #s = :s, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "failed",
            ":e": "%s (stuck for %d min)" % (reason, int(age_min)),
        },
    )
    item = dict(item)
    item["status"] = "failed"
    item["error"] = reason
    return item


def _owned(item: dict | None, owner: str) -> bool:
    return bool(item and owner and item.get("owner") == owner)


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
        job_id = uuid.uuid4().hex[:12]
        item = {
            "id": job_id,
            "owner": owner,
            "status": "created",
            # See local_server.py: detection is the safer default.
            "exercise": body.get("exercise") or "auto",
            "createdAt": _now(),
        }
        # Same contract as local_server.py: declared variant and camera side
        # travel with the job to process_job. DynamoDB rejects empty strings
        # in some item shapes, so absent stays absent.
        for key in ("variant", "view"):
            value = (body.get(key) or "").strip() if isinstance(body.get(key), str) else ""
            if value:
                item[key] = value
        table.put_item(Item=item)
        upload = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": f"{owner}/{job_id}.mp4", "ContentType": "video/mp4"},
            ExpiresIn=3600,
        )
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
        table.delete_item(Key={"id": job_id})
        return _resp(200, {"ok": True, "id": job_id})

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
            s3.complete_multipart_upload(
                Bucket=BUCKET, Key=f"{owner}/{parts[2]}.mp4",
                UploadId=upload_id, MultipartUpload={"Parts": s3parts},
            )
            table.update_item(
                Key={"id": parts[2]},
                UpdateExpression="REMOVE #u SET #s = :s",
                ExpressionAttributeNames={"#u": "uploadId", "#s": "status"},
                ExpressionAttributeValues={":s": "uploaded"},
            )
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
            return _resp(200, {"ok": True})

    if method == "POST" and len(parts) == 4 and parts[-1] == "submit":
        job_id = parts[2]
        item = _item(job_id)
        if not _owned(item, owner):
            return _resp(404, {"error": "unknown job"})
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "queued"},
        )
        if WORKER:
            lam.invoke(
                FunctionName=WORKER,
                InvocationType="Event",
                Payload=json.dumps({"job_id": job_id, "owner": owner}).encode(),
            )
        else:
            worker({"job_id": job_id, "owner": owner}, None)
        return _resp(202, _public(_item(job_id)) or {"id": job_id, "status": "queued"})

    return _resp(404, {"error": "not found"})


def worker(event, _context):
    job_id = event["job_id"]
    owner = event.get("owner") or (_item(job_id) or {}).get("owner") or ""
    dest = Path("/tmp") / f"{job_id}.mp4"

    def _fail(exc: Exception) -> None:
        # Any death inside this handler must land on the job record, not in a
        # log stream nobody reads. An async invoke that dies at import time
        # used to leave the clip queued forever while the phone showed a
        # spinner no one would ever answer.
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s, #e = :e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":s": "failed", ":e": str(exc)},
        )
        try:
            from barra.tracestore import put_failure
            put_failure(job_id, "worker", str(exc))
        except Exception:  # noqa: BLE001
            pass

    try:
        # Inside the try on purpose: a broken image (missing module, bad
        # dependency) must fail the job, not crash before the first update.
        from process import process_job

        def _stage(name: str) -> None:
            table.update_item(
                Key={"id": job_id},
                UpdateExpression="SET #st = :st",
                ExpressionAttributeNames={"#st": "stage"},
                ExpressionAttributeValues={":st": name},
            )

        _stage("receiving the clip")
        s3.download_file(BUCKET, f"{owner}/{job_id}.mp4", str(dest))
        if not dest.exists() or dest.stat().st_size == 0:
            raise RuntimeError("the clip never arrived in storage")
        item = _item(job_id) or {"id": job_id, "exercise": "muscle_up"}
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "processing"},
        )
        result = process_job(item, dest, on_stage=_stage)
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s, #r = :r",
            ExpressionAttributeNames={"#s": "status", "#r": "result"},
            ExpressionAttributeValues={":s": "done", ":r": _to_ddb(result)},
        )
    except Exception as exc:  # noqa: BLE001
        _fail(exc)
    return {"ok": True}
