# Round 2 count-rescue critical-path design

## Finding

The zero-rep fallback is still synchronous in `analyze_clip`. When both
geometric segmenters find no repetitions, `count_from_clip` probes the video,
extracts eight stills, base64-encodes them, then waits for two remote model
calls. The requests are concurrent and skip `/models`, but each still inherits
the shared client's 60-second timeout and three attempts. Concurrency removes
the sum of the two call times; it does not impose a deadline.

The Round 2 allocation gives local exercise decision, segmentation, scoring,
and this fallback together 0.5 seconds. On the prepared 30-second WA0014 clip,
five local runs measured the fallback's pre-request work as follows:

| Local operation | Median | Range |
|---|---:|---:|
| `ffprobe` duration lookup | 0.036 s | 0.030–0.085 s |
| Decode and resize eight JPEG stills | 0.407 s | 0.348–0.705 s |
| Base64 encode ~473 KB of JPEGs | <0.001 s | <0.001–0.001 s |

This excludes JSON/prompt construction, HTTP upload, both model responses,
reconciliation and result persistence. The existing 0.5-second allocation
leaves roughly 0.06 seconds after median local preparation for both remote
responses, so the allocation is structurally incompatible with the current
implementation even when the provider is healthy. None of the 193 available
local traces records a count-rescue duration; they do not provide a
provider-latency sample.

The configured retry envelope is nominally `3 × 60 s + 0.8 s + 1.6 s =
182.4 s` per model. Because the two calls run concurrently, this is not doubled
to 364.8 s, but `pool.map` inside the executor context still waits for the
slower request before returning. It is also not a strict wall-clock bound:
`urllib`'s timeout limits socket operations, not the complete request lifetime.
Thus concurrency removes the serial sum but neither bounds the first result
nor makes the 15 s objective safe.

## Synthetic provider probe (2026-10-13)

To avoid transmitting personal footage, one concurrent request per configured
count model was sent with eight locally generated 512x288 stick-figure JPEGs
(about 85,000 base64 characters total). Both used `check_model=False`, a
15-second timeout and one attempt, so this bounds the experiment and measures
one request round rather than exercising the production retries. Both models
timed out while reading at 15.06–15.07 seconds; wall time was 15.071 seconds
and neither returned a parseable count.

This is a failure sample, not a representative latency distribution: it does
not establish whether the cause was provider load, model latency or transport.
It does establish that a single concurrent count round can consume the entire
15-second target with synthetic, small images. The production configuration
(60-second timeout, three attempts and backoff) has no useful first-result
bound when this path is awaited. Production timeout must therefore be treated
as a hard critical-path defect, not just an unmeasured risk. No personal
footage was sent.

## Required behavior

The first phone result must not wait on an unbounded remote count call. At the
same time, timeout or model disagreement must never be rendered as a measured
zero. A missing count needs an explicit unmeasured/abstained state, distinct
from a measured zero, and the acceptance cohort must count such cases as
failures unless review confirms the footage is genuinely unmeasurable.

**Measured-zero behavior is still missing.** On the reviewed first 30 seconds
of WA0014, the geometric path returns zero / `unmeasured`, although the review
shows a measurable clip with no completed muscle-up. Its only turnaround
candidate at 22.95 s is rejected because the hands travel 1.76 torso lengths
against the fixed-bar limit of 0.80; this rejects the walking interval but
does not by itself prove that the whole clip contains no rep. A future
`geometry_zero` result must require adequate pose coverage and a complete,
positive account of the movement window, and must remain distinct from
tracker loss, failed segmentation and an unsupported label. Do not map every
empty `found` list to zero. Validate the rule on reviewed positive, negative
and unmeasurable clips before allowing it to satisfy the measured-result
gate.

The payload now carries `countStatus` (`geometry`, `vision`, `unmeasured` or
`hold`). Android renders frame-based vision counts as estimates and an
unmeasured count as unavailable. Phone timing rows retain the count status and
count, and `round2_phone_report.py` reports a separate under-15 measured-result
fraction. Only geometric counts and hold measurements pass it; frame-based
vision estimates and unmeasured results remain in the all-attempt denominator
but do not pass. This fixes the representation and measurement gate, not the
synchronous provider wait described above.

