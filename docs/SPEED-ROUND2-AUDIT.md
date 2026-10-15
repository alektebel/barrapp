# Round 2 — evidence and implementation decisions

2026-10-12. Companion to [SPEED-PLAN.md](SPEED-PLAN.md), based on the current
worktree, a production timing fixture, and local pose experiments. Android
findings are implementation and local test evidence, not claims about a
completed release or an attached-phone run.

## Acceptance contract

The objective remains **a randomly selected 30 s source clip, upload start to
the measured result rendered on the phone, strictly under 15 s**. A clip with
30 s of continuous exercise stays in scope. Selecting only clips that trim to
6 s would change the objective. No pose-cache hit, precomputed answer or
discarded exercise time counts as a successful uncached measurement.

Use the same phone monotonic clock for both endpoints:

- Start immediately before the first request initiating upload, including
  job creation if it has not already occurred.
- End at the first frame callback after the session containing the measured reps/score or a
  valid abstention for genuinely unmeasurable footage. A loading view, upload
  success, empty result or `done` on the server is not this endpoint.
- Record preparation separately: source copy, motion scan, human adjustment,
  export, export fallback. Also report confirm-to-render elapsed time, so a
  long transcode cannot disappear from the user experience.
- Record source duration, selected interval, prepared duration/bytes/hash,
  device/app build, network, job/trace IDs, worker build/model/config,
  cold/warm state and whether any fallback or retry occurred.

One successful phone run establishes that run only. For repeatability, select
the clips before running the candidate, then report every outcome and the
fraction under 15 s, plus p50/p95. Include short active windows, continuous
sets, static holds, moving cameras and trim/export failure. Keep warm and cold
workers separate in the report, and include cold results in the overall count.
Do not omit slow fallbacks or retry jobs from the denominator.

## Budget that fits the target

This is an allocation to test, **not a measurement or a promise**:

| Serial stage | Allocation | Evidence needed |
|---|---:|---|
| Upload protocol and bytes through submit | 3.0 s | phone monotonic request/part events |
| Worker dispatch, cold initialization and download | 1.0 s | worker entry, download start/end, init logs |
| Pose, including process/model startup, warm-up and merge | 8.0 s | whole-stage wall time; effective chunk count |
| Auto-classification vision vote | 0 s incremental after pose; must finish within pose's 8.0 s wall time | `fusionWaitMs`, locator outcome and completion-at-result |
| Local exercise decision, segmentation and scoring | 0.5 s | trace; includes synchronous decisions and the visual-count-rescue sub-timer |
| Persist the first result | 0.3 s | before/after result write |
| Phone polling, parse, store and render | 0.7 s | first done response through rendered frame |
| Reserve | 1.0 s | measured variation |
| **Total allocation** | **14.5 s** | **single phone clock, <15 s** |
| Prose, advisory vision, stored replay trim | **0 s on the critical path** | first result written before these begin/wait |

The original upload **2–5 s** and pose **6–10 s** ranges are coupled, not
independent allowances: with 2.5 s for the other stages, a 5 s upload leaves
less than 7.5 s for pose. Their simultaneous upper bounds already total 15 s
before any other work. Retain the ranges as experiments, not a passing budget.
The auto-classification vote overlaps pose, so its wall time is not added when
it finishes first. Fusion now checks the localization future without waiting:
a late vote cannot extend the first-result path, but that run then uses the
local classifier and may choose a different exercise. This implements the
zero-increment rule in code; live-provider accuracy/latency and deployed
behavior remain unverified. Prose and advisory technique vision start after
the first result and remain off the gate.

At the proposed 4 Mbit/s video bitrate, 6 s contains about 24 Mbit of video;
transferring that in 2–5 s requires 12–4.8 Mbit/s before protocol overhead.
Thirty active seconds contains about 120 Mbit and needs 24 Mbit/s merely to
transfer in 5 s. Actual encoded bytes and observed network throughput decide
the upload budget, not the resolution label.

## Critical path found in the code

```text
prepared clip -> multipart upload -> submit -> import/download
                                            |
                                            +-> pose -> classify -> fuse -> measure -> persist -> poll/render
                                            |                       ^          ^
                                            +-> locate vision ------+          |
                                                                       visual count rescue

after first persist: prose, advisory vision and replay storage
```

1. **Six configured workers do not imply six chunks.**
   `barra/pose/parallel.py` defaults to one worker. Its 240-frame minimum
   produces one chunk for 180 frames (6 s at 30 fps), three for 900 frames
   (30 s), and six only from 1,440 frames. `server/template.yaml` now requests
   10,240 MB in the worktree but leaves `BARRA_POSE_WORKERS` unset. Raising
   memory alone does not enable parallel execution.
2. **Fusion used to wait for remote vision.** The worker now calls
   `located_future.result(timeout=0)` at fusion. If the vision vote finished
   during pose, it is used; otherwise local classification proceeds at once
   and the late locator continues only for post-result clip localization.
   Android submits `auto`, so a late vote can still change the automatic label
   and is a quality risk, even though it no longer extends first-result time.
   The locator's post-result operation may run up to its existing timeout and
   retry budget; this is outside the phone's first-result gate. No live provider
   latency or label quality was measured locally.
3. **Count rescue is also a remote measurement dependency.** If geometry and
   the relaxed segmenter find no reps, `analyze_clip` can call
   `count_from_clip`. It now asks both count models concurrently and skips the
   standalone `/models` preflight; the exact agreement/reconciliation rule is
   unchanged. The calls still use the provider's retry/timeout policy and are
   awaited before the result, so slow or unavailable vision can exceed the
   budget. The trace now records `visual count rescue` duration and outcome;
   `job_timing.py` reports that sub-stage without double-counting it in the
   enclosing measurement. A bounded synthetic probe timed both concurrent
   models out at 15 s with one attempt each; it is a failure sample, not a
   success-latency distribution, but confirms one request round can consume the
   whole target. No personal footage was sent. The count-rescue critical-path
   design records the probe and the deadline/accuracy gate this path needs.
4. **VIDEO tracking has history.** Trim boundaries and independently started
   chunks change tracker state. H.264 transcoding changes input pixels. Neither
   is guaranteed to preserve numbers because the server still uses the same
   decoder or subsequently resizes the frames.
5. **Polling and rendering matter.** The Android worker loop polls every
   250 ms until 15 seconds from attempt start, then at one-second intervals.
   Additional local session writes/refreshes may
   precede the rendered result. The CLI transport checker polls every four
   seconds and is not a phone latency measurement.

