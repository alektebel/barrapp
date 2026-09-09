# Nan agent task: develop the Astra DB storage for the pipeline

You are a barrapp engineer. DEVELOP (write real, runnable code) an Astra DB storage
adapter and wire it in, following the architecture proposal at
`docs/PIPELINE-ASTRA-ARCHITECTURE.md` (read it first). Repo root:
`/home/diego/Documents/Development/barrapp`.

Read these existing files before writing:
- `barra/tracestore.py` (put_trace returns `"dynamodb"` or None; put_failure).
- `scripts/pipeline_eval.py` (`_put` uses boto3/DynamoDB; `run_one` builds a
  per-clip `record` dict + writes local artifacts under `out/pipeline-eval/<traceId>/`).
- `barra/config.py`, `barra/evidence.py` (how modules structure config/env).
- `pyproject.toml` (optional-dependencies pattern: mediapipe/ultralytics are extras).

DELIVER a complete implementation. Output ONLY the following as Markdown with clear
**file: content** blocks (exact file names + full contents), so a reviewer can
apply them verbatim:

1. `barra/astra_store.py` — the adapter. Requirements:
   - Uses the optional `astrapy` (DataStax Astra DB Data API client), imported lazily
     inside functions only; importing this module with Astra env vars absent must NOT
     import astrapy, create a client or make any network call.
   - Env config: `ASTRA_DB_APPLICATION_TOKEN`, `ASTRA_DB_API_ENDPOINT`,
     `ASTRA_DB_KEYSPACE` (default `barra`), `ASTRA_DB_COLLECTION` (default
     `pipeline_eval`). `barra.astra_store.configured()` -> bool.
   - Class `AstraStore` with a `client()` accessor (astrapy `DataAPIClient`), and
     methods: `put_evaluation(document)`, `put_trace(document)`,
     `put_failure(job_id, stage, error)`, `get(trick=None, clip=None, status=None)`,
     each returning a small result dict, and none of them raising when Astra is
     unconfigured (return `None` / `{"ok": False, "reason": "astra not configured"}`).
   - Resilient: wrap every remote call, never crash the caller; a failure returns an
     honest result, never a silent success.
   - `_id` convention from the proposal: `eval:<evaluationId>`, `trace:<traceId>`.
2. `scripts/pipeline_eval.py` changes — add a `--store astra|dynamodb|local` (default
   `astra` if configured else `local`), and in `run_one`/`_put` route the record to
   `AstraStore.put_evaluation(...)` when astra is selected/configured (keeping the
   existing DynamoDB path when `--store dynamodb`), and keep writing local artifacts.
3. `barra/tracestore.py` changes — add an Astra path: when `ASTRA_DB_*` configured AND
   `TRACES_TABLE` absent, store the trace to Astra and return `"astra"`; keep the
   existing DynamoDB path; never raise.
4. `.env.example` additions (Astra vars) — update `keystore.properties.example` or add
   a `barra/.env.example` comment block listing the 4 Astra vars.
5. `tests/test_astra_store.py` — pure-offline tests that DO NOT need a live Astra:
   (a) config guard: with vars unset, `import barra.astra_store` does no network call
   and `configured()` is False; (b) with a fake/monkeypatched client injected, `put_*`
   writes documents with the correct `_id`, and a raised client error returns an honest
   failure (does not raise); (c) `tracestore.put_trace` returns `"astra"` when Astra is
   configured and `TRACES_TABLE` is not, and `"dynamodb"` in the legacy case.
6. A `scripts/train_model.py`-style note is NOT needed; instead add a short
   `docs/ASTRA.md` (setup: create the Astra DB with the Data API, set the 4 env vars,
   run `uv pip install astrapy` as an optional extra, and how pipeline_eval uses it).

Rules: follow the repo's code style (no comments unless meaningful, concise,
three-valued honesty, graceful degradation over crashing). Do NOT modify
`barra/classify.py`, `barra/model.py`, `barra/evidence.py`, or the reviewed data.
Treat the proposal as guidance, not gospel; if a detail is ambiguous, pick the
simplest correct option and note it. Return Markdown only.
