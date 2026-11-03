#!/usr/bin/env python3
"""Overview recent BarrApp job results from DynamoDB.

    python scripts/overview_job_results.py [--since ISO8601] [--limit 20]
    python scripts/overview_job_results.py --watch --since ISO8601

With --watch: wait until at least one job created after --since exists and
none of those are still queued/processing, then print the overview and emit
AGENT_LOOP_WAKE_upload_overview so the agent can narrate the batch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_OWNER = "61d06252-2eaf-4532-9bb3-e82f8bb98fc0"
DEFAULT_TABLE = "sam-app-JobsTable-12EQEZ1EM3YR7"
DEFAULT_REGION = "eu-west-1"


def _unwrap(v):
    if not isinstance(v, dict):
        return v
    if "S" in v:
        s = v["S"]
        try:
            return json.loads(s)
        except Exception:
            return s
    if "N" in v:
        return float(v["N"])
    if "BOOL" in v:
        return v["BOOL"]
    if "NULL" in v:
        return None
    if "M" in v:
        return {k: _unwrap(x) for k, x in v["M"].items()}
    if "L" in v:
        return [_unwrap(x) for x in v["L"]]
    return v


def _client():
    import boto3
    return boto3.client("dynamodb", region_name=os.environ.get(
        "AWS_DEFAULT_REGION", DEFAULT_REGION))


def list_jobs(owner: str, table: str, limit: int = 40) -> list[dict]:
    ddb = _client()
    items: list[dict] = []
    kwargs = {
        "TableName": table,
        "IndexName": "owner-index",
        "KeyConditionExpression": "#o = :o",
        "ExpressionAttributeNames": {"#o": "owner"},
        "ExpressionAttributeValues": {":o": {"S": owner}},
        "ScanIndexForward": False,
        "Limit": min(limit, 50),
    }
    while True:
        resp = ddb.query(**kwargs)
        for raw in resp.get("Items") or []:
            items.append({k: _unwrap(v) for k, v in raw.items()})
            if len(items) >= limit:
                return items
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def deep_observed(res: dict) -> tuple[int, int]:
    """(observed_deep, checked_reps) for dip.excessive_depth if present."""
    checks = ((res.get("assessment") or {}).get("checks") or [])
    for c in checks:
        if c.get("errorId") == "dip.excessive_depth":
            return int(c.get("observed") or 0), int(
                (c.get("observed") or 0) + (c.get("notObserved") or 0)
                + (c.get("unobservable") or 0)
            )
    return 0, 0


def format_row(job: dict) -> str:
    res = job.get("result") or {}
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except Exception:
            res = {}
    det = res.get("detected") or {}
    ex = res.get("exercise") or det.get("exercise") or job.get("exercise") or "?"
    n = res.get("n_reps")
    if n is None:
        n = len(res.get("reps") or [])
    conf = (res.get("classificationConfidence") or {}).get("value")
    if conf is None:
        conf = det.get("confidence")
    deep_n, deep_tot = deep_observed(res)
    ws = res.get("workingSet") or {}
    ws_s = ""
    if ws:
        ws_s = f" ws={ws.get('startS')}–{ws.get('endS')}s"
    deep_s = f" deep={deep_n}/{deep_tot}" if deep_tot else ""
    conf_s = f" conf={conf}" if conf is not None else ""
    status = job.get("status")
    created = str(job.get("createdAt") or "")[:19]
    jid = str(job.get("id") or "")
    err = ""
    if status == "failed":
        err = f" err={(job.get('error') or '')[:60]}"
    blockers = res.get("blockers") or []
    if blockers and status == "done" and (n == 0 or n == 0.0):
        err = f" | {str(blockers[0])[:70]}"
    return (
        f"{created}  #{jid}  {status:<10}  {ex:<18}  reps={n}"
        f"{conf_s}{deep_s}{ws_s}{err}"
    )


def overview(jobs: list[dict], title: str = "Job results") -> str:
    lines = [title, "-" * 72]
    if not jobs:
        lines.append("(none)")
        return "\n".join(lines)
    for j in jobs:
        lines.append(format_row(j))
    done = [j for j in jobs if j.get("status") == "done"]
    failed = [j for j in jobs if j.get("status") == "failed"]
    active = [j for j in jobs if j.get("status") in
              ("created", "queued", "processing", "uploaded")]
    lines.append("-" * 72)
    lines.append(
        f"total={len(jobs)} done={len(done)} failed={len(failed)} active={len(active)}"
    )
    return "\n".join(lines)


def watch(since: str, owner: str, table: str, poll_s: float, idle_grace_s: float
          ) -> list[dict]:
    """Wait for a batch of jobs created after `since` to finish."""
    print(f"watching jobs with createdAt > {since} …", flush=True)
    seen_any = False
    idle_since = None
    while True:
        jobs = [j for j in list_jobs(owner, table, limit=50)
                if str(j.get("createdAt") or "") > since]
        active = [j for j in jobs if j.get("status") in
                  ("created", "queued", "processing", "uploaded")]
        if jobs:
            seen_any = True
            idle_since = None
            print(
                f"{time.strftime('%H:%M:%S')} batch={len(jobs)} active={len(active)} "
                f"ids={[j.get('id') for j in jobs]}",
                flush=True,
            )
            if not active:
                print(overview(jobs, title=f"Batch since {since}"), flush=True)
                return jobs
        else:
            now = time.time()
            if seen_any:
                # Shouldn't happen often; treat as done.
                return jobs
            if idle_since is None:
                idle_since = now
            waited = now - idle_since
            print(
                f"{time.strftime('%H:%M:%S')} waiting for first upload "
                f"({waited:.0f}s) …",
                flush=True,
            )
            if waited >= idle_grace_s:
                print(
                    "AGENT_LOOP_WAKE_upload_overview "
                    + json.dumps({
                        "prompt": (
                            "No new BarrApp jobs appeared after the watch "
                            f"baseline {since} within {idle_grace_s:.0f}s. "
                            "Check with the user whether uploads started."
                        ),
                        "since": since,
                        "jobs": [],
                    }),
                    flush=True,
                )
                return []
        time.sleep(poll_s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default=os.environ.get("BARRA_OWNER", DEFAULT_OWNER))
    ap.add_argument("--table", default=os.environ.get("BARRA_JOBS_TABLE", DEFAULT_TABLE))
    ap.add_argument("--since", default="",
                    help="ISO8601; only jobs with createdAt > this")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--poll", type=float, default=12.0)
    ap.add_argument("--idle-grace", type=float, default=900.0,
                    help="seconds to wait for the first new job before giving up")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.watch:
        since = args.since or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        jobs = watch(since, args.owner, args.table, args.poll, args.idle_grace)
        if jobs:
            payload = {
                "prompt": (
                    "BarrApp upload batch finished. Summarize the results for "
                    "the user in Spanish: exercise, reps, excessive depth, "
                    "working set, failures. Flag misclassifications."
                ),
                "since": since,
                "jobs": [
                    {
                        "id": j.get("id"),
                        "status": j.get("status"),
                        "createdAt": j.get("createdAt"),
                        "exercise": (j.get("result") or {}).get("exercise")
                        if isinstance(j.get("result"), dict)
                        else j.get("exercise"),
                        "n_reps": (j.get("result") or {}).get("n_reps")
                        if isinstance(j.get("result"), dict) else None,
                        "line": format_row(j),
                    }
                    for j in jobs
                ],
            }
            print(
                "AGENT_LOOP_WAKE_upload_overview " + json.dumps(payload),
                flush=True,
            )
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(overview(jobs) + "\n")
        return 0

    jobs = list_jobs(args.owner, args.table, limit=args.limit)
    if args.since:
        jobs = [j for j in jobs if str(j.get("createdAt") or "") > args.since]
    text = overview(jobs)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