AWS documents six vCPUs at 10,240 MB, and MediaPipe documents that VIDEO mode
uses tracking to avoid repeated detection. These establish the resource and
state model; neither promises linear speed-up or equivalence after restarting
a tracker. Sources: [AWS configuration troubleshooting](https://docs.aws.amazon.com/lambda/latest/dg/troubleshooting-configuration.html),
[MediaPipe Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python).

## Design decisions and next implementation steps

**Reusable candidate quality gate:** `scripts/round2_quality_gate.py` now
compares candidate reports with reviewed assertions in
`data/evaluation/sample_manifest.json`. It gates reviewed automatic
movement/count labels, explicit forbidden faults and reviewed not-rep intervals;
unreviewed counts/scores remain coverage gaps. It accepts both local pose
screen reports and full server measurement payloads; any gap marks that report
`incomplete`, which makes the overall command exit nonzero. Applied to saved YOLO11n
half-rate reports, it fails WA0017 (false `back_lever`) and WA0020 (automatic
`deadlift` / 0 against reviewed `push_up` / 19), although the separately
declared push-up path counts 19. A fast declared-only run cannot clear the app's
`auto` path. Example:
`python scripts/round2_quality_gate.py out/round2-latency/ultralytics-screen/stride2/*/report.json`.
Applied to the faster RTX Heavy GPU reports, the same gate rejects WA0010's
`pull_up` label, WA0017's two false muscle-ups, WA0020's automatic zero count,
and the declared WA0020 run's 18 versus 19. This remains screening evidence,
not representative coverage; the 30 s WA0014 count is unreviewed and cannot
clear a candidate by itself. Scores are not hard-gated unless the review
manifest supplies an independent reviewed score; a prior pipeline score is not
ground truth.

**First, finish the exact scheduling changes.** Publish deterministic Spanish
prose with measured results before starting model prose or replay cutting.
Handle `proseStatus` independently of `visionStatus`; the phone must re-fetch
while either is pending and eventually show a terminal status. Failed or
rejected prose retains the fallback. Validate delayed updates against the
same payload contract and preserve measured fields and provenance. The local
server should exercise the same first-result/deferred-update behavior as the
deployed worker, otherwise local E2E cannot prove this property.

**Small-clip upload protocol implementation (not yet phone-measured):** for
prepared clips at or below 8 MiB, Android now uses the one-object PUT URL from
`createJob`; larger clips and legacy in-flight multipart jobs retain multipart.
The work queue persists mode/completion, never the signed URL, and refreshes a
single-PUT URL through an owner-checked endpoint after process/network resume.
Startup recovery now resumes both single PUT and multipart work, including a
single PUT whose request was interrupted; a single-object transfer gets one
whole-file attempt per network availability, then waits for reconnection rather
than burning the budget on repeated full-file retries.
The submit route checks object existence and minimum size before queueing; the
local server mirrors these checks. This removes multipart-start, part-presign
and multipart-complete calls for eligible clips. It does not reduce uploaded
bytes, and its latency effect has not been measured on a phone. Next compare
both paths on the same controlled uplink, recording bytes, API round trips,
retries and full attempt-to-render latency. Keep the protocol only if the
complete randomized run meets the acceptance gate without quality changes.

**Make prepared video immutable for each upload attempt.** Keep original path,
selected interval, exported path/hash and export-applied state separate.
Resuming a multipart upload must read the identical bytes used for its
completed parts. Once export succeeds, restarting or retrying must not apply
the original trim interval to the already trimmed file. Failed export falls
back to the original bytes, with the fallback included in latency reports.
Motion suggestions need decoded samples at the requested instants:
`OPTION_CLOSEST_SYNC` can repeat the same keyframe for several 0.5 s samples.
The sampler now requests `OPTION_CLOSEST`, which returns a frame closest to
the requested time but can cost more when no sync frame is at that time.
Measure its preflight cost and validate the suggested interval on real footage,
with a full-clip option always available; global motion is not proof of
exercise activity.

The Media3 exporter now explicitly requests 4 Mbit/s video encoding and stores
the encoder-reported average video bitrate with the attempt. Media3 documents
that requested video settings may be ignored by a device to improve quality or
reduce failures, so this is a requested target, not a size guarantee; use the
reported rate and file bytes from an attached-phone run for upload projections.

**Local bitrate screen (2026-10-13):** the reviewed 20 s WA0020 source is
478×850, 4.37 MB and averages 1.62 Mbit/s video. FFmpeg H.264 404×720 trials
at 1/2/4 Mbit/s produced 2.82/5.31/10.30 MB respectively (reported video
rates 0.99/1.99/4.00 Mbit/s). All three declared-push-up runs retained the
reviewed 19 reps and no forbidden lift-stall fault; automatic classification
remained the incorrect muscle-up / 0. Several rep boundaries moved by up to
about 0.06 s versus the original, so this is not exact measurement parity and
cannot pass the current no-number-change gate. The 4 Mbit/s request more than
doubles this source's bytes; it is not an upload optimization for this input.
Do not globally lower the bitrate on this one clip either: screen more reviewed
clips and device exports, and use actual source/output bytes and encoder reports
to set any adaptive cap. Raw payloads and sizes are in
[`bitrate-comparison.json`](../out/round2-latency/bitrate-wa0020/bitrate-comparison.json).

The same 1 Mbit/s screen on WA0010 reduced 3.34 MB to 2.23 MB and retained
two reviewed muscle-ups, but changed auto classification from the baseline's
pull-up to muscle-up, changed score 56→54 and moved boundaries by up to 0.16 s.
Normalized visible keypoint error was 0.0039 of frame width/height on average,
with 0.0148 p95 and a 0.179 maximum outlier. On the reviewed negative control
WA0017, 5.09 MB became 3.31 MB but the output claimed two muscle-ups instead
of the expected zero; WA0018 remained at zero reps (its abstention label is
low-confidence). This rejects fixed 1 Mbit/s: its byte savings do not preserve
the reviewed negative. The per-clip runs are in
[`bitrate-wa0010/`](../out/round2-latency/bitrate-wa0010/) and
[`bitrate-negatives/report.json`](../out/round2-latency/bitrate-negatives/report.json).

The current Android path now clears the one-shot trim window when it persists
the exported path, preventing re-trimming after a process restart. It still
does not retain a distinct original path/hash. Both the retry fix and the
denser frame sampling need device-level validation before relying on trim as a
performance optimization.

**Treat short-chunk pose as a candidate, not a default.** Benchmark explicit
1/2/3/6-worker configurations on the deployed six-vCPU image, including import,
model load, warm-up, decode duplication, merge and fallback. A lower chunk
floor needs a named/versioned configuration shared by production and the
comparison harness. The existing harness's `--min-chunk 60` is not the
production floor of 240. Log the effective configuration, model hash, actual
chunk count and whether sequential fallback ran. A custom model path must be
passed to every child rather than silently selecting a different default.

**Warm-up sweep (2026-10-13):** six Heavy chunks on the prepared 30 s WA0014
source, compared to its saved sequential keypoints. Increasing overlap from
45 to 240 frames improved XY mean absolute error only from 0.304 to 0.278 px;
the 95th percentile stayed around 1 px and the largest outlier remained over
140 px. Wall time rose from 21.88 s to 30.75 s, still far outside the pose
allocation. Thus longer tracker warm-up does not recover sequential tracking
and spends more inference time. These are keypoint-only observations; no new
measurement-parity claim follows. The machine-local results and exact settings
are in [`overlap-sweep.json`](../out/round2-latency/overlap-sweep.json).

**YOLO11n stateless chunk screen (2026-10-13):** since MediaPipe VIDEO
tracking does not converge across independently started chunks, I screened the
repo's YOLO11n-pose model in stateless per-frame mode (`track=false`) as a
different candidate. The ignored harness and outputs are under
[`ultralytics-screen/`](../out/round2-latency/ultralytics-screen/); weights
SHA-256 is `869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`.
At `imgsz=640`, six chunks on reviewed WA0020 took 10.24 s versus a 29.12 s
sequential run. The chunked and sequential keypoints differed by at most
0.00052 px in the visible pairs and produced identical downstream output for
the tested auto and declared paths (19 push-ups declared, score 56, same
boundaries); the automatic class was still `dip`, not reviewed `push_up`.
At `imgsz=480`, six chunks took 7.34 s on WA0020 and 6.49 s on WA0010. WA0010
returned its reviewed two muscle-ups and the correct automatic label, score
51. WA0020 retained 19 declared push-ups and score 56, but keypoints differed
materially from 640 (visible XY MAE 9.86 px, p95 30.57 px); this is a model
input-size change, not exact parity. At `imgsz=384`, WA0020 counted only 13 of
19 and is rejected.

The full 30 s prepared WA0014 clip took 13.54 s for pose at 480, before the
roughly 0.8 s measurement step. It generated two muscle-up candidates at
26.95–28.29 s and 28.49–29.50 s, both with very low measured ROM; neither
intersects the separately reviewed walking interval at 22.61–25.16 s, but
these candidates still require label review and do not establish quality.
This misses the 8 s pose allocation and there is no attached-phone, cold
Lambda, startup/download, upload or render measurement. The experiment
therefore shows a plausible backend direction and strong speed-up over the
sequential CPU screen, not a passing end-to-end result or a rollout decision.
Breaking the same run into a parent decode plus six pre-decoded inference
workers took 0.65 s to decode and 12.78 s for inference (13.43 s total).
Duplicated per-worker decoding was not the dominant cost; more decode
plumbing alone will not close the pose gap.
Do not replace MediaPipe by default or enable chunking until broader reviewed
clips establish counts, identity, faults, scores and boundaries for this exact
configuration; retain the sequential backend as rollback.

The YOLO path is not currently deployable by flipping an environment variable:
the current `server/Dockerfile` and `server/requirements-worker.txt` ship
MediaPipe. A local experimental `barrapp-worker:yolo-pinned` image contains
Ultralytics 8.4.166 but has no YOLO pose weights at `/opt/barra` or
`/var/task`; the host checkpoint is 6.0 MB and must be deliberately baked in
or downloaded with a pinned hash. `docker image ls` reports 4.79 GB for that
candidate versus 3.32 GB for the current local worker image. Importing
Ultralytics took 1.154 s in the already-pulled local container. This is a
process import measurement only, not a Lambda cold-start or image-pull
measurement. Any production candidate still needs asset provenance, an image
size/cold-start evaluation, cache-tagging and a rollback path.

**Half-rate YOLO screen (2026-10-13):** inferred every other source frame at
`imgsz=480`, six stateless workers, then linearly interpolated keypoints onto
the original frame clock. The same full 30 s WA0014 input dropped from 13.54 s
to 7.16 s pose (0.49 s decode + 6.67 s inference); geometry/measurement took
about 0.08 s. That fits the 8 s pose allocation locally and, with a 5 s upload
and the 2.5 s non-pose/upload work allocation, projects to 14.66 s before the
1 s reserve. Including the reserve gives 15.66 s; to stay strictly under 15 s
with that reserve, upload must be under 4.34 s or another stage must shrink.
It is the first candidate in this round whose local 30 s pose result fits the
pose allocation, but it does not by itself fit the complete 15 s budget. This
is only a workstation projection; worker startup/download, actual upload and
phone rendering are absent.

**Worker-image runtime screen (2026-10-14):** ran the reproducible
`scripts/round2_container_candidate.py` harness inside local
`barrapp-worker:yolo-pinned` with `--cpus=6`, mounting the current `barra/pose`
source, pinned checkpoint and production `server` code read-only. This image is
4.79 GB, includes Ultralytics 8.4.166, but is an older build; its original pose
backend did not implement stride/chunking. The candidate source was mounted so
the timed path really used six workers, stride 2, `imgsz=480`, one PyTorch
thread per worker, and weights SHA-256
`869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`.
On the prepared 29.8 s WA0014 clip, pose took 7.363 s and measurement 0.503 s
(7.867 s combined); it emitted two unreviewed muscle-up candidates and remains
incomplete at the quality gate. Reviewed WA0010 took 5.238 s pose and 5.837 s
pose-plus-measurement (two muscle-ups); its derived score was 50, while scores
are not independently asserted in the manifest. WA0020 took 5.038 s pose but
auto-classified as deadlift / 0 against reviewed push-up / 19. WA0017 took
5.772 s pose and falsely classified the reviewed negative as back lever / 0.
The reviewed quality gate therefore fails despite the short pose times. Parent
process import was 0.17 s; image pull, Lambda initialization, network upload,
worker download and phone render were not measured. This x86 `--cpus` quota is
not a deployed Lambda 6-vCPU benchmark.

The same container/config was screened over all eight own-clip manifest rows;
the 29.8 s WA0014 case above is the prepared first-30-second crop. Times below
are pose / pose-plus-measurement, not upload-to-result:

| Clip | Pose / measured path | Current manifest review | Candidate auto output |
|---|---:|---|---|
| WA0010 | 5.238 / 5.837 s | muscle-up / 2, medium | muscle-up / 2, score 50 |
| WA0011 | 4.627 / 5.012 s | knee-raise label, count unreviewed | front-lever / 0 |
| WA0012 | 4.206 / 4.294 s | difficult visibility, count unreviewed | muscle-up / 1, score 63 |
| WA0014 first 30 s | 7.363 / 7.867 s | false interval reviewed; total count unreviewed | muscle-up / 2, unscored |
| WA0017 | 5.772 / 5.913 s | unknown / 0, medium | back-lever / 0 |
| WA0018 | 4.203 / 4.271 s | abstention expected, label unreviewed | muscle-up / 0 |
| WA0019 | 4.223 / 4.275 s | attempt/swing, movement unresolved | auto / 0 |
| WA0020 | 5.038 / 5.117 s | push-up / 19, medium | deadlift / 0 |

The gate fails WA0017 and WA0020 and marks four other rows incomplete. WA0010
matches its reviewed class/count but not the prior score-51/no-fault production
baseline; no independent score label is stored in the manifest. Therefore the
fast pose result is not a quality-cleared substitute for the current pipeline.

**Budget implication (projection, not a phone result):** the measured 7.363 s
pose plus 0.503 s measurement uses 7.866 s. Adding the remaining budget
allocations for dispatch (1.0 s), persistence (0.3 s), phone delivery (0.7 s)
and reserve (1.0 s) gives 10.866 s before upload. Upload-through-submit must
therefore stay below 4.134 s to remain strictly under 15 s. A 4.0 s upload
projects to 14.866 s; 5.0 s projects to 15.866 s. Lambda cold initialization
or any unbudgeted delay would erase that small margin.

The first disposable-container attempt without `BARRA_YOLO_POSE_WEIGHTS` tried
to download the default model: the weight resolver searched only for stronger
variants before falling back to a relative filename. It now searches for the
default `yolo11n-pose.pt` too, and has a regression test; production must still
pin the path and verify the checkpoint hash. The observed 26.5 s run used the
image's stale full-rate backend, so it is discarded as a chunked-candidate
timing.

| Assumed upload | Projected total with 7.16 s pose and the full stage budget | Target |
|---:|---:|---|
| 3.0 s | 13.66 s | within, with 1.34 s headroom |
| 4.0 s | 14.66 s | within, with 0.34 s headroom |
| 5.0 s | 15.66 s | over by 0.66 s |

These estimates use 1.0 s dispatch/download, 0.5 s decision/measurement,
0.3 s persistence, 0.7 s phone delivery and the 1.0 s reserve from the budget
table. They are not measured totals.

The reviewed WA0010 count and auto label stayed at two muscle-ups, but its
score changed 51→50 and its fault set changed from empty to lockout, control,
stall and bent-arms. WA0020's declared push-up path retained 19 reps and score
56, but auto classification changed to zero-rep deadlift. Inspecting fusion
isolated this to the learned vote: geometry names `push_up`, while the
classifier returns `deadlift` at 0.7507 confidence and fusion selects it.
The local screen has no vision vote; production starts the vision locator
alongside pose and can override this, but its arrival time on the 7 s pose
path is unmeasured. As an oracle diagnostic, feeding the reviewed manifest
label `push_up` into fusion selects geometry+vision, recovers 19 reps, score
56 and no faults; boundaries differ from the full-rate 480 run by at most
0.04 s. This is not a real vision-service response or a latency measurement;
the saved result is explicitly marked oracle-only in
[`oracle-fusion.json`](../out/round2-latency/ultralytics-screen/stride2/WA0020/oracle-fusion.json).
Android currently always creates jobs with `exercise="auto"`
even though the API accepts an explicit movement, so users cannot choose the
declared-exercise path today. The reviewed
negative WA0017 remained at zero reps, and WA0018 remained at zero reps with a
low-confidence muscle-up label. WA0014 still emitted two low-ROM candidates
near 27–30 s; neither fell in its marked walking interval, but the full clip's
true count is not reviewed. These differences fail the current measurement
gate: speed does not authorize changing score, faults, automatic identity or
rep evidence. A half-rate input therefore remains an experiment pending
frame-by-frame adjudication and broader positive/negative coverage. The exact
run settings and full payloads are in
[`ultralytics-screen/stride2/`](../out/round2-latency/ultralytics-screen/stride2/).

**Resolve exercise identity without an unbounded wait.** There are two
measurement choices to evaluate on the same labelled clips:

- A confirmed exercise supplied with the upload uses that profile immediately.
  Measure the extra interaction separately; do not silently add manual work
  to claim automatic recognition became faster.
- Automatic selection uses a measured, bounded classifier path. A locator
  reply may influence the initial measurement only if it arrives before that
  decision deadline. Late disagreement is advisory and must not silently
  rewrite counts/scores already shown. Compare classification error and
  abstention rates before accepting this change: the current fusion path was
  introduced for accuracy, so dropping its vote is not an exact optimization.

Count rescue needs the same explicit decision: retain it and count its wait,
or introduce a separately labelled preliminary measurement followed by a
measured revision. A preliminary screen alone does not satisfy this goal.

**Keep the continuous 30 s case in the design.** At the plan's historical
3.6 s of CPU inference per video second, even perfect six-way division of
30 active seconds takes 18 s, excluding 45-frame warm-ups and startup. This
is a projection from the recorded baseline, not a new Lambda measurement.
If production experiments confirm it, tuning chunk size cannot meet the
objective. The next candidate must reduce inference cost: evaluate a faster
continuous tracker/model or hardware acceleration at the same frame timestamps,
then evaluate reduced frame rate only with explicit temporal-quality gates.
Phone pose is a possible separate architecture experiment; verify device/server
parity and preparation time before claiming an upload benefit. Do not spend
the whole round optimizing only the six-second subset.

## Quality and rollout gates

Use the existing own clips for regression, then the labelled reference data
for correctness. Confirm labels cover rep boundaries and faults; an exercise
name alone does not validate scoring. Save original/prepared video hashes,
all keypoints, full payloads and full diffs. Compare counts, exercise/variant,
per-rep boundaries, scores, faults, top fixes and recommendations. Include
visibility loss and missing detections; a small average keypoint error can
hide a changed rep count. A zero-rep clip cannot establish scored-rep parity.

Until a difference has been reviewed against labels, the gate is no new
missing/extra reps or changed fault decisions on adjudicated cases. Every
numerical deviation remains visible; accepting a tolerance is a measurement
decision for Diego, not something inferred from faster runtime. Do not strip
`n_reps`, `n_candidates` or measurement version from the comparison and then
claim every number was checked. Preserve the sequential path as rollback.

Before a server rollout, record the prior image/config, complete the relevant
tests, and deploy one concrete candidate. If quality or latency fails, restore
that image/config. Validate the actual deployed artifact/config in the trace;
passing planner tests or changing the YAML does not prove a live job used it.

## Evidence and remaining access

`scripts/job_timing.py --fixture tests/fixtures/job_timing_31103ccedfc3.json`
reproduces the existing production baseline without AWS:

| Stage | Seconds |
|---|---:|
| Upload | 69.000 |
| Dispatch to receiving stage | 2.000 |
| Probe through pose backend | 133.817 |
| Pose end through first payload | 20.992 |
| First payload through persisted result | 44.069 |
| Upload completion through persisted result | 202.000 |
| **Upload start through persisted result** | **271.000** |
| Persisted result through advisory vision | 68.000 |

This historical log has whole-second server timestamps. Decimal formatting
cannot recover missing precision. The updated tool preserves fractions and
UTC offsets when supplied, selects the earliest result even if append order
differs, reports submit/download/dispatch, and exposes the nested fusion wait.
The upload recorder now writes milliseconds, and the tool reports deferred
prose separately without moving the first-result timestamp. All 32 timing and
upload-log tests pass. Its `upload end -> result` legacy key still means server
persistence. No phone-render measurement is present in this fixture.

### Local heavy-model feasibility experiment

The first 6 s and 30 s of own clip `VID-20260827-WA0014.mp4` were prepared as
404×720 H.264 at a 4 Mbit/s target. The files contain 174 and 894 frames
respectively; measured durations are 6.000 and 30.000 s. All runs used the
current heavy model, VIDEO mode, every decoded frame, 45-frame overlap and
CPU affinity 0–5 (six distinct physical cores) on a shared Ryzen AI 7 350.
These are single workstation trials; they do not predict Lambda latency.

| Prepared input | Sequential | Forced six chunks, floor 1 | Production floor 240, explicit workers=6 |
|---|---:|---:|---:|
| 6 s | 9.48 s | 7.72 s | one chunk, sequential path |
| 30 s | 47.24 s | 19.13 s | three chunks, 18.28 s |

Six forced chunks did not make the full 30 s case fit even the entire 15 s
budget. Startup/warm-up and resource contention matter; worker count alone is
not a useful speed guarantee. On the 6 s input, automatic exercise selection
changed from `pistol_squat` to `muscle_up`. Shared-visible XY landmark distance
averaged 18.04 px (p95 91.53 px); visibility changes are recorded separately.
The raw 1,553 px maximum is an offscreen, near-zero-confidence landmark and
must not be presented as ordinary visible-pose error.

For 30 s, the exercise stayed `muscle_up` and the six-chunk shared-visible
distance averaged 0.404 px (p95 1.39 px), but classifier/view fields changed.
Every variant counted **zero reps** with null score. Therefore this experiment
establishes a latency miss and tracker sensitivity, not accuracy or scored-rep
equivalence. A positive, labelled rep sequence is required next.

The reviewed manifest does provide one useful negative gate for WA0014:
22.61–25.16 s is standing/walking around the rig and must not be retained as a
rep. The zero-rep outputs satisfy that limited gate. The manifest does not
assert the full clip's true count.

Artifacts: [experiment/config/hashes](../out/round2-latency/experiment.json),
[complete downstream differences](../out/round2-latency/downstream-comparison.json)
and [experiment notes](../out/round2-latency/README.md). The videos, keypoints
and payloads stay in ignored `out/`, not source control. The 30 s exported
file is 14,613,167 bytes; compression is not automatically a byte saving for
an already compressed source. The exporter should avoid unnecessary upscale
or bitrate inflation and record the actual size ratio.

### Faster-model feasibility experiment

The official [MediaPipe model bundles](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/index#models)
include Full and Lite. Both were downloaded only into the experiment directory;
production still selects Heavy. Each candidate's absolute path was pinned in
`BARRA_POSE_MODEL` for the parent and every subprocess, and its exact SHA-256
was saved. No frames were skipped and the prepared video was unchanged.

| Model, same 30 s / 894 frames | Sequential | Six forced chunks | Three chunks, current floor |
|---|---:|---:|---:|
| Heavy | 47.24 s | 19.13 s | 18.28 s |
| Full | 14.42 s | 7.64 s | 6.82 s |
| Lite | 10.30 s | 6.29 s | 5.91 s |

Model/task creation and subprocess startup are included in each pose call;
downloads and video preparation are excluded. The same shared-host/single-run
caveats apply. Three chunks outperformed six in these trials, so the next
deployed experiment must sweep effective chunk count instead of assuming six
cores means six chunks is optimal.

Full sequential versus Heavy sequential had 4.29 px mean shared-visible
landmark displacement (p95 8.55 px); Lite had 5.60 px (p95 12.18 px). More
landmarks became visible under each candidate; this is a change in model
confidence, not proof that either answer is more correct. Every candidate
still counted zero reps with null score on this sample. Classification,
visibility and blocker details changed.

**Current decision: keep Heavy sequential deployed; Full and Lite remain
candidates.** Follow-up comparisons on the two reviewed positive clips show
that every tested model/chunk pair misses at least one automatic class/count
gate. Full+chunks is fast enough locally on these inputs, but does not
preserve automatic class labels; Lite sometimes passes one clip and misses a
rep on the other. First resolve classifier/geometry disagreements and broaden
the labelled movement/fault set, then rerun the winning configurations on
Lambda and finally the phone. Any new model needs its identity/hash in traces
and pose-cache keys, matching assets baked into the image, and a
Heavy/sequential rollback. A cache tagged only `mediapipe` must not silently
mix the variants.

Artifacts: [candidate timing/config/hashes](../out/round2-latency/candidate-models.json)
and [full candidate payload comparisons](../out/round2-latency/candidate-downstream.json).

### Reference labels and gates

`data/evaluation/sample_manifest.json` version `2026-09-08.1` has reviewed
labels for the own clips. WA0020 is one positive gate: 19 push-ups,
reviewed from a contact sheet at medium confidence, with
`push_up.lift_stall` explicitly forbidden. Hip sag is unobservable from its
unknown viewpoint. The manifest gives no frame-by-frame rep boundaries or
positive fault annotations, so it cannot certify those outputs.

The raw WA0020 bytes were used for Heavy sequential versus Full sequential and
Full chunks, isolating model/chunk changes from export changes. Automatic and
declared-exercise outputs are saved. Compare the current Heavy result as a
regression baseline and the reviewed count/forbidden stall as correctness
gates. Historical score 55 is a pipeline output, not a label.
`sessions.csv`/`capture.csv` call this clip a dip; preserve that disagreement
and use the explicitly reviewed manifest for this experiment. The only other
reviewed positive is WA0010 (two muscle-ups, medium confidence by contact
sheet); its phase-scoped support-extension constraint does not assert a
positive fault label.

### Positive-rep comparison: classification is part of the latency problem

Fresh WA0020 runs use the same raw 497-frame video (19.940 s video stream,
20.000 s container), so this comparison adds no export/trim confound:

| Pose configuration | Pose time | Auto exercise / reps | Declared push-up reps |
|---|---:|---|---:|
| Heavy sequential | 20.15 s | muscle-up / 0 | 19 |
| Full sequential | 9.65 s | dip / 19 | 19 |
| Full, workers=6, floor=240 → two chunks | 4.68 s | dip / 19 | 19 |

Remote model calls were disabled. The geometric detector correctly says
`push_up` in every run, but the learned classifier overrides it at fusion:
Heavy votes `muscle_up` with confidence 1.0, Full votes `dip` around 0.995.
Those confidences are not evidence of correctness. This is direct evidence
against simply omitting the vision vote to fit the deadline. Any bounded
classifier proposal needs evaluation of model/geometry disagreements and
backend-dependent calibration, not just an inference timer.

Supplying the reviewed exercise lets all configurations count 19 reps and
avoids the forbidden `push_up.lift_stall`. Full adds
`push_up.incomplete_lockout` fault decisions absent in Heavy. There are no
positive fault labels to adjudicate them, and current session scores are null
for this view. Thus count/no-stall passes the limited label gate; automatic
recognition and the no-changed-fault regression gate do **not** pass. This is
not ready to promote. The current no-vision Heavy result also fails the
reviewed automatic-recognition gate, so it cannot be treated as ground truth.

Artifacts: [pose timings and provenance](../out/round2-latency/positive-reps/pose-runs.json)
and the full `*-measurement.json` payloads and saved pose arrays in
`out/round2-latency/positive-reps/`. Keep the faster Full candidate for further
evaluation; the next design work is a validated bounded exercise decision
and adjudication of changed fault decisions, followed by real Lambda/phone
measurements. No production model/worker default changed in these experiments.

### Second reviewed positive: WA0010 muscle-ups

The only other reviewed positive has 367 frames at 24 fps (15.3 s), 3.34 MB,
and medium-confidence contact-sheet labels of two muscle-ups. All runs use the
same raw clip bytes, CPUs 0–5 on the shared Ryzen AI 7 350 workstation, and
`measure_job` with remote vision disabled. These timings exclude upload and
Lambda startup.

| Pose config | Pose seconds | Auto result | Declared muscle-up reps / score |
|---|---:|---|---:|
| Heavy sequential | 20.55 | pull-up / 2 | 2 / 56 |
| Full sequential | 9.41 | pull-up / 2 | 2 / 56 |
| Full, 6 workers, 60-frame floor (6 chunks) | 6.58 | pull-up / 2 | 2 / 56 |
| Lite sequential | 7.39 | muscle-up / 1 | 1 / 56 |
| Lite, 6 workers, 60-frame floor (6 chunks) | 3.44 | muscle-up / 2 | 2 / 58 |

Lite's chunked run is the fastest and matches this clip's reviewed class/count;
its sequential result misses a rep. Full and Heavy both misclassify this clip
as pull-up. Yet WA0020 makes Lite fail the same gate: the automatic label is
dip, and six chunks reduce its count from 19 to 18 (also when declared
push-up). Full gets 19 declared push-ups there but calls it dip automatically;
Heavy calls it muscle-up with zero reps. Thus no tested model/chunk pair passes
automatic class and count on both reviewed positives. The medium-confidence
labels are useful screening evidence, not enough to calibrate a production
classifier or adjudicate the altered fault/score details.

The current 240-frame production floor would not split WA0010 at all; the
six-chunk Full/Lite rows above deliberately use a 60-frame experimental floor.
The six-chunk WA0020 Lite run took 5.17 s versus 10.11 s sequential, but missed
one push-up. Full SHA-256 is `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`;
Lite SHA-256 is `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a`.
Keep both the model and worker gate closed until a classifier and chunk policy
pass both positives and a broader movement/fault regression set.

Artifacts: raw arrays, complete auto/declared payloads and per-run summaries
are under [`positive-reps/wa0010/`](../out/round2-latency/positive-reps/wa0010/)
and [`positive-reps/vid-20260827-wa0020/`](../out/round2-latency/positive-reps/vid-20260827-wa0020/).
The probe entry point is
[`wa0010_candidate_probe.py`](../out/round2-latency/positive-reps/scripts/wa0010_candidate_probe.py).

### Full-model corpus screen on the manifest set

To broaden the speed/quality screen, Full with the production floor (up to six
workers, 240-frame minimum, 45-frame overlap) was run on all eight root-level
manifest clips, with automatic exercise selection and remote vision disabled.
This is still a workstation screening run, and several manifest labels are
explicitly unreviewed. The positive and negative examples with reviewed labels
already reject the automatic candidate:

| Clip | Reviewed expectation | Full auto result | Pose seconds | Effective chunks |
|---|---|---|---:|---:|
| WA0010 | muscle-up / 2 (medium) | pull-up / 2 | 9.96 | 1 |
| WA0011 | knee raise / count unreviewed | front lever / 0 | 3.48 | 1 |
| WA0012 | muscle-up / count unreviewed | muscle-up / 1 | 5.41 | 1 |
| WA0014 | must reject 22.61–25.16 s walking interval (high) | muscle-up / 1 at 32.09–34.13 s | 13.51 | 5 |
| WA0017 | unknown / 0 (medium) | muscle-up / 2 | 9.04 | 2 |
| WA0018 | expected abstention / 0 (low) | muscle-up / 0 | 5.17 | 1 |
| WA0019 | attempt/swing; no movement label asserted | knee raise / 3 | 4.56 | 1 |
| WA0020 | push-up / 19 (medium) | dip / 19 | 9.07 | 2 |

WA0010 and WA0020 have the right reviewed counts but wrong exercise names;
WA0017 counts reps on a reviewed negative control. The 40-second WA0014 source
also exceeds the 8-second pose allocation despite five effective chunks. The
shorter clips mostly execute sequentially: six configured workers do not
create six workers below the frame floor. These results reject Full as a
production configuration even though its model file hash is shared with the
two-positive comparison. Exact inputs and all outputs are in
[`corpus-full-production.json`](../out/round2-latency/corpus-full-production.json).
The next candidate needs a materially better detector or a corrected training
set, not just a model-size reduction; do not turn on chunks or Full based on
runtime alone.

The app now records phone monotonic timestamps for upload attempt start,
submit completion, first `done` response and first applied result composition.
Records are retained in `round2-timings.json` and completion is copied to the
diagnostics event log; the `Round 2 phone timing` event reports submit, result
and total-to-render durations, plus the result-received-to-render interval.
A timing row also records `countStatus` and the rep count from the rendered
result. `round2_phone_report.py` reports the strict under-15 fraction for all
attempts, a geometry/hold count-status proxy, and a separate explicitly
quality-approved fraction. The proxy does not establish correctness; a row
must also carry `qualityApproved: true` after review to pass the latter.
A separate preparation duration captures source copy and pose sampling; trim
export duration and trim-confirmation-to-render are also recorded when present.
The phone also accumulates monotonic durations for job creation, multipart
session start, presigned-URL requests, part transfer, multipart completion and
submit (including retry delays). The event log exposes these when the result
renders, so a phone run can distinguish a slow uplink from API setup or retry
time. Transfer time is measured per concurrent batch wall-clock, not summed
per part. `scripts/round2_phone_report.py` now summarizes each recorded phase
and estimates effective transfer Mbps from prepared bytes over `singlePut` or
multipart batch-wall time. This makes a future phone cohort useful for deciding
whether to tune request concurrency; it is an effective rate, not a carrier
speed test, and no on-device cohort exists yet.
A boot ID guards subtraction across reboots, the attempt ID survives
process/network resume, and explicit retry gets a new ID.
The store writes off the UI thread and makes no telemetry network request.
An older in-flight work that predates timing instrumentation is marked with an
incomplete origin, so its shortened resume interval cannot pass the 15 s gate.
Multipart URLs are presigned and bytes uploaded in bounded batches of up to
three requests. Each completed part is persisted as it finishes; if a sibling
fails, completed siblings stay saved before the batch pauses, preserving
resume semantics. This only helps files that span
multiple parts: the server returns an 8 MiB part size, so an approximately
6-second 4 Mbit/s trim is one part while a full 30-second 4 Mbit/s clip is
about 15 MB and two parts. The bound and partial-success behavior have unit
coverage, but the speed effect has not been measured on the phone or on a
realistic uplink.
The phone also polls every 250 ms until 15 seconds from attempt start, then
returns to its 1-second cadence. This reduces the result-detection wait inside
the Round 2 window without keeping a high polling rate on long-running jobs;
network RTT and the actual render path still need a device measurement.
Completed timing rows now also include poll count, cumulative `pollGet` wall
time (including dispatch to the IO context), cumulative nonterminal-response
handling time, and cumulative `pollSleep` delay. The phone report gives p50/p95
for poll count and each phase, so the 0.7 s phone-delivery allocation can be
separated into request time, status/store/notification handling, intentional
cadence delay, and result-to-frame time on the next device cohort. This adds
no per-poll disk writes; counters are persisted with the first result. The
render endpoint waits for a frame callback after result composition and takes
the timestamp using the same elapsed-realtime clock as the upload/result
events. This approximates the first app frame; it does not prove physical
display presentation.
This implementation still needs an attached-phone run to verify the callback
and compare real timings against the stage budget. Server wall-clock timestamps
can explain the wait, but must not be subtracted from the phone clock.

The API now records `dispatch-started` and `dispatch-accepted`; the worker
records `worker-entry` before importing `process` and `worker-ready` after.
`job_timing.py` reports invocation request, accepted-to-entry and handler import
intervals separately. The cross-function accepted-to-entry measurement uses
wall clocks and is omitted if clock skew makes it negative; it is diagnostic,
not proof of a pure Lambda queue or cold-start duration. The import interval
uses the worker's monotonic clock for its duration and reports through the same
timestamped event stream. Phone measurements remain authoritative for the
under-15-second acceptance gate. The worker also records monotonic locator
duration, the time the fusion vote waited for it, whether localization had
finished when the first result was persisted, and any post-result wait to
finish it. `job_timing.py` keeps the locator's total runtime separate from its
fusion wait, so a fast parallel locator is not counted twice and a late
advisory trim is not mistaken for first-result latency. These fields are
covered by simulated fast and late locator tests; late fusion is now
nonblocking. No live provider call was made from local personal footage.

Access rechecked on 2026-10-13: `aws sts get-caller-identity` reports no
credentials and `/home/diego/android-sdk/platform-tools/adb devices -l` lists
no devices. Java is installed at `/home/diego/.local/jdk21/bin/java`, even
though it is absent from the default shell PATH. Cloud deployment and the
actual phone gate remain unverified; local design, tests and benchmarks can
proceed.

**Android build verification (2026-10-14):** using the documented JDK path,
`./gradlew testDebugUnitTest` and `./gradlew assembleDebug` both succeed for
the current Round 2 worktree; the full Python suite passes (688 passed, 2
skipped). Rechecking `/home/diego/android-sdk/platform-tools/adb
devices -l` still lists no attached phone, and the SDK has no emulator binary
or AVD. `aws sts get-caller-identity` still reports no credentials. This
verifies compilation and local unit behavior, not a deployed service or a
real upload-to-frame timing sample.

**Multipart range reader and single-PUT A/B candidate (2026-10-14):** a test
with an `InputStream` that advances only part of each `skip()` exposed that the
part body could start at the wrong byte and did not explicitly fail on early
EOF. The reader now advances until the exact part offset, copies exactly the
requested length, and fails on truncation. Tests cover partial skips and EOF. The
8 MiB single-PUT limit is now a debug-build property; release remains 8 MiB.
Built the default 8 MiB debug APK and an otherwise identical 16 MiB candidate
(`-Pbarrapp.singlePutMaxBytes=16777216`). With the measured 14.61 MB WA0014
prepared clip (13.94 MiB), this switches multipart to the direct PUT URL while
keeping the payload bytes unchanged. The candidate could save multipart
control round trips, but loses per-part resume and may retransmit the complete
file after a failure. No phone/network A/B has run; do not raise the release
cutoff based on endpoint-count arithmetic alone. APK artifacts are in
`out/round2-latency/apk/`.

**Source-bitrate export screen (2026-10-13):** the 40.4 s, 478x850 WA0014
source averages 1.63 Mbit/s. Re-encoding its first 30 s at the current 4 Mbit/s
target produced a 14.61 MB file; using a 1.6 Mbit/s target produced 5.86 MB,
about 60% fewer bytes. MediaPipe Full on the two 404x720 encodes had 1.43 px
mean and 3.38 px p95 landmark displacement on points visible in both, with
306 visibility flips and a 285 px maximum outlier. This clip has no adjudicated
reps, so the comparison measures signal drift only; it does not pass a
measurement-quality gate. Source-rate-aware bitrate is a promising upload
experiment, but do not change the exporter default until rep-bearing positive
and negative clips pass the complete measurement comparison and actual phone
export/upload timings confirm the savings.

**Near-source-rate positive check (2026-10-13):** WA0010 was re-encoded at
1.6 Mbit/s (actual file-average about 1.65 Mbit/s; 3.15 MB versus the 3.34 MB
source). Heavy sequential measurement retained two reps and score 56, but the
automatic label changed from `pull_up` to `muscle_up`; the source result was
`pull_up`, score 56. Thus setting the target near the source bitrate does not
avoid the earlier 1 Mbit/s classification instability, even though it largely
avoids up-bitrate bloat. Do not ship a source-bitrate cap as a general fix. The
next useful export experiment must compare complete measured outputs across a
preselected, reviewed positive/negative corpus and can only pass if its
classification and score behavior meet the agreed gate; use measured upload
bytes/time to decide whether the resulting trade is worth keeping.

**Phone acceptance report:** `scripts/round2_phone_report.py` summarizes the
app-private `round2-timings.json` after a test cohort. Pull the file with
`/home/diego/android-sdk/platform-tools/adb exec-out run-as com.fitness.barrapp cat files/round2-timings.json > round2-timings.json`,
then run `python scripts/round2_phone_report.py round2-timings.json --current-boot-id "$(/home/diego/android-sdk/platform-tools/adb shell cat /proc/sys/kernel/random/boot_id)"`.
The strict under-15-second fraction uses every recorded attempt as the
denominator; missing endpoints, partial origins and timings from a different
boot are non-passes. p50/p95 are reported only for complete comparable attempts,
with attempt-to-submit, submit-to-result (including server work, network and
polling) and result-to-render intervals shown separately. The geometry/hold
count-status fraction is only a proxy: it says what the app reported, not
whether that count is correct. The quality-approved fraction requires an
explicit `qualityApproved: true` review annotation on a row and a valid
geometry/hold count. Current app timing rows do not carry this review field,
so they cannot yet establish quality-approved under-target performance.
Collect a quiescent cohort so an in-progress attempt is not mistaken for a
terminal failure. The report is a measurement aid, not device or deployment
evidence; no phone run is available in this environment.

**Cold locator preflight removed (2026-10-13):** the latency-critical
localization request now skips the standalone `/models` preflight, whose client
timeout is 15 s. The completion endpoint remains authoritative: an unsupported
model still returns its explicit 4xx failure, which the client does not retry;
all other LLM callers keep the preflight by default. This removes one serial
network round trip from cold auto-classification without changing the prompt,
model, or success-path response. Mocked tests verify the locator opts out and
ordinary calls retain the model-list guard. The amount saved on a deployed
worker and the model's live latency remain unmeasured.

**Worker-image CPU screen (2026-10-13):** built `server/Dockerfile` locally as
`barrapp-worker:round2-local` (image ID
`sha256:21ad9c63787a0565ae7da9c32cae694c0cdc81ed66162380bc3d7a918762caf4`,
3.32 GB), without pushing or deploying. Ran the actual MediaPipe backend in a
container limited to six CPUs and 10 GiB, `BARRA_POSE_WORKERS=6`, on the
prepared 894-frame, 29.8 fps WA0014 clip. Heavy took 17.779 s with the
production planner's three chunks, so it misses the 8 s pose allocation. The
timer starts after container launch and parent imports; it includes chunk
subprocess startup, per-process model initialization, decode and inference, but
not container cold start or Lambda dispatch.

The Full candidate model (SHA-256
`4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`), mounted
for the screen but not present in the production image, took 6.695 s on that
WA0014 pose-only run. On reviewed WA0020 (598 frames), Full plus the local
measurement path took 6.765 s in `auto` and returned `dip`, 19 reps and an
unmeasured session score; the reviewed movement is push-up / 19. Supplying an
oracle `push_up` vision vote locally changed the label to push-up, kept 19 reps,
but the score remained unmeasured (6.531 s). No remote vision request was made.
Thus Full demonstrates that this worker image can run a candidate within the
pose allocation, but it fails the automatic-classification/score quality gate;
Heavy remains too slow. These timings exclude Lambda cold start, upload,
localization network time, persistence and phone rendering. They do not justify
a model switch or a claim that Round 2 passes.

**Current worker-image Heavy repeat (2026-10-14):** I reran the production
MediaPipe backend on the prepared 894-frame, 29.8 fps WA0014 first-30-second
clip in the current headless worker image (`sha256:7c6a3876f64e`, 1.79 GB),
with `--cpus=6`, 10 GiB memory and `BARRA_POSE_WORKERS=6`. Two fresh-container
runs took 15.490 s and 15.596 s (median 15.543 s); both returned all 894 pose
rows. The production chunk planner still creates three chunks at this length.
This includes `estimate()` setup, chunk process startup, per-process model
initialization, decode and inference, but excludes Docker/Lambda cold start,
parent imports, upload, measurement, persistence and phone delivery. It
confirms the Heavy worker path misses the 8 s pose allocation by about 1.9x,
even before the rest of the end-to-end budget. The image-size reduction is a
deployment improvement, not a pose-speed improvement. The run was local on a
16-logical-CPU host with a six-CPU container quota, without CPU pinning; it is
not Lambda timing or quality-gate evidence.

**YOLO worker-image packaging screen (2026-10-13):** the local worker image
can import CPU-only PyTorch 2.14.0, torchvision 0.29.0 and Ultralytics 8.4.166
while retaining the worker's NumPy 1.26.4, OpenCV-Contrib 4.10.0 and MediaPipe
0.10.21. The experimental overlay image is 4.79 GB, 1.47 GB larger than the
3.32 GB MediaPipe worker image. Under the same six-CPU/10-GiB Docker limit,
the existing half-rate YOLO11n `imgsz=480`, six-process screen took 0.727 s to
decode and 27.837 s for inference (28.563 s total) on the prepared WA0014
30-second clip. It misses the pose budget in this CPU-only image, despite the
7.16 s workstation result. The timer excludes container and parent-import
startup but includes six subprocess starts, per-process model loading and
inference. This is a packaging/performance screen only: the production worker
still has no Ultralytics backend or weight file, and this candidate did not
run the measurement path in the container. Do not add the dependency or deploy
this image; the current optional model path needs a CPU-efficiency or runtime
backend improvement before it can meet the budget here.

**Batched single-process YOLO candidate (2026-10-13):** replacing six
independent PyTorch processes with one CPU-only YOLO11n instance and bounded
batches removes repeated model loading and materially improves the worker
container screen. At batch 32 on the prepared 894-frame clip, a warmed run took
7.204 s total (0.583 s decode, 0.021 s model load, 6.600 s inference); a fresh
container run took 7.997 s. At batch 64, a fresh run took 7.799 s (0.566 s
decode, 0.020 s model load, 7.213 s inference). Timer excludes container
startup and Python imports. On WA0020, batch 32 took 4.596 s for its 249 sampled
frames, including decode and model load; 19 reps and score 56 remained with an
oracle `push_up` vote. The automatic class still needs the vision vote to
finish in parallel within the pose window.

Batch 32/64 keypoints were numerically identical to each other. Against the
previous six-process YOLO result on WA0020, shared-visible landmark drift was
2.55 px mean / 8.09 px p95, with 35 visibility flips and a 97.78 px maximum.
The downstream declared push-up result retained 19 reps and score 56, but now
adds a `lockout` fault where the previous candidate had no faults. This fails
measurement parity. On WA0014, mean drift against the prior YOLO candidate was
0.46 px / 1.43 px p95, but that clip has no reviewed rep labels. Thus batching
solves the worker-image throughput shortfall for this screen; it does not make
the half-rate candidate quality-approved or demonstrate a full upload-to-phone
pass. The batch benchmark and arrays are under
[`docker-results/`](../out/round2-latency/ultralytics-screen/docker-results/);
source scripts are in the ignored experiment directory.

**Batch-64 reviewed-control extension (2026-10-13):** the one-process CPU
candidate was run on the existing reviewed controls, with half-rate inference
and `imgsz=480`. The six-CPU container timings (decode + model load + inference;
container/Python imports excluded) and local geometry/model outcomes were:

| Clip | Frames sampled | Pose s | Auto result without remote vision | Declared/oracle measurement |
|---|---:|---:|---|---|
| WA0010, reviewed muscle-up / 2 | 184 | 3.39 | muscle-up / 2, score 50 | score 50; bent arms, control, lockout, momentum, stall |
| WA0017, reviewed negative / 0 | 347 | 6.21 | back lever / 0 | negative count retained; class unreviewed by model |
| WA0018, expected abstention / 0 (low) | 140 | 2.86 | muscle-up / 0 | no rep invented |
| WA0020, reviewed push-up / 19 | 249 | 3.99 | deadlift / 0 | oracle push-up: 19 / score 56, plus lockout fault |

WA0010's reference score is 51 with no faults; WA0020's prior half-rate
six-process declared path had 19 / 56 with no faults. This single-process
candidate therefore misses score/fault parity on both reviewed positives, and
its unassisted auto label/count fails WA0020. It preserves zero reps on the two
negative/abstention controls. The 30-second WA0014 speed result is 7.80 s but
has no reviewed rep labels. The candidate is fast enough for the pose stage on
these inputs; no reviewed clip set passes the current output gate, and the
remote vision call's arrival time remains unmeasured.

**Baseline-stream single-model replay (2026-10-13):** the lockout regression
above came from the experimental `stream=False` call with explicit batches.
Using one loaded CPU YOLO11n model, six sequential chunks, and the baseline
`model.predict(..., stream=True)` call preserves the reviewed behavior. On
WA0020, landmarks were bit-for-bit equal to the saved six-process array and
measurement matched: auto remained deadlift / 0; declared push-up remained
19 reps / score 56 / no faults. On WA0010, WA0017 and WA0018, rep counts and
fault sets also matched their saved six-process outputs; classifier fusion
confidence shifted by at most 0.04 on the two zero-rep controls. WA0010's
saved output itself remains score 50 with lockout/control/stall/bent-arms
faults, so this is parity with that run, not parity with its separate human
reference of score 51 and no faults. On the prepared 30-second WA0014 clip,
decode plus inference took 7.64 s (0.585 s decode, 7.053 s inference) in the
six-CPU worker container. Its two reps, detected class, score and fault set
were identical to the saved six-process measurement; landmarks differed by
1.67 px mean / 6.40 px p95, with 17 visibility flips and a 669.56 px maximum.
Model load, container startup and Python imports were excluded from all of
these single-model timings.

These results make one-model streaming a viable performance candidate for
continued comparison; they do not approve it for production. A fresh six-
process WA0020 replay reproduced the saved array exactly but took 22.00 s in
this container run, versus the earlier 5.68 s report, so this timing comparison
is unstable. The one-model WA0010, WA0017 and WA0018 arrays were not bitwise
equal, despite preserving the listed measured outputs. Next gates are repeated
timing distributions (including model/container cold start), full payload
comparisons across the reviewed corpus, and a complete upload-to-render phone
cohort. No AWS deployment or phone timing is available yet.

Three additional capped-WA0014 worker-container trials took 7.36, 7.83 and
8.02 s for decode plus inference (median 7.83 s); all three output arrays were
bit-for-bit identical. This repeatability is encouraging for the 8 s pose
target, but measurements exclude worker/model initialization and Lambda cold
start, and do not include upload, vision classification, report generation or
phone rendering. The evidence supports further deployment-shaped testing, not
an end-to-end under-15-second claim.

**Six-worker thread-cap retest (2026-10-13):** the 22–27 s six-process
container results above were oversubscribed. The container exposes 16 CPUs via
`os.cpu_count()` despite its six-CPU quota; Ultralytics derives
`NUM_THREADS=min(8, os.cpu_count()-1)` and `select_device("cpu")` resets
PyTorch to eight threads in every worker, overriding `OMP_NUM_THREADS=1`.
Pinning Ultralytics' `torch_utils.NUM_THREADS` to one per worker before
inference brought the capped 30-second WA0014 six-worker run to 6.81 s
(0.70 s decode plus 6.11 s inference). An equivalent per-worker CPU-count
cap measured 6.72 s. On WA0020, the thread-capped six-worker run took 4.95 s
(0.29 s decode plus 4.66 s inference). These are in the requested 6–10 s
pose window and use six independent chunks across a six-CPU container.

The capped six-worker WA0014 landmarks match the earlier single-model replay
within 0.0002 px maximum; the two runs preserve the same measured class, two
reps, score and faults. On WA0020, the capped run retains auto deadlift / 0
and declared push-up 19 / 56 / no faults, matching the saved run's measured
outputs. The WA0020 keypoints still differ from its saved six-worker array
(3.22 px mean / 10.07 px p95), so numerical parity is not established there.
The thread cap depends on the pinned Ultralytics internal constant
`torch_utils.NUM_THREADS`. The opt-in path has now been wired into
`UltralyticsBackend` and synced to `server/vendor/barra`, with controls
`BARRA_POSE_WORKERS`, `BARRA_YOLO_POSE_STRIDE`, `BARRA_YOLO_POSE_IMGSZ`, and
`BARRA_POSE_CPU_THREADS`. This is version-sensitive and has not been added to
the deployed worker image, which still lacks Ultralytics and its weights.
Before adoption, pin and test the Ultralytics version, check full output parity
across all reviewed controls, and measure initialization, cold start and the
complete phone path. The 4.79 GB overlay image and absent phone/AWS timings
remain deployment constraints.

Two more six-worker thread-capped WA0014 repeats took 6.80 and 6.68 s; all
three module-constant-capped runs (6.81, 6.80, 6.68 s) produced bit-for-bit
identical landmark arrays. These three timings include frame decode, six
subprocess/model startups and inference, but exclude the container startup and
parent Python imports. Their median is 6.80 s, within the 8 s pose allocation
with about 1.2 s of measured headroom; Lambda cold-start and startup variance
remain unmeasured.

**Opt-in backend integration check (2026-10-13):** the code path in
`UltralyticsBackend` was run inside the CPU-only YOLO worker overlay, with the
current `barra/` mounted into the image, six subprocess chunks, stride 2,
`imgsz=480`, and one PyTorch thread per worker. The API worker's local
`analyze_clip` path completed the prepared 30 s WA0014 clip in 8.52 s
including measurement, returning 2 muscle-ups and the same fault set as the
saved candidate; its score was null. WA0020 completed in 6.73 s including
measurement, returning declared push-up / 19 / score 56 / no faults. These
timings include child-process and model initialization but exclude the
container start. Unit tests cover balanced partitioning, empty and short
inputs, interpolation, configuration and the backend's sampled-frame path;
the full suite passes (658 passed, 2 skipped). This verifies the opt-in code
against a local overlay image, not the deployed Lambda image, remote vision
arrival, upload or phone rendering. No server deployment or model-quality
approval follows from this integration run.

A follow-up WA0020 run mounted `server/vendor/barra/barra` at the worker's
actual `/opt/barra/barra` import location (rather than the source tree) and
returned the same declared push-up / 19 / 56 / no-fault result in 6.86 s.
This confirms the vendored modules execute in the local worker overlay; that
image still supplies Ultralytics and the weights as temporary overlays, so
the shipped worker image remains unchanged.

The vendored backend was then run through the current `server/process.py` on
the other reviewed controls. WA0010 took 6.43 s with the declared muscle-up
label and returned 2 reps, score 50, and lockout/control/stall/bent-arms faults;
the human reference is score 51 with no faults. WA0017 took 5.82 s and retained
0 reps (auto label back lever); WA0018 took 5.11 s and retained 0 reps (auto
label muscle-up). The local run had localization disabled, so it does not
measure the automatic remote-vote path. These results confirm the prior
quality finding rather than clearing it: WA0010 remains a material mismatch,
while the two zero-rep controls did not gain false reps.

**640 px full-duration resolution screen (2026-10-13):** to test whether the
480 px input setting is the main source of the reviewed-output drift, I ran
the same prepared 29.8 s WA0014 clip with the vendored opt-in backend, stride 2,
six worker processes, one CPU thread per process, and `imgsz=640`. On the
workstation, pose took 13.425 s and local measurement another 0.629 s; the
result was `muscle_up`, zero reps, and `countStatus=unmeasured`. This is 6.6 s
slower for pose than the earlier 480 px workstation screen (7.16 s), and it
still does not produce a reviewed measurement on WA0014. The 640 px setting
therefore misses the 8 s pose allocation locally without resolving the quality
question. This was not run in the worker container and is not an end-to-end
timing or a production recommendation.

**Continuous MediaPipe Full screen (2026-10-13):** to test whether changing
only the model, while retaining a single uninterrupted VIDEO tracker, avoids
the chunk-boundary quality risk, I ran the same prepared 29.8 s WA0014 clip
sequentially with `pose_landmarker_full.task` (`BARRA_POSE_WORKERS=1`). The
estimate took 16.433 s including model initialization and decoding; local
measurement took another 0.528 s and returned the same auto label, zero reps,
and `countStatus=unmeasured`. This preserves a continuous tracker but is over
twice the 8 s pose allocation and does not establish useful measurement on
this clip. It rules out this Full-model sequential configuration as the
Round 2 latency path on this workstation; chunking or a faster backend would
still be required, with quality separately validated.

**Budget implication from the integrated 480 px screen:** its 8.52 s local
`analyze_clip` wall time already includes measurement, so it should replace the
separate 8.0 s pose + 0.5 s measure allocations for this projection. Keeping
the other allocations (1.0 s dispatch, 0.3 s persistence, 0.7 s phone render,
1.0 s reserve) leaves a strict upload ceiling below 3.48 s:

| Upload assumption | Projected upload-to-render total | Margin to 15 s |
|---:|---:|---:|
| 3.0 s | 14.52 s | 0.48 s |
| 4.0 s | 15.52 s | -0.52 s |
| 5.0 s | 16.52 s | -1.52 s |

This is a budget projection, not a measured phone run: the 8.52 s stage came
from a local worker-image integration screen, while upload, persistence,
render and cold-start allocations remain assumptions. It shows that the
original 2–5 s upload range is not wholly compatible with this candidate; the
candidate needs an observed upload below 3.48 s or a faster analysis path even
before its quality gate can be considered.

**MediaPipe Lite continuous-vs-chunked screen (2026-10-13):** Lite offers a
second quality/latency trade-off without switching to YOLO. On the prepared
29.8 s WA0014 clip, continuous sequential VIDEO pose took 12.338 s; the
six-worker path (three production-sized chunks) took 7.763 s. Both produced
the same local auto outcome—muscle-up, zero reps, `unmeasured`—on a clip without
a reviewed rep label, so the faster result cannot be treated as a measured
success. On reviewed WA0020, sequential Lite took 5.385 s and the six-worker
path took 4.223 s in the first run (a later chunked repeat took 8.354 s,
showing substantial timing variance on this shared workstation). Both retained
19 geometric reps but auto-labeled the reviewed push-ups as dips and returned
no score. Declaring `push_up` still returned 19 reps with a null score and
lockout faults. Sequential Lite counted 10 lockout, 15 too-deep and 15 bounce
faults; chunked Lite counted 11, 16 and 15 respectively. The reviewed labels
available for WA0020 specify push-up / 19; they do not supply score or fault
labels. The earlier YOLO11n half-rate oracle-label run produced score 56 / no
faults, but that is a candidate output, not independent human ground truth.
Lite estimates the view as frontal and not knowable, and explicitly withholds
the score because the torso ruler cannot be measured; that abstention should
not itself be treated as a quality regression. The auto-label mismatch and
chunk-sensitive fault output still fail the candidate/parity gate, but the
fault counts require human adjudication before calling them false positives.
Lite reaches the pose budget on one full-duration workstation run; it is not
a rollout candidate without reviewed output and view labels.

**MediaPipe Lite in the current worker image (2026-10-14):** I mounted Lite
(`pose_landmarker_lite.task`, SHA-256
`59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a`) into
the current 1.79 GB headless worker image, limited each run to six CPUs and
used the production VIDEO/chunk planner. The prepared 29.8 s WA0014 clip took
5.035 s for pose plus 0.424 s for measurement; it returned muscle-up / 0 with
`countStatus=unmeasured`, failing the reviewed measured-zero gate. WA0020 took
3.999 s plus 0.108 s and retained 19 reps, but auto-labeled reviewed push-ups
as dips. WA0010 took 4.279 s plus 0.065 s and returned the reviewed muscle-up
/ 2. The strict gate passed WA0010 and failed WA0014 and WA0020. These runs
show that Lite fits the pose allocation in the worker image, but does not yet
produce a quality-approved measured result across the reviewed clips; keep it
out of production. Full payloads and pose hashes are in
`out/round2-latency/mediapipe-lite-worker/`. Timings exclude container/Lambda
startup, upload and phone delivery; the worker image was locally CPU-limited,
not an AWS Lambda measurement.

The detailed Lite trace separates the negative result from a tracking
dropout: observed fraction was 0.756 over the clip and 0.889 within active
frames, with each active span at or above 0.770. The stationary 13.15–22.28 s
span measured 0.074 torso lengths against the 0.15 still floor; the only
turnaround at 22.92 s was observed and rejected for 1.717 torso lengths of
hand travel. This supports an experiment for a typed measured-zero outcome,
but one reviewed negative does not validate it against missed shallow reps.
Detailed trace, keypoints and candidate payloads are retained under
`out/round2-latency/mediapipe-lite-worker/`.

**Lite six-chunk floor A/B (2026-10-14):** the production planner uses three
chunks for the 894-frame sample (`MIN_CHUNK=240`). I forced six equal ranges
(149 frames each, 45-frame warm-up) in the same six-CPU worker image, without
changing the backend or model. The two six-chunk pose runs took 5.344 and
5.503 s (median 5.424 s), compared with 5.035 s for the matched three-chunk
trace run: about 8% slower. Both chunk plans returned muscle-up / zero /
`unmeasured`. Shared-visible keypoints differed (three chunks versus six):
mean 1.17 px, p95 2.96 px, with 260 landmark confidence-threshold crossings
and a 188.88 px maximum outlier. This is one clip and not a general timing
benchmark, but it gives no evidence that forcing all six workers helps Lite;
it adds chunk-boundary drift while leaving the count failure unchanged. Keep
the production floor for now; test any new floor across clips and downstream
measurements before changing it. The candidate six-chunk keypoints are
`out/round2-latency/mediapipe-lite-worker/WA0014-first30-lite-sixchunks.npy`.

**Worker image build-layer reduction (2026-10-13):** the final image only
installs binary wheels (`pip --only-binary=:all:`), yet its system package
layer also installed GCC, G++, Make and Python headers. Removing those
build-only packages while retaining the OpenCV/MediaPipe runtime libraries
reduced the matched local worker image from 3,318,809,327 bytes to
2,739,483,115 bytes (579,326,212 bytes / 17.46%). Docker history reports the
system-package layer falling from 718 MB to 290 MB. The baseline was rebuilt
from the committed Dockerfile against the same current source/vendor context;
the candidate used the edited Dockerfile.

Both images passed a fresh-container smoke that imported `handler`, OpenCV and
MediaPipe and constructed a Heavy `PoseLandmarker` from the bundled model.
Across four fresh local containers per image, worker import plus landmarker
construction had a median of 1.445 s on the baseline and 1.388 s on the
candidate. Image layers were already cached on the host, so the 57 ms change
does not measure image download or Lambda cold start; it is within the noise
expected from this small local sample. The size reduction is concrete, while
its effect on Lambda cold starts and upload-to-phone latency remains
unmeasured. The Dockerfile contract test now guards against reintroducing
build tools while the install remains wheel-only. This image has not been
pushed or deployed.

**MediaPipe pose-dependency trim (2026-10-13):** MediaPipe 0.10.21 declares
JAX/JAXLib, audio capture and SentencePiece dependencies at package level, but
the worker only calls `PoseLandmarker` in VIDEO mode. Source references to JAX
and SentencePiece are in GenAI modules; `sounddevice` is in audio capture.
`matplotlib` does load through MediaPipe's package initialization, so it stays
explicitly installed, along with the pinned `absl-py`, `attrs`, `flatbuffers`
and `protobuf` runtime packages. The pinned MediaPipe wheel now installs with
`--no-deps` after that explicit runtime set. This is a deliberate restriction
to the worker's image/video pose path; adding another MediaPipe task requires
reviewing its imports and dependencies first.

Against the matched committed-Dockerfile baseline above, the pose-dependency
image is 2,236,707,838 bytes: a total reduction of 1,082,101,489 bytes
(32.61%). Its pip layer is 778 MB, down from 1.18 GB in the full-dependency
image. The candidate and baseline both imported `handler`, created a Heavy
PoseLandmarker and ran the prepared six-second WA0014 clip through
`analyze_clip`. Both returned 174 frames, muscle-up / zero reps /
`unmeasured`; their `(174, 17, 3)` keypoint arrays were bitwise identical
(SHA-256 `58da2661f84b25913eb154dbd736fad5cbffbee69a3f841980521f8b015d0810`).
Four fresh cached-layer containers per image had a median worker import plus
landmarker-init time of 1.459 s for the full-dependency baseline and 1.457 s
for the trimmed candidate. The timing difference is negligible; the useful
evidence is the smaller image and unchanged pose output. This still does not
measure ECR transfer, Lambda cold start, deployment, or upload-to-phone time.
The worker import and pose tests pass locally; no AWS deployment was made.

**Headless OpenCV and graphics-layer removal (2026-10-13):** the worker uses
OpenCV for video capture, frame seeking, resize, color conversion, JPEG writes
and video artifacts; it does not open GUI windows or use contrib-only APIs.
Replacing `opencv-contrib-python` with the ABI-matched
`opencv-python-headless` wheel let the Dockerfile drop its Mesa, X11, EGL,
fontconfig and libgomp package layer entirely. The image is now
1,793,052,722 bytes, 443,655,116 bytes (19.84%) smaller than the prior
pose-dependency image and 1,525,756,605 bytes (45.97%) smaller than the
matched original worker image.

The candidate passed worker/OpenCV/MediaPipe imports, a MediaPipe Heavy
PoseLandmarker run and `analyze_clip` on the same prepared six-second WA0014
H.264 clip used for the previous image. Both OpenCV builds returned 174 frames,
the same muscle-up / zero / `unmeasured` local result, and bitwise-identical
`(174, 17, 3)` keypoints (SHA-256
`58da2661f84b25913eb154dbd736fad5cbffbee69a3f841980521f8b015d0810`). An
additional container check encoded and decoded an MP4 with `VideoWriter` and
rendered a Matplotlib Agg plot without the graphics libraries. This checks the
tested H.264 and writer paths, not every input codec or a deployed Lambda cold
start. The candidate also built with the same single-image Docker v2 export
shape and Lambda entrypoint used by `server/deploy.sh`; a fresh container
successfully imported `handler`, OpenCV 4.10.0 and MediaPipe 0.10.21. This is
local packaging evidence only: the container remains undeployed.

**Trim-to-upload byte accounting review (2026-10-13):** the current app records
trim-export duration, output bitrate, multipart phase durations and the
selected upload file's byte count in its work log. It does not preserve the
original byte count beside the prepared byte count in the Round 2 timing row,
so the phone report cannot compare source and output sizes across attempts.
`Media3ClipExporter` requests 4 Mbit/s; a low-bitrate source can therefore
produce a trimmed file larger than the original. The code currently uploads
any non-empty exported file, without comparing its size to the source.

Do not make “output is smaller” the sole selection rule: a larger six-second
trim can still reduce total time versus uploading and posing the full
30-second source. The next phone experiment should retain source bytes,
prepared bytes and trim duration with each attempt, then compare upload time,
server pose time and measured-count parity for the original and trimmed forms.
No device timing or size cohort is available yet, so the speed or quality
effect of the current fixed bitrate is unknown.

**Phone byte instrumentation added (2026-10-13):** each timing row now stores
the source and exact prepared/upload file sizes. The source size is recorded
before export and retained across a resumed upload; the prepared size is
recorded before the first network request. `scripts/round2_phone_report.py`
reports the number of comparable attempts, median source/prepared bytes, and
how many prepared files grew. The report tests pass and Android unit tests pass
with the persistence/resume coverage. This makes the next phone comparison
actionable; it does not supply a size or latency cohort in the absence of a
connected device.

**Full-rate YOLO resolution screen (2026-10-13):** to avoid the output
interpolation and frame loss of the half-rate candidate, the six-worker CPU
backend was run on every source frame (`stride=1`) at 480, 384 and 320 px.
Each measurement used six pinned CPUs, one PyTorch thread per worker, and
included decode, model load, inference and local analysis. WA0010's reviewed
reference is muscle-up / 2 / score 51 / no faults; WA0020's available reviewed
label is push-up / 19, with no independent score or fault labels.

| Size / confidence | WA0010: seconds, reps, score | WA0020: seconds, reps, score | WA0014 29.8 s: seconds, reps, score/status |
|---|---:|---:|---:|
| 480 / .25 | 10.88, 2, 51 | 13.44, 19, 56 | 15.32, 2, null / geometry |
| 384 / .25 | 8.99, 2, 57 | 8.66, 13, 56 | 16.53, 0, null / unmeasured |
| 320 / .25 | 12.53, 1, 64 | 7.42, 19, 56 | 9.87, 1, 41 |
| 320 / .10 | 9.85, 1, 64 | 7.37, 19, 56 | 9.89, 2, 42 |

Lowering detector confidence to .10 did not recover WA0010's missing second
rep. The 320 px full-rate WA0014 result fits the local pose-stage range, but
there is no reviewed label for that clip and it is not a measured parity pass.
The 384 px 30-second run exceeds the pose allocation; 480 px exceeds both the
pose allocation and the whole 15-second goal. At 384 px the reviewed WA0020
count drops by six; at 320 px WA0010's count and score are wrong. This screen
does not identify a production setting. The code now exposes
`BARRA_YOLO_POSE_CONF` for controlled local experiments, defaulting to
Ultralytics' existing .25 threshold; it has not been added to the worker image
or deployed.

The first 384 px WA0014 run was stopped after it stalled in the zero-rep
fallback. A local provider key was available to that process, so its stills
may have been sent to the configured vision service; no result from that run
is used as evidence. The 384 px timing above is the subsequent no-credential
run. All later experiment commands explicitly removed provider credentials.

**Low-resolution coordinate-noise follow-up (2026-10-13):** direct full-rate
320-versus-480 inference arrays on WA0010 show both wrists above the detector's
.25 confidence threshold in every frame of the missed second-rep interval.
The median wrist confidence is .77 at 320 px and .91 at 480 px, but the mean
per-frame wrist displacement is 9.74 px versus 4.77 px and p95 displacement
is 25.53 px versus 11.02 px. Mean absolute XY drift across all keypoints is
8.18 px. This supports coordinate jitter, rather than detector abstention, as
the reason lowering `BARRA_YOLO_POSE_CONF` did not fix WA0010.

Offline filters were applied to the saved 320 px arrays and passed through
`analyze_clip` without another model call. Median smoothing of only the wrists
over seven frames recovered two reps, but the score remained 63 versus the
reviewed 51. Whole-skeleton median windows from 7 to 13 frames also recovered
the count but produced scores from 62 down to 59; none matched the reference.
The smoother changes the measured signal and still fails the known score gate,
so it is rejected as a Round 2 fix. Arrays and measurements are in
`out/round2-latency/fullrate-size-screen/`; no filter was added to production.

**MediaPipe CPU-thread control screen (2026-10-13):** the installed Tasks
Python API's `BaseOptions` exposes only model path/buffer and delegate, and
`PoseLandmarkerOptions` has no CPU thread-count field. To test whether TFLite
honors ambient thread variables anyway, the sequential Heavy backend posed the
same 497-frame WA0020 clip pinned to six CPUs with
`OMP_NUM_THREADS`, `TF_NUM_INTRAOP_THREADS`, and
`TF_NUM_INTEROP_THREADS=1`, then with intra-op/OMP set to 6. End-to-end pose
times were 28.337 s and 28.120 s. The arrays were bitwise identical (SHA-256
`9809e9ac53c961f8f71a491da79f0102e7a057120b0abbcf96741d60329747cc`). This
single-run screen shows no material speedup or output change; it does not
replace Lambda measurements. Merely raising common thread environment values
is not a route to the six-core budget for this backend.

**Full-rate YOLO intermediate-size screen (2026-10-14):** to check whether an
image size between 384 and 480 px could keep the 30-second candidate inside
the pose allocation, I ran six-worker, stride-1 YOLO11n inference at 416 and
448 px on WA0010, WA0020 and the prepared 29.8-second WA0014 clip. Provider
credentials were removed. The reviewed labels available here are WA0010
muscle-up / 2 / score 51 / no faults and WA0020 push-up / 19 (no independent
score/fault labels).

| Size | WA0010: pose s, reps, score/faults | WA0020: pose s, reps, score/faults | WA0014 29.8 s: pose s, reps, score/status |
|---|---|---|---|
| 416 | 12.56, 2, 60; stall + bent arms | 11.17, 18, 56; no faults | 17.67, 2, null / geometry |
| 448 | 10.96, 2, 53; momentum + stall + bent arms | not captured, 16, 56; lockout | 15.85, 1, null / geometry |

The 416 and 448 WA0010 results both disagree with its reviewed score and fault
labels. Both WA0020 intermediate sizes undercount the reviewed 19 reps. At
448 px the long clip still exceeds the 8-second pose allocation and the whole
15-second target; its result also changes from two reps at 480 px to one.
This rejects the intermediate sizes without suggesting that a lower size is a
safe compromise. The workstation was under substantial concurrent desktop and
agent CPU load, so these single-run times are diagnostic only; the count and
score differences are output-quality evidence, not a timing distribution.
Raw summaries and measurement payloads are in
`out/round2-latency/resolution-followup/`.

**FP32 ONNX Runtime CPU screen (2026-10-14):** I exported the same YOLO11n-pose
checkpoint as a fixed-480, dynamic-batch FP32 ONNX graph (SHA-256 recorded in
`out/round2-latency/resolution-followup/onnx-screen.json`) and ran it through
the existing six-worker inference and measurement path on six pinned CPUs.
The first fixed-batch export was incompatible with the runner, which submits
one chunk as a batch; the dynamic-batch export ran successfully. End-to-end
pose/decode times were 13.05 s for WA0010, 15.88 s for WA0020 and 24.95 s for
the 29.8-second WA0014 clip. The reviewed counts stayed 2 and 19 on WA0010 and
WA0020, with scores 51 and 56 respectively, but WA0010 still emitted
lockout/control/stall/bent-arm faults against the reviewed no-fault label.
This local runtime was slower than the earlier PyTorch CPU 480 px screen
(10.88 s, 13.44 s and 15.32 s), under substantial concurrent desktop/agent
load; it does not meet the pose budget and is rejected as the next backend
candidate. No production dependency or pose backend was changed. This is a
workstation comparison, not Lambda evidence.

A PyTorch CPU control on the same pinned six CPUs immediately afterward posed
WA0014 in 17.12 s and returned the same two-rep, unscored geometry result.
Thus the dynamic ONNX run was about 46% slower than its same-session PyTorch
control, even with the noisy workstation load held broadly constant. The
PyTorch control itself missed the pose budget, so this does not establish a
passing backend.

Repeating ONNX with one ONNX Runtime intra-op and inter-op thread per worker
reduced its WA0014 time to 17.59 s, and the keypoint array was bit-for-bit
identical to the dynamic ONNX run. This removes the large oversubscription
penalty but is still marginally slower than the paired PyTorch control and
over twice the 8-second pose allocation. Do not add ONNX Runtime to the worker
image on this evidence.

**Reviewed-window trim screen (2026-10-14):** I cropped WA0010 from 2.4 to
14.8 s, covering both reviewed rep intervals with lead-in, and prepared it at
404×720 H.264 using the app's requested 4 Mbit/s rate. The 12.42 s output has
298 frames, but is 6.33 MB versus the 15.31 s source's 3.34 MB. The fixed
4 Mbit/s request nearly doubled upload bytes on this low-bitrate source.

| Backend and mode | Pose s | Result on the prepared crop | Compared with full-source Heavy |
|---|---:|---|---|
| Heavy sequential | 17.75 | 2 reps / score 56 / lockout, control, stall | Same count, score and fault counts |
| Heavy, 4 chunks, 45-frame overlap | 12.26 | 2 / 56 / same faults | Same measured count, score and fault counts |
| Heavy, 6 chunks, 45-frame overlap | 13.15 | 2 / 56 / same faults | Same measured count, score and fault counts |
| Full sequential | 4.35 | 2 / 56 / lockout, stall | Omits the control fault |
| Lite sequential | 3.36 | 1 / 56 / lockout, control, bent arms | Misses one reviewed rep |

The four- and six-chunk Heavy outputs preserve the full-source Heavy count,
score and fault counts despite landmark drift (mean absolute COCO landmark
delta 0.232 and 0.275 px respectively); six chunks are slower than four here.
This is parity with the current Heavy pipeline, not human-ground-truth parity:
the reviewed WA0010 reference is score 51 with no faults. Heavy also remains
above the 8-second pose allocation after trimming; Full is fast but changes
faults, and Lite loses a rep. Crop-relative rep timestamps start at zero, so
the phone must use the same prepared clip for replay or explicitly retain the
trim offset. No trim/model combination passes both gates. Inputs and per-run
payloads are in `out/round2-latency/trim-pairing/`.

I also encoded the same crop at 1.6 Mbit/s, close to WA0010's source rate. It
fell from 6.33 MB to 2.55 MB (about 60% fewer bytes than the 4 Mbit/s output,
and 24% fewer than the full source), but Heavy returned 2 / score 58 with
lockout and stall, versus 2 / 56 with lockout, control and stall at 4 Mbit/s.
The lower-rate encode therefore improves upload size while changing measured
values. This crop-specific screen does not justify changing the app's export
rate; the source-rate choice still needs a reviewed quality gate across clips.

**H.264 stream-copy trim screen (2026-10-14):** the WA0010 source has IDR
keyframes only at 0.00 and 12.50 s. Asking FFmpeg to stream-copy the reviewed
2.4–14.8 s window with a 12.4 s duration kept the source's exact first decoded
frame and produced a 14.83 s, 2.996 MB file. This is only 10% smaller than the
15.31 s, 3.338 MB source: the muxer could not discard the non-keyframe start
and still decode the requested middle section. It preserves pixels but saves
almost no pose time or upload bytes. Accurate arbitrary trimming of this GOP
requires re-encoding (and therefore a quality gate), or changing capture to
emit more frequent keyframes and evaluating the decoder/payload tradeoff.
The stream-copy file and command output are in
`out/round2-latency/trim-pairing/`.

**Full-rate single-process batch screen (2026-10-14):** the earlier batched
candidate sampled every other frame. I reran its one-loaded-model pattern at
every frame, `imgsz=480`, batch 32 and six PyTorch CPU threads pinned to six
cores. Pose plus decode took 9.64 s on WA0010, 8.56 s on WA0020, and 15.03 s
on the prepared 29.8-second WA0014 clip; the clip-local analysis added about
0.7 s. WA0010 remained muscle-up / 2 / score 51 but still emitted four fault
types against its reviewed no-fault label. WA0020 retained push-up / 19 / 56
with no faults. WA0014 returned two unreviewed reps with no score. This avoids
six model startups and uses six CPU threads, but the full-duration pose still
misses the 8-second allocation and exceeds the entire 15-second goal before
upload and delivery. Keep it as a measured baseline, not a rollout candidate.
Keypoints, payloads, and timings are in
`out/round2-latency/ultralytics-screen/fullrate-batched-6t/`.

**YOLO26n-pose FP32 ONNX CPU screen (2026-10-14):** Ultralytics documents a
CPU speed advantage for YOLO26n over YOLO11n on a different Xeon workload;
that made the newer model worth a local screen, not a predicted pass. I
exported the official 7.9 MB pose checkpoint as an 11.8 MB dynamic-batch,
dynamic-spatial FP32 ONNX graph and ran the existing six-worker stride-1 path
with ONNX Runtime threads capped at one per worker. At 320 px, pose took 7.86 s
on the 29.8 s WA0014 clip, but measurement returned zero reps with
`countStatus=unmeasured`; the reviewed full count for that clip is not
available, and a known walking interval must not be counted. The two clips
with useful references do not rescue this size: WA0010 stayed at two reps but
scored 60 versus reviewed 51 and emitted two stall faults versus no reviewed
faults; WA0020 matched 19 reviewed push-ups, with no reviewed score/fault
reference. Control clips also show unsafe recognition behavior: WA0017 was
reviewed unknown but auto-classified as dip, while WA0018 was expected to
abstain but auto-classified as muscle-up. Thus the sub-8-second long-clip pose
time does not pass the output gate. This is a few local single-run screens,
not a timing distribution, Lambda measurement, or phone result. Do not deploy
YOLO26 or change the worker dependency on this evidence. Checkpoints, graph,
hashes, per-clip summaries and timings are in
`out/round2-latency/yolo26-screen/`.

**MediaPipe Heavy input-width screen (2026-10-14):** I compared the current
640 px processing cap (which leaves these 478 px-wide sources at native size)
with 320 px, keeping the same Heavy VIDEO tracker, every decoded frame and the
same production measurement code. On WA0010, pose fell from 20.79 to 15.47 s,
but the 320 px result still scored 56 versus the reviewed 51 and changed the
auto label from pull-up to muscle-up; both runs found two reps and lockout,
control and stall faults. On WA0020, pose rose from 20.16 to 20.70 s and the
declared push-up count fell from the reviewed 19 to 18; auto recognition
remained muscle-up / zero. Shared-visible landmark displacement at 320 px was
1.30 px mean / 3.92 px p95 on WA0010 and 3.78 px mean / 8.67 px p95 on WA0020
(confidence threshold 0.5). These are one local pair per clip, not a timing
distribution, but show that reducing source pixels neither gives consistent
speed nor preserves reviewed measurement. Keep the 320 px setting rejected;
do not change the deployed processing width based on WA0010's faster run. The
summary and keypoint arrays are in `out/round2-latency/heavy-resolution/`;
the Heavy task model SHA-256 is
`64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b`.

**MediaPipe Heavy tracking-threshold screen (2026-10-14):** keeping the same
model, full frame rate and native input size, I lowered only
`min_tracking_confidence` from the production 0.5 to 0.1. WA0010 took 17.38 s
at 0.5 and 15.14 s at 0.1 (13% faster in this paired run); it returned the
same auto label, two reps, score 56, fault set and rep boundaries, still
against reviewed score 51 and no faults. WA0020 took 20.38 s at 0.5 and
20.81 s at 0.1; both declared runs returned 19 push-ups with the same
boundaries. Lowering the threshold therefore did not give consistent speed
and did not bring either clip near the pose budget. Keep 0.5. Raw summaries
are in `out/round2-latency/heavy-tracking-threshold/screen.json`.

**MediaPipe Heavy stateless IMAGE chunks (2026-10-14):** to remove VIDEO
tracker state from chunk boundaries, I ran every frame through Heavy's IMAGE
mode in six independent processes and stitched the full-rate outputs. The
478×850 WA0010 clip took 12.03 s; it returned two muscle-ups, score 50 versus
reviewed 51, and changed the fault set and rep boundaries. WA0020 took 11.28 s
but returned only 9 of 19 reviewed push-ups; auto recognition called it dips.
Per-frame inference is chunk-independent, but repeated person detection makes
it too slow and the output fails the reviewed gate. These timings are local
single runs and workers were not pinned to six specific cores. Reject IMAGE
mode as the Heavy parallel path. Outputs and the harness are in
`out/round2-latency/heavy-image-chunks/`.

**MediaPipe Heavy half-rate VIDEO screen (2026-10-14):** to test whether the
current Heavy tracker can tolerate fewer inference calls better than the
YOLO half-rate candidate, I posed every other source frame while preserving
the original timestamps and measured the resulting sequence at half FPS.
Sequential pose took 8.95 s on WA0010 (367 source frames; 184 posed) and
11.10 s on WA0020 (497 source frames; 249 posed). WA0010 retained two reps
and score 56 but still disagreed with reviewed score 51/no faults and kept an
incorrect auto label. WA0020 collapsed from 19 reviewed push-ups to one.
This rejects half-rate Heavy before chunking; the positive-count gate fails,
and the sequential WA0010 time does not project to the 6–10 s full-30-second
pose range. No frame skipping or interpolation should be enabled. Raw results
and keypoints are in `out/round2-latency/heavy-half-rate/`.

**OpenCV thread-pool screen (2026-10-14):** I set `cv2.setNumThreads(1)` via
an inherited `sitecustomize.py` so the parent and all three production Heavy
chunk workers used one OpenCV thread, then compared against an uncapped control
on the same pinned CPUs and 30-second WA0014 input. Capped and uncapped runs
took 23.70 s and 23.46 s, respectively, under shared workstation load. Both
keypoint arrays were bit-for-bit identical to the saved Heavy production-six
output. Limiting OpenCV threads therefore preserved pose output but produced
no meaningful speed gain in this screen; do not add a production thread cap
on this evidence. The timing is local and noisy, not a Lambda or phone result.

**MediaPipe Heavy GPU-delegate screen (2026-10-14):** `BaseOptions.Delegate.GPU`
initialized successfully through EGL on the workstation's integrated AMD Radeon
860M (OpenGL ES 3.2); it did not select the discrete RTX GPU. Keeping Heavy,
VIDEO tracking, full frame rate, and the production measurement path, WA0010
(367 frames) took 5.47 s including delegate setup and returned pull-up / 2 /
score 56, exactly matching Heavy CPU's automatic result but not the reviewed
muscle-up / score 51 / no-fault reference. WA0020 (497 frames) took 7.23 s;
its automatic muscle-up / zero / unmeasured result also matches Heavy CPU's
automatic result, which misses the reviewed 19 push-ups. In a separate
declared-push-up replay, CPU counts 19 while the GPU keypoints count 18. The
full 29.8 fps, 30 s WA0014 clip took 11.33 s including setup and returned
unmeasured; there is no reviewed count for it. Thus this delegate is much
faster, and agrees with current CPU behavior on the auto path, but it does not
clear the reviewed quality gate: auto is wrong on the labelled clips and the
declared WA0020 count loses one rep. This is a local integrated-GPU screen, not
an Android GPU benchmark or an end-to-end result. WA0020 had both hips above
0.5 confidence in 99.6% of frames (CPU: 99.8%); the keypoint arrays differed
by 3.20 px mean absolute value. That points to downstream sensitivity to
landmark drift rather than wholesale pose-detection failure. The full auto
payloads are not identical: WA0010 has 207 differing leaves, including
classifier confidence, trace values, and a 0.08 s turn-boundary shift; WA0020
has 18 differences, mainly blocker values and view calibration. Reproduction
runner and raw outputs are under
[`gpu-screen/`](../out/round2-latency/gpu-screen/).

**GPU delegate device and tracking follow-up (2026-10-14):** setting
`EGL_PLATFORM=surfaceless` made MediaPipe select the discrete RTX 5060 instead
of the default Radeon 860M. WA0020 pose fell to 4.49 s (4.84 s including
landmarker setup); its automatic result remains the same as CPU's, while the
declared-push-up replay counts 18 rather than CPU's 19. The full 30-second
WA0014 clip took 7.77 s for pose and 8.15 s including setup, inside the
pose-only allocation, but remained unmeasured. Lowering
`min_tracking_confidence` to 0.1 on the Radeon produced bitwise-identical
WA0020 keypoints. GPU delegate outputs differ across Radeon and RTX (1.26 px
mean absolute landmark delta). The RTX timing shows that accelerated Heavy
can meet the pose slice locally, but current auto classification still fails
the labelled clips and the declared count changes; these desktop GPUs do not
predict the phone's delegate or a CPU-only Lambda. Reproduce with
`EGL_PLATFORM=surfaceless .venv/bin/python out/round2-latency/gpu-screen/run_mediapipe_gpu.py NAME CLIP [EXERCISE]`;
omit `EXERCISE` for `auto`, or pass `push_up` to replay the declared WA0020
gate. Per-run arrays and payloads are alongside the runner.

**Discrete-GPU reviewed-exercise replay (2026-10-14):** rerunning the RTX
screen with declared labels makes the speed/quality trade explicit. WA0010
muscle-up took 3.35 s of pose (3.70 s with setup), counted 2 and retained the
CPU fault set, but scored 57 versus CPU 56 and the reviewed 51; the second turn
moved from 12.54 to 12.46 s. WA0020 push-up took 4.47 s of pose (4.81 s with
setup) and counted 18 versus CPU and review at 19. It omitted the CPU interval
2.89–3.93 s. Repeating at tracking confidence 0.1 still counted 18 and took
4.49 s of pose. Thus the RTX can process the reviewed clips quickly, but this
Heavy GPU output changes reviewed measurements and fails the strict parity
screen. The saved declared-payload JSON files record full rep output; the
runner accepts an optional exercise name for reproduction.

**RTX tracking-threshold sweep (2026-10-14):** to test whether tracker
confidence explained the GPU count loss, I reran the same MediaPipe GPU
runner and clips at thresholds 0.3 and 0.7, compared with the saved 0.1 and
0.5 outputs. For WA0020 declared push-ups, all four 497-frame COCO keypoint
arrays are bitwise identical and all four produce the same 18 rep intervals;
the reviewed count is 19, including the missing [2.89, 3.93] s interval.
WA0010's 0.7 array is also bitwise identical to its 0.5 declared-muscle-up
array and still scores 57 versus the reviewed 51. The new 0.3/0.7 WA0020
trials took 4.09/4.02 s wall including setup, but these are single noisy runs
and do not show a threshold speed effect. Within this tested range, changing
`min_tracking_confidence` does not change RTX GPU output, so stop tuning that
option as a fix for GPU measurement parity. This leaves the GPU path fast but
quality-failing; the next useful work is measurement/classifier diagnosis or
a different accelerator path, not more tracker-threshold sweeps. Arrays and
payloads are in `out/round2-latency/gpu-screen/WA0010-track07-*` and
`WA0020-track{03,07}-*`.

I aligned the WA0020 RTX array with the saved Heavy CPU 640 px array to locate
the lost count. Over the reviewed missing interval [2.89, 3.93] s, shoulder
and elbow XY drift averages 15.59 and 12.70 px (p95 52.98 and 49.77 px); hip
drift averages 51.77 px (p95 158.94 px), while wrists average 4.31 px (p95
7.84 px). Both backends report confidence >=0.5 on 92–96% of these body
landmarks, so confidence gating alone would not identify the bad pose. In the
adjacent [3.93, 4.81] s counted interval, the same joints differ by only
2.26–4.61 px on average and at most 11.54 px for hips. This localized
high-confidence pose drift is consistent with the GPU geometry losing the
rep, while the clip-wide 3.20 px mean had hidden it. It is a causal lead, not
proof that hip drift alone causes the segmentation miss; the frame-level
arrays are in `gpu-screen/` and `heavy-resolution/`.

**RTX pose-detection threshold probe (2026-10-14):** the segmenter trace
identifies the exact loss: at the candidate turnaround 3.41 s (frame 85), the
0.5 GPU pose array is all zero for frames 85 and 86. The CPU array observes
both frames. `segment_reps_verbose` finds the candidate peak from neighboring
interpolated samples, then correctly rejects it because the turnaround itself
was not observed. Lowering `min_tracking_confidence` could not restore these
frames. I then varied `min_pose_detection_confidence` while holding the RTX,
Heavy model, VIDEO mode, frames, presence threshold (0.5) and tracking
threshold (0.5) fixed. At 0.25 the GPU produced three all-zero frames (84–86)
and still counted 18 declared push-ups. At 0.1, frames 85–86 were detected,
the lost turnaround was observed, and the declared count returned to 19 with
intervals matching the CPU count sequence except for the shared boundary
moving from 3.93 to 3.89 s (one frame). It still had a separate invalid pose
at frame 109. The 0.1 run took 4.02 s wall / 3.72 s pose; the 0.25 run took
3.99 / 3.65 s. These single local trials show a quality effect, not a speed
gain. Raw candidates, keypoint hashes and invalid-frame indices are summarized
in [`detection-threshold-screen.json`](../out/round2-latency/gpu-screen/detection-threshold-screen.json).

The same 0.1 setting was then checked on reviewed controls: WA0010 auto still
labels the reviewed muscle-up as pull-up (2 reps, score 56); WA0020 auto still
labels the reviewed push-ups as muscle-up and returns zero/unmeasured;
negative WA0017 remains a false muscle-up / 2; and WA0018 remains an
unmeasured muscle-up rather than an unknown label. The reviewed WA0014 first
30 s remains zero/unmeasured. Running `round2_quality_gate.py` on all five
reports fails: the WA0010, WA0020 and WA0017 movement/count assertions fail,
and WA0014's reviewed zero is not a measured count (WA0018 remains an
unreviewed coverage gap). Lower detector confidence repairs one documented
GPU dropout and recovers the declared WA0020 count, but does not make the GPU
backend an acceptable auto-measurement candidate. Keep 0.5 as production
configuration; test 0.1 only in the on-device parity spike, with full
classification and negative-control gates.

**RTX geometry-only fusion screen (2026-10-14):** because the learned model
overrides the geometry on both the CPU and GPU for WA0020 (geometry says
`push_up` / model says `muscle_up`, model confidence 1.0) and also overrides
WA0010 (geometry says `muscle_up` / model says `pull_up`), I reran the same
0.1-detector RTX poses with the learned model disabled and no remote vision
vote. This is a fusion policy experiment, not a speed change. WA0010 auto
returned the reviewed muscle-up / 2; WA0020 auto returned the reviewed
push-up / 19 (`countStatus=geometry`). The full reviewed gate still fails:
WA0017 is classified as front lever / two hold attempts instead of reviewed
unknown / zero reps, and the reviewed WA0014 first-30-second zero remains
`unmeasured`; WA0018's count label is still unreviewed. The five-report gate
has two passes (the positive WA0010/WA0020 clips), two failures (WA0017 and
WA0014), and one coverage gap (WA0018). Geometry-only therefore fixes the
two reviewed positive disagreements on this set but is not a passing general
policy. The stage-only GPU runs took 2.71 s pose for WA0010, 3.67 s for
WA0020 and 6.45 s for WA0014 first-30; these exclude upload, server startup
and phone delivery. Full payloads and the exact gate output are in
[`geometry-only-screen.json`](../out/round2-latency/gpu-screen/geometry-only-screen.json).

**Rejected straight-arm front-lever gate (2026-10-14):** WA0017's false
front-lever geometry had `arms_straight_frac=0.165`, so I screened a 0.70
minimum with a synthetic extended-arm / bent-arm pair. The synthetic tests
behaved as intended, and the WA0017 Heavy pose abstained as unknown. The
cached classification corpus rejects this as a global rule: on the same 261
clips present in the prior report, geometric accuracy fell from 62/261 (0.238)
to 58/261 (0.222), losing four correctly labeled front-lever examples and
gaining no correct labels. Their measured straight-arm fractions were 0.151,
0.513, 0.286 and 0.174, showing that this feature is not reliable enough on
these real pose tracks to gate the class. I removed the rule and its test.
With Lite plus the existing learned classifier enabled, WA0017 is still a
false muscle-up / 2 in 5.136 s pose + 0.420 s measurement; the learned label
overrides geometry's front-lever label. Classification/fusion therefore
remains a quality defect on this fast path; do not ship the synthetic-only
gate. Candidate corpus outputs are under
`out/round2-latency/front-lever-corpus-eval/`, and the Lite report is under
`out/round2-latency/mediapipe-lite-worker/`.

The WA0014 trace gives a concrete zero-count design case: one candidate at
22.95 s was rejected because wrist travel was 1.76 torso lengths against the
0.80 fixed-bar limit; the other active spans had no accepted turnarounds.
That is evidence against counting the walking candidate, not by itself proof
that a clip has a measured zero. Keep the count `unmeasured` until a
zero-result rule can distinguish a verified no-rep clip from tracker or
segmentation failure and passes both positive and negative controls.

**Hybrid-CPU chunk-count follow-up (2026-10-14):** I reran Heavy on the
current Ryzen AI 7 350 host, pinning the same 30-second WA0014 input to six
logical CPUs that map to six distinct physical cores. The production planner
made three chunks and took 23.52 s. Six forced chunks took 21.31 s, with
0.404 px mean / 1.391 px p95 visible XY displacement from the sequential Heavy
reference. Four chunks pinned to CPUs 0, 2, 4 and 6 (the four higher-clocked
physical cores in `lscpu`) took 22.11 s and had 0.438 px mean / 1.366 px p95
displacement. Pinning six workers to those four performance cores plus two SMT
siblings took 23.98 s, slower than six distinct physical cores; its keypoints
were bitwise identical to the six-physical-core result. Six workers are
fastest in this one paired screen, but still need about 2.7× the 8-second pose
budget. These are single noisy workstation runs and not Lambda timings; they
do not justify a planner change. Arrays and config details are in
`out/round2-latency/`.

**GPU negative-control extension (2026-10-14):** on RTX, WA0017 took 6.22 s
for pose (6.63 s including setup) and returned muscle-up / 2 / score 48 with
lockout and bent-arm faults. A matched sequential Heavy CPU run took 34.05 s
and returned the same headline result and faults. The reviewed expectation is
unknown / zero, so this is a severe existing model false positive rather than
a new GPU-only regression; the GPU makes that wrong result much faster. On
WA0018, RTX pose took 2.64 s (3.05 s including setup) and returned muscle-up /
zero / unmeasured, preserving the expected abstention count. Together these
controls confirm that GPU speed can match CPU behavior while both fail a
reviewed unknown clip. GPU results remain ineligible for a random-clip pass
until the detector abstains correctly on WA0017 as well as preserving the
positive-rep measurements.

**YOLO11n fusion screen (2026-10-14):** I replayed the eight-clip screen
through the pinned worker container with current sources mounted and explicit
`PYTHONPATH=/opt/barra/server:/opt/barra`; without that path order, the image's
older installed `process.py` was imported and the seven initial reports did
not exercise the candidate policy. Those first reports are superseded. The
corrected run used six CPU quota, stride 2, 480 px input, one PyTorch thread
per worker, and the checkpoint SHA recorded in each JSON report. The opt-in
`ultralytics-screen-v1` policy selects geometry only above 0.75 and when more
confident than the classifier, keeps a classifier vote only above 0.75, and
abstains on weaker disagreement. Production's default fusion policy is
unchanged. The corrected replay returns reviewed WA0010 muscle-up / 2, WA0017
unknown / 0, and WA0020 push-up / 19. The quality gate initially misread
WA0017's requested `exercise: auto` as its final label even though
`detected.fusion.exercise` was `unknown`; the gate now reads that final vote.
On movement/count, all three reviewed clips pass. WA0010's score remains 50
versus the reference score 51, and score is not currently a hard assertion in
the quality gate. WA0011, WA0012, WA0014, WA0018 and WA0019 remain incomplete
because their movement/count labels are not fully reviewed. This tiny reviewed
sample is not enough to calibrate or ship a production policy.

Corrected container stage times were: WA0010 5.21 s pose + 0.44 s
measurement; WA0011 3.71 s + 0.05 s; WA0012 4.14 s + 0.08 s; WA0017 5.69 s
+ 0.16 s; WA0018 4.13 s + 0.06 s; WA0019 4.19 s + 0.06 s; WA0020 5.04 s
+ 0.15 s; and the prepared 29.8 s WA0014 clip 6.54 s + 0.15 s. WA0014 fits
the local pose-plus-measurement slice at 6.70 s, but its count is unreviewed.
These container timings exclude upload, Lambda cold start, image pull,
persistence, phone polling/render and device network; they do not establish
the under-15-second phone target. Corrected reports and gate inputs are in
[`round2-container-yolo-fusion-v1/`](../out/round2-container-yolo-fusion-v1/).

**YOLO11n timing instrumentation (2026-10-14):** the opt-in six-worker,
stride-2, 480 px backend now records decode, chunk serialization, worker wall,
output load/merge, densification and total pose time in candidate reports.
Three local runs on the 40.4 s corpus WA0014 source (1,206 frames), pinned to
six physical CPU cores and sampled to 603 frames, took 13.50, 11.18 and 12.05
s for backend pose (median 12.05 s). Median parent
stages were 0.66 s decode, 0.22 s chunk writes, 11.12 s worker wall, and under
1 ms each for output load/merge and densification. Worker reports split the
parallel work further: six-worker per-process medians were 1.20 s importing
Ultralytics, 0.12 s loading weights and 7.71 s inside `model.predict`; each
worker's concurrent wall median was 9.16 s. Startup/import and inference both
matter, while parent frame handling is small. This is a host run, not Lambda,
and excludes upload and phone delivery, so it cannot pass Round 2. The raw
measurements are in `out/round2-latency/yolo11-substage-profile.json`;
candidate reports include `candidateTiming.poseSubstagesSeconds` and
`candidateTiming.poseWorkerSubstagesSeconds` when regenerated.

**Inherited-frame fork workers (2026-10-14):** six Linux fork workers inherit
the already-decoded frame list and the parent-imported Ultralytics/Torch
modules. They therefore avoid serializing frame arrays and repeating the
1.2-second worker imports. Two order-balanced pairs on the same 40.4 s corpus
WA0014 source (1,206 frames; 603 sampled; six pinned physical cores, stride 2,
480 px) took
10.82/11.08 s in subprocess mode and 8.13/9.51 s in fork mode: medians 10.95
and 8.82 s (19.5% lower). Both keypoint arrays were bit-for-bit identical in
each pair. The candidate runner now defaults to this mode on POSIX CPU hosts;
an OS fork-launch failure is reaped and falls back to the existing subprocess
path. Reviewed candidate replays still return WA0010 muscle-up / 2 (score 50
versus reference 51) and WA0020 push-up / 19. This removes a real startup and
frame-transfer cost, but does not make the 30 s result a Round 2 pass: the raw
WA0014 source remains unmeasured, and upload plus phone delivery are absent
from these local benchmarks. Raw A/B timings and exact-difference checks are in
`out/round2-latency/yolo11-worker-mode-ab.json`; candidate payloads are in
`out/round2-latency/yolo11-fork-quality/`.

On the 40.4 s corpus WA0014 source, the default fork-mode candidate took 11.77
s for pose and 0.72 s for measurement (12.49 s local processing total), but
returned zero reps with `countStatus=unmeasured`. On the separate prepared
30.0 s, 720p WA0014 clip, the worker container took 5.28 s for pose and 0.49 s
for measurement (5.77 s total), returning two geometry-counted reps but a null
session score because `split_depth` could not be observed, leaving the
score's required range component unavailable. Contact-sheet review added a
medium-confidence no-rep interval [26.6, 29.9] s to the manifest; it catches
both candidates. WA0014's total count remains unreviewed. Docker could not
enforce CPU affinity on this host, so this six-worker timing may use more than
six cores. It excludes upload, Lambda dispatch/cold start and phone delivery.

**Trim-window sensitivity follow-up (2026-10-14):** the full 40.4 s source
produced one scored muscle-up at [31.95, 34.13] s (score 42). I re-encoded a
30 s window from source time 10.4 s through 40.4 s at 720p / 4 Mbit/s; it
contains that source interval at local time [21.55, 23.73] s, but the same
fork-mode candidate returned zero reps and `countStatus=unmeasured` in 5.81 s.
The separate first-30-second crop returned two geometry counts, but 10 fps
contact-sheet review of its source frames from 26.6–29.9 s shows the athlete
still in a stationary dead hang. A later 2 fps contact sheet spanning the
whole first 30 s shows the approach, static hang, drop and walk-away without
a completed ascent/transition. I widened the reviewed no-rep interval to
[0, 30] s in `data/evaluation/sample_manifest.json` without asserting
WA0014's full-source count; the gate fails both candidate intervals against
it. The review sheets are `out/round2-latency/WA0014-idle-hang-review.jpg`
and `out/round2-latency/WA0014-first30-review.jpg`. Those
reps also have no score because their required range could not be measured.
This is direct evidence that fast pose alone does not validate trim
equivalence: crop start and re-encoding can remove a usable result. The shifted
30-second crop returned zero reps even though it includes the source's scored
rep. Neither 30-second crop has a reviewed total count. Docker could not
enforce CPU affinity here either. The re-encoded clip is 16.23 MB, so the
2–5 s upload allocation requires roughly 65–26 Mbit/s of sustained goodput
before request overhead; the actual Media3 export and phone network still need
measurement. Reports and the encoded test clip are in
`out/round2-latency/yolo11-fork-30s/` and
`out/round2-latency/yolo11-fork-prepared30s/` and
`out/round2-latency/yolo11-fork-window30s/`.

**Amplitude-floor shadow, not a production change (2026-10-14):** I replayed
the same candidates with the experimental runner override
`--min-span-amplitude 0.25`. It removes the two geometry candidates inside the
reviewed stationary-hang interval on the first-30-second WA0014 crop; the
shifted crop remains unmeasured. The reviewed WA0010 muscle-up / 2 and WA0020
push-up / 19 reports still pass their hard movement/count assertions (scores
50 and 56 respectively). WA0014 is still `incomplete`, because its total
movement/count is not reviewed; suppressing a known false positive is not
evidence that the remaining count is correct. The regular default-floor
first-30-second report still fails the reviewed no-rep interval. Gate replay:
`python scripts/round2_quality_gate.py` over the three candidate reports and
the two default-floor WA0014 reports. The override run took 4.61 s pose +
0.136 s measurement for the crop, versus 5.28 s + 0.485 s in the earlier
default-floor worker-container run; this is one uncapped-container pair, so
the timing difference is not a speed claim.

Do not promote 0.25 globally: the cached-pose shadow changes counts in 15 of
160 supported rows, including hold movements. A muscle-up-only shadow changes
one of 12 weak-label muscle-up rows (19 to 18), with no exact silver-label
change, but those silver labels do not provide enough reviewed coverage to
establish safety. Keep the override in the candidate runner for controlled
experiments only. The next quality step is to review the complete WA0014
source count and build a movement-stratified set of reviewed static-hang,
partial-ROM and valid muscle-up examples; then compare default and
movement-specific floors for false positives, missed reps, score/fault
changes, and measurement time. No segmenter default or `Movement` profile was
changed from this experiment. Artifacts: `min-span-amplitude-025-shadow.json`,
`min-span-muscleup-025-shadow.json`, and `yolo11-minspan025/` under
`out/round2-latency/`.

**Fork-worker count sweep with array identity (2026-10-14):** I compared 3,
4 and 6 fork workers in the pinned YOLO11n container (`--cpus=6`, stride 2,
480 px, one Torch thread per worker, the opt-in fusion screen) on WA0010,
WA0020 and the prepared 30-second WA0014 crop. The candidate runner now stores
the pose-array shape and SHA-256, so this compares the actual pose output as
well as measured counts. In one serial pass, WA0014 pose took 7.249, 6.367
and 5.773 s for 3, 4 and 6 workers; measurement took 0.123, 0.129 and 0.124 s.
WA0010 took 4.157, 3.899 and 3.866 s pose; WA0020 took 4.449, 4.130 and
3.875 s. For each clip, all three worker counts produced the same keypoint
shape and bit-for-bit identical keypoint SHA-256. WA0010 stayed muscle-up / 2
(score 50) and WA0020 push-up / 19 (score 56); both pass the reviewed hard
movement/count gate. WA0014 still returns the two candidates overlapping the
reviewed stationary hang, so its report fails that interval despite pose under
6 s with six workers. This is one serial timing sweep without enforced CPU
affinity; it supports keeping six workers as the fastest candidate to repeat,
but it neither validates the false positives nor proves a 6-core Lambda or
phone result. Reports are under
`out/round2-latency/yolo11-worker-count-hash/{workers3,workers4,workers6}/`;
the three-clip gate replay on workers6 fails WA0014 as expected.

**WA0014 floor A/B on unchanged pose (2026-10-14):** I then applied the
experimental 0.25 span floor to the full 40.4-second WA0014 source with the
same six-worker YOLO11n configuration. The default and floor runs have the
same keypoint SHA-256; both retain one muscle-up candidate at [31.95, 34.13]
s, score 42, with the same reported fault set. Pose took 7.585 s in the
default run and 7.864 s with the floor, so this is a segmentation-quality
comparison, not a speed gain. On the prepared first-30-second crop, the prior
matched-configuration screen with the same floor removed the two candidates
inside the reviewed 26.6–29.9 s stationary hang. This makes a muscle-up-only
floor a plausible next reviewed experiment: it suppresses that idle-span
error while leaving the later source candidate unchanged. WA0014's total
count is still unreviewed, and this does not establish that the later candidate
is a valid rep or that partial-range muscle-ups remain safe. Keep the override
experimental until those examples are reviewed. A/B reports are in
`out/round2-latency/WA0014-full-floor-pair/{default,floor025}/`.

**Source-time quality-gate alignment (2026-10-14):** candidate intervals are
clip-local, while manifest assertions use source-video timestamps. The
candidate runner now records `sourceOffsetS`; the quality gate shifts reported
rep intervals back to source time before applying reviewed `notReps` checks,
and rejects invalid offsets. This prevents a shifted crop from being compared
to the wrong part of the reviewed source. A regression test maps a local
12.4–14.7 s candidate in a 10.4 s-offset crop onto the reviewed 22.8–25.1 s
walking interval and correctly fails it. The previous shifted-window run had
no reps, so the offset bug did not change that verdict; this fixes future crop
gates. The reviewed whole first-30-second no-rep interval is now [0, 30] s;
the full WA0014 source count remains unreviewed.

**Full-rate trim sensitivity check (2026-10-14):** to test whether stride-2
sampling caused the shifted-window miss, I reran both prepared WA0014 windows
with the earlier YOLO11 / opt-in-fusion candidate at stride 1, six workers and
480 px input. Pose took 10.062 s on the
first-30-second window and 9.835 s on the shifted window. The first window
still returns the two candidates in the reviewed stationary hang; the shifted
window still returns unmeasured, despite containing the full-source
[31.95, 34.13] s candidate at local [21.55, 23.73] s. Full rate therefore
does not repair this trim-sensitivity case and consumes the full pose budget;
reject it as a fix for the crop miss. The first-window quality gate still
fails the two forbidden intervals.

I also saved pose arrays for the full source and shifted window and aligned
their frame timestamps. The two runs have 13,530 high-confidence landmark
pairs with mean normalized XY drift 0.00256 and p95 0.00856; both have 853
frames with at least eight confident landmarks. In the corresponding
31.8–34.3 s source interval (21.4–23.9 s in the crop), 1,142 confident
landmark pairs have mean normalized XY drift 0.00558, p95 0.01792 and max
0.06980. Despite comparable detector coverage, measured count changes from
one to unmeasured. This shows materially greater pose drift around the missed
attempt than the clip-wide average, but does not isolate crop context versus
encoding or their interaction. Source/crop hashes,
array hashes, exact alignment and summary are in
[`comparison.json`](../out/round2-latency/WA0014-pose-alignment/comparison.json);
the raw arrays and candidate reports are beside it.

**Turnaround-height threshold A/B (2026-10-14):** I exposed the historical
0.60 peak-height fraction as `Thresholds.min_turn_peak_fraction` and added
candidate-only overrides to the container runner and cached-pose replay. The
default remains 0.60. To avoid the earlier checkpoint/policy mismatch, the
decisive A/B used the same YOLO26n checkpoint (SHA-256
`eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9`),
stride 2, six fork workers, 480 px and default fusion on both settings. At
0.60 and 0.59, the shifted 10.4–40.4 s crop produced the same one rep at
local [21.67, 23.73] s (score 42) and identical pose SHA-256; pose took 6.43
and 6.58 s respectively. On the reviewed first-30-second window, both
settings produced zero reps with `countStatus=unmeasured`; the offline harness
has remote count credentials removed, so the reviewed zero is not a measured
zero from this run and the quality gate fails. Thus the threshold change does not
recover that window or account for the shifted crop's recovery. The first
window's gate is still a hard fail.

The 0.59 cached-pose replay changed three weak-silver rows (two planche and
one squat, each +1), while reviewed WA0010 muscle-up / 2 and WA0020 push-up /
19 counts stayed intact. Weak-silver exact matches remained 24/159 and MAE
moved from 3.145 to 3.164. These scraped estimates are not ground truth; the
three changed rows are a reason to keep the setting experimental, not a
quality claim. Gate replay still fails WA0014's unmeasured first window and
WA0020's candidate auto-classification as dip. The first 30 s, shifted crop,
WA0010, WA0020 reports and both corpus replays are under
`out/round2-latency/peak060-*`, `peak059*` and `peak0{59,60}-shadow.json`.
No production segmentation threshold changed.

**YOLO26n input-size screen (2026-10-14):** with the same
`yolo26n-pose.pt` checkpoint (SHA-256
`eb3bb8268828aeaf515cec23a4bfafd793944a86fe9af94ba7823609c14522a9`),
six fork workers, stride 2, one Torch thread per worker and default fusion,
I compared 416 and 448 px against the existing 480 px candidate. On the same
prepared first-30-second WA0014 clip, 480 px took 7.621 s pose / 0.467 s
measurement and returned zero `unmeasured`; 416 px took 5.375 / 0.231 s but
returned one geometry rep [27.11, 28.32] s inside the reviewed [0, 30] s
zero-rep window. At 448 px, pose took 5.707 / 0.232 s and returned two reps,
both overlapping the reviewed no-rep window. The quality gate fails both
smaller sizes on this hard negative; this is not a case to trade count quality
for roughly 25–30% faster pose.

The same one-pass 416 / 448 screens preserved WA0010 at 2 muscle-ups (scores
52 / 53) but kept WA0020 at 19 reps under the wrong `dip` label (scores 56 /
55). The reviewed unknown WA0017 remained a false movement classification
(`dip` at 416, `pull_up` at 448), though its count was unmeasured zero. All 8
reports fail the hard gate except the WA0010 count anchor. Keep 480 px as the
current candidate setting; it also has unresolved gates and is not approved
for production. This was one serial `docker --cpus=6` pass per size, with no
repeats or controlled CPU affinity, so timing is a screening result only. The
reports and pose-array hashes are under
`out/round2-latency/yolo26-imgsz{416,448}/`; the 480 px comparison is under
`out/round2-latency/peak060-first30/`.

**YOLO26n stride-3 screen (2026-10-14):** at 480 px, six fork workers and
default fusion, stride 3 reduced inference work and kept WA0010 at two
muscle-ups / score 53. To remove a confound in the first screen, I reran
stride 2 at the same 0.60 turnaround threshold. WA0010 pose was 4.771 s at
stride 2 and 2.447 s at stride 3; its first-rep score stayed 50, while the
estimated duration shifted from 5.33 to 5.83 s. WA0020 took 4.607 / 2.816 s
and stayed at 19 reps / score 56, but both strides auto-labeled the reviewed
push-ups as dips. On the shifted WA0014 crop both strides found one candidate,
but its score changed from 42 to 37, so interval/count retention does not
establish metric parity. Timing is a single pass on a shared x86 host and is
screening evidence, not a deployment estimate.

The stride-3 strict quality gate still fails: WA0014's reviewed first 30 s is
`unmeasured` rather than a measured zero; WA0017 is falsely labeled `dip`
instead of `unknown`; WA0020 is falsely labeled `dip` instead of `push_up`.
Keep stride 3 as an opt-in speed experiment, not a production default. Reports
are under `out/round2-latency/yolo26-stride3*/`; the same-threshold stride-2
controls are under `out/round2-latency/yolo26-stride2-mt060/`.

**Local Android render-marker check (2026-10-14):** I installed the debug
build on an API 35 x86_64 emulator and submitted the 15.29 s WA0010 source to
the local API with provider credentials blank. The app showed the compact
`ANÁLISIS` result (score 56, two geometry-counted reps). The first completed
rows had `renderedNs=0`: results in this compact record surface do not pass
through the detailed-session callback. I added a first-frame marker to
`TrackerRecord` and tied it to the matching job and trace. The next completed
row recorded result at 688.106 s and first frame at 688.206 s on the same
phone monotonic clock, a 100 ms result-to-frame gap and 22.979 s from upload
start to first frame. The displayed result confirms the marker is attached to
the visible surface. This fixes measurement coverage; it does not improve
latency. The emulator/local loopback run is not a physical-phone or real
network measurement, uses a 15.29 s clip rather than a random full 30 s clip,
and misses the <15 s end-to-end target by about 8 s. It provides no evidence
that the target is met. Focused Android unit tests for the marker and polling
timings pass.

**2 Mbit/s upload-size screen (2026-10-15):** I encoded the prepared 30 s
WA0014 crop at 2 Mbit/s with local FFmpeg/libx264. It is 7.38 MB versus
14.61 MB at the current 4 Mbit/s request (49% fewer bytes). Lite on the
workstation's six-worker setting took 6.84 s pose + 0.60 s measurement and
returned the same zero / `unmeasured` result as the existing 4 Mbit/s Lite
run. This is an upload-byte result plus a limited negative check, not Media3,
phone, or network timing.

I also screened 2 Mbit/s encodes of the reviewed anchors with Lite. WA0010
became 1 muscle-up / score 47 against the reviewed 2; WA0017 became
`knee_raise` / 2 against reviewed `unknown`; WA0018 became unsupported
`handstand` / unmeasured against reviewed `unknown`. WA0020's existing Heavy
2 Mbit/s comparison retains 19 push-ups, but auto-labels as `muscle_up` rather
than reviewed `push_up`. The 2 Mbit/s setting therefore fails the current
measurement/classification gate across this reviewed set. Do not lower the
exporter default based on the byte saving. Raw screen output is under
`out/round2-latency/bitrate-2mbps/`; all pose times are workstation-only.
To isolate bitrate on the WA0010 Lite result, I encoded the same source at
4 Mbit/s and reran the same pipeline: it returned 2 muscle-ups / score 56,
versus 1 / score 47 at 2 Mbit/s. The paired result strengthens the evidence
that the lower encode loses measurement signal; it remains a single local
pair, not a population estimate.

**Intermediate bitrate follow-up (2026-10-15):** I screened 2.5, 2.75 and
3 Mbit/s using the same local FFmpeg/libx264 720p settings and Lite six-worker
measurement path. On WA0010, both 2.5 and 2.75 Mbit/s returned 1 of the
reviewed 2 muscle-ups (score 56); 3 Mbit/s returned 2 (score 57). Thus this
single clip's observed count changes between 2.75 and 3 Mbit/s, with the
3 Mbit/s output 5.93 MB versus 7.92 MB at 4 Mbit/s. On WA0020, all three
bitrates returned 19 when declared `push_up`; auto remained the wrong `dip`
label at both 3 and 4 Mbit/s on this Lite path. WA0014 remained zero /
`unmeasured` at 2.5, 2.75 and 3 Mbit/s; its 3 Mbit/s file is 11.12 MB,
23.9% below the 14.61 MB 4 Mbit/s file. This gives a promising size/count
trade for further review, but not a passing random-clip gate: only one
positive count changes across this narrow sweep, WA0020 auto-label still
fails, and WA0014 does not have an accepted measured zero. Do not change the
Media3 default. All measurements are local, single-run FFmpeg/MediaPipe
screens, not Android export or network timings. Raw results are under
`out/round2-latency/bitrate-{2_5,2_75,3}mbps/`.

**Combined fast-path gate rerun (2026-10-15):** I combined the opt-in
`ultralytics-screen-v1` fusion policy with the experimental 0.25 movement
amplitude floor in the pinned six-CPU worker image (YOLO11n weights SHA-256
`869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`, stride
2, 480 px, six fork workers). The reviewed gate passes WA0010 muscle-up / 2,
WA0017 unknown / 0, and WA0020 push-up / 19; WA0018 remains a review coverage
gap. On WA0014's explicitly mapped first-30-second no-rep window, it removes
the prior false candidates and returns 0, but `countStatus=unmeasured`, so
the strict measured-result gate correctly fails. Pose plus measurement for
that 30-second clip took 5.75 s in the source-window rerun (pose substage
5.53 s, measurement 0.22 s); another pass in the same screen took 4.82 s
combined. This is a promising pose/known-label candidate, not a Round 2 pass:
its key no-rep case is still unmeasured, timing is a local container screen,
and upload, Lambda init/dispatch, persistence and phone render are absent.
Do not enable it in production until the measured-zero rule has reviewed
negative coverage and the complete phone path is validated. Reports and gate
inputs are in `out/round2-latency/yolo11-fusion-v1-floor025-fullgate/`.

The saved WA0014 zero trace and keypoints give a concrete shadow-rule shape:
the movement signal observes 732/894 frames overall (0.819), and observes all
frames in each detected active span. Span amplitudes are 0.0986, 0.2883 and
0.2200 torso lengths; the 0.25 floor discards the first and third. The only
standard turnaround at 22.89 s is rejected because the supposed rest posture
has the shoulders 0.613 torso lengths above the hands (limit 0.30). Rescue
also rejects a 12.45 s candidate for a missing leg (0.4537 vs 0.6734 required)
and the 22.89 s candidate for insufficient drop dynamics (0.0135 vs 0.0143
required). This explains why the candidate returns zero rather than counting
the walk or dead hang. It is credible evidence for one reviewed negative, but
still only one: use these explicit coverage, per-span motion and rejection
reasons in a shadow `geometry_zero` eligibility report, and require more
independently reviewed zero-rep sets before making zero a measured result.
I checked the weak-silver label set for an independent negative: two clips
whose generated descriptions claimed no reps (weighted pull-up
`youtube_02-QZma9_Xo` and knee raise `youtube_GSOfcbwbd-g`) visibly contain
repetition movement in 2 fps contact sheets. I did not add either as a reviewed
zero. This confirms those weak labels cannot supply the missing negative
coverage; the artifacts are
`out/round2-latency/weak-silver-02-QZma9_Xo-zoom.jpg`,
`out/round2-latency/weak-silver-GSOfcbwbd-g-first30-review.jpg` and
`out/round2-latency/weak-silver-GSOfcbwbd-g-last25-review.jpg`.

**30 s emulator transport probe (2026-10-15):** I installed the current debug
app against the local API and uploaded the prepared full 30 s WA0014 file over
the emulator loopback route. The app trace records 14.37 s from attempt start
to result availability (14 polls), including 1.61 s part transfer and 7.13 s
poll GET time; preparation was separately recorded as 54.93 s. The result was
0 reps with `countStatus=unmeasured`, so it fails the quality gate and cannot
count as a <15 s measured-result pass. `renderedNs` remained zero. That render
observation is inconclusive because I selected two more clips while the first
job was completing, replacing the record screen state; those two uploads were
never started. This is emulator/local-loopback timing, not phone-network or
production timing. The raw device trace is in
`out/round2-latency/emulator-local-20261015/partial-WA0014-timings.json`; do
not use it as a latency claim until a controlled single-job run reaches the
visible result surface. The phone report now shows
result availability and observed transport phases for this partial attempt,
while still excluding it from completed and under-target success rates.

**Controlled emulator positive and 30 s candidate probes (2026-10-15):** On
the same local API/emulator configuration, the reviewed 20.00 s WA0020
push-up control rendered `geometry / 19` in 13.284 s from upload-attempt
start; the displayed count matched its reviewed 19. Its result-to-frame gap
was 89 ms. The trace had 18 polls, 6.454 s cumulative GET time and 4.526 s
intentional poll delay. This validates the phone marker on a visible measured
result, but the input is shorter than 30 s and the local loopback path is not
production networking.

I then selected the 29.64 s rings muscle-up clip
`youtube_fsL30RRJ9ds` (weak-silver estimate: 2; contact sheet shows repeated
ring transitions, but it is not a reviewed ground-truth count). Two imports
of that same clip completed in 11.594 s and 8.146 s respectively, both with
`countStatus=unmeasured`, 0 reps, and the automatic label `dip`. These are
quality failures despite meeting the timing threshold; the warmed second run
is not an independent latency sample. Together with WA0014's 30 s unmeasured
zero, this shows the present bottleneck is not only speed: a 30 s auto-labeled
clip still lacks a valid measured result. The traces and phone report are
saved under `out/round2-latency/emulator-local-20261015/`; the emulator
and local API were stopped afterward. No production or random-clip acceptance
claim follows from these local runs.

**Reproduced the long-clip abstention in the worker candidate (2026-10-15):**
I ran `youtube_fsL30RRJ9ds` through the pinned six-CPU YOLO11 candidate with
stride 2, 480 px, amplitude floor 0.25 and `ultralytics-screen-v1`, with all
remote provider keys removed. The worker reproduced `dip / 0 / unmeasured`
in 5.407 s total (5.176 s pose, 0.230 s measurement). The underlying votes
were YOLO geometry `dip` at 0.78 and the learned classifier `muscle_up` at
0.7425 with 0.6603 margin; the fusion rule compares these unlike raw
confidence values and chose geometry. The video title and weak label call it
a rings muscle-up, but the label is not reviewed ground truth, so this is a
reproduced disagreement and a review target, not proof that `muscle_up / 2`
is correct. The candidate JSON is saved beside the phone traces at
`out/round2-latency/emulator-local-20261015/candidate/youtube_fsL30RRJ9ds.json`.
The next quality experiment must add reviewed rings-muscle-up and dip examples
before changing this fusion boundary; a one-pair override would overfit this
clip and could break WA0020, where geometry `push_up` correctly beats the
classifier's `deadlift` vote.

**On-device motion-sampler screen (2026-10-15):** an isolated Android 35
x86_64 benchmark ran the same `MediaMetadataRetriever` frame-difference and
trim-window logic on the exact 30 s WA0014 crop and reviewed positive clips
WA0010/WA0020. Current 0.5 s `OPTION_CLOSEST` sampling took 17.31 s on one
WA0014 run and 13.97–14.71 s in crossed-order reruns; 1.0 s sampling took
6.66 s initially and 6.68–6.82 s in the crossed-order check (about 2.1–2.6x
faster). The returned WA0014 window changed from 0–7.5 s to 1–8 s. On WA0010
both modes were wider than the 80% trim limit and did not trim. On WA0020 the
0.5 s mode suggested 0.5–12.5 s, while 1.0 s suggested 1–19 s, which the
current trim rule rejects and therefore preserves the full 19-rep clip. When
forced as diagnostic re-encoded crops, those windows measured 11/19 and 18/19
respectively; the app would not force the latter because it is not a material
trim. This supports a 1 s closest-frame candidate as a speed and conservative
boundary improvement, not as a production default yet: the tested set is
small, WA0014 remains a false-short suggestion, and there is no reviewed 30 s
positive clip. The `OPTION_CLOSEST_SYNC` shortcut took 0.28–1.48 s but returned
only 5.5–7.5 s or 6–8 s on both positive clips, so it is rejected. Full timings,
windows, crop measurement reports, harness source and reproduction notes are
in `out/round2-latency/android-sampler-20261015/`.

**YOLO worker-count screen (2026-10-15):** I ran the same 30 s WA0014 crop
and reviewed WA0020 source with the current worktree's YOLO11n candidate
(stride 2, 480 px, fork workers, one Torch thread per worker) at 3, 4 and 6
workers, pinned to six physical host cores. WA0014 pose took 9.918 s / 6.009 s
/ 6.007 s; WA0020 took 3.579 s / 3.366 s / 3.583 s. Four and six workers
were effectively tied in this one-pass screen. All three worker counts
produced bit-identical keypoints for each clip, so the count failures did not
come from chunk-boundary drift: WA0014 emitted two late false muscle-up reps
overlapping the reviewed no-rep window, and WA0020 auto-detected deadlift /
zero / `unmeasured` instead of reviewed push-up / 19. The quality gate failed
all six reports. The first 3-worker WA0014 timing is also an obvious warm-up
outlier relative to the later 4/6 runs; these are not enough repetitions to
change the worker default. The data says worker-count tuning alone has no
quality upside and no stable speed win here; the next server-side work should
target label/count correctness or a different pose execution path, not assume
more chunks will fix the measured-result gate. Keypoint hashes, reports and
the six failure assertions are in
`out/round2-latency/yolo-worker-screen-20261015/`.

**Rechecked screened YOLO count configuration (2026-10-15):** using the same
weights and six-worker fork path with the documented 0.25 minimum-span
amplitude and `ultralytics-screen-v1` fusion, the current worktree passed the
reviewed WA0010 muscle-up / 2 and WA0020 push-up / 19 assertions. Pose took
2.951 s and 3.525 s respectively, with 0.048 s and 0.083 s for measurement.
The exact 30 s WA0014 reviewed window took 8.396 s for pose on the first run
and 5.920 s on the source-window-scoped repeat; measurement took 0.083–0.085 s.
Both runs returned muscle-up / 0 / `unmeasured`. The quality gate failed that
third case specifically because `unmeasured` is not a measured zero; its
reviewed zero still requires the independently validated `geometry_zero`
behavior described above. The three-case gate therefore remains failed (2/3),
even though pose is within its 6–10 s allocation on WA0014. These are local
candidate timings without upload, cloud startup or phone render, and the
screened fusion settings remain experimental. Reports, including the explicit
`sourceWindowS: [0, 30]` zero-case assertion, are in
`out/round2-latency/yolo-screened-recheck-20261015/`.

**Measured-zero data triage (2026-10-15):** the weak-silver corpus offered a
60.07 s pull-up clip whose label claimed zero reps and whose cached geometry
also found zero. Its 2 fps contact sheet shows repeated extended-hang to
raised-pull-up positions, so it is not a clean negative and was excluded from
zero validation. The image and closer 12–24 s sheet are under
`out/round2-latency/geometry-zero-review/`. The scrape labels and cache are
useful candidate-finding signals, not reviewed counts; this leaves WA0014 as
the only reviewed supported-movement zero case in the current manifest. A
second zero-silver knee-raise clip (`youtube_FUnw-dy_rtQ`) visibly contains
repeated hanging knee raises and the cached segmenter found three; its contact
sheet is also under `out/round2-latency/geometry-zero-review/`. Both examples
are excluded from negative validation, reinforcing that model-generated
descriptions and scraped counts need human review before entering the gate.

**1 s sampler in the app (2026-10-15):** I changed the app's closest-frame
motion scan from 0.5 s to 1.0 s and ran the reviewed 20 s WA0020 control
through the debug app against the local API. It uploaded the original full
clip (4,372,595 bytes; `trimConfirmedNs=0`) and rendered `geometry / 19` in
13.898 s from upload-attempt start; the result-to-frame gap was 63 ms and
preparation took 7.187 s. The prior 0.5 s app run took 12.451 s to prepare
the same control. This is a single local-loopback positive-control run, not
a 30 s, production-network, or random-clip acceptance result. The phone report
correctly records one under-15 s measured result but zero quality-approved
results because this run has not passed the complete quality gate. Raw trace
and report: `out/round2-latency/android-sampler-20261015/app-integration/`.

**30 s positive phone run (2026-10-15):** I manually reviewed a 30 s window
`(12.5, 42.5)` from `youtube_PKsKcvDfLCQ`, whose scraped zero label is wrong;
the window contains 10 pull-ups. The local YOLO11n six-worker default-fusion
path returned `geometry / 10`, and the candidate passed the experimental
quality gate. The Android emulator also rendered that measured result, but
took 29.003 s from attempt start (26.800 s submit-to-result, 91 ms
result-to-frame); it is an accuracy-positive, latency-negative run. Upload and
submit took 2.111 s total, and preparation took 11.535 s. The phone recorded
13.464 s in GET polling and 13.267 s sleeping across 26 polls. Its single-run
phone report is `out/round2-latency/geometry-zero-review/phone-timings.json`.

The matching server trace spans 22.071 s. Pose produced all 900 keypoint rows
by 10.616 s; geometry/fusion and all 10 accepted segments were complete by
10.705 s. The advisory technique-vision stage then ran from 11.580 to 22.066 s
and skipped after receiving no usable provider reply. This confirms a 10.486 s
post-measurement stage in the worker trace, but does not by itself explain the
full phone delay: the worker handler writes the measured payload before its
post-result vision work, while the observed phone did not receive `done` until
26.800 s after submit. Emulator polling/GET time consumed most of that tail and
requires a second run with per-GET timestamps plus server upload/job event
timings to separate server availability from emulator scheduling. Do not count
this run as meeting the 15 s target; it establishes a reviewed 30 s positive
control and narrows the next instrumentation experiment.

**Local API parity correction (2026-10-15):** inspection after the 29.003 s
phone run found that its local backend did not match the deployed worker's
first-result path. `server/local_server.py` synchronously localized the clip,
then called `process_job` (measurement plus advisory vision), and only
then marked the job `done`. I changed it to overlap localization with
`measure_job`, publish `done` with the measured payload immediately, and do
localization, replay trimming, advisory vision and prose enrichment afterward.
The local job response now exposes `resultReadyAtEpochMs` and
`serverMeasurementMs`; HTTP request logs carry millisecond wall timestamps so
the first phone poll that sees `done` can be compared with server result-ready
and per-GET response times. A focused test asserts that advisory enrichment
sees the result already published. This fixes the local benchmark path; it is
not yet a measured speedup because the repeat emulator run did not complete.

The earlier phone timing is therefore a valid rendered-count positive
control but not a valid measurement of the intended Round 2 server path. The
emulator was also using a software-rendered AVD and later consumed over two
logical CPUs, so its GET latency is resource-contended evidence. Rerun on the
aligned local backend with a controlled emulator or physical device before
attributing the remaining latency to polling, server work or pose. Keep the
reported 29.003 s as a failed end-to-end sample; do not use it to tune the
poll cadence.

**Correctly configured six-core local worker benchmark (2026-10-15):** the
reusable `scripts/round2_local_fastpath_benchmark.py` now times the local
worker's first measured result separately from post-result enrichment. On the
reviewed 30 s pull-up clip (5,018,982 bytes), pinned to six physical cores and
using the backend's actual `BARRA_YOLO_POSE_*` settings (YOLO11n, stride 2,
480 px, six fork workers), it returned `pull_up / 10 / geometry`. Server
measurement-to-ready was 9.587 s; pose was 8.681 s, including 8.060 s for
chunk workers; per-worker inference was 5.986–6.631 s. Worker return was
11.716 s, including 2.129 s of post-result work. The result JSON and log are
`out/round2-latency/geometry-zero-review/local-fastpath-screened.json` and
`.log`; the trace includes per-stage and per-worker timings. This puts the
server-side candidate inside the allocation but is not an upload-to-phone
pass. Combined with the earlier 2.111 s upload/submit on the same file, only
about 3.3 s remains for polling, response handling and result rendering, so a
phone rerun is still required. Three intervening diagnostics used misspelled
backend environment variables and silently fell back to stride 1 / 640 px;
exclude their 16–18 s timings from Round 2 comparisons.

