# On-device pose for the Round 2 first result

## CAPABILITY

Let an athlete receive a measured first result for a random 30-second clip in
under 15 seconds by running the current Heavy PoseLandmarker in Android VIDEO
mode while the clip upload starts, then sending the derived pose array to the
worker for the existing geometry and scoring pipeline. The video remains
available for replay and advisory vision, but those later tasks must not hold
the first result.

This is an alternate architecture candidate for the same user-visible
15-second outcome. It does not yet prove the Round 2 server-side requirement
for six-core chunked pose and must not be described as passing that gate.

## CONSTRAINTS

- The measured result remains based on every decoded frame of the prepared
  clip. Do not lower frame rate, interpolate missing frames, or change model
  size without a reviewed quality decision.
- Use the same Heavy `.task` model asset and MediaPipe Tasks VIDEO mode as the
  Python worker. Android VIDEO mode tracks decoded frames and requires
  monotonically increasing timestamps; the official Android guide describes
  video-frame inference and tracking behavior ([Pose Landmarker for Android](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/android)).
- Preserve the current Python adapter's conversion: BlazePose 33 landmarks to
  COCO-17; normalized x/y back to original prepared-video pixels; confidence
  equals visibility × presence; retain source width, height and FPS.
- The model result is untrusted client input. The server validates schema,
  frame count, finite values, confidence range, dimensions, payload length,
  frame-rate bounds, model identifier, and owning job before measurement.
- A first result with no geometric count remains `unmeasured`; an estimate or
  abstention does not pass the measured-result cohort.
- Video upload, replay artifact preparation, vision notes and prose continue
  after the first result. They need independent `videoStatus`, `visionStatus`
  and `proseStatus` lifecycles; none may overwrite measurement fields.