**Lite zero-count trace screen (2026-10-14):** the current six-CPU worker
image produced 676 observed movement-signal frames out of 894 on the reviewed
WA0014 first-30-second negative (`observed_frac=0.756`). Within the three
active spans, coverage was 75/89 (0.843), 273/273 (1.000), and 167/217
(0.770), for 0.889 overall observed coverage on active frames. The middle
span's movement amplitude was 0.074 torso lengths, below the 0.15 still-span
floor. The only candidate turnaround, at 22.92 s, was rejected because the
hands travelled 1.717 torso lengths against the 0.80 fixed-bar limit. The
reviewed contact sheet confirms this window contains approach, a static hang,
then a drop and walk-away without an ascent/transition. This is stronger
evidence than an empty `found` list: the main active spans were observed, the
stationary hang was explicitly discarded, and the lone candidate was
structurally rejected as off-bar motion. It still represents only one
reviewed negative, so it supports a shadow-rule prototype but does not justify
publishing a measured zero.

A zero-count prototype should preserve this evidence per span: observed-frame
fraction, movement amplitude and floor, candidate-turnaround times, and the
physical reason each candidate was rejected. It must abstain if any active
span is under-observed, any candidate turnaround is itself unobserved, or an
accepted rep exists. Its output should remain a distinct `geometry_zero`
status until reviewed negatives establish that it deserves the same measured
gate as ordinary `geometry` counts. The positive anchors WA0010 (2 muscle-ups)
and WA0020 (19 push-ups) must continue to count as positives; WA0017/18 must
remain unknown rather than becoming measured zeroes. The current evidence
does not yet test a second independently reviewed negative or distinguish a
missed shallow rep from a completed absence, so no production status change is
made.

**Trace coverage support (2026-10-15):** segmentation traces now record the
observed-frame count, total frames and observed fraction inside each active
span, alongside the existing per-span amplitude and candidate rejection
evidence. This makes the coverage prerequisite measurable without changing
the payload or interpreting an empty candidate list as a zero. The current
WA0014 six-CPU run had 732/894 observed frames overall. Replaying its saved
pose array through the current segmenter showed all active-span frames
observed: 273/273, 97/97 and 113/113. The sole candidate still fails the
physical rest-posture check (0.613 torso lengths above the hands; limit 0.30),
and the outcome remains 0 / `unmeasured`. These are useful shadow-rule inputs,
not proof that no shallow rep was missed; no measured-zero status has been
implemented.

The saved-pose five-clip screen classifies WA0010 and WA0020 as positive-count
guards, WA0017 as unknown-movement abstention, WA0018 as no qualifying active
span, and WA0014 as a negative candidate that still needs independent review.
This prevents the unknown and coverage-gap controls from turning into zeroes
under the proposed guard. The screen is recorded at
[`zero-coverage-shadow-screen.json`](../out/round2-latency/fusion-v2-final/docker-reviewed-cohort-amplitude025/zero-coverage-shadow-screen.json);
it reuses saved six-CPU poses and does not add another inference timing sample.

**Current screened candidate confirmation (2026-10-15):** the six-worker YOLO11n
candidate with stride 2, 480 px, `ultralytics-screen-v1` fusion and a 0.25
span-amplitude floor reproduced the WA0014 pattern on the exact reviewed
`[0, 30]` s window: three active spans, only one candidate turnaround, and
that candidate was rejected because its rest posture had the shoulders 0.615
torso lengths above the hands (limit 0.30) over `[22.55, 25.13]` s. It returned
0 / `unmeasured`; the window-scoped quality gate correctly failed it because
an empty result is not a measured zero. Pose took 5.920 s on the scoped repeat
(8.396 s on the first run); local measurement took about 0.08 s. This puts pose
inside the target allocation but does not make the clip pass. A prior trace
from the same video/config has nearly the same span amplitudes and rejection,
so it is a repeatability check, not an independent negative example.

The next shadow experiment should use this fixed matrix before any count
status change:

| Reviewed case | Required shadow outcome | What it guards |
|---|---|---|
| WA0010, muscle-up / 2 | `geometry / 2`; never zero | Positive hanging reps cannot be swallowed by zero logic |
| WA0020, push-up / 19 | `geometry / 19`; never zero | Positive support reps cannot be swallowed by zero logic |
| WA0014 `[0, 30]`, muscle-up / 0 | Candidate `geometry_zero`; require adequate observed coverage in every active span and explicit physical rejection for the sole turnaround | Only reviewed zero-count case; still not sufficient alone |
| WA0017, unknown | `unknown / unmeasured` | Unknown movement is not a measured zero |
| WA0018, unknown | `unknown / unmeasured` | Poor visibility is not a measured zero |
| WA0019, unlabeled swing/attempt | Abstain / `unmeasured` | Unreviewed movement cannot authorize zero |
| A second independently reviewed supported-movement negative | Candidate `geometry_zero` only after the same per-span coverage and candidate-rejection checks | Needed before zero can be considered measured |