**Phone repeat on the aligned backend (2026-10-15):** the same 30 s reviewed
pull-up window was uploaded to the corrected local API with the actual YOLO11n
settings (stride 2, 480 px, six fork workers) and rendered as 10 geometric
reps. The app recorded **9.886 s from upload-attempt start to its result
composition callback**: 2.221 s upload+submit, 7.581 s submit-to-result, and
83 ms result-to-callback. It made 10 polls; GET time was 5.193 s and sleep
2.352 s. The server marked the measured result ready 7.375 s after worker
start, and its first GET returning the result was logged 199 ms after that
mark. The app's saved attempt has `countStatus=geometry`, `repCount=10`, and
`renderedNs`; the exact payload independently passed the reviewed `WA9001`
quality gate. The one-attempt report is
`out/round2-latency/geometry-zero-review/phone-timings-fastpath-approved.json`
(under 15 s and quality-approved), with its summary in
`phone-report-fastpath.json`; the exact phone payload, server job response and
poll timeline are also saved in that folder. Preparation took 16.708 s before the
attempt clock, and no trim was confirmed; the prepared and source files were
both 5,018,982 bytes. This is the first full-length, quality-approved local
phone pass, not a random-clip distribution or production-network result. The
emulator used the host GPU and was isolated from pose workers on separate host
CPUs; this remains a local-loopback sample.

