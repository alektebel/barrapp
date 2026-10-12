# Round 2 — evidence and implementation decisions

2026-10-12. Companion to [SPEED-PLAN.md](SPEED-PLAN.md), based on the current
worktree, a production timing fixture, and local pose experiments. The prose
and Android trim implementations were being edited by another session during
this audit; findings about those paths are integration checks, not claims
about a completed release.

## Acceptance contract

The objective remains **a randomly selected 30 s source clip, upload start to
the measured result rendered on the phone, strictly under 15 s**. A clip with
30 s of continuous exercise stays in scope. Selecting only clips that trim to
6 s would change the objective. No pose-cache hit, precomputed answer or
discarded exercise time counts as a successful uncached measurement.

Use the same phone monotonic clock for both endpoints:

- Start immediately before the first request initiating upload, including
  job creation if it has not already occurred.
- End at the first rendered session containing the measured reps/score or a
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
| Exercise decision, segmentation and scoring | 0.5 s | trace, including any vision wait/count rescue |
| Persist the first result | 0.3 s | before/after result write |
| Phone polling, parse, store and render | 0.7 s | first done response through rendered frame |
| Reserve | 1.0 s | measured variation |
| **Total allocation** | **14.5 s** | **single phone clock, <15 s** |
| Prose, advisory vision, stored replay trim | **0 s on the critical path** | first result written before these begin/wait |

The original upload **2–5 s** and pose **6–10 s** ranges are coupled, not
independent allowances: with 2.5 s for the other stages, a 5 s upload leaves
less than 7.5 s for pose. Their simultaneous upper bounds already total 15 s
before any other work. Retain the ranges as experiments, not a passing budget.

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
2. **Fusion can wait for remote vision.** `server/api/handler.py` supplies a
   callable that waits on `located_future.result(timeout=300)`;
   `server/process.py` resolves it before deciding the exercise for `auto`.
   Overlap hid this while pose took 128 s; it becomes a bottleneck when pose
   takes 8 s and the locator still takes tens of seconds.
3. **Count rescue is also a remote measurement dependency.** If geometry and
   the relaxed segmenter find no reps, `analyze_clip` can call
   `count_from_clip`. That model contributes to the measurement, so it cannot
   simply be labelled advisory and ignored in the latency total.
4. **VIDEO tracking has history.** Trim boundaries and independently started
   chunks change tracker state. H.264 transcoding changes input pixels. Neither
   is guaranteed to preserve numbers because the server still uses the same
   decoder or subsequently resizes the frames.
5. **Polling and rendering matter.** The Android worker loop currently polls
   at one-second intervals. Additional local session writes/refreshes may
   precede the rendered result. The CLI transport checker polls every four
   seconds and is not a phone latency measurement.

AWS documents six vCPUs at 10,240 MB, and MediaPipe documents that VIDEO mode
uses tracking to avoid repeated detection. These establish the resource and
state model; neither promises linear speed-up or equivalence after restarting
a tracker. Sources: [AWS configuration troubleshooting](https://docs.aws.amazon.com/lambda/latest/dg/troubleshooting-configuration.html),
[MediaPipe Python guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python).

## Design decisions and next implementation steps

**First, finish the exact scheduling changes.** Publish deterministic Spanish
prose with measured results before starting model prose or replay cutting.
Handle `proseStatus` independently of `visionStatus`; the phone must re-fetch
while either is pending and eventually show a terminal status. Failed or
rejected prose retains the fallback. Validate delayed updates against the
same payload contract and preserve measured fields and provenance. The local
server should exercise the same first-result/deferred-update behavior as the
deployed worker, otherwise local E2E cannot prove this property.

**Make prepared video immutable for each upload attempt.** Keep original path,
selected interval, exported path/hash and export-applied state separate.
Resuming a multipart upload must read the identical bytes used for its
completed parts. Once export succeeds, restarting or retrying must not apply
the original trim interval to the already trimmed file. Failed export falls
back to the original bytes, with the fallback included in latency reports.
Motion suggestions need decoded samples at the requested instants:
`OPTION_CLOSEST_SYNC` can repeat the same keyframe for several 0.5 s samples.
Validate the suggested interval on real footage, with a full-clip option
always available; global motion is not proof of exercise activity.

**Treat short-chunk pose as a candidate, not a default.** Benchmark explicit
1/2/3/6-worker configurations on the deployed six-vCPU image, including import,
model load, warm-up, decode duplication, merge and fallback. A lower chunk
floor needs a named/versioned configuration shared by production and the
comparison harness. The existing harness's `--min-chunk 60` is not the
production floor of 240. Log the effective configuration, model hash, actual
chunk count and whether sequential fallback ran. A custom model path must be
passed to every child rather than silently selecting a different default.

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

**Next candidate to evaluate: Full with a measured chunk-count policy.** It
fits the pose allocation on this local clip while avoiding a frame-rate
change. That is a falsifiable experiment choice, not permission to switch the
deployed model. First compare labelled, positive rep sequences and holds;
then repeat the winning configurations on Lambda and finally on the phone.
Any new model needs its identity/hash in traces and pose-cache keys, matching
assets baked into the image, and a Heavy/sequential rollback. A cache tagged
only `mediapipe` must not silently mix the variants.

Artifacts: [candidate timing/config/hashes](../out/round2-latency/candidate-models.json)
and [full candidate payload comparisons](../out/round2-latency/candidate-downstream.json).

### Reference labels selected for the next comparison

`data/evaluation/sample_manifest.json` version `2026-09-08.1` has reviewed
labels for the own clips. WA0020 is the first positive gate: 19 push-ups,
reviewed from a contact sheet at medium confidence, with
`push_up.lift_stall` explicitly forbidden. Hip sag is unobservable from its
unknown viewpoint. The manifest gives no frame-by-frame rep boundaries or
positive fault annotations, so it cannot certify those outputs.

Use the raw WA0020 bytes for Heavy sequential versus Full sequential and
Full chunks, isolating model/chunk changes from export changes. Save automatic
and declared-exercise outputs if the classifier changes. Compare the current
Heavy result as a regression baseline and the reviewed count/forbidden stall
as correctness gates. Historical score 55 is a pipeline output, not a label.
`sessions.csv`/`capture.csv` call this clip a dip; preserve that disagreement
and use the explicitly reviewed manifest for this experiment. WA0010 offers
a second medium-confidence positive (two muscle-ups) and a constraint that
support-extension faults refer only to the support phase.

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

Phone instrumentation is still required: emit timestamps from
`SystemClock.elapsedRealtimeNanos()` at preparation/transfer stages, first
done response and the rendered result. Pair events with an upload-attempt ID
and boot identifier; process restart can resume an attempt, but a reboot
must not subtract a new monotonic origin from an old one. Persist the start
before sending bytes. Log completion after rendering, without adding a
synchronous telemetry request before the result. Server wall-clock timestamps
can explain the wait, but must not be subtracted from the phone clock.

The dispatch event currently follows Lambda invocation and `receiving` follows
Python imports. Thus their interval mixes dispatch and initialization, and
can even invert under concurrent event recording. New instrumentation should
bracket invocation and worker entry explicitly before assigning a pure queue
or cold-start duration. Negative diagnostic intervals are not a speed-up.

Access rechecked on 2026-10-12: `aws sts get-caller-identity` reports no
credentials. `/home/diego/android-sdk/platform-tools/adb devices -l` lists no
devices. Java is installed at `/home/diego/.local/jdk21/bin/java`, even though
it is absent from the default shell PATH. Cloud deployment and the actual
phone gate remain unverified; local design, tests and benchmarks can proceed.