- Android MediaPipe Tasks supports CPU and GPU delegates. GPU availability is
  device-dependent and must be detected with a CPU fallback; the Android Tasks
  setup guide documents delegate selection ([hardware acceleration](https://developers.google.com/edge/mediapipe/solutions/setup_android)).

## IMPLEMENTATION CONTRACT

### Actors and surfaces

- Android `BarrappViewModel` owns the upload-start clock, local decode and pose
  work, the pose payload upload, and the existing background video upload.
- The API owns an authenticated measurement-job lifecycle and a bounded,
  versioned pose-payload upload.
- The worker validates the pose payload, constructs `PoseResult`, calls the
  existing measurement path, persists the first result, then processes the
  video when it becomes available.
- The existing result screen renders the first result as soon as the current
  `done` contract is met. It can show replay/advisory sections as pending.

### Data contract

Define `pose-v1` as a little-endian contiguous `float32` array with shape
`[frameCount, 17, 3]`, ordered COCO-17 and containing `(xPx, yPx, confidence)`.
For 900 frames this is 183,600 bytes before envelope or compression. Send a
small JSON metadata envelope separately or prefix a fixed binary header with:

- schema version and pose backend identifier;
- SHA-256 of the model asset and app build/version;
- prepared video SHA-256, width, height, FPS, frame count, duration and
  orientation after trim/export;
- coordinate units, landmark order and confidence formula;
- payload byte length and SHA-256.

Use the same prepared video for local inference and background upload. This
keeps the result timestamps aligned with replay and avoids making the Android
decoder infer from one crop while the worker later analyzes another.

### Job lifecycle and interfaces

1. The phone starts the authenticated job and its video upload, then begins
   local VIDEO-mode pose inference. Both operations share the same first-result
   monotonic clock. Video parts may finish before or after measurement.
2. The phone uploads `pose-v1` under the same job id using a bounded body
   limit and idempotency key. The server rejects duplicate/conflicting hashes
   and validates every frame before queueing measurement.
3. The worker consumes the pose payload through a new `measure_pose_job`
   entrypoint. It must not open, probe or download the video on this path.
   Refactor metadata-dependent code to accept validated `PoseResult` metadata
   directly; do not synthesize a dummy video file.
4. The worker writes the first measured result and marks measurement complete.
   Video upload completion is a separate state transition; it cannot reset or
   delay the result poller's terminal measurement state.
5. Once the video arrives, background work may generate replay artifacts,
   technique notes and prose under their existing post-result ownership rules.
6. If local pose or pose-payload validation fails before a result exists, the
   app falls back to the existing full-video worker path. It records the
   fallback reason and keeps the same attempt id so timing denominators do not
   hide failures.

### Latency budget

The video upload and local pose run concurrently. The first-result budget is
measured from the start of that upload to the first rendered, measured result.

| Stage | Target |
|---|---:|
| Job creation + video upload start | 0.5 s |
| Full-rate on-device decode + pose | 8.0 s, overlapping video upload |
| Pose serialization + authenticated upload | 0.5 s |
| Dispatch + worker initialization | 1.0 s |
| Local classification, geometry and scoring | 1.0 s |
| Result persistence | 0.3 s |
| Phone polling, parsing and render | 0.7 s |
| Reserve | 3.0 s |
| **Total first-result wall-clock allocation** | **14.5 s** |
| Full video upload, replay, vision note and prose | **after first result** |

Because pose and video upload overlap, the stage targets are not summed as
sequential durations. The measured acceptance gate remains strict: every
attempt is in the denominator, and the result must carry a geometric or hold
count to pass. Report p50/p95 for pose, upload, server measurement, and
upload-start-to-render separately.

## NON-GOALS

- This capability does not replace the current server-side Heavy backend until
  parity and end-to-end gates pass.
- It does not add asynchronous count repair, alter scoring rules, infer a
  different exercise from video, or treat a frame-based estimate as measured.
- It does not make full video upload optional; replay and advisory analysis
  still require the video.
- It does not assume every Android GPU delegate supports the model or that
  local inference will meet the budget on every device.

## OPEN QUESTIONS

- Can Android VIDEO-mode Heavy produce the same `[T,17,3]` values as the
  Python Tasks backend on all eight own clips after matching frame decode,
  rotation, resize, timestamps and model hash?
- What is the on-device pose p95 on Diego's phone, including decoder and model
  startup, and does GPU execution remain stable under thermal throttling?
- Should the `.task` asset ship inside the APK or download once with a signed,
  versioned model manifest? The 30 MB asset affects app download size versus
  first-use time.
- Can the API create one logical job with both a pose payload and a resumable
  video upload while preserving the current authorization and cleanup rules?
- Which API field reports measurement completion independently from video
  upload completion without causing the client to stop polling too early?
- How are Android decoder orientation, variable-frame-rate timestamps and
  Python OpenCV frame sampling normalized for parity? Existing quality gates
  compare values, not just schema compatibility.

## HANDOFF

**Decision update (2026-10-14): the server CPU path has no passing candidate.**
On the prepared 30 s clip, Heavy took 47.24 s sequentially and 19.13 s in six
forced chunks; the production floor produced three chunks in 18.28 s. Further
local screens rejected lower input width, lower tracker confidence, stateless
IMAGE chunks and 15 fps Heavy on reviewed quality or timing. The server path
still remains the primary architecture until an alternative proves parity,
but this evidence makes an on-device accelerator spike the highest-value next
experiment. It does not establish that a phone GPU will be fast enough.

**Desktop GPU delegate screen (2026-10-14):** Heavy VIDEO on the local RTX
processed a full 29.8 s clip in 7.77 s of pose (8.15 s including landmarker
setup), but returned unmeasured. On reviewed WA0020 it counted 18 declared
push-ups versus 19 for Heavy CPU and the reference; on WA0010 the declared
score was 57 versus CPU 56 and reviewed 51, with a 0.08 s turn-boundary
shift. On reviewed negative WA0017, both GPU and CPU returned the same false
positive (muscle-up / 2 / score 48) despite the GPU taking 6.22 s and CPU
34.05 s. Thus local GPU speed is credible, but keypoint/measurement parity
and the classifier's negative behavior are not. Do not port this as an
approved Android path. A real-phone probe must gate on decoded-frame parity,
the full reviewed payload, thermal repeats, and a correct negative-control
abstention before measuring upload overlap.

On the same RTX candidate, disabling learned-model fusion while keeping
geometry-only classification recovered both reviewed positives (WA0010 / 2
muscle-ups and WA0020 / 19 push-ups), but the five-clip gate still failed the
WA0017 unknown hold and WA0014 measured-zero cases. The phone spike should
compare both fusion policies on identical poses and preserve these failures in
its acceptance report; the two positive fixes are not enough to promote it.

The RTX follow-up rules out `min_tracking_confidence` tuning as the fix:
WA0020's GPU keypoint arrays were bitwise identical at 0.1, 0.3, 0.5 and 0.7,
yet all missed the same reviewed rep. Lowering `min_pose_detection_confidence`
from 0.5 to 0.1 restored the two all-zero GPU frames at that turnaround and
recovered the declared 19-rep count (0.25 did not). This did not fix auto
classification or the WA0017 negative control, so it is only a candidate
configuration to test on-device. The GPU/CPU comparison around the interval
found high-confidence hip drift of 51.77 px mean / 158.94 px p95, versus 4.61
px mean in the adjacent counted interval. On-device comparison should report
per-joint and per-reviewed-window drift alongside confidence, and compare
complete rep intervals, labels, scores and faults. A clip-wide mean or
confidence-only gate can hide the failure mode observed here.

**Needs a physical-device spike before implementation.** The repository has a
reusable measurement entrypoint that accepts a precomputed pose object, but the
worker lifecycle still requires a video and there is no Android pose
dependency or pose-payload endpoint. On Diego's phone, first compare full-rate
Heavy VIDEO-mode keypoints against Python for WA0010 and WA0020; time decode,
model startup, pose and thermal repeats. Only after keypoint and reviewed
measurement parity should a 30 s clip test measure overlapping upload through
first render against the same 14.5 s allocation. Continue only if both parity
and the end-to-end budget are credible; keep the existing server path as
fallback and do not weaken the quality gate.
