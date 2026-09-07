# barrapp — On-device UI Feedback

- **Device:** Moto (model 24117RN76E), 1080×2400, serial `eida4h4xamzhroeq`
- **App:** `com.alektebel.barrapp` (`com.barrapp.MainActivity`), Week 36 · Diego
- **Collected:** 2026-09-06, via ADB (`uiautomator dump` element maps + screenshots)
- **Flows exercised:** Ladder → + FAB → system photo picker → video select → Measuring queue → Work log → Week → session detail → Each rep → Calendar (day cells + session rows + month arrows) → Coach chat (chips, empty send) → "?" button on Week/Coach → NEXT UNLOCK card → "Ask what the week shows" CTA
- **Full navigation map:** see `ux-tree.md` (9 screens, 34 edges verified)

---

## Critical bugs

### B1. Every session entry point opens the same stale record (Aug 14 Muscle-up)
Repro (all three, independently):
- Week → LAST SESSION card, labeled "Push-up · 189 reps · 5 Sept" (ring 49)
- Calendar → day cell **4 Sept** (bounds 614,592–749,727)
- Calendar → day cell **5 Sept** (bounds 757,592–892,727)
- Calendar → session row "Push-up 189 reps · 5 Sept" (bounds 82,1672–998,1807)

All open the detail screen for **"THU 14 AUG · MUSCLE-UP · 78 SOLID · 2 reps"**.
The preview data (movement, reps, date, score) never matches the opened detail.
Looks like the detail route always resolves to the same/last cached session id instead of the tapped one.

### B2. Coach chat silently fails on unanswered questions
Tap chip "Am I getting better, or is that just noise?" (413,656–666,791): the question
bubble appears, then **nothing** — no reply, no spinner, no timeout, no error, no retry,
even after 7+ s. Compare the clip queue, which does surface failures. Empty-input send
correctly no-ops (good), but unanswered questions need a pending + error state.

### B3. "Watch the replay" is a dead button
Session detail (ui-09 dump): the button is rendered with primary outlined styling but has
**no clickable node** in the hierarchy. Only "Each rep" responds. Either disable it
visually (greyed + reason, e.g. "clip not kept on device") or wire it up.

### B4. "?" is not help — it silently jumps to Coach
Tap (923,121–1058,250) from Week → lands on the **Coach chat tab**. It is a mislabeled
navigation shortcut, not a help affordance: users tapping "?" expect instructions and get
a chat instead, and on the Coach tab it is a visible no-op (screen unchanged, verified by
dump). There is no help/onboarding screen anywhere in the app. Fix: use a chat/speech-bubble
icon for the Coach shortcut (or drop it — Coach is already in the bottom nav) and add real
help, or remove the dead button.

### B5. Week chart: Friday bar swallows the "F" day label
Week screen: the day-label row exposes M, T, W, T, S, S TextViews — **no F node exists**;
the tall Friday bar draws over the label baseline. Bars are also not anchored to the same
baseline as the empty-day dashes.

### B6. Calendar last row is misaligned
28/29/30 sit at x≈186/519/852 (pitch ~333 px) vs the grid pitch of ~143 px, and the row
gap is 238 px vs 143 px elsewhere. The trailing week is laid out with different column
math than the full rows.

### B7. Ladder: duplicated copy
Muscle-up card renders "Still needed: Still needed: the same volume at 73 or better…".
Prefix is applied twice (template + data).

### B8. Calendar month arrows are dead controls
‹ (center 906,306) and › (center 996,306) render as outlined buttons but are plain TextViews
with `clickable=false` and no clickable ancestor. Precise taps on both produced no month
change (September 2026 persists; verified twice by dump). Users cannot reach any other
month — the whole history beyond the current month is unreachable.

---

## Moderate bugs

### M1. Stale "← Week" back-link on root tabs
Coach (a root tab) shows "← Week" (45,220–180,355). It also persists after navigating
Calendar → detail, and tapping it lands on **Week**, not Calendar — back context is lost.

### M2. Ladder cards are not clickable
No CLICK flags on Pull up / Muscle up / Weighted pull-up cards (0,250–1080,2059 scroll
area). Dead content on the app's namesake screen.

### M3. Queue list: ambiguous and developer-facing entries
- Two clips labeled identically "Clip · 00:20" (add-time HH:MM); no duration/thumbnail to
  disambiguate.
