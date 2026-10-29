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
from botocore.exceptions import ClientError

import auth
import referral
import uploads

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lam = boto3.client("lambda")
table = ddb.Table(os.environ["JOBS_TABLE"])
feedback_table = ddb.Table(os.environ["FEEDBACK_TABLE"])
referrals_table = ddb.Table(os.environ["REFERRALS_TABLE"])
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
        upload = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET, "Key": f"{owner}/{job_id}.mp4", "ContentType": "video/mp4"},
            ExpiresIn=3600,
        )
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
        uploads.record(job_id, owner, "submitted",
                       "handed to the worker" if WORKER else "measured in-process")
        return _resp(202, _public(_item(job_id)) or {"id": job_id, "status": "queued"})

    return _resp(404, {"error": "not found"})


def _store_trimmed_clip(src: Path, owner: str, job_id: str, start_s: float,
                        end_s: float, duration_s: float | None = None) -> bool:
    """Cut the located window out of the clip and overwrite the stored object.

    Best-effort by design: if there is no cutter, the cut fails, or the upload
    fails, the original stays in S3 and the job still succeeds. A localization
    that cannot be stored is not a reason to lose the measurement.
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
    if trim_clip(src, start, end, out) is None:
        return False
    try:
        s3.upload_file(str(out), BUCKET, f"{owner}/{job_id}.mp4",
                       ExtraArgs={"ContentType": "video/mp4"})
        return True
    except Exception:  # noqa: BLE001 - keep the original on any upload failure
        return False


def _set_stage(job_id: str, owner: str, name: str) -> None:
    """Where the job is. `stage` stays the English phrase the installed app
    matches on; `stageCode` is stable and `stageText` is what to show."""
    code, text = _i18n_stage(name)
    table.update_item(
        Key={"id": job_id},
        UpdateExpression="SET #st = :st, #sc = :sc, #sx = :sx",
        ExpressionAttributeNames={"#st": "stage", "#sc": "stageCode", "#sx": "stageText"},
        ExpressionAttributeValues={":st": name, ":sc": code, ":sx": text},
    )
    uploads.record(job_id, owner, "stage", name)


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

        def _stage(name: str) -> None:
            _set_stage(job_id, owner, name)

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

        # Locate the exercise ALONGSIDE the pose, not before it: the vision call
        # took 57 s of a 375 s job on 2026-10-11, and pose (128 s) does not need
        # it. Fusion asks for the vote when it gets there, by which time the
        # call has long finished. The measurement still runs on the FULL clip:
        # every reported timestamp is in the source video's time, and the
        # phone seeks its own local copy with them. Localization decides what
        # is kept, not what is measured.
        from concurrent.futures import ThreadPoolExecutor
        from process import add_vision, measure_job

        _stage("locating the exercise")
        pool = ThreadPoolExecutor(max_workers=1)

        def _locate():
            try:
                from vision import locate_exercise
                return locate_exercise(dest, Path("/tmp") / f"{job_id}-locate",
                                       item.get("exercise"))
            except Exception:  # noqa: BLE001 - localization never fails a job
                return None

        located_future = pool.submit(_locate)

        # When pose was ~128 s, locate was always done by fusion. Full + chunks
        # finish pose in seconds while locate can still take tens of seconds —
        # do not re-serialize that wait onto upload→result. A short grace lets
        # a nearly-done call land; otherwise fusion runs on geometry+model and
        # locate still drives the post-result clip trim below.
        _VISION_VOTE_WAIT_S = float(os.environ.get("BARRA_VISION_VOTE_WAIT_S", "2") or 2)

        def _vision_vote():
            try:
                located = located_future.result(timeout=_VISION_VOTE_WAIT_S)
            except Exception:  # noqa: BLE001 - late locate is no vote, not a failure
                return None
            label = (located or {}).get("exercise") or None
            if label and str(label).lower() in ("none", "unknown", ""):
                return None
            return label

        result = measure_job(item, dest, on_stage=_stage, vision_label=_vision_vote)

        # The measurement reaches the phone now. Cutting and re-uploading the
        # stored clip (~44 s on 2026-10-11), the model prose (~10-15 s,
        # docs/SPEED-PLAN.md B) and the advisory vision note come after it.
        _write_result(job_id, result)
        uploads.record(job_id, owner, "done",
                       f"{result.get('exercise', '?')}, {result.get('n_reps', 0)} rep(s)")

        try:
            located = located_future.result(timeout=300)
        except Exception:  # noqa: BLE001
            located = None
        pool.shutdown(wait=False)
        localization = None
        if located and located.get("usable"):
            loc = dict(located)
            loc["source"] = "vision"
            loc["trimmed"] = _store_trimmed_clip(
                dest, owner, job_id, located["startS"], located["endS"],
                located.get("durationS"))
            localization = loc
        # Vision unavailable or it found no window: fall back to the geometric
        # working set the measurement already computed.
        if localization is None:
            trim = result.get("trim") or {}
            s, e = trim.get("startS"), trim.get("endS")
            if s is not None and e is not None and e > s:
                if _store_trimmed_clip(dest, owner, job_id, s, e,
                                       result.get("duration_s")):
                    localization = {"source": "geometry", "startS": s, "endS": e,
                                    "durationS": result.get("duration_s"),
                                    "trimmed": True}
        if localization is not None:
            result["localization"] = localization
            print(f"[barra] stored clip localized by {localization.get('source')} "
                  f"{localization.get('startS')}-{localization.get('endS')}s "
                  f"trimmed={localization.get('trimmed')}", flush=True)
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
