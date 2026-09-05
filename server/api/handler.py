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

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lam = boto3.client("lambda")
table = ddb.Table(os.environ["JOBS_TABLE"])
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


def _owner(event) -> str:
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == "x-device-id":
            return (value or "").strip()
    return ""


def _public(item: dict | None) -> dict | None:
    if not item:
        return None
    out = {k: v for k, v in item.items() if k != "owner"}
    return out


def _item(job_id: str) -> dict | None:
    return table.get_item(Key={"id": job_id}).get("Item")


def _owned(item: dict | None, owner: str) -> bool:
    return bool(item and owner and item.get("owner") == owner)


def api(event, _context):
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
        return _resp(200, {"ok": True})

    if method in {"POST", "GET", "DELETE"} and path.rstrip("/") != "/health" and not owner:
        return _resp(401, {"error": "missing X-Device-Id"})

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
        jobs = [_public(i) for i in resp.get("Items") or []]
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

    parts = [p for p in path.split("/") if p]

    if method == "GET" and len(parts) == 3 and parts[0] == "v1" and parts[1] == "jobs":
        item = _item(parts[2])
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
    from process import process_job

    job_id = event["job_id"]
    owner = event.get("owner") or (_item(job_id) or {}).get("owner") or ""
    dest = Path("/tmp") / f"{job_id}.mp4"

    def _stage(name: str) -> None:
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #st = :st",
            ExpressionAttributeNames={"#st": "stage"},
            ExpressionAttributeValues={":st": name},
        )

    _stage("receiving the clip")
    s3.download_file(BUCKET, f"{owner}/{job_id}.mp4", str(dest))
    item = _item(job_id) or {"id": job_id, "exercise": "muscle_up"}
    table.update_item(
        Key={"id": job_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "processing"},
    )
    try:
        result = process_job(item, dest, on_stage=_stage)
        table.update_item(
            Key={"id": job_id},
            UpdateExpression="SET #s = :s, #r = :r",
            ExpressionAttributeNames={"#s": "status", "#r": "result"},
            ExpressionAttributeValues={":s": "done", ":r": _to_ddb(result)},
        )
    except Exception as exc:  # noqa: BLE001
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
    return {"ok": True}
