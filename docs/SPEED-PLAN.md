# barrapp — Making the pipeline fast

> **Current objective (Round 2):** a randomly selected 30-second clip reaches a
> measured result rendered on the phone in **under 15 seconds from upload
> start**. The per-stage allocation and acceptance evidence are in the Round 2
> section below. This objective remains unverified on a real phone.
>
> **Round 1 history (2026-10-11):** the earlier goal was to show reps and score
> within about a minute after upload, with unchanged measurements. Its results
> and constraints below describe that completed phase, not the current Round 2
> acceptance rule.

## Where the time goes (measured in production)

| Stage | Job `7135be1d598a` (before) | Job `31103ccedfc3` (after deploy 4) |
|---|---|---|
| Upload | 10 s | ~70 s (slow network) |
| Locate the exercise (vision) | 57 s, **before** pose | in parallel with pose |
| **Pose (MediaPipe heavy, ~1,100 frames, ~2 vCPU)** | **128 s** | ~same |
| Measure (classify, segment, score) | < 1 s | < 1 s |
| Report + technique artifacts | 28 s | ~same |
| Vision note + second opinion | ~145 s, **before** the result | after the result |
| **Upload end → result on the phone** | **~365 s** | **~205 s** |

Already in place: frames are resized to 640 px before pose (`PROCESS_WIDTH`);
the result no longer waits for the vision models; locating runs alongside pose.
What remains on the critical path: **pose (~128 s)**, the report + artifacts
(~28 s), and the upload.

## Round 1 rules

- Tests first; each step lands as its own commit and, where it touches the
  server, its own deploy with the previous image noted for rollback.
- **No step may change a measured number.** Steps that would (fewer frames, a
  lighter model) are out of this plan and wait for the reference clip set.
- Each step is measured with the same tool (step 0) on a real job.

## Steps

## Results so far (2026-10-11)

| Step | Status | Finding |
|---|---|---|
| 0 Timing tool | ✅ `scripts/job_timing.py` | Named a hidden stage: **~44 s** cutting and re-uploading the stored clip *before* `done` was written |
| 1 Vision calls overlap + result before the clip cut | ✅ exact (no number changes) | ~44 s off the critical path; note arrives ~20 s sooner |
| 2 Pose in parallel chunks | ⚠️ built, **off by default** | ~1.6–1.8× faster with 4 workers, but **not identical**: sequential MediaPipe is bit-for-bit deterministic, yet a chunk started cold never converges to it (VIDEO mode carries tracking/smoothing state through the whole clip; 1–10 px for the chunk's full length, any warm-up). On two real clips: score 55 → 56, a distance 1.2 → 1.1 torso. `scripts/pose_parallel_check.py` reproduces it. |
| 3 More vCPU | ❌ no effect | The model uses one core: 58.6 s on 1 core, 61.6 s on 2, 59.7 s on 6, identical output. Decoding is negligible (0.5 s of 1,206 frames). |
| 4 Phone compression | ⚠️ changes numbers too | Re-encoding changes the pixels the model sees, so keypoints move like in step 2. |

**Conclusion:** with steps 0–1 the exact speed-ups are exhausted. ~100% of the
remaining critical path is MediaPipe inference, one frame at a time. Every
further gain (chunks, fewer frames, a lighter model, compression, pose on the
phone) changes the keypoints by a few pixels. That is a measurement decision:
it must be taken on the reference clip set, comparing each option's error
against the labels - not against today's sequential output, which is itself
only one of the many answers a tracker gives depending on where the clip
starts (a cold start anywhere in a clip moves it by the same 1–10 px). A later
screen also found no material speedup from raising common TFLite/OpenMP thread
environment variables on the current Tasks backend; see the
[Round 2 audit](SPEED-ROUND2-AUDIT.md).

### Step 0 — A timing tool
`scripts/job_timing.py <job_id>`: reads the job's upload log and trace from
production and prints each stage's duration (upload, locate, pose, measure,
report, vision, total). Used before and after every step.
*Tests:* stage durations computed from a recorded upload log + trace fixture.

### Step 1 — Vision note and second opinion at the same time
Today they run one after the other (124 s + 21 s). They are independent: run
them in two threads. Off the critical path already, but the note reaches the
phone ~20 s sooner and the job ends sooner.
*Tests:* both calls start before either finishes; a failure in one keeps the
other; `visionStatus` rules unchanged.

### Step 2 — Pose in parallel chunks  *(the big one: ~128 s → ~25–35 s)*
Split the clip into N contiguous frame ranges (N = CPUs), pose each in its own
**subprocess** (Lambda has no `/dev/shm`, so `multiprocessing` cannot be used),
and stitch the keypoints back in order.
- **Same output as today:** VIDEO mode carries tracking state between frames,
  so each chunk starts `OVERLAP` frames early (warm-up) and those frames are
  discarded. The stitched result must match the sequential one.
- Falls back to the sequential path on any worker failure, and is the
  sequential path when N = 1 (`BARRA_POSE_WORKERS`).
*Tests:* chunk planning (ranges cover every frame exactly once, warm-up never
crosses frame 0); stitching order; fallback on a failing worker; equivalence
against the sequential path with a fake landmarker; and **one real check on two
of Diego's own clips** (`data/calisthenics/videos/own/`): sequential vs chunked
keypoints, with every downstream number (reps, score, metrics) identical.

### Step 3 — More CPU for the worker
Lambda gives CPU in proportion to memory: 3008 MB ≈ 2 vCPU, 10240 MB = 6 vCPU.
Raise `WorkerFunction` to 10240 MB so step 2 has six cores. Cost per second
goes up ~3.4×, duration goes down ~4–5×, so cost per clip stays about the same.
*Tests:* template contract (memory, `BARRA_POSE_WORKERS` unset → auto = CPUs).
*Gate:* `scripts/job_timing.py` on a real job shows pose ≤ 40 s.

### Step 4 — Prepare the clip on the phone before uploading
Pose runs at 640 px; a 1080p/4K phone clip may carry pixels the worker discards.
Transcode on the phone to 720p H.264 before upload; on any failure upload the
original. The exporter requests 4 Mbit/s video, but that is not a promise of
smaller output: the request can be ignored, and a low-bitrate source can grow.
Measure source and output bytes and verify pose/measurement quality before
claiming an upload win. A stream-copy trim of WA0010 kept the source's first
frame because its only nearby IDR is at 12.5 s, saving just 10% of bytes;
accurate arbitrary crops need re-encoding or a capture GOP change. See the
Round 2 bitrate and trim-boundary screens in the audit.
*Tests:* the decision (when to transcode, target size) and the fallback; a
Robolectric test cannot transcode, so the real check is one clip on the phone.

### Step 5 — Measure end to end and write it down
One real clip from the phone after steps 1–4: `job_timing.py` before/after
table in this document.

## Later (not in this plan)
- **Fewer frames (15 fps) or another pose model** — half-rate YOLO11n at
  480 px is the first local 30 s candidate under the 8 s pose allocation
  (7.16 s, stateless six-way chunks), but it changes scores/faults on WA0010
  and automatic recognition on WA0020. It remains off pending label review,
  broader coverage and Lambda/phone timing. A matched six-worker YOLO11n
  candidate with opt-in fusion and a 0.25 movement-amplitude floor took 5.75 s
  pose-plus-measurement on a reviewed 30 s clip and passed WA0010, WA0017 and
  WA0020 movement/count assertions, but WA0014's reviewed zero remained
  `unmeasured` and failed the measured-result gate; WA0018 remains a review
  gap. Neither candidate is production-approved or an upload-to-phone pass.
  See the [Round 2 audit](SPEED-ROUND2-AUDIT.md) for the quality gate and
  timing limits.