For every row, preserve the exact source window, pose-backend/model hash,
observed-frame fraction, active spans, per-span observed coverage and amplitude,
candidate turnaround timestamps, accepted reps and each rejection reason. The
gate should reject a zero candidate if pose coverage is inadequate in any
active span, a turnaround overlaps an unobserved gap, an accepted rep exists,
or the movement label is unknown/unsupported. The reviewed matrix must pass
before `geometry_zero` is included in the phone's measured-result denominator;
latency alone cannot promote it. Available reports constrain the first six
cases across different backends and workflows; they are not yet one uniform
end-to-end gate, and the independent negative is missing.

**Rejected weak-silver negative candidate (2026-10-15):** I screened the
60.07 s pull-up clip `youtube_PKsKcvDfLCQ` because its scraped label says
`reps_estimate=0` and cached geometry also returned zero. A 2 fps contact sheet
shows repeated changes between an extended hang and raised pull-up positions
throughout the clip, so this is visibly not a clean no-rep example. I did not
promote it into the reviewed manifest or use its zero estimate as validation.
The sheet is saved at
`out/round2-latency/geometry-zero-review/youtube_PKsKcvDfLCQ-2fps.jpg`; a
closer 12–24 s sheet is beside it. This is a concrete reason to keep scraped
zero labels out of the measured-zero gate and to require an independently
reviewed negative with source-window/count annotations. A second zero-silver
candidate, `youtube_FUnw-dy_rtQ`, is a 57.24 s knee-raise clip: its contact
sheet shows an interview first, then repeated hanging knee raises, while the
cached segmenter emitted three reps despite the scraped zero estimate. It is
also unsuitable as a negative and demonstrates that the weak zero labels can
hide real repetitions. Its 2 fps sheet is saved at
`out/round2-latency/geometry-zero-review/youtube_FUnw-dy_rtQ-2fps.jpg`.

## Result-lifecycle constraint

`handler.worker` calls `measure_job` before `_write_result`, and `_write_result`
sets the job to `done`. The Android poller treats `done` as terminal and
records the first rendered result. Although the worker later adds advisory
vision/prose and writes the row again, a phone that already observed `done`
does not keep polling for a count update. Therefore a count that finishes
after the first write cannot repair the result the athlete saw. The first
payload must carry a reconciled count or an explicit unmeasured state; a
background count update requires a separate API/client completion protocol.

## Design to test

**Relaxed-pass overlap screen (2026-10-14):** a 300-frame synthetic
three-rep pull-up sequence took a median 2.06 ms in the standard segmenter
and 0.87 ms in `rescue_reps` across nine local runs. This does not model every
phone clip, but it rejects the narrow idea of hiding meaningful remote-count
latency by starting the provider request only after standard segmentation and
running it beside the relaxed pass: that overlaps under a millisecond here.
Hiding the 0.35–0.71 s still-extraction stage would require preparing frames
earlier, while work is already running, and needs an explicit CPU/quality
comparison. Hiding provider latency requires an earlier speculative request,
which sends footage for some clips whose geometric count later succeeds; keep
that as a separate cost/privacy/coverage experiment.

1. Start count rescue speculatively while pose runs only where its prompt has a
   known movement label. Reuse the same extracted stills for both models. This
   overlaps preparation and remote latency with pose instead of placing them
   after the pose result. Automatic-label clips need either a prompt that can
   count the visible movement without a supplied label, or a local label early
   enough to start the requests; benchmark both before selecting a path.
2. Give the speculative task an absolute wall-clock deadline derived from the
   job's remaining first-result budget. The caller performs a non-blocking
   lookup at fusion/measurement completion; it never joins a thread pool whose
   shutdown waits for unfinished model calls.
3. If both replies are not reconciled by that deadline, return a typed
   unmeasured count state, never `0` by implication. Keep the remote work out
   of the first-result path and record completion, timeout, disagreement and
   acceptance separately. The client must render that state before stopping
   its poll loop.
4. Compare the speculative strategy against the current serial fallback on
   reviewed positive, negative and genuinely unmeasurable clips. The gate is
   measured-count parity plus a completed first result under 15 seconds; an
   unresolved count is not a latency pass for a clip that should be measurable.

The experiment is not approved for rollout yet. It adds two model calls to
clips that may ultimately have a valid geometric count, and the app needs to
render an explicit unmeasured state correctly. If latency or measurement
coverage fails, the next candidate is a local count fallback with reviewed
parity, not a longer provider timeout.

## Candidate rejection is not a measured zero

The seeded 30 s sample `youtube_1Wdn3GhtKkU` exposed another lifecycle edge:
the standard segmenter proposed two candidates, but `rep_metrics` rejected both
because each started above the bar. The relaxed validator found none. The old
payload set `countStatus=geometry` whenever the candidate list was nonempty,
even though it returned zero usable reps. `server/process.py` now reports
`geometry` only when at least one candidate passes physical and quality checks;
otherwise, absent an accepted vision count, it reports `unmeasured` while
preserving `n_candidates` and each rejection for diagnosis.

