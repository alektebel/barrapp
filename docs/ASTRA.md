# Astra DB store for the pipeline evaluation state

The classification/debugging pipeline (`scripts/pipeline_eval.py`,
`barra/tracestore.py`) now has a primary store on DataStax **Astra DB
Serverless** (the Data API document model), holding one row per analysed video
— the intermediate classifier state and the program/model that produced it —
plus the decision-chain traces and best-effort failure records. Local files
under `out/pipeline-eval/<traceId>/` remain the source of truth for the heavy
artifacts (payload, trace, stills); Astra makes the state queryable and durable.

The design is `docs/PIPELINE-ASTRA-ARCHITECTURE.md` (proposed by Codex). The
adapter is `barra/astra_store.py`; it is optional and lazy, exactly like the
pose backends.

## Install

`astrapy` is an optional extra (it must not join the dependency-locked core):

```bash
uv pip install -e ".[astra]"
```

## Create the database

In the Astra console (or via the API):

1. Create a Serverless database; note its **API endpoint** (the HTTPS /api/json
   URL, e.g. `https://<uuid>-<region>.apps.astra.datastax.com/api/json/v1`) and
   a database **Application Token**.
2. Record the keyspace (default `barra`). Collections are created on first use
   by the adapter: `pipeline_eval`, `pipeline_eval_traces`,
   `pipeline_eval_failures` (or one named by `ASTRA_DB_COLLECTION` with those
   suffixes).

## Configure

In `server/.env` (see `server/.env.example`):

```sh
ASTRA_DB_APPLICATION_TOKEN=<token>
ASTRA_DB_API_ENDPOINT=<https://.../api/json/v1>
ASTRA_DB_KEYSPACE=barra
ASTRA_DB_COLLECTION=pipeline_eval
```

When these are set, `pipeline_eval.py` writes per-clip evaluation rows to Astra
and `tracestore.put_trace` returns `"astra"`. When they are unset nothing changes:
importing the module does no Astra import/client/network call, writes degrade to
the local-on-disk path, and the legacy DynamoDB path (`TRACES_TABLE`) is kept.

## Run

```bash
# write per-clip rows to Astra (it is the default when configured)
python scripts/pipeline_eval.py --tricks squat,push_up --per-trick 3

# force the legacy DynamoDB path, or skip the remote row
python scripts/pipeline_eval.py --store dynamodb ...
python scripts/pipeline_eval.py --store local ...
```

## Data model

| collection | `_id` | purpose |
|---|---|---|
| `pipeline_eval` | `eval:<evaluationId>` | one evaluation attempt for one clip (`trick`, `detected`, `modelClass`, `nanLabel`, `poseBackend`, `barra`, `commit`, `python`, `status`, …) |
| `pipeline_eval_traces` | `trace:<traceId>` | the decision chain + trace metadata |
| `pipeline_eval_failures` | `failure:<jobId>` | a job that died before it had a trace |

A re-run of the same clip upserts by `_id` (deterministic), so it does not
duplicate a row. Query helpers: `AstraStore().get(trick=..., clip=..., status=...)`
and `AstraStore().trace(trace_id=...)`.

## Testing (offline)

`tests/test_astra_store.py` runs with no live Astra: it asserts the config guard
(no import/network when unset), an honest `{"ok": False}` on write when it cannot
reach a client, the `_id` namespacing and round-trip, and that a raised client
error never propagates. It uses a fake client that keeps documents in a dict.