- **Pose on the phone** — an alternative path is to run full-rate Heavy pose
  inference while the video uploads, then send keypoints for server-side
  measurement. This could put replay and advisory work after the first result,
  but phone latency, thermal behavior, and Python parity are unmeasured; it is
  not a Round 2 pass. See the [on-device pose capability design](SPEED-ON-DEVICE-POSE-CAPABILITY.md).

---

**Shipped (2026-10-12, deployed to sam-app, smoke green: worker imports, api
/health 200, WorkerFunction MemorySize=10240 confirmed):**

| Step | Commit | State |
|---|---|---|
| A untranslated_text | `032d8b2` | deployed |
| B prose after result (`proseStatus`) | `c66ed71` | deployed |
| C trim before upload (app) | `e68c246` | built; needs an APK install to reach users |
| D worker 6 vCPU + gate | `ed48f31` | memory deployed; chunks OFF (gate DEVIATES) |

Baselines (`scripts/job_timing.py`, server persistence only): job
`7135be1d598a` 375 s total (pose 127 s, measure+report 174 s); job
`31103ccedfc3` 202 s upload-end→result (pose 134 s, report 21 s, +44 s clip
cut); job `cd6f518ec47d` 149 s upload-end→result (pose 127 s, report 16 s,
vision note +135 s after result).

**The physical-phone acceptance run is still missing.** A debug APK has now
been exercised on an API 35 x86_64 emulator against the local API. On a
15.29-second WA0010 clip the first visible result took 22.98 s from upload
start; the result-to-first-frame gap was 0.10 s. This confirms the Android
render endpoint and demonstrates that fast polling/rendering cannot make up
the current processing time. It is emulator loopback evidence, not physical
phone, real-network, random-30-second, or production evidence. The measured
clip itself does not meet the <15 s objective. Do not claim that trimming a
30 s clip reduces pose time to 6 s: the random-clip target includes full 30 s
active sets, and trim equivalence has not passed its quality gate. See the
[Round 2 audit](SPEED-ROUND2-AUDIT.md) for the run and the remaining quality
gates. A later 20 s WA0020 control rendered its reviewed 19-rep geometric
count in 13.284 s, with an 89 ms result-to-frame gap. Two 29.64 s ring-clip
imports reached the phone in 11.594 and 8.146 s, but both were
`dip/0/unmeasured`; neither passes the end-to-end accuracy gate. The local worker
reproduces that disagreement: geometry calls it `dip` while the classifier
calls it `muscle_up`. Thus the timing endpoint works on a positive control,
but a full-length measured result and production phone acceptance remain open.

**30 s positive local control (2026-10-15):** a manually reviewed 30 s
pull-up window rendered 10 measured reps, but took 29.003 s. Inspection found
that the local API serialized optional localization and advisory vision before
publishing `done`, unlike the intended worker first-result path. The local
server now publishes `measure_job`'s result first and enriches afterward; its
response and request logs expose server result-ready and per-poll timestamps.
A correctly configured six-core worker rerun measured 9.587 s from worker
start to measured result (pose 8.681 s). The aligned local API then rendered
the reviewed 10-rep result on the emulator in 9.886 s from upload-attempt
start; the payload passed its reviewed quality gate. This is one local-loopback
positive-control pass. A repeat using the opt-in supported-only policy rendered
the same reviewed 10/10 count in 10.195 s, also under the 15 s target. Both are
local-loopback samples on one emulator, not a random-clip distribution or
production-network acceptance. The opt-in supported-only candidate passes
three of four reviewed controls (10 pull-ups, 19 push-ups, and an unknown
negative), but still fails the reviewed muscle-up zero as `unmeasured`. A
single-GPU screen was slower than six-core CPU chunking on the same 20 s
push-up clip, so CPU remains the benchmark candidate. A seeded random-corpus
30 s probe returned in 7.844 s but was correctly marked `unmeasured`; random
clip accuracy and phone coverage remain open. A five-window seeded worker
cohort reached server result-ready in 5.401–8.114 s (median 5.529 s); four of
five met the 8 s server allocation. Only three were geometric counts; quick
visual review found two sampled windows were non-exercise footage, including a
transit window falsely counted as one dip, and a dip window labeled
`muscle_up / 0 / unmeasured`. This is latency-only evidence, not an accuracy
pass. The status correction retained
the 10-pull-up and 19-push-up positive counts in the four-case rerun; WA0014
still lacks a measured zero. An opt-in v2 fusion screen made the squat-like and
transit windows abstain and preserved three reviewed controls, but a visibly
dip-like window still returned `muscle_up / 0 / unmeasured`; the reviewed
measured-zero control also remains unmeasured. Its five-window worker result
times were 4.940–7.564 s (median 5.165 s), excluding upload and phone render.
One reviewed 30 s emulator run with v2 rendered 10 pull-ups in 8.740 s from
upload-attempt start (2.018 s upload+submit, 6.627 s submit-to-result, 94 ms render).
The seeded random 30 s dip-tutorial window initially rendered `dip / 2 / geometry`
in 7.884 s and appeared to pass its medium-confidence review. That run used the
host's OpenCV 5.0 decoder, while the Lambda image uses OpenCV 4.10. Pinning the
local decoder to 4.10 made host CPU keypoints bitwise equal to the Lambda CPU
keypoints; the aligned result is `dip / 3 / geometry` and fails the reviewed
count gate. The earlier 7.884 s result is therefore not valid quality-approved
evidence. This is an emulator/local-loopback result on a tutorial montage,
not a representative athlete-recorded clip or real-network acceptance.
This small local screen and loopback phone pass do not establish production
calibration or random-clip acceptance. See the [Round 2 audit](SPEED-ROUND2-AUDIT.md).

**Runtime parity is still a release gate:** these under-15 s phone runs use the
local API with opt-in YOLO, while the deployed Lambda image currently ships
MediaPipe Heavy and leaves `BARRA_POSE_WORKERS` unset (one worker). The local
timings therefore do not establish a production result time. Before any
rollout, the separate Lambda-base shadow image must pass cold and warm AWS
invocations through persistence and the exact-payload quality gate. The image
now builds and imports locally, but its six-CPU Docker-quota run returned three
reps while the host wheel returned two on the same input. A 10 fps review
confirmed two completed reps; the extra CPU-wheel segment is an assisted
dismount. The CPU-wheel pose is deterministic on repeat,
but differs from the host pose by 1.214 px mean / 2.628 px p95 on shared
visible landmarks, with large per-frame outliers. That candidate is not ready
for AWS timing or rollout; explain the runtime pose drift and revalidate the
exact deployment wheel first. A saved-pose sweep of turnaround height 0.60–0.90
and amplitude floor 0.15/0.25 did not remove its extra dismount count; the
highest height reduced WA0020 from 19 to 15. See the exact
[CPU-wheel sweep](../out/round2-latency/fusion-v2-final/cpu-wheel-count-threshold-sweep.json).
A physical-phone, real-uplink run is still
required for end-to-end acceptance. See the
[Round 2 audit](SPEED-ROUND2-AUDIT.md) for the container run and exact gate.

A later six-core Lambda-base resolution screen at 416/448/512 px returned the
correct count on that random window faster (4.05–5.21 s pose), but each setting
lost or invented reps on at least one reviewed control. The 480 px candidate
with a 0.25 amplitude floor preserved the reviewed positives but still
overcounted the random clip and left WA0014 unmeasured. No tested CPU setting
currently passes the complete measured-result gate; see the
[resolution screen](../out/round2-latency/fusion-v2-final/cpu-resolution-screen.json).