**Three-case fusion accuracy matrix (2026-10-15):** I ran the same local
worker, 6-core affinity, YOLO11n/stride-2/480 settings on the manually reviewed
10-rep pull-up window, the reviewed WA0014 `[0,30]` muscle-up zero window, and
the reviewed WA0017 unknown negative. The default phone policy passed the
pull-up, but returned `muscle_up / 0 / unmeasured` for WA0014 and the unsupported
`back_lever / 0 / unmeasured` for WA0017. The screened policy passed WA0017 as
`unknown / 0 / unmeasured`, but abstained on the real pull-up as
`unknown / 0 / unmeasured`; it also left WA0014 unmeasured. The consolidated
six-report gate is saved at
`out/round2-latency/geometry-zero-review/round2-matrix-results.json`, with its
reviewed rows in `round2-matrix-manifest.json` and full payloads beside them.
Only two of the six policy/case combinations pass, and neither policy passes
all three cases.

The confidence values explain why a single global threshold is not a useful
fix: default fusion accepts the pull-up classifier at about 0.615 and the
negative's unsupported back-lever guess at about 0.621. The screened 0.75
threshold rejects both. The next candidate should preserve provisional
model-only labels long enough to test for geometric reps or a measurable hold,
then abstain on a detector disagreement with no corroborating measurement;
independent reviewed cases must verify that this does not erase valid holds or
shallow repetitions. WA0014 remains a separate requirement: a measured zero
needs per-span visibility and a complete physical rejection account, with a
second independently reviewed supported-movement negative before promotion.
Do not lower the threshold or mark the empty segment list as zero.

