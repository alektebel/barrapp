#!/usr/bin/env python3
"""End-to-end check of the barrapp pipeline, from job creation to measurement.

This is the test that would have caught the "unknown job" regression: it walks
the exact sequence the phone walks - create, multipart upload, complete,
submit, poll - against the real API, and asserts on the shape of what comes
back. Nothing is mocked, because every bug the pipeline has actually had lived
in the seams between the phone, API Gateway, S3 and the worker.

  scripts/e2e_pipeline.py                      # happy path + contract checks
  scripts/e2e_pipeline.py --negative           # also the failure modes
  scripts/e2e_pipeline.py --clip path/to.mp4   # a clip of your choosing
  scripts/e2e_pipeline.py --keep               # do not delete the job after

Exit code is 0 only when every check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIP = ROOT / "VID-20260827-WA0010.mp4"
PART_FLOOR = 5 * 1024 * 1024  # S3's minimum for a non-final part


# ---- tiny test harness -------------------------------------------------

class Failure(Exception):
    pass


def _brief(detail: str, limit: int = 160) -> str:
    """Presigned URLs are a few thousand characters of signature. Keep the
    part of a failure a person can read."""
    text = re.sub(r"https://\S+", "<presigned-url>", str(detail))
    return text if len(text) <= limit else text[:limit] + "…"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []
        self.t0 = time.time()

    def ok(self, name: str, detail: str = "") -> None:
        self.rows.append((name, True, detail))
        print(f"  \033[32mPASS\033[0m {name}")

    def bad(self, name: str, detail: str) -> None:
        self.rows.append((name, False, detail))
        print(f"  \033[31mFAIL\033[0m {name} — {_brief(detail)}")

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        """`detail` explains the failure and is printed only when it happens -
        a passing line that carries its own failure text reads as a bug."""
        (self.ok if cond else self.bad)(name, detail)
        return cond

    def finish(self) -> int:
        failed = [r for r in self.rows if not r[1]]
        secs = time.time() - self.t0
        print(f"\n{len(self.rows) - len(failed)}/{len(self.rows)} checks passed "
              f"in {secs:.0f}s")
        for name, _, detail in failed:
            print(f"  FAILED: {name} — {_brief(detail)}")
        return 1 if failed else 0


# ---- http --------------------------------------------------------------

def request(method: str, url: str, *, device: str | None = None,
            body: bytes | None = None, json_body: dict | None = None,
            content_type: str | None = None) -> tuple[int, dict, dict]:
    """Returns (status, parsed_json_or_empty, headers). Never raises on 4xx/5xx."""
    data = body
    headers: dict[str, str] = {}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    if device:
        headers["X-Device-Id"] = device
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
            return resp.status, _maybe_json(raw), dict(resp.headers)
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, _maybe_json(raw), dict(err.headers or {})


def _maybe_json(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"_raw": raw[:400].decode("utf-8", "replace")}


def put_part(url: str, chunk: bytes) -> tuple[int, str | None]:
    """Send one part to a presigned S3 URL.

    No Content-Type, deliberately: the presigned URL for upload_part signs no
    content type, and S3 rejects a signature computed over a header the
    request then sends differently. urllib adds one for you if you let it.
    """
    req = urllib.request.Request(url, data=chunk, method="PUT")
    req.add_unredirected_header("Content-Type", "")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, resp.headers.get("ETag")
    except urllib.error.HTTPError as err:
        return err.code, None


# ---- the pipeline ------------------------------------------------------

def api_base(explicit: str | None) -> str:
    if explicit:
        return explicit.rstrip("/")
    env = os.environ.get("BARRAPP_API")
    if env:
        return env.rstrip("/")
    props = (ROOT / "gradle.properties").read_text(encoding="utf-8")
    found = re.search(r"^barrapp\.apiUrlRelease=(.+)$", props, re.M)
    if not found:
        raise Failure("no API url: pass --api, set BARRAPP_API, or fill "
                      "barrapp.apiUrlRelease in gradle.properties")
    return found.group(1).strip().rstrip("/")


def upload_clip(rep: Report, api: str, device: str, job: str, clip: Path) -> bool:
    """The multipart dance, exactly as the phone does it."""
    status, start, _ = request("POST", f"{api}/v1/jobs/{job}/upload/start",
                               device=device, json_body={})
    if not rep.check("upload/start accepts the job id", status == 201,
                     f"HTTP {status} {start}"):
        return False
    upload_id = start.get("uploadId", "")
    part_size = int(start.get("partSize") or 0)
    if not rep.check("upload/start returns an uploadId and part size",
                     bool(upload_id) and part_size >= PART_FLOOR,
                     f"uploadId={bool(upload_id)} partSize={part_size}"):
        return False

    size = clip.stat().st_size
    total = max(1, (size + part_size - 1) // part_size)
    parts = []
    with clip.open("rb") as handle:
        for n in range(1, total + 1):
            status, presigned, _ = request(
                "POST", f"{api}/v1/jobs/{job}/upload/part",
                device=device, json_body={"partNumber": n})
            if not rep.check(f"part {n}/{total} presigned", status == 200,
                             f"HTTP {status} {presigned}"):
                return False
            code, etag = put_part(presigned["url"], handle.read(part_size))
            if not rep.check(f"part {n}/{total} accepted by S3", code == 200,
                             f"HTTP {code}"):
                return False
            if not rep.check(f"part {n}/{total} returned an ETag", bool(etag), ""):
                return False
            parts.append({"partNumber": n, "etag": etag})

    status, done, _ = request("POST", f"{api}/v1/jobs/{job}/upload/complete",
                              device=device, json_body={"parts": parts})
    return rep.check("upload/complete assembles the object", status == 200,
                     f"HTTP {status} {done}")


def poll(rep: Report, api: str, device: str, job: str, budget: int) -> dict:
    deadline = time.time() + budget
    seen: list[str] = []
    while time.time() < deadline:
        status, item, _ = request("GET", f"{api}/v1/jobs/{job}", device=device)
        if status != 200:
            rep.bad("polling the job", f"HTTP {status} {item}")
            return {}
        stage = item.get("stage") or item.get("status", "")
        if stage and (not seen or seen[-1] != stage):
            seen.append(stage)
            print(f"       …{stage}")
        if item.get("status") in {"done", "failed"}:
            rep.ok("the worker reached a terminal state",
                   f"{item['status']} after {len(seen)} stage(s)")
            return item
        time.sleep(4)
    rep.bad("the worker reached a terminal state",
            f"still {item.get('status')} after {budget}s")
    return {}


def check_result(rep: Report, item: dict) -> None:
    """The contract the phone parses. A field that silently goes missing here
    shows up as a blank screen, not an error, which is why it is asserted."""
    result = item.get("result") or {}
    rep.check("status is done", item.get("status") == "done",
              item.get("error") or item.get("status", ""))
    for field in ("exercise", "n_reps", "reps", "sessionBand", "traceId",
                  "provenance", "duration_s"):
        rep.check(f"result carries {field}", field in result,
                  "missing — the phone renders this as empty")
    reps = result.get("reps") or []
    rep.check("reps is a list", isinstance(reps, list), type(reps).__name__)
    if reps:
        first = reps[0]
        for field in ("label", "score", "band", "components"):
            rep.check(f"rep[0] carries {field}", field in first, "missing")
    prov = result.get("provenance") or {}
    rep.check("provenance names the barra version", bool(prov.get("barra")),
              json.dumps(prov)[:80])
    rep.check("n_reps agrees with the reps list",
              float(result.get("n_reps") or 0) == len(reps),
              f"n_reps={result.get('n_reps')} len(reps)={len(reps)}")


def negatives(rep: Report, api: str, device: str, job: str) -> None:
    """The failure modes that have actually bitten this pipeline."""
    other = f"local-{uuid.uuid4().hex[:12]}"
    status, body, _ = request("POST", f"{api}/v1/jobs/{other}/upload/start",
                              device=device, json_body={})
    rep.check("a local work id is rejected, not silently accepted",
              status == 404 and body.get("error") == "unknown job",
              f"HTTP {status} {body}")

    status, body, _ = request("GET", f"{api}/v1/jobs/{job}",
                              device=f"someone-else-{uuid.uuid4().hex[:8]}")
    rep.check("another device cannot read this job", status == 404,
              f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/jobs", json_body={})
    rep.check("a request with no device id is refused", status == 401,
              f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/jobs/{job}/upload/part",
                              device=device, json_body={"partNumber": 0})
    rep.check("part number 0 is refused", status == 400, f"HTTP {status} {body}")


def auth_checks(rep: Report, api: str) -> None:
    """Accounts: the shapes that must hold before anyone trusts a password to
    this server. Uses a throwaway address; the account is left unconfirmed,
    which is the state a real signup sits in until the code is entered."""
    status, body, _ = request("GET", f"{api}/health")
    if not body.get("accounts"):
        rep.check("accounts are enabled on this server", False,
                  "/health says accounts:false - Cognito is not wired up")
        return
    rep.ok("accounts are enabled on this server")

    email = f"e2e-{uuid.uuid4().hex[:12]}@example.com"
    status, body, _ = request("POST", f"{api}/v1/auth/signup", json_body={
        "email": email, "password": "short"})
    rep.check("a short password is refused", status == 400, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/signup", json_body={
        "email": "not-an-email", "password": "barrapp2026x"})
    rep.check("a malformed email is refused", status == 400, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/signup", json_body={
        "email": email, "password": "barrapp2026x"})
    rep.check("a valid signup is accepted", status == 200 and body.get("needsConfirmation"),
              f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/signup", json_body={
        "email": email, "password": "barrapp2026x"})
    rep.check("the same email cannot sign up twice", status == 409, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/login", json_body={
        "email": email, "password": "barrapp2026x"})
    rep.check("an unconfirmed account cannot sign in", status == 403, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/login", json_body={
        "email": email, "password": "the-wrong-one"})
    rep.check("a wrong password is refused", status in {401, 403}, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/confirm", json_body={
        "email": email, "code": "000000"})
    rep.check("a wrong confirmation code is refused", status == 400, f"HTTP {status} {body}")

    # The regression that matters most: a token that does not verify must be
    # an error, never a quiet fall back to whatever device id came along.
    status, body, headers = request(
        "GET", f"{api}/v1/jobs", device="some-device-id")
    ok_device = status == 200
    req = urllib.request.Request(f"{api}/v1/jobs", method="GET", headers={
        "Authorization": "Bearer not-a-real-token",
        "X-Device-Id": "some-device-id"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
    except urllib.error.HTTPError as err:
        code = err.code
    rep.check("a bad bearer token is rejected, not downgraded to the device id",
              code == 401 and ok_device,
              f"bearer+device HTTP {code}; device-only HTTP {status}")

    status, body, _ = request("POST", f"{api}/v1/auth/nonsense", json_body={})
    rep.check("an unknown auth action is a 404", status == 404, f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/auth/claim",
                              device="some-device-id", json_body={"deviceId": "x"})
    rep.check("claiming without an account is refused", status == 401,
              f"HTTP {status} {body}")


def feedback_checks(rep: Report, api: str, device: str) -> None:
    """The feedback route: text lands in the table, a clip goes to the bucket
    through a presigned PUT - the same dance an upload speaks - and an empty
    message is refused rather than stored."""
    status, body, _ = request("POST", f"{api}/v1/feedback", device=device,
                              json_body={"message": ""})
    rep.check("an empty message is refused", status == 400,
              f"HTTP {status} {body}")

    status, body, _ = request("POST", f"{api}/v1/feedback", device=device,
                              json_body={"message": "e2e: the score looked wrong",
                                         "traceId": "deadbeef1234"})
    if not rep.check("a text-only feedback is accepted", status == 201 and body.get("id"),
                     f"HTTP {status} {body}"):
        return
    rep.check("text-only feedback has no upload url",
              not body.get("uploadUrl"), str(body)[:80])

    status, body, _ = request("POST", f"{api}/v1/feedback", device=device,
                              json_body={"message": "e2e: with a clip", "video": True})
    if not rep.check("a feedback with video is accepted", status == 201 and body.get("id"),
                     f"HTTP {status} {body}"):
        return
    url = body.get("uploadUrl") or ""
    if not rep.check("the feedback carries a presigned upload url", bool(url),
                     json.dumps(body)[:120]):
        return
    code, _etag = put_part(url, b"e2e feedback clip placeholder bytes")
    rep.check("the feedback clip is accepted by storage", code == 200, f"HTTP {code}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="API base url (default: gradle.properties)")
    ap.add_argument("--clip", type=Path, default=DEFAULT_CLIP)
    ap.add_argument("--device", help="device id to act as (default: a throwaway)")
    ap.add_argument("--budget", type=int, default=300, help="seconds to wait for the worker")
    ap.add_argument("--negative", action="store_true", help="also run the failure modes")
    ap.add_argument("--auth", action="store_true", help="also run the account checks")
    ap.add_argument("--feedback", action="store_true", help="also run the feedback checks")
    ap.add_argument("--keep", action="store_true", help="do not delete the job afterwards")
    args = ap.parse_args()

    rep = Report()
    try:
        api = api_base(args.api)
    except Failure as err:
        print(f"FAIL {err}")
        return 1
    device = args.device or f"e2e-{uuid.uuid4().hex[:12]}"
    if not args.clip.exists():
        print(f"FAIL clip not found: {args.clip}")
        return 1

    print(f"api    {api}\ndevice {device}\nclip   {args.clip.name} "
          f"({args.clip.stat().st_size / 1e6:.1f} MB)\n")

    status, body, _ = request("GET", f"{api}/health")
    if not rep.check("the API answers /health", status == 200 and body.get("ok"),
                     f"HTTP {status} {body}"):
        return rep.finish()

    status, created, _ = request("POST", f"{api}/v1/jobs", device=device,
                                 json_body={"exercise": "auto"})
    if not rep.check("a job is created", status == 201 and created.get("id"),
                     f"HTTP {status} {created}"):
        return rep.finish()
    job = created["id"]
    print(f"       job {job}")
    rep.check("the new job starts in 'created'", created.get("status") == "created",
              created.get("status", ""))

    if upload_clip(rep, api, device, job, args.clip):
        status, queued, _ = request("POST", f"{api}/v1/jobs/{job}/submit",
                                    device=device, json_body={})
        if rep.check("submit queues the job", status == 202, f"HTTP {status} {queued}"):
            item = poll(rep, api, device, job, args.budget)
            if item:
                check_result(rep, item)
                status, hist, _ = request("GET", f"{api}/v1/history", device=device)
                ids = [h.get("id") for h in (hist.get("history") or [])]
                rep.check("the job appears in /v1/history", job in ids,
                          "a done job the calendar would never show")

    status, listing, _ = request("GET", f"{api}/v1/jobs", device=device)
    ids = [j.get("id") for j in (listing.get("jobs") or [])]
    rep.check("the job appears in /v1/jobs", job in ids, f"HTTP {status}")

    if args.negative:
        negatives(rep, api, device, job)

    if args.auth:
        auth_checks(rep, api)

    if args.feedback:
        feedback_checks(rep, api, device)

    if not args.keep:
        status, _, _ = request("DELETE", f"{api}/v1/jobs/{job}", device=device)
        rep.check("the job can be deleted", status == 200, f"HTTP {status}")

    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
