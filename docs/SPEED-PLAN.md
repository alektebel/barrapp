# barrapp — Making the pipeline fast

> 2026-10-11. Goal: the athlete sees reps and score **in under ~1 minute** after
> the upload finishes, without changing a single measured number. Every step is
> measured before and after on real jobs, and has tests first.

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

## Rules for every step

- Tests first; each step lands as its own commit and, where it touches the
  server, its own deploy with the previous image noted for rollback.
- **No step may change a measured number.** Steps that would (fewer frames, a
  lighter model) are out of this plan and wait for the reference clip set.
- Each step is measured with the same tool (step 0) on a real job.

## Steps

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

### Step 4 — Compress the clip on the phone before uploading
Pose runs at 640 px; a 1080p/4K phone clip is uploaded for nothing. Transcode
on the phone to 720p H.264 (~4 Mbit/s) with Media3 Transformer before the
upload; on any failure upload the original. 3–10× fewer bytes: the upload
becomes seconds even on a slow network, and so does the worker's download.
*Tests:* the decision (when to transcode, target size) and the fallback; a
Robolectric test cannot transcode, so the real check is one clip on the phone.

### Step 5 — Measure end to end and write it down
One real clip from the phone after steps 1–4: `job_timing.py` before/after
table in this document.

## Later (not in this plan)
- **Fewer frames (15 fps) or the *full* model** — 2–3× more, but changes what is
  measured: only with the reference clip set and its gates.
- **Pose on the phone** — MediaPipe runs faster than real time on the phone's
  GPU; the app would send keypoints (KB) and the result would be seconds after
  picking the clip. The video goes up later, in the background, for the vision
  note and the replay. The right long-term shape; needs phone/server parity.