**Supported-only fusion candidate update (2026-10-15):** the opt-in
`ultralytics-supported-only-v1` rule now keeps ordinary supported-model votes,
chooses a measurable geometric label when its confidence is at least 0.75 and
exceeds a conflicting unsupported model label, and otherwise abstains on that
unsupported disagreement. A GPU screen exposed why the first version needed
the geometry exception: it abstained on WA0020 despite `push_up` geometry at
0.78. After the change the six-core CPU run returned the reviewed `push_up / 19`
result, and WA0017 remained `unknown`. The four-case reviewed gate now passes
WA9001 (10 pull-ups), WA0020 (19 push-ups), and WA0017 (unknown negative), but
still fails WA0014 because its correct-looking zero is `unmeasured`. The exact
four-case manifest and gate reports are in
`out/round2-latency/geometry-zero-review/supported-only-v1-four-case-manifest.json`
and adjacent `*-supported-only-v1-final-report.json` files. Candidate first
results on six-core CPU were 8.543 s for WA9001, 6.823 s for WA0014, 4.989 s for
WA0017, and 4.242 s for WA0020. These are isolated local runs, not a latency
distribution, and the policy remains opt-in.

**GPU comparison (2026-10-15):** one-worker YOLO11n on the local RTX 5060 took
7.450 s to first result for the reviewed 30 s pull-up, versus 8.543 s for the
six-core CPU run. On the same reviewed 20 s push-up, GPU took 7.200 s while
six-core CPU took 4.242 s; both returned 19. The GPU path did not show a
consistent gain, and local GPU timing says nothing about a Lambda CPU worker or
phone, so it is not the Round 2 candidate. Reports are
`WA9001-gpu-single-report.json`, `WA0020-gpu-single-v1-report.json`, and
`WA0020-cpu-six-v1-report.json` in the geometry-zero-review folder.

