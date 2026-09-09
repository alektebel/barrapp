# Pipeline storage architecture: Astra DB

> Proposed by Codex (gpt-6-astra) on 2026-09-09, applying the classification/debugging pipeline's primary store to DataStax Astra DB Serverless Data API.

**Proposal: make Astra DB Serverless’s Data API the primary store for evaluation records, decision traces, and replay artifacts.** Keep local files as the offline fallback and replay cache; retain DynamoDB as an explicitly configured legacy fallback. No implementation changes are proposed inside the measurement algorithms.

### 1. Storage model

Use non-vector **Data API collections**, accessed through the optional Python `astrapy` dependency. This fits the existing dictionaries and the requested token/endpoint configuration.

Default keyspace: `barra`. Let `ASTRA_DB_COLLECTION` default to `pipeline_eval`, with related collection names derived from it:

| Collection | Document key `_id` | Purpose |
|---|---|---|
| `pipeline_eval` | `eval:<evaluationId>` | One evaluation attempt for one clip |
| `pipeline_eval_traces` | `trace:<traceId>` | Decision chain and trace metadata |
| `pipeline_eval_artifacts` | `artifact:<evaluationId>:<artifactKey>` | Artifact manifest/reference |
| `pipeline_eval_chunks` | `chunk:<artifactId>:<sha256>:<ordinal>` | Artifact content |

**Partition and clustering keys:** these are document collections, so the application specifies `_id`, not CQL partition/clustering definitions. Astra manages the underlying layout. `trick` is an indexed query field, not a partition key.

If corpus scale later requires partition-local ordered reads, an alternative table design would use partition key `(trick, runMonth)` and clustering keys `(createdAt, evaluationId)`, plus a separate lookup table partitioned by `clipId`. That requires maintaining duplicate query projections; it is unnecessary for this initial collection design.

Configure selective indexing during provisioning:

- Evaluations: `_id`, `clipId`, `clip`, `trick`, `runId`, `createdAt`, `status`, `detected`, `modelClass`, `nanLabel`, `poseBackend`, `commit`, `expiresAt`.
- Traces: `_id`, `traceId`, `jobId`, `evaluationId`, `expiresAt`.
- Artifacts: `_id`, `evaluationId`, `traceId`, `expiresAt`.
- Chunks: `_id`, `artifactId`, `expiresAt`.