- "unknown job" shown as the entire error for two clips.
- Raw exception text surfaced to users: `Unable to resolve host "gogtzcttw6.execute-api…":
  No address associated with hostname` (queue + Work log).
- Work log shows raw hex ids ("job b7fac9eb67ca") in the header card.
- Third queue row's Retry/Log/Dismiss start hidden behind the bottom nav until scrolled;
  "failed" badge crowds the wrapped error text.

### M4. Contradictory numbers across screens for the same dates
- Coach: "2026-09-04: Muscle-up, **4 reps** measured" and "your **1** recorded session".
- Ladder: Muscle-up best session "**58 verified reps**" on 2026-09-04.
- Calendar: 4 Sept = **Push-up, 514 reps**; 2 measured days; Week: 703 reps.
Three different rep counts for 09-04 and a session-count disagreement (1 vs 2).

### M5. Unlabeled scores
"49" ring on Week LAST SESSION card, "49"/"56" on Calendar session rows — no caption
explaining these are technique scores (the detail screen's "78 SOLID" has one; previews don't).

### M6. Session detail: raw enums + contradictory verdict state
Observed on the 5 Sept push-up detail (reached via Week card after the queue drained):
- Header leaks the raw enum and ISO date: **"2026-09-05 · PUSH_UP"**, while another record
  renders humanized "THU 14 AUG · MUSCLE-UP". Two different formatters for one field.
- Ring shows **"— / UNMEASURED"** while the headline verdict says **"Solid set. Fix the
  stall."** — an unmeasured set cannot be "Solid".
- Section header **"TWO THINGS TO CARRY INTO THE NEXT SET"** above a **one**-item list.
- Rep counts disagree with the entry card: Week card "189 reps" vs detail "19 reps over a
  19-second working set".

### M7. Suspected auto-navigation when a background job completes (needs repro)
While on Calendar, tapping ‹ at 16:04 coincided with the queued clip finishing measuring
(Week total jumped 703→744) and the app **switched to the Week screen** unrequested. A
repeat of the same tap stayed on Calendar — so either a job-completion listener calls
navigate (focus-stealing), or a stray gesture handler exists near the header. Needs a
controlled repro with the queue busy.

---

## Polish / suggestions