**Repeat 30 s phone run with the supported-only candidate (2026-10-15):** I
restored the existing API 35 AVD and ran the six-core local API with
`ultralytics-supported-only-v1`. The phone selected the same 5,018,982-byte,
reviewed `[12.5,42.5]` pull-up clip and rendered `DOMINADA / 10 reps` on screen.
Upload-attempt start to result-render callback was **10.195 s**: 2.016 s from
attempt start through upload and submit, 8.112 s submit-to-result, and 67 ms
result-to-render. The API worker published its measured result after 7.950 s;
the first poll returning `done` arrived 151 ms later. Eleven polls consumed
5.582 s in GETs and 2.503 s in scheduled sleeps. The exact phone payload passed
the reviewed WA9001 quality gate. Preparation took 9.180 s before the attempt
clock, and the prepared file remained 5,018,982 bytes; the trim suggestion was
not confirmed. Attempt timing, the one-row approved summary, result payload,
job response and screenshot are saved as `phone-timings-candidate-repeat.json`,
`phone-timings-candidate-repeat-approved.json`,
`phone-report-candidate-repeat-approved.json`,
`phone-result-candidate-repeat-gate.json`, `phone-job-candidate-repeat.json`,
`phone-repeat-final.png`, and `server-polls-candidate-repeat.json` under
`out/round2-latency/geometry-zero-review/`.
The full timing file retains three earlier incomplete attempts; the approved
summary includes only this complete, same-boot attempt. This is a second
reviewed positive local-loopback sample, not evidence that a randomly selected
30 s clip or a physical phone meets the target.

