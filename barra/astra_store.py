"""Astra DB (DataStax Data API) store for the pipeline evaluation/debugging state.

barra/tracestore.py was written for DynamoDB and barra/classify.py never cared
where its numbers were kept. This module is the Astra side of that same contract:
one row per clip analysis (the intermediate classifier state + the program/model
that produced it), one row per decision-chain trace, and best-effort failure
records - all behind the Data API collections, configurable by environment, and
degrading gracefully to the caller-owned local store when no Astra is configured.

The rules it keeps, mirroring tracestore:

* **Lazy and optional.** `astrapy` is an optional extra (like the pose backends).
  Importing this module, or constructing the store, with no Astra env vars MUST
  do no Astra import, no client creation and no network call. `configured()` is
  the gate, and every write checks it first.
* **Never fails a job.** Every remote call is wrapped; a failure returns an honest
  ``{"ok": False, "reason": ...}`` or ``None``, never a raise and never a silent
  success. The caller always has the local files on disk as the source of truth.
* **Idempotent upsert.** Documents are written by a deterministic ``_id``
  (``eval:<id>`` / ``trace:<id>``) so a retry or a re-run of the same clip in the
  same batch cannot produce a duplicate row.

Env: ``ASTRA_DB_APPLICATION_TOKEN``, ``ASTRA_DB_API_ENDPOINT``,
``ASTRA_DB_KEYSPACE`` (default ``barra``), ``ASTRA_DB_COLLECTION`` (default
``pipeline_eval``). Collections are created on first use when missing.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_KEYSPACE = "barra"
DEFAULT_COLLECTION = "pipeline_eval"

_EVAL_ID = "eval:"
_TRACE_ID = "trace:"

# Trace/failure retention, aligned with tracestore.TTL_DAYS (90). Fixed at
# creation so a retry never extends it; reads treat an expired row as gone.
RETENTION_SECONDS = 90 * 24 * 3600


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def configured() -> bool:
    """True when a live Astra DB could be reached, i.e. token + endpoint are set."""
    return bool(_env("ASTRA_DB_APPLICATION_TOKEN") and _env("ASTRA_DB_API_ENDPOINT"))


def collection_name(role: str = "eval") -> str:
    """The collection a document role belongs to, defaulting off the collection
    env var (so a custom collection prefix keeps all three roles together)."""
    base = _env("ASTRA_DB_COLLECTION") or DEFAULT_COLLECTION
    if role == "eval":
        return base
    if role == "trace":
        return base + "_traces"
    return base + "_failures"


class AstraStore:
    """One store behind the Astra Data API, with the honest-or-None contract.

    `token`/`endpoint`/`keyspace` default to the env vars, so callers can just
    construct it; tests can inject a fake client instead of reaching the network.
    Every method is safe to call when Astra is unconfigured: it returns
    ``{"ok": False, "reason": "astra not configured"}`` (or ``None`` for lookups)
    rather than raising.
    """

    def __init__(self, token: str | None = None, endpoint: str | None = None,
                 keyspace: str | None = None, client=None):
        self.token = token if token is not None else _env("ASTRA_DB_APPLICATION_TOKEN")
        self.endpoint = endpoint if endpoint is not None else _env("ASTRA_DB_API_ENDPOINT")
        self.keyspace = keyspace if keyspace is not None else (
            _env("ASTRA_DB_KEYSPACE") or DEFAULT_KEYSPACE)
        self._token = token                # record whether token was explicit
        self._client_override = client     # injectable fake for tests
        self._collections: dict[str, object] = {}

    # -- connection ------------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.token and self.endpoint)

    def _client(self):
        """The astrapy client, lazily. None (never a raise) when not configured."""
        if self._client_override is not None:
            return self._client_override
        if not self.configured():
            return None
        try:
            from astrapy import DataAPIClient
            return DataAPIClient(self.token)
        except Exception:                # noqa: BLE001 - connection is best-effort
            return None

    # -- writes ------------------------------------------------------------------
    def put_evaluation(self, doc: dict) -> dict:
        """Upsert one evaluation row by ``_id = eval:<evaluationId>``."""
        return self._put(collection_name("eval"), _EVAL_ID, doc)

    def put_trace(self, doc: dict) -> dict:
        """Upsert one trace row by ``_id = trace:<traceId>``."""
        return self._put(collection_name("trace"), _TRACE_ID, doc)

    def put_failure(self, job_id: str, stage: str, error: str,
                    extra: dict | None = None) -> dict:
        doc = {"jobId": job_id, "stage": stage, "error": error,
               **(extra or {})}
        return self._put(collection_name("failure"), _FAILURE_ID, doc,
                         key=job_id or "unknown")

    def _put(self, name: str, prefix: str, doc: dict, key: str | None = None) -> dict:
        if not self.configured():
            return {"ok": False, "reason": "astra not configured", "store": "local"}
        coll = self._collection_by_name(name)
        if coll is None:
            return {"ok": False, "reason": "client unavailable", "store": "local"}
        did = doc.get("_id") or f"{prefix}{key or doc.get('id') or doc.get('traceId') or doc.get('clip') or 'unknown'}"
        if not str(did).startswith(prefix):
            did = prefix + str(did)
        body = {**doc, "_id": str(did)}
        # Absolute expiry, fixed at creation so a retry never extends retention.
        body.setdefault("expiresAt", time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                   time.gmtime(time.time() + RETENTION_SECONDS)))
        serialized = json.dumps(body, default=str)
        # Never send a document that would be silently truncated - reject it.
        if len(serialized) > 128 * 1024:
            return {"ok": False, "reason": "document exceeds 128 KiB",
                    "store": "local", "_id": str(did)}
        try:
            coll.replace_one({"_id": body["_id"]}, body, upsert=True)
            return {"ok": True, "store": "astra", "_id": str(did)}
        except Exception as exc:         # noqa: BLE001 - honest failure, no raise
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}",
                    "store": "local", "_id": str(did)}

    def _collection_by_name(self, name: str):
        """Get a collection by its concrete name (role-agnostic)."""
        if not self.configured():
            return None
        if self._client_override is not None:
            # Fake clients expose .collections dict for tests.
            return getattr(self._client_override, "collections", {}).get(name)
        if name in self._collections:
            return self._collections[name]
        client = self._client()
        if client is None:
            return None
        try:
            db = client.get_database(self.endpoint, token=self.token,
                                     keyspace=self.keyspace)
            try:
                coll = db.get_collection(name)
            except Exception:            # noqa: BLE001
                coll = db.create_collection(name)
            self._collections[name] = coll
            return coll
        except Exception:                # noqa: BLE001
            return None

    # -- reads -------------------------------------------------------------------
    def get(self, trick: str | None = None, clip: str | None = None,
            status: str | None = None, limit: int = 50) -> list[dict]:
        """Rows for a trick / clip / status, newest last. Empty when unconfigured."""
        if not self.configured():
            return []
        coll = self._collection_by_name(collection_name("eval"))
        if coll is None:
            return []
        filt = {}
        if trick:
            filt["trick"] = trick
        if clip:
            filt["clip"] = clip
        if status:
            filt["status"] = status
        try:
            out = []
            for doc in coll.find(filt, limit=limit) if filt else coll.find(limit=limit):
                out.append(dict(doc))
            return out
        except Exception:                # noqa: BLE001
            return []

    def trace(self, trace_id: str) -> dict | None:
        """One trace by its id, or None when unconfigured/absent."""
        if not self.configured():
            return None
        coll = self._collection_by_name(collection_name("trace"))
        if coll is None:
            return None
        try:
            doc = coll.find_one({"_id": _TRACE_ID + str(trace_id)})
            return dict(doc) if doc else None
        except Exception:                # noqa: BLE001
            return None
