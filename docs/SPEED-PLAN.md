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
starts (a cold start anywhere in a clip moves it by the same 1–10 px).

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

---

# Round 2 — the 15-second goal (2026-10-11, evening)

**Goal: a random 30 s clip the athlete picks is measured, end to end, in under
15 s — upload to result on the phone.** This is not yet achieved. A–B preserve
measured numbers; C and D require measurement validation: trimming restarts
the VIDEO tracker and re-encoding changes its input pixels. See the
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

Revised allocation (2026-10-12; targets, not measurements):

| Stage | Budget |
|---|---:|
| Upload protocol + bytes through submit | 3.0 s |
| Dispatch, worker initialization, download | 1.0 s |
| Pose, including startup/warm-up/merge | 8.0 s |
| Exercise decision + measurement | 0.5 s |
| First result persistence | 0.3 s |
| Phone polling + parse/store/render | 0.7 s |
| Reserve | 1.0 s |
| **Total** | **14.5 s** |
| Prose/advisory vision/replay preparation | **off the critical path** |

Upload ~2–5 s and pose ~6–10 s cannot both consume their upper budgets:
with 2.5 s of other work, a 5 s upload leaves less than 7.5 s for pose.
Preparation/export and confirm-to-render time are also recorded, separately
from the upload-to-render gate. Full 30 s active sets remain in scope.

## Steps (each its own commit; server changes need deployed measurements)

### A — The untranslated_text sentinel (first, small, independent)
The 16:32 jobs (a muscle-up and a "dragon flag") tripped
`barra/contracts.py` `untranslated_text`: English text still reaches the
phone, probably from an exercise we do not measure (blockers/next-step copy
for a skill with no fault taxonomy). Find the hole in the catalog
(`barra/i18n.py`), close it, test in `tests/test_spanish_payload.py`,
re-vendor (`server/vendor_barra.sh`).

### B — Report prose after the result (exact)
`server/process.py measure_job` waits ~10–15 s of model prose before writing
the result. Send the result first with the fixed Spanish fallback
(`barra/summary.describe`, already `server/report._fallback`), then update
with the model's prose when it lands, exactly like the vision note
(`visionStatus` pending → done). `proseStatus` mirrors `visionStatus`; the
phone re-fetches a session opened in between, same mechanism that already
exists. `proseSource` records what was finally shown. A rejected/failed
model must leave the fallback in place, never an empty headline.

### C — Trim in the app before uploading (upload+pose win; validate quality)
The phone and server must use the same prepared video so replay timestamps
line up. Restarting tracking at a trim boundary or transcoding can change
keypoints and downstream measurements; compare against labels before rollout.
The prepared video's origin is 0; the measured set's `trim.startS` can still
be later than 0 if the prepared video retains a lead-in.

- Suggest the working set on the phone: frame-difference on downscaled
  thumbnails (`MediaMetadataRetriever`) finds the moving window; the slider
  defaults to it, the athlete adjusts.
- Export the trim with Media3 Transformer (720p H.264 ~4 Mbit/s — this is
  SPEED-PLAN step 4 folded in; it changes the pixels decoded by the worker).
  On any Transformer failure upload the original, untrimmed, as today.
- The app-side pipeline (`BarrappViewModel.upload`, `UploadScreen`,
  `WorkStore`) owns this; it must not touch the prose fields of step B.

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

**Additional dependency to resolve:** `auto` exercise fusion waits for the
vision locator (up to 300 s), and visual count rescue can also block the
measurement. Faster pose exposes those waits. A bounded classification path
needs its own accuracy gate; moving advisory prose alone does not remove them.

### E — Measure end to end
`scripts/job_timing.py` before/after on a real 30 s phone job after A–D,
paired with a monotonic phone trace from upload start through first rendering
of the measured result; table in this section. The script alone stops at
server persistence. **AWS credentials and a connected phone are unavailable
in this shell as of 2026-10-12** (STS and ADB checked); deployment and phone
verification remain outstanding. The implementation and local experiments
can continue independently.