**Seeded random-corpus performance probe (2026-10-15):** using seed
`20261015`, I selected one clip uniformly from the 202 videos in supported
movement folders that are at least 30 s long. The selected source was the
40.72 s `youtube_1Wdn3GhtKkU` muscle-up video; its first 30 s were prepared as a
720p, 30 fps clip. On the first six-core run it returned
`muscle_up / 0 / geometry` in 7.942 s. The trace then showed why that status
was too strong: segmentation proposed two candidates, both starting above the
bar, and measurement rejected both as physically impossible. The relaxed
validator also found no usable rep. I changed the result contract so only
quality-accepted geometric reps set `countStatus=geometry`; a repeated run on
the same clip returned `muscle_up / 0 / unmeasured` in 7.844 s. Reducing the
movement-amplitude floor from 0.25 to 0.15 did not recover a rep. The contact
sheet suggests a ring transition and sustained support but does not establish
a reliable count, so this remains a performance diagnostic, not a quality
gate or phone test. The selected source, prepared clip, contact sheets,
payloads, timings, rescue diagnostic and trace are under
`out/round2-latency/random-sample-20261015/`; the final trace is
`out/traces/261015-163214-a3b593.json`. This is one sampled worker timing, not
a random-clip phone acceptance sample.

**Five-window random-corpus worker cohort (2026-10-15):** using seed
`20261016`, I sampled five distinct videos uniformly from supported-movement
folders with at least 30 s of footage, then sampled a uniform 30 s window from
each and prepared each at 720p/30 fps. With the same six-worker CPU
`yolo11n-pose.pt`, stride-2, 480 px and `ultralytics-supported-only-v1`
configuration, server result-ready times were 8.114, 5.401, 5.532, 5.529 and
5.482 s (median 5.529 s; range 5.401–8.114 s). Four finished within the
8 s server allocation; the first took 8.114 s. These times exclude phone
preparation, upload and rendering. Full worker durations including post-result
prose were 8.619, 6.080, 5.532, 5.886 and 5.482 s. Three results had
`countStatus=geometry`, while two were
`unmeasured`; the outputs were `dip/3`, `dip/2`, `auto/0`, `dip/1`, and
`muscle_up/0`. Contact sheets show that at least two selected windows contain
non-exercise footage (an equipment promotion and a transit scene), while the
`dip`-folder window that visibly shows dips was returned as
`muscle_up / 0 / unmeasured`. The source folders are weak labels, and this
quick visual screen is not a full count review. The cohort therefore measures
worker latency only; it does not pass result accuracy or the upload-to-phone
objective: the transit scene was assigned `dip / 1 / geometry` despite no
visible exercise rep. It also demonstrates why a representative random-phone
gate must sample athlete-recorded exercise clips and review each selected
window, rather than treating arbitrary source-folder windows as ground truth.
Full per-window
payloads, timings, contact sheets and the sampling manifest are in
[`random-cohort-20261016/`](../out/round2-latency/random-cohort-20261016/).

**Reviewed random-window join (2026-10-15):** cohort clip 02 is the same
`youtube_koXdDlPRiQM` source interval `[88.166, 118.166]` that has a
frame-by-frame `dip / 2` review. The cohort's six-worker result on its 1.39 MB
prepared file is also `dip / 2 / geometry`; the exact-window gate passes at
[`clip-02-quality-gate.json`](../out/round2-latency/random-cohort-20261016/clip-02-quality-gate.json)
(5.401 s server measurement; 6.080 s worker total). Separately, the same
source interval was encoded as a 13.87 MB 720p/4 Mbps payload for the phone
upload A/B: its three rendered single-PUT trials took 13.526–14.157 s and
passed the same reviewed movement/count gate. This joins one seeded random
window to valid server and phone evidence, but the phone artifact uses a
different encoding, and the other four cohort windows remain unreviewed or
unmeasurable. It is one reviewed random-window success, not a cohort success
rate or proof for arbitrary athlete-recorded clips.

**Low-confidence disagreement fusion screen (2026-10-15):** the cohort
payloads show that v1 could report `dip / 1 / geometry` on the transit window
when YOLO geometry said `dip / 0.78` and the classifier weakly preferred
`pistol_squat / 0.177`. I added the opt-in
`ultralytics-supported-only-v2` policy: it abstains on that weak supported-label
conflict and only lets geometry overrule a conflicting unsupported model label
when the model confidence is at least 0.70 and geometric confidence is at least
0.75 and higher. It keeps v1's agreement and supported-model rules while
tightening its unsupported-model exception.
Rerunning the five windows changed two apparent false positives to
`auto / 0 / unmeasured`: the squat-like demonstration (`dip / 3` under v1) and
the transit scene (`dip / 1`). An equipment-promotion window remains
`unmeasured`, as does a `dip`-folder window that visibly shows dips but returns
`muscle_up / 0`. A `muscle_up` video window overlaid with “Super Man Dips”
returns `dip / 2`; it is reviewed separately below. These contact-sheet
judgments do not constitute a scored random-clip distribution.

The same policy reran all four reviewed controls: WA9001 remains
`pull_up / 10 / geometry`, WA0020 remains `push_up / 19 / geometry`, and WA0017
remains unknown/unmeasured; each passes its reviewed gate. WA0014 remains
`muscle_up / 0 / unmeasured` and fails the measured-zero requirement, so the
overall gate is still 3/4. Local server result-ready was 5.429 s for WA9001,
3.893 s for WA0020, 4.558 s for WA0017 and 5.156 s for WA0014. The five-window
screen had 4.940–7.564 s result-ready (median 5.165 s). This opt-in policy
does not change pose latency and is not calibrated for production; its 0.70
floor is only a screen between the current WA0020, WA0017 and squat-like
examples. Full outputs are in
[`fusion-v2-final/`](../out/round2-latency/fusion-v2-final/); its screen JSON
contains all nine final-policy worker runs, and its reviewed gate JSON records
the 3/4 result. The earlier intermediate run under
[`fusion-v2-validated/`](../out/round2-latency/fusion-v2-validated/) is
superseded; it exposed and helped fix a v2 unsupported-label regression. The
full suite passed 697 tests with 2 skipped, and focused fusion coverage is 99%.
No upload or phone rendering was included in that worker screen.

**Fusion-v2 30 s phone control (2026-10-15):** on the API 35 emulator, the
existing debug APK imported the same manually reviewed WA9001
`[12.5,42.5]`-second, 5,018,982-byte pull-up clip. It rendered
`pull_up / 10 / geometry` in **8.740 s** from upload-attempt start: 2.018 s
upload + submit, 6.627 s submit-to-result and 94 ms result-to-render. The local
worker published the result after 6.350 s; the transfer was 997 ms at a measured
40.27 Mbit/s. The exact result payload passed the reviewed movement/count gate.
Preparation took 6.951 s before the attempt clock and did not trim the clip.
The screenshot, job payload, exact phone timings, one-row approved report and
quality gate are under
[`fusion-v2-final/`](../out/round2-latency/fusion-v2-final/). This is another
emulator/local-loopback positive control, not a random-clip or production
network acceptance run. The measured random windows still include a missed
dip set, and WA0014 still lacks a measured zero.

**Fusion-v2 seeded random-window phone run (2026-10-15):** after correcting an
initial duplicate-media selection, the API 35 emulator imported the actual
seeded `clip-02` window from the `muscle_up` folder: source interval
`[88.166,118.166]`, 30.033 s and 1,391,452 bytes. The app rendered
`dip / 2 / geometry` in **7.884 s** from upload-attempt start: 2.016 s upload
+ submit, 5.816 s submit-to-result and 50 ms result-to-render. The PUT took
994 ms (11.2 Mbit/s); the local worker reported 5.425 s to result. Eight
status polls consumed 4.045 s in GET calls and 1.752 s in scheduled waits
(the app polls every 250 ms in the fast window). This was initially marked
quality-approved at medium confidence. Decoder-parity investigation later
showed that the host used OpenCV 5.0 while the Lambda image uses OpenCV 4.10;
after pinning local inference to OpenCV 4.10, the same window returns three
reps and fails the reviewed count gate. Treat this 7.884 s phone run as a
historical latency result, not a current quality pass. A later 10 fps
review showed the Lambda-base candidate at 27.57–29.07 s is the demonstrator
being assisted off the bars, without a completed rep. The host and phone count
two under OpenCV 5; the aligned CPU runtime counts three and fails the reviewed
gate. This is a real randomly selected window and an under-15 s phone-path
result, but the video is
not an athlete-recorded set, and the run used emulator loopback. It does not
establish representative random-clip accuracy or real-network latency. The
source clip, exact job payload, timings, screenshot and gate outputs are saved
in [`fusion-v2-final/`](../out/round2-latency/fusion-v2-final/).

**YOLO26 stride-3 check on the same random window (2026-10-15):** to test
whether more sparse inference could lower the dominant pose stage, I ran the
same 30.033 s, 1,391,452-byte `clip-02` through the YOLO26n-pose checkpoint
with six fork workers, stride 3, `imgsz=480`, one Torch thread per worker and
fusion v2. This is a sequential local screen, not a paired production trial.
It returned `auto / 0 / unmeasured` in 6.758 s to first result; pose took
5.975 s (5.834 s worker wall, 0.138 s decode). The exact report failed the
window-specific gate: reviewed `dip / 2 / geometry` expected. For comparison,
the prior YOLO11n stride-2 run on this same window took 5.425 s to first result
and passed the gate, though the runs were not paired. YOLO26 stride 3 is
therefore not a safe speed setting for this sample; reducing sampled frames
can erase the repetitions being counted. Candidate timing, exact report and
failed gate are `random-yolo26-stride3.json`,
`random-yolo26-stride3-report.json` and `random-yolo26-stride3-gate.json` in
the `fusion-v2-final/` folder.

**Production runtime parity gate (2026-10-15):** the latest local phone timings
use opt-in YOLO; the deployed `WorkerFunction` still selects MediaPipe Heavy
and leaves `BARRA_POSE_WORKERS` unset, which means one sequential worker. The
production worker requirements also omit Ultralytics and PyTorch. Thus local
5–8 s worker results and sub-15 s emulator runs do not predict the deployed
Lambda's result time. The next deployment experiment is a separately pinned
shadow Lambda image with the six-core candidate; record cold and warm image
initialization, dispatch/download, pose, measurement, persistence and first
result for a reviewed 30 s cohort, then apply the exact-payload quality gate.
Keep production defaults unchanged until that image passes the reviewed gate
and a physical-phone run passes over a measured uplink. The current local
trace attributes 5.358 s of its 5.422 s to pose, of which 5.145 s is the six
inference workers; decode is 0.208 s and merge/densification are below 1 ms.
This makes model/inference quality the primary local pose tradeoff, rather
than decode or merge micro-optimization.

**Lambda-base shadow image smoke (2026-10-15):** I added the isolated
`server/Dockerfile.round2-yolo` build target. It uses the Lambda Python 3.12
base, six CPU workers, stride 2 at 480 px, PyTorch CPU 2.14.1, Ultralytics
8.4.166 and the SHA-pinned YOLO11n checkpoint; `server/deploy.sh` and the
production `Dockerfile` do not select it. The image built locally at 3.21 GB
(image digest `f9e754e20a4fc2696e6538f013f70e58646c4e2fb270c659755fa52e73a68008`),
and an import smoke loaded OpenCV, PyTorch, Ultralytics and `handler.worker`.
This is a Lambda-base container screen with a six-CPU Docker quota, not an
AWS Lambda invocation. On the exact random 30 s phone source window, with the
same explicit `dip` selection sent by the phone, it returned `dip / 3 / geometry`
in 4.879 s to first result (5.664 s total worker), while the host runtime
returns two. The 10 fps review confirms the third segment is an assisted
dismount, so the exact-payload gate fails on the overcount.
With `auto`, the container abstains as `unknown / 0 / unmeasured`; that is a
separate request mode and also does not pass this reviewed window. These results
show that the Lambda-base package is executable and fast locally, but runtime
parity and count quality are not established. The build target and outputs are
`server/Dockerfile.round2-yolo`, `random-yolo11-lambda-base-dip.json`,
`random-yolo11-lambda-base-dip-report.json` and
`random-yolo11-lambda-base-dip-gate.json` in `fusion-v2-final/`.

A same-source host rerun with the same explicit `dip` request returned two
reps, in 7.508 s to first result. Both runs
used YOLO11n SHA `869e83…19dc0`, Ultralytics 8.4.166, stride 2, 480 px and
CPU inference; the host had PyTorch `2.14.1+cu130`, while the Lambda-base
image has `2.14.1+cpu`. The timings are sequential, not a controlled latency
pair, but the one-rep discrepancy is an accuracy failure that must be resolved
before AWS timing. It makes exact runtime-wheel and keypoint parity part of the
candidate gate, not merely a packaging check. The passing host report and gate
are `random-yolo11-host-cpu-dip-report.json` and
`random-yolo11-host-cpu-dip-gate.json` in the same folder.

To localize the drift, I saved both 901-frame pose arrays under
`host-keypoint-runtime/poses/` and `docker-keypoint-runtime/poses/`. They are
not identical: among landmarks visible in both arrays, absolute XY drift is
1.214 px mean / 2.628 px p95, with eight frames exceeding 100 px. A second
shadow-image run reproduced its first array bit-for-bit and again returned
three reps. The CPU-wheel result is therefore repeatable within this image but
not measurement-parity with the host wheel. The cross-runtime discrepancy is
already visible in pose output, before segmentation or scoring; any future
quality gate must run on the exact deployment wheel and architecture.

**Six-CPU inference batch screen (2026-10-15):** I compared Ultralytics
`batch=1` with `batch=4` on the same 901-frame random tutorial window, sampling
every other frame at 480 px with six workers in the pinned Lambda-base image
under a six-CPU quota. Batch 1 took 4.633 s for the chunk inference pipeline;
batch 4 took 4.669 s. Both produced the exact same dense keypoint SHA-256
(`5b2392…34445`), but the 0.8% timing difference favors batch 1 and is within
run noise. Batching is therefore not a useful latency lever for this candidate;
the default and production code remain unchanged. This was a two-run screen on
one clip, not a cohort benchmark. Raw timings and hashes are in
[`batch-inference-screen.json`](../out/round2-latency/fusion-v2-final/batch-inference-screen.json).

**Pinned Lambda-base reviewed cohort (2026-10-15):** I mounted the current
worktree into the pinned Lambda Python 3.12 shadow image and ran five reviewed
inputs with six CPUs, stride 2, 480 px, one Torch thread per worker and the
supported-only-v2 fusion policy. Pose took 2.01–4.99 s and measurement
0.049–0.113 s, excluding dispatch, image initialization, S3 download, phone
upload/polling and render. WA0010 muscle-up / 2, WA0017 unknown abstention,
and WA0020 push-up / 19 passed their current checks. WA0014's reviewed
`[0,30]` zero-rep window instead emitted two late muscle-up reps, both
overlapping the reviewed no-rep interval; its exact-payload gate failed.
WA0018 correctly remained unmeasured but emitted a muscle-up model label, so
its unreviewed abstention assertion remains a coverage gap. The cohort is
therefore a pose-budget pass but not a measured-result quality pass. Exact
reports, per-worker timings, keypoint arrays and the gate are in
[`docker-reviewed-cohort/`](../out/round2-latency/fusion-v2-final/docker-reviewed-cohort/).

The worker now measures its synchronous stage-table and upload-log writes,
S3 download, processing-status write and first-result persistence separately.
Those diagnostics are attached to the post-persistence `worker-timing` event
and surfaced by `scripts/job_timing.py`; stage updates remain synchronous. The
next AWS shadow cohort can identify whether telemetry writes materially affect
first-result latency before any are moved off-path.

**Reviewed cohort amplitude-floor screen (2026-10-15):** I reran those same
five inputs in the same six-CPU Lambda-base image and policy, changing only the
experimental minimum active-span amplitude from 0.15 to 0.25. The five saved
pose arrays stayed byte-identical, and pose time remained 1.97–4.92 s. WA0010
still returned muscle-up / 2, WA0020 push-up / 19, and WA0017 abstained as
unknown. WA0014's two false late reps disappeared; the result is now
muscle-up / 0 / `unmeasured`. The gate therefore still fails the reviewed
measured-zero assertion, and WA0018 remains a review-coverage gap, but the
candidate removes a false-positive count without changing pose or positive
counts in this small cohort. Keep 0.25 experimental: one negative clip does
not validate measured-zero behavior. Reports and the exact gate are in
[`docker-reviewed-cohort-amplitude025/`](../out/round2-latency/fusion-v2-final/docker-reviewed-cohort-amplitude025/).

**Status-contract recheck on the four reviewed clips (2026-10-15):** after
changing geometric counts to require at least one usable, quality-accepted
rep, I reran the same six-core candidate and four-case manifest. WA9001 remained
`pull_up / 10 / geometry` (8.479 s to first result), WA0020 remained
`push_up / 19 / geometry` (4.236 s), and WA0017 remained `unknown` (4.840 s).
WA0014 remained `muscle_up / 0 / unmeasured` (6.685 s), and therefore still
fails the measured-result gate. The fresh gate output is
`out/round2-latency/geometry-zero-review/status-fix-four-case-results.json`;
it passes three reviewed controls and fails WA0014 for the expected reason.
`uv run pytest -q` passed 694 tests with 2 skipped. This verifies that the
status correction preserves the reviewed positive and unknown cases; it does
not validate measured-zero behavior.

**Per-span coverage tracing (2026-10-15):** I extended the segment trace to
record observed and total pose frames for each active span, alongside its
existing amplitude and candidate rejections. On replay of the saved WA0014
six-CPU pose array, the three active spans were fully observed (273/273,
97/97, 113/113), despite overall coverage of 732/894 frames. The candidate at
22.89 s still fails the muscle-up rest-posture check (0.613 torso lengths
above the hands; maximum 0.30), and count status remains `unmeasured`. This
provides the coverage and rejection evidence needed for a shadow-rule screen;
it does not establish that every shallow rep would be detected. The trace
change is covered by the active-span test in `tests/test_trace.py`; the focused
trace and segmentation suite passed (31 tests).
The saved-pose five-clip guard screen keeps WA0010/WA0020 as positive controls,
WA0017 as unknown abstention and WA0018 as no-active-span abstention; WA0014 is
the only negative candidate and is explicitly marked as needing independent
review. See
[`zero-coverage-shadow-screen.json`](../out/round2-latency/fusion-v2-final/docker-reviewed-cohort-amplitude025/zero-coverage-shadow-screen.json).
This screen adds no pose-time evidence and does not change the measured-result
gate.

**CPU-wheel count-threshold sweep (2026-10-15):** to test whether a cheap
segmentation adjustment could resolve the random-window host/CPU discrepancy,
I replayed the saved Lambda-base CPU poses while crossing minimum turnaround
height 0.60–0.90 and minimum active-span amplitude 0.15/0.25. Raising the
turnaround threshold did not remove the third assisted-dismount count on the
random dip clip; at 0.90 it reduced WA0020 from 19 to 15. The 0.25 amplitude
floor removed WA0014's false late reps in this crop, but did not change the
random dip overcount. No tested threshold satisfies both targets, so I did not
promote one. The exact result matrix is
[`cpu-wheel-count-threshold-sweep.json`](../out/round2-latency/fusion-v2-final/cpu-wheel-count-threshold-sweep.json).

**Six-core CPU pose-resolution screen (2026-10-15):** I tested 416, 448 and
512 px on the same reviewed random 30 s dip window plus WA0010, the prepared
WA0014 first-30-second window and WA0020, with the pinned Lambda-base image,
six fork workers, stride 2 and supported-only-v2 fusion. All three resolutions
returned the random window's reviewed dip / 2 and took 4.05, 4.25 and 5.21 s
for pose. But 416 lost one WA0010 rep and invented one on WA0014; 448 preserved
WA0010 but invented two WA0014 reps and lost one WA0020 rep; 512 preserved
WA0010 but invented two WA0014 reps and lost thirteen WA0020 reps. At 480 px
with the experimental 0.25 amplitude floor, WA0010/WA0020 are correct and
WA0014 is zero / `unmeasured`, but the random dip still overcounts three.
Therefore no tested global resolution/floor combination passes the full
reviewed measured-result gate. Keep 480/0.25 as a diagnostic candidate only;
do not trade away these counts for the faster random-window screen. Per-input
times, counts and gate dispositions are in
[`cpu-resolution-screen.json`](../out/round2-latency/fusion-v2-final/cpu-resolution-screen.json).

**Host/Lambda decoder parity root cause (2026-10-15):** the host dependency
lock had OpenCV 5.0.0.93, while the Lambda worker image pins
`opencv-python-headless==4.10.0.84`. Both decoded the same 901 frames at 30 fps
and 720×406, but all 901 per-frame BGR hashes differed; sampled pixels had
0.353 mean absolute difference (p95 3, max 14 on 8-bit channels). Running host
CPU inference with OpenCV 4.10 produced pose arrays byte-for-byte equal to the
Lambda CPU arrays on the random dip window, WA0010, WA0014 and WA0020. This host
used PyTorch 2.14.1+cu130 in CPU mode; Lambda used 2.14.1+cpu, with the same
reported MKL-DNN 3.12 and AVX512 capability. The regular
`opencv-python==4.10.0.84` wheel produced pixel-identical frames to Lambda's
headless 4.10 wheel, so the project dependency is now pinned to that version;
`uv.lock` was regenerated and a deploy-contract test prevents drift. The
aligned local server now reports `dip / 3 / geometry` in 7.681 s and fails the
reviewed count gate. A full-rate six-worker 480 px screen took 7.871 s for pose
and preserved WA0010 / 2 and WA0020 / 19, while still returning three on the
random window; the exact gate fails `3 != 2`. WA0014 remained zero /
`unmeasured`, which separately fails the measured-zero gate. Decoder parity is
fixed, but there is still no quality-passing random result. The exact stride-1
gates are in
[`docker-stride1-amplitude025/random-gate.json`](../out/round2-latency/fusion-v2-final/docker-stride1-amplitude025/random-gate.json)
and
[`geometry-zero-gate.json`](../out/round2-latency/fusion-v2-final/docker-stride1-amplitude025/geometry-zero-gate.json).
The decoder and pose hashes,
current local result and failed gate are in
[`opencv-runtime-parity.json`](../out/round2-latency/fusion-v2-final/opencv-runtime-parity.json);
the stride-1 results are in
[`docker-stride1-amplitude025/`](../out/round2-latency/fusion-v2-final/docker-stride1-amplitude025/).

