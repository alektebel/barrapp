# Plan

## Overview
Evaluate the three algorithmic stages of the barra measurement core (rep segmentation in `barra/ingest.py`, movement classification in `barra/classify.py`, fault/error classification in `barra/faults.py` + `barra/faults_taxonomy.py`), rank concrete weaknesses by severity, and deliver a prioritized fix plan that stays inside the project's fixed philosophy: geometric rules, no learned classifiers, no labelled footage, three-valued logic on missing measurements, and falsifiable documentation. Every fix is paired with a label-free validation method (synthetic invariant tests via `barra/synthetic.py` + the 137-test harness, deliberate-fault clips through the `barra/validate_faults.py` corpus, null-distribution/FPR checks under the verdict rule in `barra/config.py`, and hand-marked reconciliation on the documented real clips). No code changes are made in this deliverable.

## Scope
- In:
  - **Findings (severity-tagged, each named to file + mechanism):**
    - **F1 (S1, measured-but-wrong):** hip-origin movements inherit bar-referenced faults. `barra/faults_taxonomy.py:283-296` (`classify_failures`) routes `squat`/`pull_up`/`dip`/`push_up` into `muscle_up()`, which reads `lockout_pct`/`hang_pct` derived in `values_for_rep` (faults_taxonomy.py:163-194) from `peak_height`/`start_depth`. For a squat, `barra/metrics.py:_series` (metrics.py:164-190) measures `shoulder_above` against the **hip midpoint** (origin), so `peak_height ≈ 1.0` torso (shoulder always ~1 torso above hip) and `start_depth ≈ -1.0`. Result: `lockout_pct ≈ 100·torso/arm` (fires when the athlete's arm:torso ratio exceeds ~0.85 — an anatomical lottery) and `hang_pct ≈ -83` (**"dead hang" fires on every squat rep, unconditionally**). Squat depth is invisible to these quantities (`rom ≈ 0`), so the range component (`barra/quality.py:range_component`) is a near-constant for squats and the score cannot see depth at all. Same self-reference makes `swing` (hip lateral vs hip origin) identically ~0 for hip-origin movements, so `momentum` can never fire for squats regardless of sway.
    - **F2 (S2, never-measured but advertised):** `muscle_up` track advertises `"bent arms"` in `TRACK_FAILURES` (faults_taxonomy.py:276), but no rep-path code ever produces `arms_straight_frac` (only `barra/holds.py:_hold_metrics` does), and `_f(values.get("arms_straight_frac"), 1.0)` defaults a **missing** measurement to the healthy value — the exact "missing measurement satisfies a condition" anti-pattern documented in docs/FINDINGS.md §4, here in its inverse form (missing → healthy → fault can never fire).
    - **F3 (S2, measured-but-wrong):** `pistol_geometry` (faults_taxonomy.py:197-243) computes PLANAR quantities with no view gate in the server path: (a) `knee_valgus = |knee_x − (hip_x+ankle_x)/2|` (lines 221-231) **aliases forward knee travel with valgus** — from a sagittal camera `hip_x ≈ ankle_x` so the metric reads normal forward knee travel as valgus (the synthetic `knee_travel` error would trip it), while true frontal valgus is nearly invisible from sagittal (docs/FINDINGS.md: 1.2× noise); (b) `torso_lean = hip_x − sh_x` (lines 211-215) has an arbitrary sign that depends on facing/camera side and is meaningless from frontal views; (c) `heel_raise = 1 − p5(ankle_below_hip)` (lines 234-239) is **confounded with squat depth** — it only exceeds the 0.20 threshold when the ankle is within 0.8 torso of hip height, i.e. deep reps look like heel raises. `server/process.py` never runs `barra/viewpoint.py` and never threads `view`/`declared_bin` (available in `out/reps.csv` and sessions.csv) into the payload, so `classify_failures` consumes these un-gated.
    - **F4 (S2, measured-but-wrong):** regex coupling to human-readable strings. `barra/faults.py:35-37` parses `why` strings emitted by `barra/quality.py` (`"lockout NN% of full"` from range_component, quality.py:128-130; `"% of the ascent made no progress"` from smoothness_component, quality.py:194-198), and `app/src/main/java/com/barrapp/Cues.kt:26-43` duplicates the same regexes and the same thresholds (0.4 / 85 / 75) as literals. The stall threshold is doubly hidden: the `why` string is only emitted when `stalled >= 0.05` (quality.py:196), while `faults_taxonomy.py:126` re-tests `stalled_frac >= 0.05` with an inline literal. Any wording or formatting change (e.g. Python's `.0%` banker's rounding at the 84.5% boundary) silently breaks the phone contract.
    - **F5 (S2, threshold duplication):** `SWING_TORSO`/`LOCKOUT_MIN`/`HANG_MIN` defined in both `barra/faults.py:31-33` and `barra/faults_taxonomy.py:36-38`; `CONTROLLED_TEMPO` and `STALL_RATE` duplicated between `barra/quality.py:51-57` and `faults_taxonomy.py:39-40`; plus ~20 more pinned constants in `classify.py` (`OVER_BAR`, `ARTICULATION`, `KNEES_UP`, `HOLD_BAND`, `HOLD_FRAC`, `BELOW_HANDS_DIP`, ...) with no single source and no phone-parity check.
    - **F6 (S2, measured-but-fragile):** classification features are whole-clip statistics (classify.py:179-337). `shoulder_above_hands_p95` (used by the muscle_up/pull_up split, classify.py:485-507) and `arm_articulation` (p95−p05 of shoulder-above-hands) include approach/rest/walk-away frames: standing with hands at the sides puts `above ≈ +1.4` torso, so any pull-up clip containing a still 3 s stand with hands low produces `anchored=True` (best 3 s window is still), `articulated=True`, `p95 ≈ +1.4 ≥ OVER_BAR` → **classified muscle_up at 0.98 confidence**; if the rest dominates instead, `hands_overhead_frac < 0.35` and the same set falls through to "no branch matched" → unknown. The test fixtures (`tests/test_classify_quality.py:bar_clip`) contain no standing frames, so this path is unexercised.
    - **F7 (S3, never-measured):** one movement label per clip (classify.py:371). Mixed clips (e.g. pull-ups then dips) and clips whose camera swings bins cannot be measured; nothing reports the disagreement.
    - **F8 (S2, undercounting, pain point a):** `segment_reps_verbose` computes a single global `rest=p15/apex=p97` amplitude over all active frames (ingest.py:282-284) and one global 0.35-prominence/0.60-peak gate (ingest.py:292, 319). Under camera rotation (clip 0011) the drifting baseline inflates/deflates the amplitude so no turnaround clears it; in fatiguing sets the late shallow reps fall under the 0.6 gate — exactly the reps the QUALITY.md degradation check needs. The rescue pass (`_rescue_candidates`, ingest.py:496-604) only runs when the standard pass finds **nothing**, and its own walk is unbounded to the whole clip (no active-span trim). Known real-clip costs: 0010 3→2, 0012 2→1, 0011 0, 0014 0 (docs/CORE.md).
    - **F9 (S3, never-measured, pain point d):** taxonomy coverage vs `tecnicas-errores-comunes.md`: squat has **no dedicated classifier at all** (F1's fallback is wrong, not a substitute); push-up "sagging hips"/"head position" unmeasured; dip "bounce at bottom"/"too deep"/"shrugged scapulae"/"inconsistent torso angle" unmeasured; pull-up "no active hang"/"too fast" unmeasured; planche "shoulders not following (protraction)" unmeasured. Items that are honestly not geometrically measurable (grip type, lumbar rounding without spine landmarks, wrist loading, gaze, progression-skipping) are not declared as unmeasured anywhere in docs.
    - **F10 (S4):** `max_half_rep_s=4.0` (ingest.py:160) truncates slow eccentrics (negatives > 4 s), corrupting `eccentric_s`/`tempo_ratio`; `_f(..., 0.0)` healthy defaults for `swing`/`heel_raise` (faults_taxonomy.py:78, 147) repeat the F2 anti-pattern; rescue-pass `walk()` (ingest.py:553-562) can run into non-active frames.
  - In scope for fixes: all of F1-F10, phase-ordered below; every threshold change mirrored in `Cues.kt`; docs/CORE.md, docs/FINDINGS.md, docs/QUALITY.md updated in the same change.
- Out:
  - Any learned classifier, any labelled-footage dependency, any cross-subject comparison, any claim about *why* a rep deviated (fixed philosophy, docs/CORE.md).
  - GPU inference or unbounded compute (CPU Lambda, 3 GB, mediapipe pose): all fixes are O(T) array operations on the existing (T,17,3) keypoints.
  - Re-litigating documented decisions (rotation kept in normalisation, per-set scale, hand-marked references, hold-reject ordering at 0.55) without new evidence.
  - Replacing segmentation: `out/reps.csv` stays the user-editable contract; nothing downstream re-derives it.
  - Changing the 0-100 score semantics or band boundaries (docs/QUALITY.md conventions) except where F1 makes them meaningless for hip-origin tracks.

## Phases

### Phase 1: Fix measured-but-wrong fault semantics (F1, F2, F10) — P0
**Goal**: Stop the fault layer from emitting geometrically false faults (every squat rep flagged "dead hang", anatomy-lottery "lockout", dead "bent arms") and restore three-valued logic in the taxonomy.

#### Task 1.1: Route hip-origin tracks to track-appropriate classifiers, not `muscle_up`
- Location: `barra/faults_taxonomy.py` (CLASSIFIERS, classify_failures, values_for_rep), `barra/metrics.py` (`_series`), `server/process.py` (wiring), `tests/test_classify_quality.py`
- Description: Add a `squat(values)` classifier with faults that mean something for hip-origin geometry: `insufficient depth` from an **ankle-referenced** hip height (hip-over-ankle at turn vs standing baseline — vertical distances, azimuth-invariant), `uncontrolled descent` (tempo), and nothing else for now (valgus/heel arrive view-gated in Phase 3). Remove the automatic `muscle_up` fallback for `squat`; keep it only for `pull_up`/`dip`/`push_up` (wrist-origin, where lockout/hang semantics are valid). In `values_for_rep`, only compute `lockout_pct`/`hang_pct` for wrist-origin movements (thread `movement.origin` in — `process.py` already has `movement`). Suppress `momentum` for hip-origin tracks until a hip-origin sway signal exists (current `swing` is self-referential ≈ 0).
- Estimated Tokens: 60000
- Dependencies: none
- Steps:
  - Extend `_series` with `hip_over_ankle = (ankle_y − hip_y)/torso` and expose per-rep `standing_hip_height` (p50 over the rep's own start frames) and `bottom_hip_height` (p05) in metrics values.
  - Add `squat()` to CLASSIFIERS/TRACK_FAILURES; update `classify_failures` dispatch; thread `origin` into `values_for_rep` and gate the bar-fault block on it.
  - Pin the depth threshold in the new single-source module (Phase 2 lands first in code order if sequencing demands; otherwise define in faults_taxonomy with a pointer) BEFORE looking at any firing results, per the config.py discipline.
  - Update `docs/CORE.md` movement/fault table; note in `docs/FINDINGS.md` that hip-origin self-reference was silently feeding bar faults.
- Acceptance Criteria:
  - Synthetic clean squat sets (`barra selftest`) produce **zero** lockout/dead-hang/momentum faults; shallow-depth synthetic error sets produce `insufficient depth` on ≥60% of reps with FPR ≤ 20% on clean sets (verdict rule, `barra/config.py:18-19`).
  - New unittest: a `squat_clip` fixture through the full `classify_failures("squat", values_for_rep(...))` path yields no bar faults; a `dip` fixture still yields the five bar faults.
  - 137 existing tests stay green; `barra validate_faults` corpus run re-labelled (`observed` column) for any squat-track clips.

#### Task 1.2: Remove healthy-value defaults on missing measurements (F2, F10)
- Location: `barra/faults_taxonomy.py` (`_f` call sites: lines 69, 73, 76, 91, 95, 99, 131, 147, 155), `tests/test_core.py`
- Description: Change the fault predicates from `_f(key, healthy_default)` to explicit three-valued handling: if the key is absent/NaN, the fault is **not fired and not counted as clean** — record it in a per-rep `unmeasured` list shipped in the payload, so "we could not check bent arms" is a stated fact, not silent health. Either measure `arms_straight_frac` for rep rows (elbow angle at lockout frames via `classify._angle`, cheap O(T)) or drop `"bent arms"` from `TRACK_FAILURES["muscle_up"]` and say so in docs.
- Estimated Tokens: 40000
- Dependencies: Task 1.1
- Steps:
  - Add elbow-angle computation for wrist-origin rep rows (reuse `_angle` from classify.py) so `bent arms` becomes measurable rather than deleted, if tokens allow; otherwise remove the failure name and document.
  - Convert every `swing`/`heel_raise`/`arms_straight_frac`/`legs_straight_frac` default to the unmeasured pattern; add the `unmeasured` key to the rep row in `server/process.py` and to hold rows in `barra/holds.py`.
- Acceptance Criteria:
  - Unit test: a values dict missing `arms_straight_frac` yields `bent arms` in `unmeasured`, not absent silence; a rep with measured `arms_straight_frac=100` yields neither.
  - Null check: on all 8 documented sample clips, `unmeasured` lists match exactly the quantities that are geometrically unavailable, inspected once by hand and pinned as a fixture.

### Phase 2: Single-source thresholds + structured fault contract (F4, F5) — P0
**Goal**: Kill the regex-parsed why-string contract and the triplicated constants; make the phone and harness provably agree.

#### Task 2.1: Ship structured fault inputs in the rep payload
- Location: `server/process.py` (rep row construction, lines ~494-545), `barra/faults.py`, `app/src/main/java/com/barrapp/Cues.kt`, `barra/quality.py`
- Description: Add `lockout_pct`, `hang_pct`, `stalled_frac`, `tempo_ratio`, `swing` as **numeric fields** on each rep row (all already computed in `values_for_rep`/quality context but never shipped). Rewrite `faults.py:rep_faults` to read these numbers; keep the regex path only as a deprecated fallback for one release. Mirror the same reads in `Cues.kt` (`repFaults` reads `RepRow` numeric fields instead of regexing `range.why`/`smoothness.why`).
- Estimated Tokens: 55000
- Dependencies: none
- Steps:
  - Extend the rep-row schema in `process.py`; extend the Kotlin `RepRow` data class (app/src/main/java/com/barrapp/data) with nullable numeric fields.
  - Rewrite `repFaults` in both `barra/faults.py` and `Cues.kt` to read numbers with three-valued semantics (null → not fired, recorded unmeasured).
  - Pin the boundary rule: fault fires when `value < LOCKOUT_MIN*100` on the **unrounded** float (removes the `.0%` rounding hazard).
- Acceptance Criteria:
  - Golden-payload tests: rep rows built with known numbers produce identical fault lists in Python; a test that mutates only the `why` strings still passes (proves decoupling).
  - Boundary tests: lockout_pct 84.9 vs 85.0 vs 85.1 produce fired/not-fired as documented.
  - `tests/test_server_payload.py` extended: every fault-relevant field present-or-explicitly-null in `_empty` and success payloads.

#### Task 2.2: One thresholds module + phone parity test
- Location: new `barra/thresholds.py`; edits in `barra/faults.py`, `barra/faults_taxonomy.py`, `barra/quality.py`, `barra/classify.py`; new test `tests/test_threshold_parity.py`; `docs/CORE.md`
- Description: Move every pinned constant (SWING_TORSO, LOCKOUT_MIN, HANG_MIN, CONTROLLED_TEMPO, STALL_RATE, the stall-emission 0.05, plus classify.py's OVER_BAR/ARTICULATION/KNEES_UP/HOLD_*/BELOW_HANDS_DIP and faults_taxonomy's STRAIGHT_*/HORIZONTAL/PIKE/PISTOL_*) into `barra/thresholds.py` with a comment field stating its evidence ("measured gap 0.68-1.00 vs 0.00-0.49", etc. — carried from existing docstrings). Import everywhere; delete duplicates. Add a parity test that parses `Cues.kt` literals and asserts they equal the Python values (text-level, no build coupling), so a phone/harness divergence is a red test, not a silent product bug.
- Estimated Tokens: 45000
- Dependencies: Task 2.1
- Steps:
  - Mechanical move + imports; keep old names as module aliases for one release to avoid churn in tests.
  - Parity test with an explicit allowlist of constants that must exist on both sides; fail with the differing values printed.
- Acceptance Criteria:
  - `rg` confirms no numeric literal duplicated for any parity-listed constant outside `thresholds.py` (test enforces).
  - All 137 tests green; `barra validate_faults` re-run shows identical fault counts pre/post refactor on the labelled corpus (behaviour-preserving proof).

### Phase 3: Viewpoint-gated PLANAR faults (F3) — P1
**Goal**: PLANAR fault quantities are only computed (and only fire) when the view supports them; aliasing between valgus and knee travel is broken.

#### Task 3.1: Thread view/bin into the server pipeline and gate planar geometry
- Location: `server/process.py`, `barra/viewpoint.py` (expose a clip-level estimator), `barra/faults_taxonomy.py` (`pistol_geometry`, `classify_failures`), `barra/synthetic.py`, `scripts/viewpoint_sensitivity.py`, `docs/FINDINGS.md`
- Description: Compute or read the viewpoint for server jobs: prefer the declared `bin`/`view` (sessions.csv contract already exists in `barra/ingest.py:load_metadata`), else run the lightweight shoulder-ratio azimuth estimator from `viewpoint.py` on the clip's keypoints (O(T), trivial CPU). Attach `bin` to each rep row. In `pistol_geometry`: compute `knee_valgus` only when `bin == FRONTAL` (else NaN → unmeasured, Phase 1 pattern); compute `torso_lean` only when `bin` is SAGITTAL **and** the facing sign is resolved via `viewpoint.camera_side`; replace `heel_raise` with a per-rep self-referenced signal gated to sagittal: rise of the planted ankle relative to its own start-frame height at bottom (vertical, azimuth-invariant), threshold small; declare the old hip-relative `heel_raise` formula invalid in docs. Add the same view caveat to `momentum` (swing): fires from any bin but its magnitude is projection-dependent — state it, and skip firing when bin == UNKNOWN.
- Estimated Tokens: 70000
- Dependencies: Task 1.1, 1.2 (unmeasured pattern), 2.2 (thresholds)
- Steps:
  - Refactor `viewpoint.py` so azimuth/bin estimation works on an in-memory keypoint array (not just `out/` parquet), reusing `_apparent_ratios` logic.
  - Wire into `analyze_clip`; add `bin` to rep rows and payload; gate the three quantities; extend `values_for_rep`/`pistol_geometry` signatures.
  - Extend `barra/synthetic.py`: add a frontal knee-valgus error set at azimuth 88° (the generator's `z`-axis valgus already exists — `err02` at 12° just needs a frontal twin) and a `knee_travel` twin at 88° to prove non-aliasing; add a heel-lift error mode (`ankle_y` rises at bottom while toe stays).
- Acceptance Criteria:
  - Synthetic: `knee_valgus` fault fires on ≥60% of frontal valgus reps, 0% of frontal knee-travel reps, 0% of sagittal clean reps; `heel_raise` fires on heel-lift sets and never on deep clean pistols (the old formula fired on depth).
  - Null-distribution: run the gated detectors on all 8 real sample clips' reps — zero planar faults from SAGITTAL-labelled clips where the geometric condition is absent, verified against docs/CORE.md's clip table.
  - Extend `scripts/viewpoint_sensitivity.py` with a fault-layer table (azimuth vs fault firing) appended to `docs/FINDINGS.md`, falsifiable and reproducible.

### Phase 4: Rep detection undercounting (F8, F10) — P1
**Goal**: Raise the standard pass's recall on real clips (rotation, fatigue tails, undercounts) without inventing reps, using better geometry and signals — no ML.

#### Task 4.1: Per-span amplitude + drift-robust peak search
- Location: `barra/ingest.py` (`segment_reps_verbose`, `active_mask`), `barra/movements.py` (`tracking_signal`), `tests/test_core.py`, `barra/synthetic.py`
- Description: Compute `rest/apex` **per active span** (from `_runs(active)`) instead of clip-wide, and find peaks per span with per-span amplitude; keep the existing per-candidate rejections (interpolation frac, anchor travel, overlap) unchanged. For rotation-like drift, add a **roll normalization** before peak-finding for wrist-origin movements: the wrist-wrist vector is the bar axis and is horizontal in the world, so per-frame camera roll is `angle(wrist_pair_vector) − 0`; rotate signals by −roll (hip-origin movements use the ankle-ankle line). This is bounded (one arctan + rotation per frame) and philosophically pure (uses the apparatus itself as the level).
- Estimated Tokens: 90000
- Dependencies: none (independent of Phases 1-3)
- Steps:
  - Refactor `segment_reps_verbose` to loop spans; keep the global path as fallback when a single span holds everything (regression safety).
  - Add roll estimation + signal rotation in `tracking_signal` (flag-gated, on by default only when roll range across the clip exceeds ~5°, so well-filmed clips are untouched).
  - Extend `barra/synthetic.py` with (a) a roll(t) ramp fixture, (b) a fatigue set (`depth_gain` decaying per rep), (c) a slow-eccentric set (> 4 s descent) — marks stay generated, so counts/boundaries are exact for the selftest.
  - Fix F10's truncation: replace the fixed `max_half_rep_s=4.0` with `max(4.0, 3×min_rep_s)`-style bound plus a velocity floor so walks still terminate the walk.
- Acceptance Criteria:
  - Synthetic invariants: rep counts equal generated marks for roll-ramp, fatigue, and slow-eccentric fixtures; boundaries within ±2 frames; clean `SETS` fixtures segment **identically** to today (no regression in count or boundary beyond ±1 frame).
  - Null: noise-only and drift-with-wiggles fixtures (tests/test_rescue.py style) still produce 0 reps through the new path.
  - Real-clip reconciliation: re-run `scripts/demo_sessions.py` on clips 0010/0012 (targets: 3 and 2) and 0011 (target: hand-marked count); 0014/0017/0019 must remain 0 (holds, failed attempts, walk-around are correctly refused). Record the before/after table in `docs/CORE.md`; if a target is still missed, the trace must name the exact geometric reason and the doc keeps the honest count.

#### Task 4.2: Fatigue-tolerant re-admission + rescue scoping
- Location: `barra/ingest.py` (`segment_reps_verbose` rejection loop, `_rescue_candidates`, `rescue_reps`)
- Description: After the standard pass, re-admit rejected peaks whose leg-to-leg displacement ≥ 0.6 × the **median accepted amplitude** AND that pass the existing velocity-MAD gradient validation from `_rescue_candidates` (climb/drop ≥ 2.5×MAD) — relaxation is earned per candidate, not global, and every other rejection (interpolated, anchor, untracked turnaround) still applies. Scope the rescue pass's `walk` to the active spans and run it per-span with per-span amplitude.
- Estimated Tokens: 50000
- Dependencies: Task 4.1
- Steps:
  - Implement re-admission as an explicit second loop with its own trace rejections/names (`barra explain` must show which pass admitted each rep — the trace schema already supports this via `tr.decision`).
  - Bound `_rescue_candidates.walk` to the containing span.
- Acceptance Criteria:
  - Synthetic fatigue fixture: all reps counted, each re-admitted rep trace-tagged; noise fixtures still 0; the 8-clip real table unchanged except where Task 4.1 already documents gains.
  - Two-phone reliability protocol (docs/QUALITY.md §2) on one repeat-filmed set: identical rep counts both passes.

### Phase 5: Movement classification robustness (F6, F7) — P1
**Goal**: Classification evidence comes from the set, not from the walk-in; mixed clips are refused loudly instead of force-labelled.

#### Task 5.1: Scope percentile features to active spans
- Location: `barra/classify.py` (`features`, `classify`), `tests/test_classify_quality.py`, `docs/CORE.md` (8-clip table)
- Description: Compute `shoulder_above_hands_p95/p05`, `arm_articulation`, `hands_overhead_frac/below_frac` over the frames of the best-anchored window(s) (reuse `active_mask` spans), while keeping the whole-clip `parked_frac` hold-rejection exactly as is (it must see rest frames to work — docs/FINDINGS.md §5). This is the minimal change that kills the standing-prefix muscle_up misfire without disturbing the verified hold/attempt behaviour.
- Estimated Tokens: 55000
- Dependencies: none
- Steps:
  - Add span selection into `features()` (pass spans computed once); recompute the extremal percentiles on the union of frames where the hands are overhead OR inside the anchored span.
  - New fixtures: `bar_clip` prefixed with 40% standing frames (hands at sides) → still `pull_up`/`muscle_up` as the base clearance dictates; standing-dominant fixture → whatever the honest branch is, asserted explicitly.
  - Re-run the 8-clip blind check (docs/CORE.md table) and append the post-change table to `docs/CORE.md`; 7-of-8 must hold or the regression is documented with evidence.
- Acceptance Criteria:
  - Prefix invariance test: adding standing frames cannot flip pull_up→muscle_up (or reverse), nor turn a labelled set into unknown unless the set itself is < the minimum anchored span.
  - All existing classify tests green unchanged.

#### Task 5.2: Per-span classification with disagreement refusal
- Location: `barra/classify.py`, `server/process.py`, `tests/test_classify_quality.py`
- Description: For clips with multiple active spans, run the branch gates per span; if spans agree → single label plus span count; if they disagree → payload blocker naming each span's verdict ("span 1: pull_up, span 2: dip — mixed clip, not measured as one movement"). No per-rep re-labelling beyond the span level (keeps the user's reps.csv contract intact).
- Estimated Tokens: 45000
- Dependencies: Task 5.1
- Steps:
  - Add a `classify_spans` entry point returning per-span Classification list + aggregate; `analyze_clip` uses it and refuses on disagreement (existing `_empty`/blocker machinery).
  - Mixed synthetic fixture: concatenate `squat_clip` + `bar_clip` → two spans, disagreement blocker.
- Acceptance Criteria:
  - Mixed fixture produces the blocker, not a label; single-movement fixtures produce the unchanged label; token cost bounded (classification is O(spans × T), trivial).

### Phase 6: Taxonomy coverage for the measurable subset (F9) — P2
**Goal**: Add the geometrically honest subset of the 5-most-cited-errors lists per track; declare the rest unmeasured rather than fake them.

#### Task 6.1: Push-up, dip, pull-up detectors
- Location: `barra/faults_taxonomy.py` (new `push_up()`, `dip()`, `pull_up()` classifiers + a shared geometry helper), `barra/synthetic.py` (new error modes), `data/calisthenics/faults.csv` (deliberate clips), `docs/CORE.md`
- Description: Measurable now, each with signal + threshold pinned before firing results are seen: push-up `sagging hips` (hip sags below the shoulder-ankle line by > threshold, vertical offset — survives azimuth), `head position` (nose above the shoulder-ankle line); dip `too deep` (elbow angle at bottom < 90°, reusing `classify._angle`), `bounce at bottom` (no near-zero velocity frame within ±3 frames of the turnaround — magnitude of |vel| at turn vs the ascent's own p90, O(T)); pull-up `no active hang` (elbow angle < 150° at rep start), `too fast` (concentric_s < 0.5× the set's own median — self-referenced, INVARIANT). Deliberately NOT measured and declared so: elbows-flared-90° (needs a top-down camera), arm-curl/lat engagement, grip type, wrist loading, lumbar rounding, gaze.
- Estimated Tokens: 100000
- Dependencies: Phase 1 (unmeasured pattern), Phase 2 (thresholds module), Phase 3 (view gating where needed)
- Steps:
  - Implement the three classifiers; add `push_up`/`dip`/`pull_up` to CLASSIFIERS/TRACK_FAILURES; remove their `muscle_up` fallback from `classify_failures` (keep the five shared bar faults by calling the shared block explicitly).
  - Add synthetic error modes (`sagging_hips`, `head_up`, `bounce`, `shallow_dip`, `bent_hang`) to `barra/synthetic.py` with magnitudes fixed in the same commit as the thresholds (before any observed output).
  - Film/collect deliberate-fault clips per QUALITY.md §4 sensitivity protocol; register them in `data/calisthenics/faults.csv` with `expected` labels via the existing `validate_faults --emit-candidates` → watch → label loop.
- Acceptance Criteria:
  - Each new detector: ≥60% detection on its induced synthetic reps, FPR ≤ 20% on clean synthetic sets, and no firing on the clean reps of the 8 real clips (null check recorded in docs).
  - Deliberate-fault corpus: at least one expected-positive clip per shipped fault via `python -m barra.validate_faults` (exit 0); faults with no corpus clip are listed INCONCLUSIVE in `docs/QUALITY.md`-style terms, never silent.
  - `docs/CORE.md` gains a "measured vs declared-unmeasured" table mapping every entry of `tecnicas-errores-comunes.md` to its status.

#### Task 6.2: Hold-path additions (planche protraction, scapular elevation signal)
- Location: `barra/holds.py` (`_hold_metrics`), `barra/faults_taxonomy.py` (`front_lever`, `planche`)
- Description: Add `shoulders_over_hands` (median shoulder-above-hands over the hold; planche protraction proxy) to hold metrics and a `no protraction` planche failure; add an experimental `scapular elevation` signal (ear-to-shoulder distance compression p05 vs standing-baseline) gated to holds and marked experimental in docs until the deliberate-clip loop validates it.
- Estimated Tokens: 40000
- Dependencies: Task 6.1
- Steps:
  - Extend `_hold_metrics`; wire into both classifiers; keep `TRACK_FAILURES` exhaustive (the harness and UI read it).
- Acceptance Criteria:
  - Hold fixture with sagging/piked geometry still classified by the existing tests; new signals present in `unmeasured` when occluded (three-valued).
  - Null: clean front-lever synthetic hold fires nothing.

## Testing Strategy
- Keep and extend the 137-test invariant suite (`python -m unittest discover -s tests`): every fix lands with parametric fixtures in the existing style (`tests/test_classify_quality.py`), including prefix-invariance, mixed-clip, boundary-value, and three-valued (NaN/missing) cases.
- Synthetic selftest extensions (`barra/synthetic.py`): roll-ramp, camera pan, fatigue decay, slow eccentric, frontal valgus/knee-travel twins, heel-lift, sagging-hips, bounce, head-up, bent-hang — each with generated marks so counts/boundaries are exact. The suite validates machinery, not reality; every report and doc line derived from it must keep the existing "synthetic data only" caveat.
- Deliberate-fault clips: extend the `barra/validate_faults.py` loop (`--emit-candidates` → watch → `expected`/`forbidden` in `data/calisthenics/faults.csv` → validate) for every new and changed fault; exit-code gate in CI-style runs.
- Null-distribution checks: every detector run across the clean reps of the 8 documented clips and the synthetic clean sets; firing on clean reps counts against the `MAX_ACCEPTABLE_FPR = 0.20` verdict rule (`barra/config.py:18`), detection must clear `MIN_ACCEPTABLE_DETECTION = 0.60` (`barra/config.py:19`).
- Real-clip reconciliation: hand-marked counts for clips 0010/0011/0012/0014/0017/0019/0020 (docs/CORE.md) as the segmentation reference; after/tables appended to `docs/CORE.md`, with any remaining misses named by their trace (`barra explain`).
- Phone-parity: `tests/test_threshold_parity.py` parsing `Cues.kt` constants; golden-payload tests for the structured fault fields; one manual app smoke test per released threshold change.
- Two-phone reliability (docs/QUALITY.md §2) on one set after Phase 4 changes: identical rep counts and fault lists.

## Risks
- **F1's fix changes live scores and fault lists for squat-track users; "dead hang"-on-every-squat was at least consistent day to day.** Mitigation: ship with a docs note and a one-release deprecation window where the old behaviour is logged alongside; the change is objectively a correctness fix, and the golden tests pin the new semantics.
- **Self-critique: the Phase 4 roll-normalization assumes the wrist-wrist vector is the bar axis — false for rings, false for a single-arm hang, and false when mediapipe confuses left/right wrists on a side-on clip, where the pair routine may already be using one wrist alone (then the "bar axis" is undefined).** The flag-gated rollout (only when roll range > 5°) hides the failure on exactly the marginal clips it was built for, and I have no evidence yet that 0011's rotation is roll rather than azimuth/pitch — if it is azimuth, vertical signals barely change and this fix won't move the count at all. The 0011 reconciliation result must be checked before claiming the pain point addressed.
- **Self-critique: the Phase 6 detection targets (≥60% / ≤20%) are evaluated mostly on synthetic fixtures whose noise model I am also extending — the repo itself states this measures the noise model, not reality.** The deliberate-clip corpus is thin (one clip per fault is the plan's own minimum), so several new thresholds will be INCONCLUSIVE on real footage at ship time; the plan accepts that but a reviewer could reasonably call the "validated" claim over-strong until 3+ deliberate clips per fault exist.
- **Self-critique: Phase 1's squat depth threshold is pinned before firing results, but the *choice of signal* (hip-over-ankle drop) was made after reading the synthetic generator, which was itself built around a realistic 25-35° shank range — the fixture and the signal are not independent.** A real squat with a heel plate, uneven ground, or camera pitch could shift the standing baseline; the plan has no test for a pitched camera on the squat track.
- **Active-span-scoped classify features (Phase 5) may starve short clips**: a 4 s clip has at most one window, and `_best_window` returns whole-clip when n ≤ win — behaviour changes least there, but clips just over one window could see `hands_overhead_frac` re-computed on a subset and flip the hold-reject boundary (HOLD_FRAC 0.55) that docs/FINDINGS.md §5 pinned. Mitigation: keep hold-rejection whole-clip (as scoped) and add an explicit regression test on the 23-second-hold fixture class.
- **Threshold parity with Cues.kt is text-parsed and app releases lag server deploys**: mid-transition payloads carry new numeric fields the old app ignores (regex path) and old why-strings the new app ignores; the plan keeps both readers one release, but the real risk is an app build that reads numbers with the old thresholds while the server ships new ones — the parity test checks code, not installed builds. Mitigation: ship numeric fields and thresholds in the same server release; version the payload.

## Rollback Plan
- Each phase lands as an independent commit series (phase-sized, task-sized commits); any single phase reverts cleanly with `git revert` without touching others (Phases 2-6 depend only on the unmeasured-pattern and thresholds module, which are additive).
- The structured fault fields are additive payload keys; the regex readers in `barra/faults.py` and `Cues.kt` are kept one release as a documented fallback, so reverting the server alone restores the old contract.
- Behaviour-preserving refactors (thresholds module, per-span amplitude with single-span fallback) are gated by before/after golden runs: `barra selftest` fixture segmentation and `validate_faults` counts must be identical pre/post; if not, the commit is reverted and the divergence becomes a documented finding instead.
- Roll-normalization and fatigue re-admission are flag-gated in code (constant in `barra/thresholds.py`), so a bad real-world outcome is a one-line disable plus revert, with traces (`barra explain --replay`) showing which pass admitted each rep.
- `out/reps.csv` is never re-derived downstream, so any segmentation regression is user-correctable in the interim and the ingest log (`out/ingest_log.csv`) preserves rejection reasons for post-mortem.
- Docs (`docs/CORE.md`, `docs/FINDINGS.md`, `docs/QUALITY.md`) are updated in the same commit as each behaviour change; a revert reverts its doc claims with it, keeping the honesty contract intact.

## Edge Cases
- Clips shorter than one `ANCHOR_WINDOW_S` window (classify and active_mask fall back to whole-clip — scoped features must not change this path).
- All-NaN / below-floor confidence streams for any new signal (three-valued: unmeasured, never a default).
- `lockout_pct` exactly at 85.0 boundary; Python `.0%` rounding at x.5 percents; fps 0 or missing (`ingest.py:425` defaults 30).
- Side-on occlusion: single-side pair mode active — elbow angles exist only for the visible arm; `bent arms`/`no active hang` must handle one-sided data.
- Mixed clips and camera-bin swings mid-clip (Phase 5 blocker); a span shorter than `min_rep_s` inside an otherwise good clip.
- Holds that pass through the horizontal band transiently (skin-the-cat style) — `hold_attempts` run-trimming must not claim them; new hold signals must not fire there (null test).
- Knee-raise clips with knees unseen early (knee_excursion NaN → knee_raise branch must fail loud, not fall through to pull_up silently).
- Roll normalization when the wrist pair is in single-side mode (bar axis undefined → skip normalization, log in trace).
- Pistol with the free leg occluded (single_leg_stance from one side); deep pistols vs the old depth-confounded heel_raise.
- User-edited `out/reps.csv` rows whose `view`/`declared_bin` columns are empty — gating must fall back to estimation, then to unmeasured, in that order.

## Open Questions
- Is 0011's camera motion roll (fixable via bar-axis normalization) or azimuth/pitch (not addressable by it)? Resolvable only by running the Phase 4 probe on the clip; the plan's undercounting claim for 0011 is contingent.
- Should `momentum` (swing > 0.4) fire from FRONTAL bins where fore-aft kip is foreshortened but lateral sway is real, or only from SAGITTAL? Phase 3 ships the caveat and UNKNOWN-skip; the bin policy needs one deliberate kip clip per bin before deciding.
- Does the app team want `unmeasured` surfaced in the UI (as "not checked") or only in the payload? Affects whether `Cues.kt` changes are one release or two.
- For squat depth: accept an absolute threshold (drop ≥ 0.45 of standing hip height) or a hip-knee-ankle angle convention (thigh below horizontal)? The angle convention is more standard and view-robust in sagittal, but adds a second planar-gated quantity; decide before pinning.