**Fresh YOLO11s shadow result (2026-10-15):** a larger checkpoint plus an
opt-in geometry-first rule for high-confidence conflicts now passes the
reviewed random dip window at 2 reps: 8.262 s pose and 8.383 s through local
container measurement. On the same six-CPU Lambda-base image/config, WA0010
returns 2 muscle-ups, WA0020 returns 19 push-ups, and WA0017 remains unknown;
the five-case gate still fails WA0014 because its reviewed zero is
`unmeasured`, while WA0018 remains a coverage gap. This is the strongest
random-window server candidate so far, but its fusion threshold is only a
small screen. It has two passing emulator/local-loopback phone runs, but no
AWS Lambda or physical-phone timing. Full reports and quality gates are in
the [fresh YOLO11s run](../out/round2-latency/fusion-v2-final/docker-yolo11s-v3-fresh-gate/)
and the [Round 2 audit](SPEED-ROUND2-AUDIT.md). On the seeded five-window
cohort it returned in 7.754–8.483 s through measurement, but only the reviewed
dip window had a passing count gate; the other four windows remain unreviewed
and three returned unmeasured.

A same-window worker-count screen at 480 px kept the reviewed dip / 2 output
and identical pose-array hash at 3, 6 and 8 workers. Pose took 11.863 s, 8.650
and 9.209 s respectively; a second six-worker run took 8.385 s. A six-worker
subprocess-mode run took 10.197 s. All five window quality gates passed.
This supports retaining six fork-mode workers on the six-core target: three
workers miss the pose allocation, while oversubscribing to eight or using
subprocess mode was slower in this screen. These are single-window container
screens, not a broad workload or AWS timing study; see the
[worker-count screen](../out/round2-latency/fusion-v2-final/docker-yolo11s-workers-screen/).
A follow-up full-worker trace also caught 0.693 s of cold Ultralytics package
import that the prior backend pose timer omitted; that timing now starts
before import and reports it separately. The reviewed window still passed at
2 reps, with 8.518 s outer pose-estimate wall time in that run. See the
[timing instrumentation screen](../out/round2-latency/fusion-v2-final/docker-yolo11s-instrumentation-screen/).

A separate opt-in stride-3 screen preserved the movement/count/status outputs
on the same six cases while changing the interpolated pose arrays. The random
window passed its exact dip / 2 gate with pose at 5.524 s. Two app runs on a
separate API 35 emulator rendered the reviewed dip / 2 in 11.311 s and 9.777 s
(p50 10.544 s), versus the stride-2 pair at 14.313 s and 12.953 s (p50
13.633 s). The five reviewed controls still fail only WA0014's unmeasured
zero; WA0018 remains a coverage gap. This is a small, emulator/local-loopback
screen with no AWS, S3, physical-device or production-network validation, so
stride 3 remains experimental. See the
[stride-3 screen](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/)
and the [Round 2 audit](SPEED-ROUND2-AUDIT.md).

The pinned Lambda-base image meets the 6–10 s pose allocation on five reviewed
inputs (2.01–4.99 s), but the cohort is not quality-approved: WA0014's reviewed
zero-rep interval was counted as two reps, and WA0018 remains a review-coverage
gap. The exact-runtime cohort and outputs are in the audit. The worker now
measures synchronous stage-table/upload-log writes, S3 download and first-result
persistence separately in `worker-timing`, so the next shadow run can locate
remaining first-result overhead without changing stage behavior.

An exact-runtime `min-span-amplitude=0.25` screen removed WA0014's two false
reps while preserving the WA0010/WA0020 positive counts and WA0017 abstention;
the pose arrays were byte-identical to the 0.15 run and pose remained under
5 s. WA0014 still returns `unmeasured` instead of a validated zero, so the
candidate does not pass the measured-result gate and remains experimental.

For prepared files up to 8 MiB, the queue now selects the single-object PUT
returned by job creation; larger files continue through multipart. The job
stores only the selected mode and transfer-complete flag, allowing a resumed
single PUT to mint a fresh owner-checked URL without saving a signed URL on the
device. Submit verifies object presence and minimum size. This removes three
multipart API calls on eligible files; it does not reduce bytes or establish a
latency win. Phone A/B timing remains required.

**Larger single-PUT candidate (2026-10-14):** debug builds now accept
`-Pbarrapp.singlePutMaxBytes=16777216`; release remains fixed at the 8 MiB
default. The prepared 14.61 MB WA0014 30 s crop is 13.94 MiB, so it exercises
multipart at the default cutoff and a single PUT at the 16 MiB candidate
cutoff without changing clip bytes or pose input. A two-part multipart upload
uses start, two part-presign and completion calls; the single-object URL is
already returned at job creation. This may save control-call latency, but
single PUT must resend the whole file after failure, while multipart can
resume completed parts. The 8 MiB release default stays unchanged pending a
paired phone/network run measuring transfer time, attempt-to-render time,
retries and result parity. Both APKs compile; no attached phone is available
for the A/B. See the audit for artifact paths and the multipart range-read fix.

# Round 2 — the 15-second goal (2026-10-11, evening)

**Goal: a random 30 s clip the athlete picks is measured, end to end, in under
15 s — upload to result on the phone.** One random window rendered on the
Android emulator in 7.884 s over local loopback, but that result used the
OpenCV 5.0 host decoder and was invalidated by a runtime-parity check. With the
project pinned to the Lambda-matching OpenCV 4.10 decoder, that YOLO11n CPU
candidate returns three reps against the reviewed two and fails the count gate.
A fresh six-core Lambda-base shadow run with YOLO11s and an opt-in geometry-first
conflict rule passes the supplemental frame-by-frame reviewed random window at
dip / 2. The five-case reviewed gate still fails WA0014's measured-zero
assertion, so the full cohort gate remains open. Two earlier stride-2
emulator/local-loopback app runs rendered that random window in 14.313 s and
12.953 s. The stride-3 candidate has three exact-window-gated phone runs at
11.311 s, 9.777 s and 10.848 s (median 10.848 s); the last starts Ultralytics
import during its 0.959 s upload, with 281 ms still to wait afterward. All
are API 35 emulator/loopback results on the same tutorial montage, not
physical-phone or production-network evidence. An in-app WA0014 trim attempt exposed an exporter thread-affinity
failure and fell back to the full source; the exact 30 s crop is still untested
on-device. Round 2 acceptance remains open.
A–B preserve measured numbers;
C and D require measurement validation: trimming restarts the VIDEO tracker
and re-encoding changes its input pixels. See the
[2026-10-12 design audit](SPEED-ROUND2-AUDIT.md) for the current evidence,
critical-path dependencies, acceptance gate and revised stage budget.

Original estimate for the subset of 30 s clips whose working set is ~6 s.
This assumption does not cover a 30 s continuous set; the upper end also
exceeds the goal before queueing, download and phone delivery are counted:

| Stage | Today | After round 2 |
|---|---|---|
| Upload | 25 s (35 s of video) | ~2–5 s (6 s, 720p) |
| Pose | 3.6 s × 30 s ≈ 108 s | chunks × 6 cores on ~6 s ≈ 6–10 s |
| Measure | < 1 s | < 1 s |
| Report prose | 10–15 s **before** the result | after, like the vision note |
| **Total** | **~149 s** | **~10–16 s** |

Revised allocation (2026-10-15; targets, not measurements; local end-to-end
evidence supports an approximately 5 s upload stage for a 13.87 MB clip at
30 Mbps):

| Stage | Budget |
|---|---:|
| Upload protocol + bytes through submit (single-PUT candidate, ≤16 MiB) | 5.1 s |
| Dispatch / worker initialization / model readiness | 0 s incremental; finish during upload or charge the wait here |
| Pose on six cores with chunks, startup and merge | 7.5 s target; 8.0 s ceiling |
| Auto-classification vision vote | 0 s incremental; finish within the pose wall time |
| Exercise decision + geometry measurement, including count-rescue decision | 0.5 s |
| First result persistence | 0.3 s |
| Phone polling + parse/store/render | 0.7 s |
| Reserve | 0.4 s |
| **Total** | **14.5 s** |
| Prose/advisory vision/replay preparation | **off the critical path** |