**YOLO11s supported-label arbitration screen (2026-10-15):** a fresh run in
the six-CPU Lambda-base shadow image used the current mounted source, YOLO11s
checkpoint SHA `1060bda4…7ebc2ba`, stride 2, 480 px, and 0.25 span-amplitude
floor. The reviewed random 30 s window returned dip / 2 in 8.262 s pose and
8.383 s through measurement; its exact window gate passes. I added the opt-in
`ultralytics-geometry-supported-v3` policy: on a supported-label conflict,
geometry takes precedence only at confidence ≥0.75, while unsupported model
labels retain v2 abstention behavior. With that policy, WA0010 returned
muscle-up / 2 in 4.585 s through measurement and WA0020 push-up / 19 in 4.933
s; WA0017 remained unknown in 6.392 s. WA0018 is still a review-coverage gap.
The exact five-case gate fails only WA0014 because its correct-looking
muscle-up / 0 remains `unmeasured`, so this candidate is not fully quality
approved. The earlier cached-pose replay that counted two false reps used the
current source with an older report's saved poses and is superseded by this
same-image, fresh-pose run. Reports, saved poses and both exact gate outputs
are under
[`docker-yolo11s-v3-fresh-gate/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-fresh-gate/);
the raw reports are under
[`docker-yolo11s-v3-fresh-reviewed/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-fresh-reviewed/)
and
[`docker-yolo11s-v3-fresh-random/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-fresh-random/).
This is server-container evidence only. No Lambda invocation or upload-to-phone
result was measured, and the unsupported 0.75 conflict rule remains a small
screen rather than a general calibration.

**YOLO11s seeded random-cohort timing screen (2026-10-15):** I ran the same
candidate on all five 30 s windows from seed `20261016`. Pose took 7.652–8.354
s and pose-plus-measurement took 7.754–8.483 s. Only the already frame-by-frame
reviewed dip window (clip-02) is known to be correctly measured: dip / 2, with
its exact gate passing. The other four results were three `unmeasured` outputs
and one unknown; their source-folder exercise tags are sampling metadata, not
reviewed labels. Several contact sheets contain instruction, equipment-demo,
or montage footage rather than a clean athlete set. This screen therefore
shows repeatable pose-budget performance on five files, but only one reviewed
quality pass and no representative random-user success rate. Full per-window
timings and report links are in
[`docker-yolo11s-v3-random-cohort/cohort-summary.json`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-random-cohort/cohort-summary.json).

**YOLO11s random-window emulator upload-to-render run (2026-10-15):** I built
the current debug APK for `http://10.0.2.2:8081`, installed it on Android 35
x86_64, and uploaded the same 30.033 s, 1,391,452-byte reviewed source window
through the app to a `local_server.py` instance running inside the six-CPU
Lambda-base shadow image. I selected the whole clip: the app's suggested
1–21 s crop would not be the reviewed `[88.166,118.166]` window. The two
container-backed attempts rendered the reviewed `dip / 2 / geometry` in
**14.313 s** and **12.953 s** from the phone's upload-attempt clock; both exact
payload quality gates pass. The candidate-only phone report is 2/2 under 15 s
(p50 13.633 s, p95 14.245 s). Across all three completed phone attempts on
this AVD, including the preceding host-backed attempt at 18.444 s, 2/3 were
under 15 s; the two passing rows are explicitly tagged as the shadow-container
runtime. PUT time was 0.955–1.000 s, and upload plus job creation/submit was
2.012–2.022 s. The worker's end-to-end traces measured pose at 10.416 s and
10.028 s, slightly beyond the 10 s pose allocation; server result-ready was
12.327 s and 10.179 s after worker start. Thus the upload-to-render target
passed twice for this one reviewed random window, while the pose sub-budget is
still tight and variable. Phone-side file copy/scan took 3.965–4.502 s before
the upload-attempt clock; it is outside the stated upload-to-result metric and
remains a separate user wait. This is emulator/local-loopback evidence, not a
physical phone, AWS Lambda invocation, S3 transfer, or production-network
result. Exact phone timing rows, candidate-only and all-attempt summaries,
both payload gates, worker trace, job payloads, and screenshots are saved in
[`docker-yolo11s-v3-fresh-gate/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-fresh-gate/).

**Rejected YOLO11s lower-resolution variant (2026-10-15):** dropping
`imgsz` from 480 to 448 reduced the fresh random-window pose time from 8.262
to 7.537 s, but the result changed from 2 to 4 reps and failed the exact
frame-by-frame count gate. Keep the 448 px setting rejected; it cannot be used
to buy extra latency margin. Its report and gate are under
[`docker-yolo11s-v3-random-448/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-random-448/).

**YOLO11s worker-count screen on the reviewed random window (2026-10-15):** I
held the exact 30.033 s, 1,391,452-byte source, six-CPU Lambda-base image,
YOLO11s weights SHA, stride 2, 480 px input, `min_span_amplitude=0.25`, fork
mode and v3 fusion policy constant, then varied only worker count. Pose took
11.863 s at 3 workers, 8.650 s at 6, 9.209 s at 8, and 8.385 s on a repeat at
6. All four runs returned reviewed `dip / 2 / geometry` and passed the exact
window gate. The pose-keypoint SHA was identical across worker counts, so the
count parity here also comes from byte-identical inferred arrays. The three-
worker run exceeds the 8 s pose allocation by 3.863 s; oversubscribing the
six-core limit to eight was 0.559–0.824 s slower than the two six-worker runs.
This supports six workers for this workload and argues against reducing the
worker count to save overhead. It is a four-run screen on one reviewed window,
not enough to claim a general speedup distribution or resolve the end-to-end
pose trace variability (10.028–10.416 s on phone runs). Per-run reports,
keypoints and the combined passing gate are in
[`docker-yolo11s-workers-screen/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-workers-screen/).

The same screen also compared six-worker `subprocess` mode with the selected
six-worker `fork` mode. Subprocess mode took 10.197 s for pose (versus 8.385 s
and 8.650 s in fork mode), and each child spent 0.664–0.893 s importing the
runtime before inference. It still produced the same pose-array hash and
passed the exact reviewed count gate. Keep fork mode for this CPU worker; the
subprocess alternative adds measurable startup and serialization overhead
without changing this result. See the combined gate and reports linked above.

**Pose-wall timing correction (2026-10-15):** the backend's old `total_seconds`
started after `from ultralytics import YOLO`, so a cold process could omit
model-package import from the reported pose total. Full-worker instrumentation
on the reviewed random window measured backend lookup at 0 ms, end-to-end
`estimate()` at 8.518 s, and backend-internal time at 8.504 s. The backend now
records `model_import_seconds` separately and starts its total timer before
that import; this run attributed 0.693 s to import, 0.180 s to decode,
7.628 s to chunk inference/merge and under 1 ms to densification. The exact
`dip / 2 / geometry` window gate passed. Analysis imports, backend availability
and ffprobe were 2 ms, 0 ms and 4 ms respectively. This makes cold worker pose
accounting complete; it does not make the 0.693 s disappear, and a warm worker
may have already paid that import before a job. The trace now also compares
outer `estimate()` wall time with backend timing so any future residual is
visible. Full-worker result, timing and gate are under
[`docker-yolo11s-instrumentation-screen/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-instrumentation-screen/).

**YOLO11s stride-3 speed screen and emulator upload-to-render (2026-10-15):**
I changed only pose sampling stride from 2 to 3, keeping the YOLO11s weights,
480 px input, six fork workers, one CPU thread per worker and v3 fusion policy
fixed. On a six-case screen (reviewed WA0010, WA0014 `[0,30]`, WA0020 and the
random dip window, plus the WA0017/WA0018 abstention controls), all movement/count/status outputs
matched the stride-2 screen. The pose arrays differ because stride 3 samples
fewer frames and interpolates the gaps; this is not bitwise inference parity.
Pose time fell 16.6–33.1% across the six cases. On the reviewed random window
it fell from 8.262 to 5.524 s, with the exact `dip / 2 / geometry` gate passing.
WA0010 remained muscle-up / 2, WA0020 push-up / 19, WA0017 stayed unknown, and
WA0018 remained a coverage gap. WA0014 stayed `unmeasured`, so the same full
control gate still fails its measured-zero requirement. No new zero behavior
was inferred from the faster sampling.

I then built a debug APK pointed at a separate API 35 emulator loopback server
using stride 3 and submitted the exact same 30.033 s, 1,391,452-byte source
file twice without trimming or re-encoding. Both app-rendered payloads passed
the exact reviewed window gate at `dip / 2 / geometry`. Upload-attempt-to-render
took 11.311 s and 9.777 s (p50 10.544 s); the prior two stride-2 runs were
14.313 s and 12.953 s (p50 13.633 s), a 22.7% p50 reduction in this small,
non-paired emulator sample. Server first-result times were 8.640 s and 7.187 s;
the matching pose traces were 8.068 s and 7.044 s, including model import.
Upload PUT took 0.957–0.987 s, while job creation plus PUT plus submit took
about 2.0 s. Phone file preparation took 4.275–4.540 s before the upload clock
and remains a separate user wait. This is promising evidence for stride 3,
not a production setting decision: the six-case screen is small, the random
window is the only frame-by-frame reviewed clip, keypoint arrays differ, and
there is no physical-phone, production-network, AWS Lambda or S3 timing. Keep
it as an opt-in shadow candidate pending broader reviewed positive/negative
coverage and target-runtime validation. Full worker reports, both phone
payload gates, timings, traces and screenshots are under
[`docker-yolo11s-stride3-screen/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/).

**Import-overlap timing probe (2026-10-15):** I added a best-effort one-shot
Ultralytics package import on a daemon thread when the local API receives the
clip, then joined it before analysis. On one warmup-enabled emulator upload of
the same random source, the import took 815 ms and the worker waited 281 ms after
the request reached analysis; its server first result was 8.092 s and
upload-attempt-to-render was 10.848 s. The trace records 380 ms for analysis
imports, 7.263 s pose wall time, and 7.254 s internal pose time. I reran its
exact `dip / 2 / geometry` payload through the [supplemental frame-by-frame
window review](../out/round2-latency/fusion-v2-final/random-dip-window-review-manifest.json)
(the root sample manifest remains limited to root clips); the exact gate
passes with no coverage gaps. The [one-row approved phone report](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/warmup-phone-report-approved.json)
records 10.848 s, 1/1 under 15 s, and the [exact gate](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/warmup-phone-random-window-quality-gate.json)
passes. This remains one emulator/local-loopback run
on a tutorial montage, not an athlete-recorded set or a production-network
sample, and it is slower than the 9.777 s stride-3 repeat.
The worker now starts the same optional import before S3 download and joins
it afterward; it is a no-op unless `BARRA_POSE_BACKEND=ultralytics`.
`BARRA_POSE_RUNTIME_WARMUP=false` disables the hook for a paired control, and
the worker timing record captures import elapsed and wait milliseconds. The
S3/Lambda benefit remains unmeasured; worker ordering has unit coverage only.
The phone payload, approved timing row and trace are under
[`docker-yolo11s-stride3-screen/`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/).

**Paced import-overlap A/B (2026-10-15):** I compared fresh six-CPU
YOLO11s/stride-3 local containers, changing only
`BARRA_POSE_RUNTIME_WARMUP` and reversing run order. I paced the exact
1,391,452-byte upload to 0.956–0.963 s, close to the phone PUT measurements.
With warmup enabled, the 955–956 ms Ultralytics import finished during the
upload (`waitMs=0`); the disabled control imports on the inference path. In
control-then-warmup order, server result-ready fell from 7.120 to 5.962 s; in
warmup-then-control order it fell from 6.616 to 6.063 s. That is a 0.856 s
mean server-path difference across two reversed pairs. The direct client
upload-attempt-to-result times differed by 1.196 s and 0.807 s, a 1.002 s
mean in this tiny screen. All four `dip / 2 / geometry` outputs pass the
supplemental exact-window quality gate. These are still host-loopback timings,
not phone results, and shared host page cache plus four total runs leave
substantial variance. The paired artifacts
are summarized in
[`warmup-paced-summary.json`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/warmup-paced-summary.json), with each paired job payload beside it. Container logs record exact warmup elapsed/wait and result-ready values. Keep the feature opt-in for Ultralytics and validate it on a real S3/Lambda invocation before deployment.

**WA0014 in-app trim fallback (2026-10-15):** I selected the reviewed
`[0,30]` s negative window, adjusted the app crop to `0.1–29.3` s, and
confirmed it. Export failed immediately with `Transformer is accessed on the
wrong thread`, so the app fell back to uploading the full 40.4 s, 9.85 MB
source. The full-source result arrived 13.745 s after the upload-attempt clock
and reported one geometry-counted muscle-up at 31.92–34.13 s, outside the
reviewed window. This does not establish the crop's result or a valid 30 s
quality pass. The fallback upload used 3.55 s across job creation, multipart
start/presign/transfer/complete and submit; worker first-result time was
9.658 s. The device timing summary is
[`wa0014-trim-fallback-summary.json`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-trim-fallback-summary.json), the [job payload](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-full-upload-job.json) and [screenshot](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-full-upload-result.png). Android trim implementation is being changed elsewhere, so I left that code alone.

**Current WA0014 crop replay (2026-10-15):** I ran the prepared 14.6 MB
`[0,30]` s crop through the current six-worker YOLO11s stride-3 geometry
candidate in the worker container. Pose took 6.493 s, measurement 0.127 s,
and total candidate time 6.620 s. It returned `muscle_up / 2 / geometry`,
with intervals 27.05–28.42 s and 28.42–29.80 s. The default reviewed-manifest
gate fails both reps against WA0014's reviewed zero-rep `[0,30]` window and
flags both intervals as overlaps. This confirms the candidate is not quality
eligible for this negative window even though its pose path meets the 15 s
latency target in isolation. Report and timing breakdown:
[`wa0014-first30s-720p-4mbps.json`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-first30-current/WA0014-first30s-720p-4mbps.json);
reproduce the hard gate with
`python scripts/round2_quality_gate.py out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-first30-current/WA0014-first30s-720p-4mbps.json`.
The next candidate must suppress stationary-window false reps while retaining
the exact-window reviewed positive gates; further pose speedup alone does not
close this blocker.

**WA0014 amplitude-floor paired replay (2026-10-15):** with the same source,
YOLO11s weights, six-worker stride-3 geometry policy and container, raising
only `min-span-amplitude` to 0.25 changed the result from two false geometry
reps to `muscle_up / 0 / unmeasured`. Pose took 6.658 s and measurement
0.119 s (6.777 s total), compared with 6.493 + 0.127 s (6.620 s) at the
default floor. The quality gate now fails only because `unmeasured` is not a
measured count; it no longer finds reps overlapping the reviewed not-rep
interval. This single negative pair supports the floor as a shadow quality
screen, not as a global setting: positive-control WA0010/WA0020 checks with
these exact weights, stride, fusion policy and floor remain necessary before
considering it. The floor-specific payload is
[`WA0014-first30s-720p-4mbps.json`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-first30-current-amplitude025/WA0014-first30s-720p-4mbps.json); its gate has no count/interval mismatch but does fail measured status.
The existing stride-3 WA0010 and WA0020 reports use the same checkpoint SHA
`1060bda4…7ebc2ba`, 0.25 floor, six-worker fork mode, 480 px input and
`ultralytics-geometry-supported-v3` policy. Replaying the quality gate on those
positive controls passes both reviewed counts (`muscle_up / 2` and `push_up /
19`). Thus the available five-clip evidence shows the floor can suppress this
WA0014 negative while preserving those two positive anchors, but WA0014 still
fails measured status, WA0017/18 and WA0019 remain additional abstention
controls, and the pass is not one uniform, independently repeated cohort run.

**Uniform stride-3 reviewed-cohort gate (2026-10-15):** I replayed the hard
quality gate over the five saved reports using one exact candidate config:
YOLO11s checkpoint SHA `1060bda4…7ebc2ba`, six fork workers, stride 3,
480 px, 0.25 span-amplitude floor and
`ultralytics-geometry-supported-v3`. The gate passes WA0010 (`muscle_up / 2`),
WA0017 (`unknown / 0 / unmeasured`) and WA0020 (`push_up / 19`). WA0014 fails
because its reviewed zero remains `unmeasured`; WA0018 is incomplete because
its movement/count is not reviewed. Thus all explicit positive and unknown
assertions pass, but the reviewed-zero acceptance does not. The saved
[uniform gate result](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/uniform-five-clip-quality-gate-2026-10-15.json)
keeps all five outcomes. Pose took 2.521–5.707 s and local measurement
0.035–0.105 s across these existing host-container reports; these times do not
include upload or phone render and must not be compared directly with the
under-15 end-to-end goal. They do show pose is within its 6–10 s allocation on
this five-clip screen.

**Phone-to-worker variance reconciliation (2026-10-15):** I joined six phone
attempts to their worker traces using trace IDs and timing rows from the same
emulator boot. The three YOLO11s stride-3 runs on the reviewed 30.033 s dip
window took 11.311, 9.777 and 10.848 s from upload start to first render; all
three payloads pass the exact `dip / 2 / geometry` gate. Their worker pose
times were 8.068, 7.044 and 7.254 s. A later same-window attempt took 18.444 s,
but its trace reports a different dirty commit and Python 3.12.14 (candidate
traces report `round2-shadow`, Python 3.12.15); worker pose rose to 13.469 s,
with all six inference workers taking 12.72–13.06 s. This is not a controlled
stride-3 repeat and points to server runtime/inference drift, not polling
cadence. Its 9.508 s cumulative GET time overlaps worker execution and cannot
be added to pose time as a separate cost. The three-run pass is still a small
local-loopback sample on one reviewed tutorial window. Keep the current stage
budget, and pin image, commit, weights, stride, worker count and runtime for the
next A/B. The joined rows and exact trace metrics are in the
[`runtime variance audit`](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-runtime-variance-audit-2026-10-15.json).

**Lambda-base image parity diagnostic (2026-10-15):** The isolated local image
uses the candidate Lambda Python base, pinned YOLO11s checkpoint, six fork
workers, stride 3, 480 px and amplitude floor 0.25. Its random dip window and
reviewed WA0010/WA0020 positives pass; the WA0014 first-30-second window returns
zero reps but `countStatus=unmeasured`, so the measured-zero gate remains open.
Pose runs took 3.577–6.644 s and measurement 0.084–0.106 s. This image came
from a dirty checkout and the measurements exclude AWS startup, transport and
phone rendering; they are runtime-parity evidence, not deployment or <15 s
end-to-end acceptance. Per-run provenance, config, image digest and gate files
are in the [diagnostic manifest](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/lambda-image-candidate/runtime-parity-2026-10-15.json).

**Phone timing snapshot and later full-source attempt (2026-10-15):** The
current app log contains seven complete attempts from one emulator boot; six
were below 15 s, with mixed-input p50 12.953 s and p95 17.205 s. This is not a
quality-approved distribution. The three exact reviewed 30.033 s dip-window
runs remain the comparable evidence: 9.777–11.311 s, 2 reps each, all passing
the reviewed gate. A later 40.4 s WA0014 full-source attempt took 13.744 s from
network start to render; its local stride-2 worker returned one muscle-up at
31.32–34.73 s, outside the reviewed `[0,30]` interval. It therefore remains
unreviewed. Phone preparation took 12.525 s before the upload timing origin;
this is useful for the broader pick-to-result path, but not part of the defined
upload-to-result measurement. See the [snapshot](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-summary-snapshot-2026-10-15.json)
and [trace join](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-phone-run-164143-summary.json).

**Controlled current-app emulator run (2026-10-15):** I rebuilt the current
Android app to target the live stride-3 shadow worker through the emulator’s
`10.0.2.2` host bridge, then ran the reviewed 30.033 s clip through the picker
and result UI. Upload-to-visible-frame was 9.922 s: 2.082 s to submit, 7.745 s
from submit to result receipt, and 95 ms to the visible frame. The worker
returned 2 geometry-counted dips and passed the exact source-window gate. Its
server measurement was 7.616 s; this does not isolate pose from the rest of
worker processing. The phone uploaded the full file because the suggested
`[1,21]` s trim was not supported by the full-window review. This is a local
emulator/host-bridge measurement without shaping or AWS startup, not a physical
network distribution. See the [run manifest](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-controlled-run-2026-10-15-172004.json)
and exact [quality-gate result](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-quality-gate-2026-10-15-172004.json).

**Shaped large-clip Android experiment (2026-10-15):** Rebuilt the current
app against a host-side byte-paced proxy at 30 Mbps and uploaded the reviewed
13.87 MB, 720p derivative through the real picker and result screen. The
multipart body phase measured 3.751 s, validating the proxy rate; upload-start
to rendered result was 15.508 s (6.114 s upload-start to submit, 9.274 s
submit to result, 119 ms result to frame). The result was `dip / 2 / geometry`
and passed the exact source-window gate. Server aggregate measurement was
8.533 s, not a pose-only timing. This single emulator run misses the target by
0.508 s; one prior same-size result was not rendered and remains incomplete.
At that earlier collection point, 13/15 attempts completed and 10/15 were
under 15 s, but the aggregate mixed clips and included incomplete attempts, so
it was not a quality-approved rate. The long submit-to-result span
and multipart request overhead are the next design targets. See the [run
manifest](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-large-clip-shaped-2026-10-15-173042.json),
[attempt log](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-timings-current-2026-10-15.json),
and [reviewed gate](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-quality-gate-2026-10-15-173042.json).

**Same-file single-PUT comparison (2026-10-15):** The debug build's existing
size threshold was set to 16 MiB, switching the 13.87 MB reviewed input from
multipart to a single PUT without source changes. Under the same byte-paced
30 Mbps proxy, upload-start-to-submit fell from 6.114 s to 4.901 s and total
upload-start-to-visible fell from 15.508 s to 13.526 s on the first trial.
Across three rendered single-PUT trials, totals were 13.526–14.157 s (median
13.580 s); all passed the exact source-window gate at `dip / 2 / geometry`.
Their upload-start-to-submit spans were 4.901–5.031 s. Body phases were
3.751 s multipart and 3.773–3.777 s single PUT, so the observed improvement
came from removing multipart start, per-part presigning and completion
round trips. One additional single-PUT attempt produced a retrievable,
quality-gate-passing server result but no phone render, so it remains
incomplete. The successful single-PUT server aggregates were 8.417–8.459 s;
they include the full worker result path and are not isolated pose timings.
The same input now has three multipart attempts: two rendered at 15.508 and
17.138 s, and one returned a gate-passing server result without rendering.
Thus all three rendered single-PUT runs met target, while neither rendered
multipart run did; one non-rendered result occurred in each mode. The
single-PUT median was 13.580 s versus 16.323 s for the two rendered multipart
controls (2.743 s faster on this one input). Keep the release threshold
unchanged: every run used a single clip and local emulator
proxy, and an interrupted single PUT retries the whole file. The remaining
evidence is a randomized reviewed cohort, physical Wi-Fi/cellular, AWS, and a
controlled interrupted-upload/resume check.
See the [A/B artifact](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-large-clip-upload-mode-ab-2026-10-15.json).
The refreshed same-boot log has 21 attempts (17 rendered, 4 incomplete), with
13/21 under 15 s across mixed clips; this is not a quality-qualified rate.
See the [current timing summary](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-summary-snapshot-2026-10-15.json).