- Coach reply greets with lowercase "diego" ("I only answer from what has been measured,
  diego,") — template reads unnaturally; use the display name capitalized or drop it.
- Chat history has no "new conversation"/clear action; old answers ("1 recorded session")
  persist misleadingly after new data arrives.
- Session detail has a large empty area below the fold on a 2400-px screen; consider
  pulling "Each rep" content up or adding next steps.
- Week chart bars aren't tappable — no way to inspect a day from the chart.
- "+703 vs last" badge floats right of the stat block; aligns oddly with the two-line label.
- Queue could offer a bulk "Dismiss all failed" (5 individual dismisses needed).
- Photo picker inherits system locale (Spanish UI) while the app is English — unavoidable
  system component, but worth noting for bilingual users.

## Accessibility gaps (from hierarchy dumps)

- Bottom-nav items, + FAB, "?" button, and queue Retry/Log/Dismiss all have **empty
  content-desc** and no resource-ids (Compose) — TalkBack announces nothing useful.
- Calendar day cells expose only the bare number ("4") — no date/state description
  (e.g. "4 September, measured, solid").
- Tap targets are otherwise good: ≥135 px everywhere, nav labels help icon-only buttons.

## What works well (keep)

- Four named stages instead of a fake percentage; honest, distinctive copy throughout.
- Per-rep card: trajectory sparkline + weighted Range·40/Control·25/Smoothness·35.
- Work log ("WHAT HAPPENED, IN ORDER") with Copy log; failed clips keep the clip and
  offer Retry/Log/Dismiss — good failure affordances.
- "Skip ahead to the result" and leave-while-processing messaging.
- Queue survives navigation; empty-send is correctly ignored.
- Cross-tab shortcuts are wired and work: Week → NEXT UNLOCK card → Ladder;
  Week → "Ask what the week actually shows →" → Coach.

## Not covered (next pass)

- Retry/Dismiss end-to-end in the queue; "Skip ahead to the result"; Coach free-text
  keyboard send; success "result" celebration screen (if any) now that a clip measured;
  landscape; TalkBack walkthrough; multi-select in picker; Aug/Oct calendar views
  (blocked by B8).

---

# barrapp — Algorithm evaluation: rep detection, movement classification, fault classification

- **Collected:** 2026-09-07, LLM Council run (3 Nan planners: deepseek-v4-flash,
  glm5.3-flash, qwen3.6; deepseek-v4-flash judge; plans anonymized + randomized)
- **Scope:** all three measurement stages — rep segmentation (`barra/ingest.py`),
  movement classification (`barra/classify.py`), fault/error classification
  (`barra/faults.py` + `barra/faults_taxonomy.py` + `barra/holds.py`)
- **Constraints held:** no learned classifiers, geometric rules that fail loudly,
  CPU-only Lambda worker, thresholds mirrored to Android `Cues.kt`, label-free validation
- **Full artifacts:** `llm-council/runs/20260907-evaluate-the-three-algorithm-stages-of-t/`
  (`judge.md`, `final-plan.md`, 5 raw plan attempts). Judge scores: 8.5/10 and 7.5/10
  (qwen3.6 failed plan validation on 3 attempts — recorded, judged without it).

## P0 — Fault layer emits geometrically false faults

**Finding C1. Squat/dip/push-up/pull-up inherit muscle-up's bar faults on hip-origin geometry**
(`barra/faults_taxonomy.py` `classify_failures:283-296`, `barra/metrics.py` `_series:164-190`).
`classify_failures` routes `squat`/`pull_up`/`dip`/`push_up` to `muscle_up()`. For hip-origin
movements, `shoulder_above` is measured against the **hip midpoint**, so `start_depth ≈ −1.0`
torso and `peak_height ≈ 1.0`. Downstream in `values_for_rep` this yields:
- **"dead hang" fires on every squat rep unconditionally** (`hang_pct ≈ −100/arm < 75` always);
- **"momentum" can never fire** — `swing` is hip-lateral vs the hip origin itself, self-referential ≈ 0;
- lockout is an anatomy lottery: `lockout_pct = 100/arm < 85` fires when arm:torso > ~1.18.

**Fix (planned):** add a `squat()` classifier with ankle-referenced depth (hip-over-ankle at
turn vs the rep's own standing baseline — vertical, azimuth-invariant) and `uncontrolled
descent` (tempo); keep the bar-fault block for wrist-origin tracks only; suppress `momentum`
for hip-origin until a real sway signal exists.

**Finding C2. "bent arms" can never fire — missing measurement defaults to healthy**
(`barra/faults_taxonomy.py` `_f` call sites: 69, 73, 76, 91, 95, 99, 131, 147, 155).
`_f(values.get("arms_straight_frac"), 1.0)` treats an absent measurement as 1.0 = healthy.
Only `holds.py:_hold_metrics` produces that key; the rep path never does, so the fault is
dead code on reps. Violates the repo's own rule: *a missing measurement never satisfies a
condition*. **Fix:** three-valued handling — absent/NaN → not fired and recorded in a
per-rep `unmeasured` list; either measure elbow angle at lockout for rep rows (O(T), reuse
`classify._angle`) or drop and document the fault.

## P0 — Fragile fault contract

**Finding C3. Faults derived by regex-parsing human-readable strings**
(`barra/faults.py:35-63`). Lockout/hang/stall are extracted by regex from the `range` /
`smoothness` components' **why-strings** ("lockout NN% of full"). Any copy rewrite silently
breaks fault detection on phone and harness. **Fix:** ship structured numeric rep-row fields
(`lockout_pct`, `hang_pct`, `stalled_frac`, `tempo_ratio`, `swing`); keep the regex path one
release as a deprecated fallback; pin boundary comparisons on the unrounded float. Validate
with a **reword-invariance test** (mutate the why-string, assert the fault set is unchanged).

**Finding C4. ~20 pinned constants scattered and triplicated**
(`faults.py`, `faults_taxonomy.py`, `classify.py`, and Android `Cues.kt`).
`SWING_TORSO 0.4`, `LOCKOUT_MIN 0.85`, `HANG_MIN 0.75` duplicated in two modules plus
mirrored on the phone; segmentation adds `0.35` prominence, `0.6` turnaround gate,
`ANCHOR_FIXED 0.80`, `HOLD_FRAC 0.55`, etc. **Fix:** one frozen `THRESHOLDS` block in
`barra/config.py` (honoring the `docs/CORE.md:188` contract that thresholds live there and
are fingerprinted) + a `Cues.kt` parity test that parses the Kotlin literals and asserts
equality.

## P1 — Rep detection undercounting

**Finding C5. Clip-wide amplitude and rotation poison the standard pass**
(`barra/ingest.py` `segment_reps_verbose`, `active_mask`; `movements.py` `tracking_signal`).
rest/apex percentiles are taken clip-wide over active frames, so one span's amplitude sets
the bar for all spans; camera roll/azimuth drift lowers apparent turnarounds (0011: camera
rotating through the set → 0 reps; 0010: 3 shown, 2 counted; 0012: 2 shown, 1 counted).
Also `max_half_rep_s=4.0` truncates slow eccentric reps. **Fix (planned, flag-gated):**
per-active-span amplitude; roll normalization of the **segmentation signal only** (bar-axis
from the wrist pair; never the normalized skeleton — `test_rotation_is_not_removed` holds);
fatigue-tolerant re-admission via the existing gradient-MAD validation; rescue pass walk
scoped to the containing span. Targets: 0010 → 3, 0012 → 2, with camera-motion and
noise-only nulls so nothing is invented.

## P1 — Movement classification

**Finding C6. Whole-clip percentile features include the standing walk-in**
(`barra/classify.py` `features`). `shoulder_above_hands_p95/p05`, `arm_articulation`,
`hands_overhead/below_frac` are computed over the whole clip; standing prefix/suffix frames
with hands at the sides shift the extremes. A fixture shows a standing-prefix bar clip can
flip `pull_up` ↔ `muscle_up`, and a rest-dominant clip falls to `unknown`.
**Fix (planned):** scope those features to active/anchored spans (prefix-invariance test:
adding standing frames cannot flip the label); keep whole-clip `parked_frac` hold-rejection.

**Finding C7. One label per clip; mixed or drifting clips cannot be measured**
(`barra/classify.py` `classify`). The cascade assumes a single movement per clip. **Fix
(planned):** classify per active span; agreement → single label + span count; disagreement →
loud blocker naming each span's verdict (no silent majority).

**Finding C8. "Confidence" is really margin-to-threshold** (`classify.py:485-564`,
`certain >= 0.65`). The 0.70–0.98 numbers are threshold margins, not probabilities, but the
gate reads them as certainty. **Fix:** bounded margin statement + explicit
`certainty: "margin-to-threshold"` field.

## P1 — Viewpoint sensitivity

**Finding C9. PLANAR faults computed and fired regardless of camera bin**
(`barra/faults_taxonomy.py` `pistol_geometry:197-243`).
`knee_valgus` (frontal quantity) and `torso_lean` (sagittal quantity) are computed for every
clip; `docs/FINDINGS.md` already showed a 10° azimuth move outweighs a deliberate error.
**Fix (planned):** prefer the declared `view`/`declared_bin` from `sessions.csv`, else the
estimator; fire PLANAR faults only when the view is *knowable* (camera_side agreement ≥ 0.70
and `R_true` inside `ANATOMICAL_PRIOR_RANGE`), else emit `unmeasured`; replace the
depth-confounded `heel_raise` with a self-referenced planted-ankle-rise signal.

## P2 — Taxonomy coverage gaps

**Finding C10. The 5-most-cited errors per exercise are mostly unmeasured**
(see `tecnicas-errores-comunes.md`). Today only 5 shared bar faults exist for
squat/pull-up/dip/push-up. Planned measurable additions (each threshold pinned before
results are seen, validated on synthetic + deliberate-fault clips):
- push-up: `sagging hips` (hip below the shoulder-ankle line), `head position`;
- dip: `too deep` (elbow angle at bottom < 90°), `bounce at bottom` (no near-zero-velocity
  frame near the turnaround);
- pull-up: `no active hang` (elbow angle < 150° at rep start), `too fast` (concentric_s
  < 0.5× the set's own median — INVARIANT);
- holds: `no protraction` (shoulders-over-hands), experimental scapular-elevation signal.
Deliberately **never measured** (no 2D keypoint evidence; declare it, don't fake it): gaze,
wrist loading, grip type, elbow flare 90° (needs top-down camera), lumbar rounding,
progression-skipping.

## Judge's caveats before implementing

- **Re-establish the green test baseline first.** In this environment the suite ran
  107 tests with 2 failures/16 errors (documented baseline: 137). Until the correct
  `.venv` (mediapipe present) is green, "behaviour-preserving" parity claims are unfalsifiable.
- Roll normalization may not move clip 0011 if its motion is azimuth/pitch, not roll —
  the claim on 0011 is contingent; run the Phase-4 probe before documenting a gain.
- Synthetic detectors measure the noise model, not reality; the deliberate-fault corpus is
  thin — new thresholds ship INCONCLUSIVE on real footage until clips are filmed.
- Every fix pairs with label-free validation: synthetic invariant tests, reword-invariance,
  prefix-invariance, camera-motion nulls, `validate_faults` deliberate-fault clips,
  FPR ≤ 20% / detection ≥ 60% verdict rule, and the `Cues.kt` parity test.

---

# barrapp — Brainstorming: making the fault-classification pipeline better and more realistic

- **Date:** 2026-09-07 (brainstorming only — no implementation yet, design not yet approved)
- **Classified:** architectural — reworks how the fault layer fits together and alters the
  contract others depend on (`Cues.kt`, the payload shape, `metrics.py` geometry).
- **Goal (user):** treat the existing C1–C10 findings as the base and rework the fault layer
  cohesively ("all of it / broader redesign"), not pick a single theme.
- **Scope decision:** fault-classification stage only — `barra/faults.py`,
  `faults_taxonomy.py`, `holds.py`, `metrics.py` geometry, `config.py`, `Cues.kt` contract.
  Upstream segmentation (`ingest.py`) and movement classification (`classify.py`) findings
  (C5–C7) are out of scope / later backlog.
- **Phone-contract decision:** the server ships a **structured `faults` array** with numeric
  evidence (`value`, `threshold`, `view`/knowability). `Cues.kt` renders named faults only —
  no regex, no re-derived thresholds, no threshold copy. Fixes C3/C4 at the root.

## Why "more realistic"

The current evidence record (`metrics.py` `values` dict) is:
- **not view-aware** — planar faults are computed regardless of camera bin (C9);
- **not three-valued at the taxonomy level** — `_f(x, 1.0)` defaults an absent measurement
  to healthy, so a fault silently never fires (C2);
- **consumed by the phone via regex-parsed prose + duplicated thresholds** (C3, C4).

## Approaches considered

### A — Declarative fault table
Define a canonical set of measurement primitives (each with a knowability state: *measured /
unmeasured / view-blocked*), then a per-track table where each row is
`(fault, condition, required view, threshold)`; one engine evaluates every row.

- **Pros:** coverage is just adding rows (fixes C10 cleanly); view-gating and three-valued
  logic are enforced uniformly (C9, C2); the "deliberately never measured" set becomes data,
  not prose; thresholds referenced from `config.py` (C4); a test can enumerate every row.
- **Cons:** biggest rewrite; new engine + careful primitive taxonomy; loses the per-track
  narrative in code.

### B — In-place repair of per-track functions
Keep `front_lever()` / `planche()` / `muscle_up()` / `pistol_squat()`; add `squat()`,
`push_up()`, `pull_up()`, `dip()`; fix the `_f(x, 1.0)` default to three-valued; add a view
param; ship a structured `faults` array.

- **Pros:** smallest diff, familiar shape, easy to migrate incrementally.
- **Cons:** coverage is still per-function; view-gating and three-valued logic must be
  hand-coded in each track (easy to forget); "never measured" stays as prose; drift risk high.

### C — Evidence-first pipeline with per-track predicates (recommended)
Split into two layers:
1. **`evidence.py`** (new, or a refactor of `metrics.py`/`holds.py`) computes one canonical,
   **view-aware, three-valued** evidence record per rep/hold — each primitive carries a
   knowability state and robustness class (INVARIANT / SCALED / PLANAR).
2. **`faults_taxonomy.py`** keeps readable per-track predicates that consume *only* the
   evidence record; a fault is a predicate like `measured(depth) and depth < DEPTH_MIN` —
   absent or view-blocked primitives make the predicate unmeasured, never healthy.

- **Pros:** centralizes the hard/fragile parts (geometry, knowability, view-gating,
  three-valued logic) in one layer so no track can forget to view-gate or default-to-healthy;
  keeps the per-track docstrings; ships the structured `faults` array (chosen contract);
  fixes C1–C4, C8, C9 and sets up C10 as explicit per-track additions.
- **Cons:** meaningful refactor (new evidence layer, touches `metrics.py`/`holds.py`); needs
  the view bin threaded from `viewpoint.py` into the evidence record.

All three hold the hard constraints: geometric rules, fail loudly, no learned classifiers,
CPU-only Lambda, label-free validation.

## Open decision
Direction not yet chosen — C recommended; mix with A's table for the "never measured" set is
an option. Next step is a sectioned design + written spec at `docs/superpowers/specs/`.