On the same 13.87 MB reviewed input, three rendered single-PUT trials measured
4.901–5.031 s through submit and 13.526–14.157 s to the phone. The server's
8.417–8.459 s first-result measurement includes pose, measurement and other
worker work; it does not prove the 7.5 s pose allocation. One same-input
multipart run took 15.508 s and another 17.138 s, with a third result not
rendered. Treat 16 MiB as a debug candidate only until the randomized cohort,
production upload, cold-start overlap, and resume behavior pass their gates.

The seeded uniform video/window cohort now contributes one exact-reviewed
random window: its six-worker result matches the reviewed `dip / 2` label in
5.401 s server-measurement time, and three phone trials of the same source
interval (a separate 13.87 MB encoding) rendered in 13.526–14.157 s under the
local paced proxy. The other four sampled windows do not clear the count gate,
so this is one success, not a random-cohort pass. See the linked cohort and
gate evidence in the [Round 2 audit](SPEED-ROUND2-AUDIT.md).

A fresh-container import-overlap screen now recovers about 0.9 s of the
dispatch/download/pose path when a 0.95 s upload hides the optional Ultralytics
runtime import. All four paired payloads pass the supplemental exact-window
review, and one warmup-enabled emulator upload rendered that reviewed result
in 10.848 s. This is still a tiny local-loopback sample on a tutorial montage;
S3/Lambda and production-network behavior remain unmeasured. Details and
paired artifacts are in the [Round 2 audit](SPEED-ROUND2-AUDIT.md).