Exclude large payloads, feature arrays, and encoded content from indexing. Collection indexing policy is chosen at creation, so provisioning must be explicit. [Astra collection indexes](https://docs.datastax.com/en/astra-db-serverless/api-reference/collection-indexes.html)

**Size limits:** DynamoDB’s existing 400 KB item constraint does not transfer to Astra. Astra currently documents a maximum document size of **4 million characters**, a 5,000-property limit, and an 8,000-byte indexed-string limit. These are distinct constraints, not a blanket “4 MB” allowance. [Data API limits](https://docs.datastax.com/en/astra-db-serverless/api-reference/dataapi-limits.html)

Adopt conservative application limits:

- Evaluation/manifest documents: target below 128 KiB serialized UTF-8.
- Inline trace: only when below 256 KiB and within structural limits.
- Larger JSON and binary artifacts: 192 KiB raw chunks, base64 encoded.
- Validate serialized documents before sending; never truncate JSON.

**Retention:** retain evaluation summaries indefinitely initially. Preserve the current 90-day trace policy for traces and their artifacts. Store an absolute `expiresAt`, fixed at evaluation creation so retries do not extend retention. A scheduled adapter cleanup operation deletes expired content; readers treat it as expired immediately. A JSON `ttl` field does not itself cause expiration. This proposal does not depend on native TTL through the Data API; even its CQL-table interface documents TTL limitations. [Data API/CQL differences](https://docs.datastax.com/en/astra-db-serverless/api-reference/compare-dataapi-to-cql.html)

### 2. Document schemas

**Evaluation row**

Keep existing field names and native JSON types:

| Group | Fields |
|---|---|
| Identity | `schemaVersion`, `_id`, `evaluationId`, `runId`, `clipId`, `clip`, `file`, `traceId` |
| Expected/observed | `trick`, `expected`, `detected`, `label`, `correct`, `outcome` |
| Measurement | `nReps`, `faults`, `score`, `trim`, `durationS`, `variants` |
| Learned opinion | `features`, `featureNames`, `modelClass`, `modelConfidence`, `modelVersion`, `loadKg`, `loadEstimated` |
| Independent vision | `nanLabel`, `nanModel`, `nanNote`, `nanOk`, `nanAgreesWithGeometry`, `nStills` |
| Provenance | `poseBackend`, `poseFrames`, `poseCached`, `barra`, `commit`, `python`, `runtimeS`, `createdAt` |
| Persistence | `status`, `artifactIds`, `manifestHash`, `error`, `errorStage`, `artifactsExpireAt` |

`outcome` distinguishes `correct`, `misclassified`, `abstained`, and `error`; `status` describes persistence publication, such as `pending` or `complete`. An analysis error can therefore have a complete, durable diagnostic record.

Preserve `False`, zero, empty strings, and nulls. Convert non-finite numbers to null. Unlike `_put` today, do not stringify scalar values or slice composite JSON to 2,500 characters. Keep geometric abstention separate from the learned model’s opinion.

**Trace row**

Store:

- `_id`, `schemaVersion`, `traceId`, `jobId`, optional `evaluationId`.
- `createdAt`, `expiresAt`, `contentHash`.
- Either `payload` or `payloadArtifactId`, never an ambiguous partial payload.

The payload preserves `Trace.as_dict()` unchanged: `schema`, `traceId`, `subject`, `context`, `durationMs`, `counts`, and ordered `entries`. Each entry retains `stage`, `kind`, `atMs`, `message`, and `data`.

For oversized traces, the row references chunked `trace.json`. This replaces `tracestore`’s current 350,000-character slice, which can produce invalid JSON.

**Artifact reference**

Store:

- `_id`, `evaluationId`, `traceId`, `artifactKey`, `kind`.
- `mediaType`, `encoding`, `byteLength`, `sha256`, `chunkCount`.
- `storage: "astra"`, `contentVersion`, `createdAt`, `expiresAt`.
- `localRelativePath` as an optional cache hint.
- For stills: `rep`, `phase`, `moment`, `tS`, and label where available.

Each chunk contains its deterministic ID, `artifactId`, ordinal, content hash, encoded bytes, and expiry.

Persist `payload.json`, `features.json`, trace content, nan stills, and generated technique artifacts. The runner currently assigns `art = technique_artifacts(...)` without persisting its returned metadata; register those outputs explicitly.

**A local pathname alone is not durable storage.** Chunking places the requested debugging artifacts in Astra too. Original source videos and the separate pose-training cache remain outside this proposal. Large generated video artifacts would increase database cost substantially; an object-store alternative would be a separate scope decision.

### 3. Changes mapped to existing code

Introduce **`barra/astra_store.py`** as the persistence boundary, with operations for configuration, evaluation upsert/query, trace storage, artifact upload/download, and replay of pending local writes.

The adapter lazily imports `astrapy`, initializes clients only after configuration checks, normalizes JSON values, enforces limits, and applies bounded retries/timeouts. Provision collections separately rather than creating them per clip.

| Environment variable | Proposed behavior |
|---|---|
| `ASTRA_DB_APPLICATION_TOKEN` | Required to enable Astra; never logged |
| `ASTRA_DB_API_ENDPOINT` | Required to enable Astra |
| `ASTRA_DB_KEYSPACE` | Default `barra` |
| `ASTRA_DB_COLLECTION` | Default `pipeline_eval`; derives companion names |
| `EVAL_TABLE` | Explicitly enables legacy evaluation fallback |
| `TRACES_TABLE` | Explicitly enables legacy trace fallback |

Backend selection:

| Configuration/result | Behavior |
|---|---|
| Token and endpoint present | Astra primary; no routine DynamoDB dual-write |
| Neither present | Local storage; optionally mirror to explicitly configured DynamoDB |
| Only one present | Report incomplete configuration; use local/explicit legacy fallback without contacting Astra |
| Astra write fails | Preserve local pending bundle; report degraded persistence and retry later |

For an Astra outage, avoid silently switching individual documents to DynamoDB and claiming the bundle is durable. The local manifest records exactly what remains unacknowledged.

**`scripts/pipeline_eval.py`**

- Replace `_put`’s direct `boto3.client(...).put_item(...)` with adapter persistence. Retain the existing encoder only in the legacy DynamoDB branch.
- Remove the implicit evaluation-table default as a trigger for AWS access. Offline execution must not need AWS credentials.
- Allocate evaluation/trace identity and provenance **before pose estimation**.
- Route pose and measurement failures through the same finalization path. They currently return before row/trace persistence.
- Write `record.json` and a persistence manifest beside existing artifacts before remote upload. The final batch `results.json` alone cannot protect a partially completed run.
- Retain current report generation and local artifact layout.
- Correct the misleading `TRACES_TABLE` module constant: it does not configure `tracestore`, which independently reads `os.environ`.

**`barra/tracestore.py`**

Keep `put_trace(record, trace_id, job_id="")`, extending its return contract to **`"astra" | "dynamodb" | None`**:

1. Try Astra when configured.
2. When Astra is unconfigured, use the existing DynamoDB path if `TRACES_TABLE` is set.
3. Return `None` on remote failure or local-only operation; caller-owned disk handling remains unchanged.

Remove `put_failure`’s current early `TRACES_TABLE` guard. Otherwise Astra-only deployments would never save worker failures.

**`server/process.py`**

`_write_trace` already writes local JSON and logs any truthy backend name, so `"astra"` fits its existing behavior. Preserve its best-effort contract. `None` must continue to mean no acknowledged remote write, not proof that a local file exists.

Keep persistence outside `classify.py`, `model.py`, `evidence.py`, and `frames.py`; those modules continue producing measurements and artifacts.

### 4. Identity, upserts, and queries

Preserve `clip = "<trick>/<filename>"` for compatibility. Add `clipId` from the normalized corpus-relative source path to prevent same-filename collisions; optionally record a source SHA-256 separately.

Generate `runId` once per batch and derive `evaluationId` deterministically from `(runId, clipId)`. Persist that identity locally before work begins. A retry resumes it; a deliberate rerun gets a new run ID. This preserves history instead of overwriting the previous evaluation of a clip.

Use exact-ID `replace_one` with `upsert=True` and complete normalized documents. Full replacement prevents old optional fields surviving a rerun. Astra’s collection client supports this operation. [Replace a document](https://docs.datastax.com/en/astra-db-serverless/api-reference/document-methods/replace-one.html)

| Request | Query pattern |
|---|---|
| All completed evaluations for a trick | Filter `trick` and `status = complete`; exhaust cursor pagination |
| All rows for a trick including interrupted work | Filter `trick` without status restriction |
| Any completed evaluation by clip | Filter `clipId` and `status = complete`; `find_one` |
| Legacy clip lookup | Filter `clip = "squat/example.mp4"` |
| Exact attempt | Lookup `_id = eval:<evaluationId>` |
| Trace | Lookup `_id = trace:<traceId>` |
| Artifacts | Filter `evaluationId`, then fetch deterministic chunks |

“Any row” does not mean “latest.” If latest is needed, define it explicitly and use bounded time/run filters before sorting. Avoid assuming unlimited collection-wide sorting; Astra documents a 10,000-row in-memory sort limit. [Data API limits](https://docs.datastax.com/en/astra-db-serverless/api-reference/dataapi-limits.html)

### 5. Parallel writes and consistency

The current batch loop is sequential. Future concurrency should parallelize independent clips while preserving this publication order within each clip:

1. Atomically save the local identity, record, artifacts, and pending manifest.
2. Upsert the evaluation as `pending`.
3. Upload independent artifacts/chunks with bounded concurrency.
4. After chunk acknowledgements, publish their artifact manifests and trace row.
5. After every required reference is acknowledged, replace the evaluation with `status = complete` and its final manifest hash.
6. Mark the local bundle synchronized.

Readers use completed evaluations as publication markers. This is an application protocol, not a multi-document transaction. Direct trace lookups may expose a trace before its evaluation is published.

Use one writer per evaluation attempt; distinct reruns receive distinct IDs. Retries replay the same frozen bundle. Content-versioned chunk IDs prevent partial replacement from mixing old and new bytes. Preserve trace entry array order regardless of upload completion order.

Astra Data API reads and writes use `LOCAL_QUORUM`; cross-region replication is eventual. Use the same regional endpoint for immediate read-after-write debugging, and let readers retry missing referenced content rather than treating it as corruption immediately. [Astra consistency limits](https://docs.datastax.com/en/astra-db-serverless/databases/database-limits.html)

### 6. Small offline test strategy

Use an injected fake collection/client, temporary directories, a fake clock, and monkeypatched environment variables. No pose models or live Astra database are necessary.

1. **Configuration guard:** with Astra variables absent, constructing/importing the adapter performs no Astra import, client creation, or network call. Test partial configuration too.
2. **Backend contract:** assert `"astra"`, `"dynamodb"`, and `None` outcomes; verify `put_failure` works with Astra configured and `TRACES_TABLE` absent.
3. **Idempotency and types:** replay one bundle twice; document count stays constant, false/zero/null survive, and obsolete optional fields disappear on replacement.
4. **Artifact integrity:** oversized JSON and binary fixtures round-trip through chunks with matching hashes; Unicode and non-finite values do not cause truncation or invalid JSON.
5. **Publication ordering:** deliberately fail one parallel chunk write. The evaluation remains pending, the local bundle survives, and replay completes it without duplicates.
6. **Query and failure coverage:** fake multiple cursor pages and repeated clip evaluations; verify trick/clip filters and persistence of early pose/measurement failures.

These tests validate barrapp’s storage contract and failure handling. They do not establish production Astra latency, throughput, or service consistency guarantees.
