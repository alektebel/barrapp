[0m
> build · qwen3.6
[0m
[0m→ [0mRead docs/PIPELINE-ASTRA-ARCHITECTURE.md
[0m→ [0mRead scripts/pipeline_eval.py
[0m→ [0mRead barra/tracestore.py
[0m→ [0mRead barra/astra_store.py
[0m→ [0mRead tests/test_astra_store.py
# Astra DB Storage Implementation Review

## (1) Proposal Compliance: ID conventions, env vars, lazy-import

**IDs — partially compliant.**
- `eval:<id>` / `trace:<id>` prefixes match §1–2. ✓
- `artifact:<id>:<key>` and `chunk:<id>:<sha256>:<ordinal>` namespaces are entirely absent (no artifact/chunk methods exist). Not a bug—it's unimplemented scope—but worth noting.
- `failure:` prefix and `pipeline_eval_failures` collection are **not in the proposal** (proposal §3 mentions `put_failure` should route through the trace store, not a separate collection).

**Env vars — fully compliant.** `ASTRA_DB_APPLICATION_TOKEN`, `ASTRA_DB_API_ENDPOINT`, `ASTRA_DB_KEYSPACE` (default `barra`), `ASTRA_DB_COLLECTION` (default `pipeline_eval`) all present and checked correctly by `configured()`. ✓

**Lazy-import — compliant but with a trap.** `astrapy` is imported inside `_client()` (line 99), so `configured()` at module scope never touches it. However, `tracestore.py:32` does `from .astra_store import AstraStore, configured as astra_configured` — this imports the **module**, which is fine, but any future top-level code in `astra_store.py` that executes on import would break this contract. Currently clean. ✓

## (2) Correctness / Robustness / Security Gaps

| Gap | Severity | Detail |
|---|---|---|
| **No document size enforcement** | High | Proposal §1 mandates ≤128 KiB for evaluations, ≤256 KiB for traces, chunked artifacts. `_put()` accepts arbitrary dicts. `tracestore.py:38` does `[:MAX_PAYLOAD_CHARS]` truncation → **invalid JSON**, which is precisely what the proposal says to avoid (§2: "never truncate JSON"). |
| **`expiresAt` never set** | Medium | Proposal §1: "Store an absolute `expiresAt`, fixed at evaluation creation." Neither `put_evaluation` nor `put_trace` writes `expiresAt`. Trace retention policy is ignored. |
| **`clipId` never set** | Medium | Proposal §4: "Add `clipId` from the normalized corpus-relative source path to prevent same-filename collisions." `evaluationId` is set (line 194: `item.get("traceId") or item.get("_id") or clip_key`) but it's derived from `traceId` not from a `(runId, clipId)` tuple. No `runId` generation exists. |
| **`_collections` cache not thread-safe** | Medium | Proposal §5: "Future concurrency should parallelize." `self._collections` dict is a plain `dict` — concurrent `_collection_by_name` calls could create multiple clients/collections. Needs a lock or at least a comment noting it's single-thread-only. |
| **`put_failure` still has DynamoDB guard** | High | Proposal §3: "Remove `put_failure`'s current early `TRACES_TABLE` guard. Otherwise Astra-only deployments would never save worker failures." `tracestore.py:69–71` still checks `TRACES_TABLE` first and returns `None` if absent, **before** trying Astra. Astra-only setups lose failure records. |
| **No contentHash / contentVersion** | Low–Medium | Proposal §2: traces should have `contentHash`; artifacts should have `contentVersion`. Neither is present. |
| **`get_database` uses deprecated kwargs** | Low | `astra_store.py:150`: `client.get_database(self.endpoint, token=self.token, keyspace=...)` — `token` and `endpoint` as kwargs to `get_database` may not match current `astrapy` API. This is a brittle assumption about the `astrapy` version. |
| **`astradb.py:90` — `configured()` hides errors** | Low | `_client()` swallows all exceptions (`except Exception: return None`, line 101). A transient network error becomes permanent silence on next call — the client is created, fails, returns `None`, and all subsequent calls also return `None`. The cache isn't involved here (it returns `None` directly), so it's a one-shot failure, but it means a brief outage could permanently disable Astra for the process lifetime. |
| **Secrets potentially logged** | Low | `astra_store.py:134`: `f"{type(exc).__name__}: {exc}"` — an Astra exception message could contain endpoint/token fragments. The proposal says token "never logged". |

## (3) Dead Code / Bugs

| Location | Issue |
|---|---|
| `astra_store.py:36` | `TRACE_COLLECTION = "pipeline_eval_traces"` is defined but never referenced. The code uses `collection_name("trace")` which computes the same string. Dead constant. |
| `astra_store.py:38` | `FAILURE_COLLECTION = "pipeline_eval_failures"` — same: defined but unused (code goes through `collection_name("failure")`). |
| `astra_store.py:41` | `_FAILURE_ID = "failure:"` — also unused as a constant; `put_failure` passes `prefix="failure"` directly to `_put`, never referencing this variable. |
| `pipeline_eval.py:203–205` | The `except` block wrapping `_put()` at line 302–305 is **dead code**: `_put()` no longer raises (it catches internally since line 191 of astra_store.py). This `try/except` will never fire. |
| `tracestore.py:72–74` | `put_failure` calls `put_trace(..., f"failure-{job_id}", ...)` — the trace ID becomes `failure-<job_id>`, but there's no `failure:` prefix. This is inconsistent with the `failure:` convention in `astra_store.py:41`. |
| `astra_store.py:130` | `replace_one` return value (e.g. `upserted_id`) is never checked. For idempotency verification, ignoring the result means you don't know if an upsert actually modified anything. Minor. |

## (4) Concrete Fixes

| # | File:Line | Fix |
|---|---|---|
| 1 | `barra/tracestore.py:69–71` | **Move the `TRACES_TABLE` check below the Astra call** so Astra is tried first in Astra-only deployments. Wrap the DynamoDB block in `if not astra_configured() and table:` |
| 2 | `barra/astra_store.py:120–135` | **Add a `max_chars` param to `_put()`** (default 0 = unlimited) and enforce it *before* the API call; return `{"ok": False, "reason": "document too large"}` when exceeded instead of sending it. |
| 3 | `barra/astra_store.py:129` | **Validate the serialized size** in `put_evaluation`/`put_trace` (callers or `_put`) and reject docs exceeding proposal limits (128 KiB / 256 KiB). |
| 4 | `barra/astra_store.py:129` | **Never truncate JSON** — if a document exceeds the limit, return an error. The proposal says "never truncate JSON" for inline traces. Chunk it or reject it, don't slice. |
| 5 | `barra/astra_store.py:105–132` | **Add `expiresAt` to evaluation and trace docs** — compute once at creation time: `int(time.time()) + retention_seconds`. Proposal §1: "fixed at evaluation creation so retries do not extend retention." |
| 6 | `scripts/pipeline_eval.py:191–195` | **Derive `evaluationId` from `(runId, clipId)`** as specified. Add a batch-scoped `runId` (generated once in `main()`) and a normalized `clipId`. Currently it falls back to `traceId` or `clip_key`, which loses the run-level grouping. |
| 7 | `barra/astra_store.py:86` | **Protect `_collections` with a `threading.Lock`** or add a clear comment that parallel collection access is unprotected and will race. |
| 8 | `barra/astra_store.py:99–101` | **Don't return `None` on first failure** — cache the client reference (even `None`-ish) but allow retry on next call, or log and return a transient-failure result instead of permanent disable. |
| 9 | `barra/astra_store.py:134` | **Strip sensitive data from error messages** — don't include the full exception string if it might contain tokens/endpoints. Log internally, return a sanitized message. |
| 10 | `barra/astra_store.py:36,38,41` | **Remove `TRACE_COLLECTION`, `FAILURE_COLLECTION`, `_FAILURE_ID`** — all dead code. They're computed at runtime via `collection_name()` and `prefix` args. |
| 11 | `barra/astra_store.py:150` | **Verify `get_database()` API signature** against the installed `astrapy` version. The `endpoint` and `token` kwargs may be incorrect for the Data API client constructor. Check the docs or switch to the correct invocation pattern. |
| 12 | `barra/tracestore.py:38` | **Replace `[:MAX_PAYLOAD_CHARS]` truncation with chunking or rejection.** Per proposal §2: "For oversized traces, the row references chunked `trace.json`." Either chunk the payload or return an error — don't slice JSON. |
| 13 | `scripts/pipeline_eval.py:302–305` | **Remove the dead `try/except`** wrapping `_put()` since `_put()` now catches internally (no raise path). |
| 14 | `barra/tracestore.py:73` | **Prefix the failure trace ID with `failure:`** for consistency: `f"failure:{job_id}"` instead of `f"failure-{job_id}"`. |
| 15 | `tests/test_astra_store.py` | **Add a test for oversized document rejection** (gap #2–3 above) and a test that `put_failure` succeeds when only Astra env vars are set (gap #1). Also add a test that `configured()` returns `False` without `astrapy` in `sys.modules` (exists but doesn't test construction). |