Upload ~2–5 s and pose ~6–10 s cannot both consume their upper budgets:
with 2.5 s of other work, a 5 s upload leaves less than 7.5 s for pose.
Preparation/export and confirm-to-render time are also recorded, separately
from the upload-to-render gate. Full 30 s active sets remain in scope.
The prepared 30-second WA0014 test clip is 14.61 MB; sending those bytes in the
3.0 s upload allocation requires about 39 Mbit/s of payload goodput before
protocol overhead. The hard <15 s total leaves at most 3.5 s for upload if
every other allocation is used, so a real-device run must record effective
goodput and cannot treat the nominal 4 Mbit/s encode setting as a transfer
guarantee. A local 2 Mbit/s encode cut this clip to 7.38 MB, but it failed
the reviewed positive/negative classification and count gate, so the exporter
stays at 4 Mbit/s pending a quality-preserving policy and real phone timing.
A 3 Mbit/s screen retained both WA0010 reps and WA0020's declared count while
reducing the WA0014 crop by 23.9%, but it still fails auto-label / measured-zero
gates and one positive clip loses a rep at 2.75 Mbit/s; treat 3 Mbit/s as an
unvalidated candidate only. See the [bitrate screens](SPEED-ROUND2-AUDIT.md#2-mbits-upload-size-screen-2026-10-15).
Phone timing rows also record poll count, cumulative poll-request time and
intentional poll delay. A controlled emulator/local-API 20 s positive control
spent 6.45 s in poll GETs and 4.53 s sleeping; a 29.64 s auto-labeled clip
spent 6.39 s in GETs and 2.98 s sleeping but returned `unmeasured`. These are
single-run emulator observations, not production-network samples; GET timing
has no per-request breakdown and may include emulator connection overhead.
The allocation still needs physical-device/network cohort data.

Preparation is recorded separately from upload start. The same emulator saw
12.45 s to copy and scan the 20 s positive control, and 38.7–39.9 s for two
imports of the 29.64 s clip. The current motion sampler seeks a frame every
0.5 s; the trace does not separate file copy from this scan. This delay falls
outside the stated upload-to-result metric, but it is a substantial user wait
and needs its own stage timing and a quality-checked sampling experiment. An
isolated Android 35 benchmark finds that `OPTION_CLOSEST` every 1.0 s takes
6.66–6.82 s on WA0014's 30 s crop, versus 13.97–14.71 s at the current 0.5 s
step in a crossed-order check. On the reviewed WA0020 positive, the coarse
window is wide enough that the current 80% rule declines to trim and keeps all
19 reps; the 0.5 s window would have cut the count to 11 if forced. This makes
1.0 s closest-frame sampling the current app implementation. A full WA0020 app
run against the local API prepared in 7.19 s and rendered the reviewed
`geometry / 19` result 13.90 s after upload-attempt start, with no trim. This
is a single 20 s loopback positive control, not a production or random-clip
pass. WA0014 still gets a false-short suggestion, and the reviewed set lacks a
30 s positive, so the quality and full-target gate remains open.
`OPTION_CLOSEST_SYNC` is faster but its
2 s proposed windows would remove reps and is rejected. See the sampler
artifact in `out/round2-latency/android-sampler-20261015/` and the
[Round 2 audit](SPEED-ROUND2-AUDIT.md#on-device-motion-sampler-screen-2026-10-15).

The 0.5 s measurement allocation cannot contain the current synchronous
two-model count rescue: it extracts stills and can block on provider calls
with 60 s timeouts and retries. The first result must not wait for that path.
A late or unavailable count remains explicitly `unmeasured` and does **not**
pass the measured-result target; the goal therefore stays open until a bounded
count path passes the reviewed coverage gate. The current speculative design
is in [SPEED-COUNT-RESCUE-DESIGN.md](SPEED-COUNT-RESCUE-DESIGN.md); it is not
approved for rollout because it could send frames for clips whose geometric
count would already succeed.

## Steps (each its own commit; server changes need deployed measurements)

### A — The untranslated_text sentinel (first, small, independent)
The 16:32 jobs (a muscle-up and a "dragon flag") tripped
`barra/contracts.py` `untranslated_text`: English text still reaches the
phone, probably from an exercise we do not measure (blockers/next-step copy
for a skill with no fault taxonomy). Find the hole in the catalog
(`barra/i18n.py`), close it, test in `tests/test_spanish_payload.py`,
re-vendor (`server/vendor_barra.sh`).

### B — Report prose after the result (implemented; deployed)
`measure_job` returns the measured payload with deterministic Spanish fallback
and `proseStatus: pending`. The worker persists it before running advisory
vision and `finish_prose`; only the three prose fields can change in the later
write. A failed or rejected model leaves the fallback. This keeps report prose
off the upload-to-render critical path. Auto-classification localization is a
separate dependency: fusion uses its vote only if it is ready inside
`measure_job`.
For Round 2, fusion now takes the vision vote only if it has completed during
pose; it never adds a post-pose wait. A late vote falls back to local
classification and may change the automatic label, so the timed-out auto-label
quality gate remains unresolved. See the audit for instrumentation and the
live-provider accuracy/latency gate.

### C — Trim in the app before uploading (upload+pose win; validate quality)
The phone and server must use the same prepared video so replay timestamps
line up. Restarting tracking at a trim boundary or transcoding can change
keypoints and downstream measurements; compare against labels before rollout.
The prepared video's origin is 0; the measured set's `trim.startS` can still
be later than 0 if the prepared video retains a lead-in.

- Suggest the working set on the phone: frame-difference on downscaled
  thumbnails (`MediaMetadataRetriever`) finds the moving window; the slider
  defaults to it, the athlete adjusts.
- Export the trim with Media3 Transformer (720p H.264, currently requesting
  4 Mbit/s — this is SPEED-PLAN step 4 folded in; it changes the pixels decoded
  by the worker and may increase bytes for low-bitrate sources).
  On any Transformer failure upload the original, untrimmed, as today.
- The app-side pipeline (`BarrappViewModel.upload`, `UploadScreen`,
  `WorkStore`) owns this; it must not touch the prose fields of step B.

The 30 s 720p/4 Mbit/s test export was 16.23 MB. Uploading that amount within
the 2–5 s allocation needs about 65–26 Mbit/s of sustained network goodput,
before API/request overhead. The actual Media3 output and a phone network A/B
are still required; the bitrate setting alone does not prove the upload budget.

### D — Parallel pose, decided on the reference clips (the measurement call)
`barra/pose/parallel.py` + `scripts/pose_parallel_check.py` exist and are
off by default. The goal needs them ON: sequential pose is 3.6 s per second
of video, and even a 6 s working set is ~22 s — over budget. Gate:
sequential vs chunked on Diego's own clips
(`data/calisthenics/videos/own/`), every downstream number (reps, score,
faults, per-rep metrics) compared; if a number moves, the deviation is
documented here before anything ships. Paired with the 6-core worker
(SPEED-PLAN step 3: `WorkerFunction` → 10240 MB,
`BARRA_POSE_WORKERS=6` explicitly, only after the gate). Unset means **one**
worker. Also, `MIN_CHUNK=240` leaves a 180-frame / 6 s clip sequential even
when six workers are configured. Benchmark and validate a smaller chunk floor
before treating six-core execution as implemented.

**New local evidence:** on the same prepared 30 s clip, Heavy took 47.24 s
sequentially, 19.13 s with six forced chunks, and 18.28 s with the production
floor (three effective chunks). Full took 14.42 / 7.64 / 6.82 s respectively;
Lite took 10.30 / 6.29 / 5.91 s. These are single runs on a shared workstation
restricted to six physical cores, not Lambda or phone timings. Every variant
counted zero reps on this sample, so quality is **not validated**. A subsequent
raw WA0020 test retained the reviewed 19 push-ups when the exercise was
declared: Full with two effective chunks took 4.68 s versus Heavy sequential
20.15 s. Automatic recognition was wrong in both no-vision runs, and Full
changed fault decisions. Count parity alone is insufficient; production
remains Heavy/sequential. See the audit for the complete quality findings.
Hashes, exact settings, payload differences and commands are in the linked
audit and `out/round2-latency/`.

**Separate YOLO11n candidate (2026-10-13):** half-rate `imgsz=480` inference
in six worker processes takes 6.68–6.81 s across three trials on the prepared
30 s WA0014 clip and 4.95 s on WA0020 when Ultralytics' per-worker CPU thread
count is capped at one. Without the cap, Ultralytics resets each worker to
eight threads from the container-visible CPU count, and the same 30 s run
takes 26.76 s. The opt-in path is now implemented in `UltralyticsBackend` and
vendored; it is activated with `BARRA_POSE_BACKEND=ultralytics`, six workers,
stride 2, `imgsz=480` and one CPU thread per worker. The deployed worker image
still lacks Ultralytics; the local `yolo-pinned` image adds the package but not
the weights and grows from 3.32 to 4.79 GB. WA0020 auto-classification still
returns deadlift / 0 without its remote vision vote, and WA0010's saved
measurement differs from its human reference. This is a promising pose-time
candidate, not an approved model or a passed Round 2 gate. See the
[audit](SPEED-ROUND2-AUDIT.md) for the worker-image integration run, exact
timings, drift, packaging size and remaining quality/deployment checks.

**Current worker-image Lite screen (2026-10-14):** Lite VIDEO pose on the
prepared 29.8-second WA0014 clip took 5.04 s with the six-CPU worker image,
but returned zero `unmeasured`; WA0020 took 4.00 s and retained 19 reps under
the wrong `dip` label. WA0010 passed its reviewed movement/count anchor at
4.28 s pose + 0.07 s measurement. The three-clip quality gate therefore fails
two clips, so Lite remains off despite fitting the pose allocation. This
worker-image screen still excludes upload, Lambda startup, network fusion and
phone rendering. See the [Round 2 audit](SPEED-ROUND2-AUDIT.md) for payloads
and exact settings. Forcing six chunks on WA0014 was about 8% slower than the
production three-chunk plan (5.42 s from two runs versus 5.04 s in one control) and
changed shared-visible keypoints by 1.17 px mean / 2.96 px p95 without fixing
the unmeasured zero. Six-worker configuration therefore does not imply that
six useful chunks are faster for this backend and clip length.

**Corrected six-core YOLO fusion screen (2026-10-14):** the current mounted
sources and explicit experimental fusion policy process the prepared 29.8 s
WA0014 clip in 6.54 s pose + 0.15 s measurement. Reviewed WA0010 returns
muscle-up / 2, WA0017 abstains as unknown / 0, and WA0020 returns push-up / 19.
The full eight-clip screen has five unreviewed movement/count labels, and the
WA0010 score is 50 versus the reference 51 (score is not currently a manifest
gate). This is a small local screen, not a production calibration or a
deployed Lambda/phone measurement. An initial run imported the image's older
installed server module and is superseded; the corrected run sets
`PYTHONPATH=/opt/barra/server:/opt/barra`. See the audit for details and
artifacts.

**Full-rate size screen (2026-10-13):** six-worker YOLO inference on every
frame at 320 px completed local analysis of a 29.8 s clip in 9.89 s, within
the pose range but without reviewed measurement labels. It missed one of the
two reviewed WA0010 muscle-ups; 384 px retained that count but scored 57 versus
the reference 51 and missed six WA0020 push-ups. The 480 px full-rate run
matched WA0010's count/score but took 10.88 s on that 15 s clip and 15.32 s on
the 29.8 s clip. Lowering detector confidence did not repair the WA0010 miss.
No size passes the output gate and the 15-second phone target is still open;
seven-frame wrist smoothing restored the count but scored 63 versus the
reviewed 51, so smoothing also fails the output gate. Per-clip results and
local-only caveats are in the audit. A full-rate, single-model batch-32 run
using six CPU threads took 15.03 s for pose alone on the same 29.8 s clip and
still emitted reviewed-fault disagreements on WA0010; batching therefore does
not close the pose or output gate either.

**YOLO26n CPU screen (2026-10-14):** the full-rate 320 px ONNX candidate posed
the 29.8 s clip in 7.86 s, but measurement was unreviewed/unmeasured. On
WA0010 it returned the right count but score 60 versus reviewed 51 and added
stall faults; controls also auto-classified clips that should be unknown or
abstain. This does not pass the quality gate or prove the full phone target.
Details and limitations are in the [Round 2 audit](SPEED-ROUND2-AUDIT.md).

**YOLO11 worker startup optimization (2026-10-14):** a fork-worker A/B on the
same 40.4 s corpus WA0014 source (603 sampled frames) cut six-core pose wall
time from a 10.95 s subprocess median
to 8.82 s, with bit-identical keypoints in both pairs. The experimental
YOLO11 path now inherits decoded frames and parent imports on POSIX CPU hosts,
falling back to subprocess workers if fork launch fails. Reviewed WA0010 and
WA0020 counts remain 2 and 19; the score/fault and unknown-classification
gates remain open. This recovers pose budget locally but does not prove random
30 s clips can meet upload-to-phone under 15 s: the 40.4 s WA0014 source took
12.49 s through local measurement but returned `unmeasured`; a prepared 30 s
WA0014 clip took 5.77 s in a worker container and returned two reps but a null
session score because range could not be measured; both rep intervals now fail
the reviewed stationary-hang constraint. A prior YOLO11 / opt-in-fusion run of
a different 30 s window containing a scored source rep returned zero after
re-encoding; a later same-checkpoint YOLO26n A/B returns that rep at both 0.60
and 0.59. The full count remains unreviewed, and the container could not
enforce a six-core limit; these timings exclude upload and phone delivery. See
the audit for trim sensitivity and remaining gates.

**Turnaround threshold A/B (2026-10-14):** exposing the historical 0.60
peak-height fraction and lowering it to 0.59 did not change the result on a
same-checkpoint, same-policy comparison: both shifted WA0014 crops returned
the same one rep with identical pose arrays, and both first-30-second crops
returned zero `unmeasured`, which fails the reviewed zero-count gate. The
0.59 cached-pose shadow changed three weak-silver rows; reviewed WA0010/WA0020
counts stayed correct. Keep 0.60 as default; this knob did not repair the
trim failure and does not establish the <15 s phone target. See the
[Round 2 audit](SPEED-ROUND2-AUDIT.md) for artifacts and gate outcomes.

**YOLO26n input-size screen (2026-10-14):** reducing the six-worker CPU
candidate from 480 px to 416 px cut the prepared first-30-second WA0014 pose
time from 7.62 to 5.38 s; 448 px took 5.71 s. Both faster settings introduced
false muscle-up reps inside the reviewed zero-rep window (one at 416, two at
448), so both fail the hard count/interval gate. WA0010 stayed at 2, but
WA0020 remained misclassified as dip and the reviewed unknown WA0017 was
classified as dip/pull-up. Keep 480 px; lower input size buys speed by
breaking the measured result. Timings are single local container passes, not
Lambda or phone measurements; details are in the [audit](SPEED-ROUND2-AUDIT.md).

**MediaPipe Heavy input-width screen (2026-10-14):** reducing the frame width
from native 478 px to 320 px cut WA0010 pose from 20.79 to 15.47 s, still above
budget and still inconsistent with its reviewed score. WA0020 was slower
(20.16 to 20.70 s) and lost one reviewed push-up. This is not a reliable speed
or quality lever; keep the current processing width. See the audit for
landmark drift and exact results.

**MediaPipe tracking threshold screen (2026-10-14):** lowering
`min_tracking_confidence` from 0.5 to 0.1 was 13% faster on WA0010 but slightly
slower on WA0020, with neither clip near the pose budget. Keep the 0.5 default;
the lower threshold is not a reliable speed lever. See the audit for paired
times and output comparison.

**MediaPipe Heavy stateless IMAGE chunks (2026-10-14):** six independent
workers avoided tracker-state drift at chunk boundaries but took 12.03 s for
WA0010 and 11.28 s for WA0020. WA0020 dropped from 19 reviewed reps to 9, so
IMAGE mode fails the quality gate and cannot meet the 30-second pose budget.
Keep VIDEO mode as the measured baseline; see the audit for outputs.

**MediaPipe Heavy half-rate VIDEO screen (2026-10-14):** every-other-frame
pose reduced WA0010 to 8.95 s but still missed the reviewed score/fault gate;
WA0020 fell from 19 reviewed push-ups to one. Reject frame skipping before
chunking; faster pose does not preserve the measured result. Details are in
the audit.

**MediaPipe Heavy GPU-delegate screen (2026-10-14):** the desktop RTX 5060
processed the full 29.8 s WA0014 clip in 7.77 s of pose (8.15 s including
landmarker setup), but returned `unmeasured`. On WA0020 it took 4.47 s and
counted 18 declared push-ups versus 19 for CPU and the reviewed reference; on
WA0017 it returned the same two-rep false positive as Heavy CPU for a reviewed
unknown clip. This proves a desktop GPU can fit the pose slice, not that the
GPU path is quality-approved or deployable on a phone/Lambda. Keep it out of
production pending full positive, negative and on-device validation. A matched
RTX tracking-confidence sweep from 0.1 through 0.7 produced bitwise-identical
keypoints on WA0020 and retained the 18-versus-19 count miss; WA0010 also
stayed bitwise identical at 0.7 and retained its reviewed score miss.
Threshold tuning is not the fix. Around the missing WA0020 rep, GPU hip
keypoints drift by 51.77 px on average (p95 158.94 px) from CPU despite high
reported confidence; the adjacent counted interval has 4.61 px mean hip
drift. The actual 0.5 GPU dropout is two all-zero pose frames at the rep
turnaround; 0.1 detector confidence restores that declared WA0020 rep, but
automatic labels still fail WA0010, WA0020 and the WA0017 negative. The full
reviewed-corpus gate remains failed, so keep the setting experimental. See the
[audit](SPEED-ROUND2-AUDIT.md) for arrays, intervals and the gate output.

With the learned classifier disabled, geometry-only fusion at the 0.1
detection setting passes both reviewed positive clip gates (WA0010 muscle-up / 2,
WA0020 push-up / 19), but the five-clip gate still fails WA0017 and WA0014.
The fast pose candidate is promising only for the positive cases; fusion and
valid measured-zero behavior still need a general, quality-gated design.
An experiment requiring mostly straight arms for front-lever classification
fixed the Heavy WA0017 false positive, but removed four correct front-lever
labels from 261 comparable cached clips (geometry 62/261 to 58/261). Lite's
learned fusion still labels WA0017 muscle-up / 2. Keep the global classifier
unchanged; a valid negative-control policy must preserve genuine front levers
and address model disagreement on the fast path.

**Current Ryzen CPU chunk retest (2026-10-14):** on six pinned physical cores,
Heavy took 23.52 s with the production three-chunk plan and 21.31 s with six
forced chunks; four chunks on the four higher-clocked cores took 22.11 s. Six
chunks were fastest in this local screen but remain 2.7× over the 8 s pose
budget. These single workstation timings do not justify changing the planner;
the recorded CPU topology and landmark drift are in the audit.

**Gate result on Diego's own clips (2026-10-12): DEVIATES.**
`scripts/pose_parallel_check.py` was rewritten to pose BOTH sides with the
real MediaPipe heavy landmarker (the round-1 comparison posed only one side
and diffed keypoints), then run the production `measure_job` on each and
compare the full measured payload — every number the phone shows, not just
keypoints. Results land in `out/parallel-check/<stem>.json`
(`--replay` re-derives the verdict without posing again). All 8 clips from
`data/calisthenics/videos/own/`, 6 workers, `--min-chunk 60` (below the
production floor of 240, forced so every clip here actually splits):

| Clip | frames | seq / par wall | reps | sessionScore | exercise | keypoints max\|diff\| |
|---|---|---|---|---|---|---|
| WA0010 | 367 | 17.5 / 10.0 s | 2 / 2 | **56 → 54** | **pull_up → muscle_up** | 748 px |
| WA0011 | 171 | 6.7 / 8.7 s | 0 / 0 | — / — | knee_raise | 56 px |
| WA0012 | 285 | 11.3 / 7.0 s | 1 / 1 | **59 → 65** | muscle_up | 670 px |
| WA0014 | 1206 | 55.7 / 18.8 s | 0 / 0 | — / — | muscle_up | 823 px |
| WA0017 | 693 | 27.2 / 12.0 s | 2 / 2 | 48 / 48 | muscle_up | 552 px |
| WA0018 | 279 | 10.6 / 9.1 s | 0 / 0 | — / — | muscle_up | 423 px |
| WA0019 | 297 | 12.5 / 8.5 s | 2 / 2 | 50 / 50 | knee_raise | 176 px |
| WA0020 | 497 | 19.1 / 11.1 s | 0 / 0 | — / — | muscle_up | 539 px |

What exactly moved (5 of 7 scored reps by 1–6 points, 19 rep timestamps,
55 metric values at the phone's printed precision, all visible in the saved
JSONs):

- **The exercise flipped** (WA0010): sequential `pull_up` at 0.59 confidence,
  chunked `muscle_up` at 0.58 — the two classes were 0.01 apart sequentially,
  so 1–10 px of drift reorders them. Everything downstream changes word:
  topFixes `pull_up.dropped_descent` → `muscle_up.lift_stall`, and the rep
  metrics gain a `transition_s` the pull-up track does not measure.
- **A blocker appeared** (WA0017): chunked adds "las manos se desplazaron
  1,3 torsos… no es una repetición" for an attempt sequential accepted
  (n_reps survives at 2 only because the other two reps agree). WA0019's
  blocker text says "5,4 s" sequentially, "5,5 s" chunked.
- **Per-rep times** move by one frame mostly (±0.04 s) but up to 0.93 s
  (WA0019 rep1 end 3.5 → 2.57 s), dragging `tempo_ratio` 1.33 → 0.71 and
  `eccentric_s` 2.00 → 1.07 s.
- Keypoint max|diff| of hundreds of px is one outlier landmark for one frame
  (an ear or heel placed on the wrong side), not a uniform offset; measured
  joints move hundredths of a torso, as predicted on 2026-10-11.

**Why DEVIATES is not shippable as-is:** a classifier flip changes which
standard the athlete is judged against, and a new blocker tells an athlete a
rep was not a rep — neither is a rounding step. The gate is exactly the
procedure this plan prescribed; the deviation is now documented, and chunked
pose stays OFF until the measurement call is made on this evidence.

**Enablement, when the user makes the call (deploy decision, one line):** add
`BARRA_POSE_WORKERS: "6"` under `WorkerFunction: Properties: Environment:
Variables:` in `server/template.yaml`, in the same deploy as the 10240 MB
raise (this commit already raises memory; unset stays 1 = sequential). Rollback
is deleting the line. `pose_frames` falls back to sequential on a worker
failure, which protects availability but may exceed the latency budget;
tracker drift does not raise an exception and is not covered by that fallback.
With `MIN_CHUNK=240`, clips below 480 frames remain sequential, 480–719 frames
use two chunks, 720–959 use three, and six chunks require at least 1,440 frames.
WA0011 went 6.7 → 8.7 s at the forced 60-frame floor: startup/warm-up can cost
more than splitting saves. These settings alone do not establish the
30 s upload-to-phone goal.

**Additional dependency to resolve:** `auto` exercise fusion no longer waits
for a late vision locator, but the local fallback's accuracy when vision is
late is unmeasured; visual count rescue still waits for two remote counters
when all geometric passes find no reps. Those independent requests now run
concurrently without a model-list preflight, and its duration/outcome is now
reported by `job_timing.py`; it can still exceed the result budget under
retries. A bounded synthetic live-provider probe timed both concurrent models
out at 15 s on one attempt, already beyond the full target; this is a failure
sample, not a success-latency distribution. Faster pose exposes that rescue
path. Both need latency and accuracy gates; moving advisory prose alone does
not remove them. See the [count-rescue critical-path design](SPEED-COUNT-RESCUE-DESIGN.md).

### E — Measure end to end
`scripts/job_timing.py` before/after on a real 30 s phone job after A–D,
paired with a monotonic phone trace from upload start through the first result
frame callback; table in this section. The script alone stops at
server persistence. **AWS credentials and a connected phone are unavailable
in this shell as of 2026-10-12** (STS and ADB checked); deployment and phone
verification remain outstanding. The implementation and local experiments
can continue independently.

**WA0014 current-candidate negative gate (2026-10-15):** the prepared 30 s,
14.6 MB crop ran through the current six-worker YOLO11s stride-3 worker in
6.620 s (6.493 pose + 0.127 measurement), but returned two geometry-counted
muscle-ups at 27.05–29.80 s inside the reviewed zero-rep window. The quality
gate fails both counts and intervals. Treat 6.620 s as pose/measurement timing
only, not a qualified result or a phone end-to-end success; the negative gate
must pass alongside the reviewed positive window before promoting this speed
candidate. See the [audit](SPEED-ROUND2-AUDIT.md) and its linked report.

A paired WA0014 shadow run with `min-span-amplitude=0.25` took 6.777 s and
returned `0 / unmeasured`: it removed the false intervals without increasing
pose time materially, but still failed the measured-zero gate. Do not promote
the floor until the same exact candidate passes reviewed positive controls;
the experiment and report are in the [audit](SPEED-ROUND2-AUDIT.md).
The existing stride-3 reports for WA0010 (`muscle_up / 2`) and WA0020
(`push_up / 19`) use this same checkpoint SHA and candidate configuration; the
reviewed positive gate passes both. That narrows the next step to implementing
and validating a guarded measured-zero state plus the unknown/visibility
abstention controls, then repeating the uniform cohort gate before phone work.

The count-rescue design now has an executable, offline shadow evaluator for
measured-zero prerequisites. On the saved-pose five-clip screen it proposes
only WA0014 as a zero candidate and keeps WA0010/20 positive, WA0017 unknown,
and WA0018 low-visibility as abstentions. Every result remains explicitly
`unmeasured`; this is not a Round 2 measured-result pass. The current stride-3
WA0014 candidate still fails measured-zero status, and one reviewed negative
is insufficient to integrate the new status. See the [count-rescue design](SPEED-COUNT-RESCUE-DESIGN.md).

A screen of additional scraped zero-count videos found no valid independent
negative: some have no measurable movement, one knee-raise clip visibly contains
reps, and others are mismatched montages. None was promoted to ground truth.
The [screen and contact sheets](../out/round2-latency/geometry-zero-review/weak-zero-candidate-screen-2026-10-15.json)
record why; broader zero validation still needs an independently reviewed,
measurable negative.

The uniform six-worker stride-3 five-clip gate now passes WA0010 (2 muscle-ups),
WA0017 (unknown/unmeasured) and WA0020 (19 push-ups); WA0014 still fails because
the reviewed zero is `unmeasured`, and WA0018 remains an unreviewed coverage
gap. Pose is 2.52–5.71 s and local measurement 0.035–0.105 s on these host
reports, within the pose allocation but excluding upload and phone render. The
[gate artifact](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/uniform-five-clip-quality-gate-2026-10-15.json)
records each row. This supports keeping stride 3 in shadow; it does not close
the <15 s measured-phone requirement.

**Phone timing provenance check (2026-10-15):** I joined recent phone attempts
to their worker traces instead of pooling them by clip alone. The three
reviewed YOLO11s stride-3 runs took 9.777–11.311 s from upload start to render
and all passed the exact `dip / 2` gate; worker pose took 7.044–8.068 s. A
later 18.444 s attempt used a different dirty runtime (Python 3.12.14 versus
3.12.15 in the candidate traces) and pose took 13.469 s. Server inference
explains most of the regression; polling totals overlap worker execution and
are not additive delay. Keep the per-stage budget unchanged, but pin the worker
image, commit, model hash and pose configuration for every latency comparison.
See the [runtime variance audit](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-runtime-variance-audit-2026-10-15.json).

**Immutable Lambda-base image diagnostic (2026-10-15):** I built an isolated
YOLO11s stride-3 worker image from the pinned Lambda Python 3.12 base, with
six fork workers, 480 px input, OpenCV 4.10.0.84 and the experimental 0.25
span-amplitude floor. On four reviewed inputs, pose took 3.577–6.644 s;
measurement added 0.084–0.106 s. The random 30.033 s dip window passed its
`dip / 2` reviewed gate, and WA0010/WA0020 retained their reviewed 2/19 positive
counts. WA0014 returned zero reps but remained `unmeasured`, so its measured
zero gate still fails. This is local container timing: no AWS pull/init, upload,
API or phone render is included, and the image is stamped from a dirty checkout.
See the [image parity artifact](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/lambda-image-candidate/runtime-parity-2026-10-15.json).

**Current phone timing snapshot (2026-10-15):** The installed app now records
monotonic upload-to-render spans. Seven mixed attempts on one emulator boot had
6/7 below 15 s (p50 12.953 s; p95 17.205 s); this mixed aggregate is not a
quality-approved sample. The three comparable runs on the reviewed 30.033 s
dip window remain 9.777–11.311 s, each with `dip / 2 / geometry` and a passing
reviewed gate. A later WA0014 phone attempt took 13.744 s from network-start to
render, with 3.583 s through submit, 10.079 s submit-to-result and 83 ms render.
It uploaded the 40.4 s source (9.85 MB) to the stride-2 local worker; the result
was one muscle-up in the unreviewed 31.32–34.73 s interval. The 12.525 s
preparation measurement occurs before the upload timing origin and must stay a
separate stage. This latest result is not evidence for the random-30 s quality
gate or the stride-3 candidate. See the [phone timing snapshot](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-summary-snapshot-2026-10-15.json)
and [WA0014 trace join](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/wa0014-phone-run-164143-summary.json).

**Controlled current-app phone-flow rerun (2026-10-15):** On the Android
emulator, the current app uploaded the exact reviewed 30.033 s dip window to
the six-worker YOLO11s stride-3 container and rendered the result in **9.922 s**
from network start. The server returned `dip / 2 / geometry`; the frame marker
was 95 ms after result receipt, and the exact source SHA passed the reviewed
window gate. Upload through submit took 2.082 s; the server’s first-result
measurement was 7.616 s. Prose was still off the first-result path. The motion
sampler’s default `[1,21]` suggestion was rejected for this test because it
could crop the reviewed reps; the full, already-30-second source was uploaded.
The 4.212 s pick/copy/sampling stage precedes the defined upload origin. This
uses the emulator host bridge with no network shaping, so it verifies the
current app-to-worker flow but does not stand in for physical Wi-Fi, AWS cold
start or production. The [run manifest](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-controlled-run-2026-10-15-172004.json)
records exact app, worker, input hash, stage timings and limitations.

**Rate-shaped large-clip phone run (2026-10-15):** The same reviewed movement
window was encoded at 720p/4 Mbps (13.87 MB) and sent through a local byte-paced
30 Mbps proxy because emulator `netspeed` does not shape traffic to the host
bridge. Multipart body transfer took 3.751 s. Upload-start to visible result
took 15.508 s: 6.114 s to submit, 9.274 s from submit to result, and 119 ms to
render. The app returned 2 geometry-counted dips and the exact source-window
quality gate passed. This is one shaped emulator run, not a physical-Wi-Fi or
AWS measurement. A preceding same-size attempt returned a result but did not
render, so at that collection point it remained incomplete in the 15-attempt
aggregate (13 complete, 2 incomplete; 10/15 under 15 s, a mixed and
non-quality-approved fraction). The
long submit-to-result interval and fixed multipart request overhead now
dominate more than the paced body transfer. See the [run manifest](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-large-clip-shaped-2026-10-15-173042.json),
[timings](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-timings-current-2026-10-15.json),
and [quality gate](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-quality-gate-2026-10-15-173042.json).

**Exact-file upload-mode A/B (2026-10-15):** I rebuilt only the debug upload
threshold from 8 MiB to 16 MiB and sent the same 13.87 MB reviewed file through
the same 30 Mbps proxy. The existing chooser selected a single PUT; it took
4.901 s from upload start through submit, including a 3.777 s body transfer,
and 13.526 s upload-start to visible result. The prior multipart run on that
same SHA took 6.114 s to submit and 15.508 s to render. The single-PUT run was
1.982 s faster and both returned `dip / 2 / geometry` with passing exact-window
gates. Its server aggregate was 8.459 s, not pose-only; the phone received the
first completed poll about 39 ms after the server result-ready timestamp and
rendered 126 ms later. Three rendered single-PUT runs on this exact input took
13.526–14.157 s (median 13.580 s), and all three passed the exact quality
gate. Their upload-start-to-submit spans were 4.901–5.031 s. An additional
single-PUT attempt returned a retrievable, gate-passing server result but no
phone render, so it stays incomplete. Three multipart attempts took 15.508 s
and 17.138 s to render, while one returned a gate-passing result without a
phone render. All seven server results passed the exact clip gate.
This supports a **candidate** policy: single PUT for quality-approved trimmed
payloads up to 16 MiB when a direct PUT URL is available, with multipart
retained above that size or where resumability is needed. It does not justify
changing the release threshold yet: single PUT retries resend the whole object,
the runs all used one clip and an emulator proxy, and one result in each mode
was not rendered. The release gate still needs randomized reviewed clips,
physical Wi-Fi/cellular, AWS, and a controlled interrupted-upload/resume test.
The exact comparison and logs are in the [A/B
artifact](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-large-clip-upload-mode-ab-2026-10-15.json),
[single-PUT run](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-large-clip-single-put-2026-10-15-173448.json),
and [quality gate](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-quality-gate-2026-10-15-174019.json).

**Physical-phone check on the same reviewed file (2026-10-15):** I installed
the debug build on the Xiaomi at `192.168.1.53:43719`, pushed the exact
1,391,452-byte clip-02 file (SHA-256
`e639093737ca01d98d654c0cfdc1503c79e06a597f96b9a60ed722ca51629662`),
verified it on-device, and chose the full 30.033 s clip. The app used the
single-PUT path. It rendered `geometry / 2` in **8.069 s** from the phone's
attempt-start timestamp; submit-to-render was 7.278 s and the local worker
reported 6.865 s to first result. Upload took 0.687 s. The 17.348 s preparation
stage preceded the measured upload attempt. A saved quality-gate report for
this exact source and reviewed `[88.166,118.166]` window passes `dip / 2`, but
the phone timing row does not retain the full report payload, so this run is
not described as a trace-specific gate replay. The phone reached the host over
ADB reverse through a 30 Mbps byte-paced local proxy and a local worker; this
is a physical-device app-path check, not direct Wi-Fi/cellular or AWS evidence.
It is one run, so it does not replace the randomized phone cohort. The
[physical-phone run record](../out/round2-latency/random-cohort-20261016/physical-phone-clip-02-20261015.json)
contains the timings and provenance. This was a local-worker diagnostic, not
the required AWS acceptance run.

**AWS phone rerun status (2026-10-15):** The saved phone error was five failed
job-create attempts against `http://127.0.0.1:8083`; it came from the earlier
local-proxy build, not AWS. Both the custom domain and API Gateway `/health`
return 200, and the `sam-app` stack is `UPDATE_COMPLETE`. I rebuilt and
installed the debug APK with `https://api.barrapp.fit` and the 16 MiB single-
PUT threshold. The exact reviewed clip has not yet completed on AWS because
wireless ADB went offline during reselection; the AWS phone timing gate remains
open. A mistakenly retried non-test media upload was stopped at six of twelve
S3 multipart parts, then the multipart upload was aborted and `HeadObject`
confirmed no completed S3 object.

**Actual AWS baseline, reviewed clip-02 (2026-10-15):** While wireless ADB
was unavailable, the desktop API harness uploaded the exact 1,391,452-byte
reviewed source through `https://api.barrapp.fit` to S3 and submitted job
`e00f6497201d`. The deployed worker (`ed48f31`, MediaPipe, 10240 MiB; image
digest `8b80f5cdb5b2a0b7508bc79c195b58c30e5256fb4df3e0a42fb9e39366e48586`)
persisted the first result **73.986 s after upload start**. Pose accounted for
**69.817 s**, upload 0.969 s, and submit-to-first-worker-stage 2.042 s.
The API harness passed its 28 basic contract checks in 79 s including polling,
but the reviewed quality gate **failed: 7 dips versus the reviewed 2**. The
older payload also lacks `countStatus`, which fails the current measured-count
schema check. Prose and vision were still pending in the captured first report.
This establishes an AWS baseline that fails both speed and reviewed count;
the earlier local YOLO timing must not be represented as deployed performance.
It measures server persistence from a desktop client, not phone rendering.
See the [AWS run summary](../out/round2-latency/aws-20261015/summary.json),
[stage timings](../out/round2-latency/aws-20261015/timing.txt), and
[exact-result quality gate](../out/round2-latency/aws-20261015/quality-gate.json).

The refreshed same-boot phone log now has 21 attempts: 17 rendered, 4
incomplete, and 13/21 under 15 s. This remains a mixed-input emulator fraction,
not a quality-approved success rate. See the [current timing summary](../out/round2-latency/fusion-v2-final/docker-yolo11s-stride3-screen/emulator-phone-summary-snapshot-2026-10-15.json).