The random clip's corrected worker result remains `muscle_up / 0 / unmeasured`
at 7.844 s. The four reviewed controls were rerun: the 10 pull-ups and 19
push-ups still pass, WA0017 still abstains, and WA0014 still has no measured
zero. This is a result-integrity fix, not a count recovery or measured-zero
implementation. Never turn a rejected candidate list into a measured zero.

## Evidence limits

**Cached-pose shadow replay (2026-10-14):**
[`scripts/round2_count_shadow.py`](../scripts/round2_count_shadow.py) replays
standard segmentation and, only on standard misses, `rescue_reps` against
existing parquet poses. It does not run pose inference or make network calls.
The full pass covered 265 scraped labels: 253 cache hits, 12 misses, 85
unsupported movement labels, and 8 unusable intervals. Of 159 usable rows
with a `reps_estimate`, 24 matched exactly and mean absolute difference was
3.145 reps. These comparisons are weak silver metadata from scraped clips,
not ground truth, and should not be used to tune thresholds. Segmenter runtime
was p50 5.50 ms / p95 26.06 ms on this workstation; that is only the cached
segmentation slice, not upload-to-result latency.

The reviewed root manifest gives a small but useful constraint check: WA0010
returned 2 muscle-ups (reviewed 2), WA0020 returned 19 push-ups (reviewed 19),
and WA0014's only retained interval did not overlap the reviewed 22.61–25.16 s
walking interval. WA0017/18 were not sent through geometric segmentation
because their reviewed movement is `unknown`; this replay therefore does not
validate the production movement classifier's required abstention. The two
positive matches are far too few to establish a count-accuracy gate. Full
machine-readable output is generated at `out/round2-count-shadow/report.json`.

The local preparation measurement used
`out/round2-latency/WA0014-first30s-720p-4mbps.mp4`, `barra.frames.grab_stills`,
and the project virtual environment on the workstation. It does not include
Lambda initialization, upload, phone delivery or render. The provider probe
used only generated frames and does not estimate normal success latency.
AWS credentials and `adb` are unavailable in this shell, so the end-to-end
acceptance gate remains open.

## Executable fail-closed zero shadow (2026-10-15)

`scripts/round2_geometry_zero_shadow.py` now applies the shadow prerequisites to
`zero-coverage-shadow-screen.json`. A row becomes `candidate_geometry_zero`
only when the movement is supported, the production result is already an
explicit `0 / unmeasured`, no geometry reps were accepted, every active span
has at least 90% observed pose frames with matching amplitude evidence, and
every detected turnaround has a timestamp-matched physical rejection (failed
hang, support, or fixed-hands check). Missing, malformed, low-coverage, unknown,
accepted-rep, or unexplained-turnaround evidence abstains. The evaluator always
returns `countStatus=unmeasured`, `measured=false`; it is not wired into the
worker and cannot promote the first result.

The saved-pose screen yields one WA0014 shadow candidate, two positive-count
guards (WA0010/WA0020), one unknown-movement abstention (WA0017), and one
no-active-span abstention (WA0018). Output:
[`geometry-zero-shadow-evaluation.json`](../out/round2-latency/fusion-v2-final/geometry-zero-shadow-evaluation.json).
The pure evaluator has 88% line coverage across 12 tests. This makes the
criteria reproducible, but the one candidate still comes from a single
reviewed negative and an older saved-pose screen. It does not close the
current YOLO11s stride-3 measured-zero gate, which remains `0 / unmeasured`,
and it does not justify a production count-status change. The next data step
is an independently frame-reviewed supported-movement negative, followed by
a uniform candidate run over positives, negatives, unknown and poor-visibility
controls; only then consider integrating a measured-zero status.

**Weak-zero candidate screen (2026-10-15):** I made 1 fps contact sheets for
additional locally available videos whose scraped metadata says zero, plus
three windows of the tutorial montage used for the existing random-window
positive. The candidate sheets show why these labels cannot fill the missing
negative: several are talk/advice clips with no active apparatus span, the
knee-raise clip contains apparent repetitions despite its zero estimate, and
others are movement-mismatched montages or contain actual bar demonstrations.
I did not add any to the reviewed manifest. The machine-readable disposition
list and sheets are under
[`geometry-zero-review/`](../out/round2-latency/geometry-zero-review/weak-zero-candidate-screen-2026-10-15.json).
These sparse sheets reject poor candidates; they are not full ground-truth
annotations. We still need a second supported-movement negative with a clear,
fully observed active span and a frame-by-frame count review.
