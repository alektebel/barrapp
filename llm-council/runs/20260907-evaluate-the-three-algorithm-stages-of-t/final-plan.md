# Plan

## Overview
Evaluate and fix the barra measurement core's three stages — rep segmentation (`barra/ingest.py`), movement classification (`barra/classify.py`), and fault classification (`barra/faults.py` + `barra/faults_taxonomy.py`) — by severity-ranking the concrete weaknesses and shipping a prioritized, non-ML fix plan where every fix is validated without ground-truth labels. The project's fixed philosophy holds: geometric rules that fail loudly, no learned classifiers, no labelled footage, three-valued logic on missing measurements, bounded CPU compute, and falsifiable docs. No code is implemented here.

## Scope
- **In:** findings for all three stages, each naming the file and mechanism at fault; a phase-ordered fix plan with per-fix label-free validation. Threshold changes are mirrored on both sides (`faults.py`, `faults_taxonomy.py`, `quality.py`, and `app/src/main/java/com/barrapp/Cues.kt`). `out/reps.csv` stays the user-editable contract and is never re-derived downstream.
- **Out:** any learned classifier, labelled-footage dependency, cross-subject claim, or *why* claim (`docs/CORE.md`); GPU inference or unbounded compute (all fixes are O(T) array ops on `(T,17,3)` keypoints); re-litigating documented decisions (rotation kept in normalisation, per-set scale, hand-marked references, hold-reject at 0.55) without new evidence; re-deriving segmentation.

## Phases

### Phase 1: Fix measured-but-wrong fault semantics — P0
**Goal**: Stop the fault layer from emitting geometrically false faults for hip-origin tracks and restore three-valued logic in the taxonomy.

#### Task 1.1: Route hip-origin tracks to track-appropriate classifiers, not `muscle_up`
- **Location:** `barra/faults_taxonomy.py` (`CLASSIFIERS`, `classify_failures:283-296`, `values_for_rep:163-194`), `barra/metrics.py` (`_series:164-190`), `server/process.py` (rep loop `:505-509`), `tests/test_classify_quality.py`
- **Description:** `classify_failures` sends `squat`/`pull_up`/`dip`/`push_up` to `muscle_up()` (`faults_taxonomy.py:293-294`). For hip-origin movements `_series` measures `shoulder_above` against the **hip midpoint** origin, so `peak_height ≈ 1.0` torso and `start_depth ≈ -1.0`; `values_for_rep` then yields `lockout_pct ≈ 100/arm` and `hang_pct ≈ -100/arm`. Correct the figure: `lockout_pct < 85` fires when `arm > ~1.18` (anatomy lottery, not the quoted 0.85); `hang_pct < 75` fires on **every** squat rep unconditionally. `swing` (hip lateral vs hip origin) is self-referential ≈ 0, so `momentum` can never fire for hip-origin movements. Add a `squat(values)` classifier whose faults mean something for hip geometry: `insufficient depth` from an **ankle-referenced** hip height (hip-over-ankle at turn vs the rep's own standing baseline — vertical, azimuth-invariant), and `uncontrolled descent` (tempo). Remove the automatic `muscle_up` fallback for `squat`; keep it only for wrist-origin `pull_up`/`dip`/`push_up`. Thread `movement.origin` into `values_for_rep` and compute `lockout_pct`/`hang_pct` only for wrist-origin tracks. Suppress `momentum` for hip-origin until a real hip-origin sway signal exists.
- **Estimated Tokens:** 60000
- **Dependencies:** none
- **Steps:**
  - Extend `_series` with `hip_over_ankle = (ankle_y − hip_y)/torso`; expose per-rep `standing_hip_height` (p50 over the rep's start frames) and `bottom_hip_height` (p05).
  - Add `squat()` to `CLASSIFIERS`/`TRACK_FAILURES`; update `classify_failures`; thread `origin` into `values_for_rep` and gate the bar-fault block on it.
  - Pin the depth threshold **before** looking at any firing results (config.py discipline).
  - Update `docs/CORE.md` movement/fault table; note in `docs/FINDINGS.md` that hip-origin self-reference was silently feeding bar faults.
- **Acceptance Criteria:**
  - Synthetic clean squat sets produce **zero** lockout/dead-hang/momentum faults; shallow-depth synthetic sets produce `insufficient depth` on ≥60% of reps with FPR ≤20% (verdict rule, `config.py:18-19`).
  - A `squat_clip` fixture through `classify_failures("squat", values_for_rep(...))` yields no bar faults; a `dip` fixture still yields the five bar faults.
  - 137 baseline tests green (re-establish baseline in the correct `.venv` first); `validate_faults` re-labelled for squat-track clips.

#### Task 1.2: Remove healthy-value defaults on missing measurements
- **Location:** `barra/faults_taxonomy.py` (`_f` call sites: 69, 73, 76, 91, 95, 99, 131, 147, 155), `tests/test_core.py`
- **Description:** `_f(values.get("arms_straight_frac"), 1.0)` defaults a **missing** measurement to healthy, so `bent arms` can never fire on the rep path (only `holds.py:_hold_metrics` produces that key). Change predicates to explicit three-valued handling: absent/NaN → fault not fired and not counted clean, recorded in a per-rep `unmeasured` list. Either measure `arms_straight_frac` for rep rows (elbow angle at lockout frames via `classify._angle`, O(T)) or drop `"bent arms"` from `TRACK_FAILURES["muscle_up"]` and document it. Apply the same pattern to `swing`/`heel_raise`/`legs_straight_frac` defaults.
- **Estimated Tokens:** 40000
- **Dependencies:** Task 1.1
- **Steps:** Add elbow-angle computation for wrist-origin rep rows (reuse `_angle`); add the `unmeasured` key to rep rows in `server/process.py` and to hold rows in `barra/holds.py`.
- **Acceptance Criteria:** A values dict missing `arms_straight_frac` yields `bent arms` in `unmeasured`, not silent health; a measured 100 yields neither. On all 8 documented sample clips, `unmeasured` matches exactly the quantities geometrically unavailable (hand-pinned fixture).

### Phase 2: Single source of thresholds + structured fault contract — P0
**Goal**: Kill the regex-parsed `why`-string contract and the triplicated constants so phone and harness provably agree.

#### Task 2.1: Ship structured fault inputs in the rep payload
- **Location:** `server/process.py` (rep row `:510-545`), `barra/faults.py:35-63`, `app/src/main/java/com/barrapp/Cues.kt:26-43`, `barra/quality.py`
- **Description:** Add `lockout_pct`, `hang_pct`, `stalled_frac`, `tempo_ratio`, `swing` as numeric rep-row fields (already computed in `values_for_rep`/quality context). Rewrite `rep_faults` and `Cues.kt` `repFaults` to read these numbers with three-valued semantics (null → not fired, recorded unmeasured); keep the regex path as a one-release deprecated fallback. Pin the boundary rule on the **unrounded** float (removes the `.0%` banker's-rounding hazard at 84.5%).
- **Estimated Tokens:** 55000
- **Dependencies:** none
- **Steps:** Extend the rep-row schema and the Kotlin `RepRow` data class with nullable numerics; rewrite both readers; version the payload.
- **Acceptance Criteria:** **Reword-invariance** test — mutate the `why` strings (`"lockout 72% of full"` → `"top reached 72% of reach"`) and assert `rep_faults`/`repFaults` output is identical. Boundary tests at 84.9/85.0/85.1. Extend `tests/test_server_payload.py`: every fault-relevant field present-or-explicitly-null in `_empty` and success payloads.

#### Task 2.2: One thresholds module + phone parity test
- **Location:** `barra/config.py` (add a frozen `THRESHOLDS` dataclass), edits in `faults.py`, `faults_taxonomy.py`, `quality.py`, `classify.py`; new `tests/test_threshold_parity.py`; `docs/CORE.md`
- **Description:** Consolidate every pinned constant (`SWING_TORSO`, `LOCKOUT_MIN`, `HANG_MIN`, `CONTROLLED_TEMPO`, `STALL_RATE`, the stall-emission `0.05`, `OVER_BAR`, `ARTICULATION`, `KNEES_UP`, `HOLD_BAND`, `HOLD_FRAC`, `BELOW_HANDS_DIP`, `STRAIGHT_ARM/LEG`, `HORIZONTAL`, `PIKE`, `PISTOL_*`) into `config.py` with an evidence comment (carried from existing docstrings). Delete duplicates; keep old names as aliases one release. Add a parity test that parses `Cues.kt` literals and asserts equality.
- **Estimated Tokens:** 45000
- **Dependencies:** Task 2.1
- **Steps:** Mechanical move + imports; parity test with an allowlist of constants that must exist on both sides.
- **Acceptance Criteria:** No numeric literal duplicated outside `config.py` for any parity-listed constant (test enforces). `validate_faults` counts identical pre/post refactor (behaviour-preserving proof) once the baseline is green.

### Phase 3: Viewpoint-gated PLANAR faults — P1
**Goal**: PLANAR quantities are computed and fire only when the view supports them; valgus/forward-knee aliasing is broken.

#### Task 3.1: Thread view/bin into the server pipeline and gate planar geometry
- **Location:** `server/process.py`, `barra/viewpoint.py` (expose an in-memory azimuth/bin estimator from `_apparent_ratios` + `camera_side`), `barra/faults_taxonomy.py` (`pistol_geometry:197-243`), `barra/synthetic.py`, `scripts/viewpoint_sensitivity.py`, `docs/FINDINGS.md`
- **Description:** Prefer the declared `view`/`declared_bin` (from `sessions.csv`, `ingest.py:89`), else run the lightweight shoulder-ratio estimator. Attach `bin`/`side` to each rep row. In `pistol_geometry`: compute `knee_valgus` only when `bin == FRONTAL` (else NaN → unmeasured); compute `torso_lean` only when `bin` is SAGITTAL and the facing sign is resolved via `viewpoint.camera_side`; replace `heel_raise` with a per-rep self-referenced signal (rise of the planted ankle relative to its own start-frame height at bottom — vertical, azimuth-invariant). Gate using Plan 1's rule: emit a PLANAR fault only when the view is **knowable** (`camera_side` agreement ≥ 0.70 and `R_true` inside `ANATOMICAL_PRIOR_RANGE`), else `unmeasured`. Declare the old hip-relative `heel_raise` formula invalid in docs. Add the projection-dependence caveat to `momentum` (swing); skip firing when `bin == UNKNOWN`.
- **Estimated Tokens:** 70000
- **Dependencies:** Tasks 1.1, 1.2, 2.2
- **Steps:** Refactor `viewpoint.py` to work on an in-memory keypoint array; wire into `analyze_clip`; extend `synthetic.py` with a frontal knee-valgus twin at azimuth 88° and a `knee_travel` twin at 88° (prove non-aliasing), plus a heel-lift mode.
- **Acceptance Criteria:** Synthetic: `knee_valgus` fires ≥60% on frontal valgus reps, 0% on frontal knee-travel and sagittal clean reps; `heel_raise` fires on heel-lift sets and never on deep clean pistols. Null: zero planar faults from SAGITTAL-labelled clips where the condition is absent. Append a fault-layer table (azimuth vs fault firing) to `docs/FINDINGS.md`.

### Phase 4: Rep detection undercounting — P1
**Goal**: Raise standard-pass recall on real clips (rotation, fatigue tails, slow eccentrics) without inventing reps.

#### Task 4.1: Per-span amplitude + drift/roll-robust peak search
- **Location:** `barra/ingest.py` (`segment_reps_verbose`, `active_mask`), `barra/movements.py` (`tracking_signal`), `tests/test_core.py`, `barra/synthetic.py`
- **Description:** Compute `rest=p15/apex=p97` **per active span** (from `_runs(active)`) instead of clip-wide, with per-span amplitude, and find peaks per span. For rotation-like drift on wrist-origin movements, add a roll normalization **scoped to the segmentation signal only** (never the normalised skeleton used for scoring, so `test_rotation_is_not_removed` and the "rotation kept" contract hold): estimate per-frame roll from the wrist-wrist vector angle minus 0 (the bar axis as the level; ankle-ankle for hip-origin), and rotate the signal by −roll. Flag-gate it on (roll range across the clip > ~5°) so well-filmed clips are untouched. Fix the `max_half_rep_s=4.0` truncation: replace with `max(4.0, 3×min_rep_s)` plus a velocity floor so walks still terminate.
- **Estimated Tokens:** 90000
- **Dependencies:** none
- **Steps:** Refactor to loop spans with a single-span fallback (regression safety); add roll estimation + rotation in `tracking_signal`; extend `synthetic.py` with a roll(t) ramp, a fatigue set (`depth_gain` decaying per rep), and a slow-eccentric set (>4 s descent), all with generated marks.
- **Acceptance Criteria:** Synthetic invariants: counts equal generated marks for roll-ramp, fatigue, slow-eccentric; boundaries ±2 frames; clean `SETS` segment identically to today (±1 frame). Null: noise-only and drift-with-wiggles fixtures still produce 0 reps. Real-clip reconciliation: re-run `scripts/demo_sessions.py` on 0010 (target 3), 0012 (target 2), 0011 (hand-marked), and confirm 0014/0017/0019 remain 0; record a before/after table in `docs/CORE.md`.

#### Task 4.2: Fatigue-tolerant re-admission + rescue scoping
- **Location:** `barra/ingest.py` (rejection loop, `_rescue_candidates:496-604`, `rescue_reps`)
- **Description:** After the standard pass, re-admit rejected peaks whose leg-to-leg displacement ≥ 0.6× the **median accepted amplitude** AND pass the existing velocity-MAD gradient validation (`climb_floor = 2.5×scale`); every other rejection (interpolated, anchor, untracked turnaround) still applies. Scope the rescue pass's `walk` to the containing active span (its current walk is unbounded to the whole clip).
- **Estimated Tokens:** 50000
- **Dependencies:** Task 4.1
- **Steps:** Implement re-admission as an explicit second loop with trace rejection names (`barra explain` shows which pass admitted each rep); bound `_rescue_candidates.walk` to the span.
- **Acceptance Criteria:** Synthetic fatigue fixture: all reps counted, each re-admitted rep trace-tagged; noise fixtures still 0; the 8-clip table unchanged except where Task 4.1 already documents gains. Two-phone reliability protocol (`docs/QUALITY.md` §2): identical counts both passes.

### Phase 5: Movement classification robustness — P1
**Goal**: Classification evidence comes from the set, not the walk-in; mixed clips refuse loudly; confidence is stated as margin-to-threshold.

#### Task 5.1: Scope percentile features to active spans
- **Location:** `barra/classify.py` (`features`, `classify`), `tests/test_classify_quality.py`, `docs/CORE.md`
- **Description:** Compute `shoulder_above_hands_p95/p05`, `arm_articulation`, `hands_overhead_frac/below_frac` over the anchored/active-span frames (reuse `active_mask` spans) rather than the whole clip, which includes standing prefix/suffix frames with hands at the sides. Keep whole-clip `parked_frac` hold-rejection exactly as is (it must see rest frames). Add new fixtures: `bar_clip` prefixed with 40% standing frames (hands low) and a standing-dominant fixture.
- **Estimated Tokens:** 55000
- **Dependencies:** none
- **Steps:** Add span selection into `features()`; recompute extremal percentiles on the union of overhead/anchor-span frames; re-run the 8-clip blind check and append the post-change table.
- **Acceptance Criteria:** Prefix-invariance test — adding standing frames cannot flip `pull_up`→`muscle_up` (or reverse) nor turn a labelled set into `unknown` unless the set is below the minimum anchored span. All existing classify tests green unchanged.

#### Task 5.2: Per-span classification with disagreement refusal
- **Location:** `barra/classify.py`, `server/process.py`, `tests/test_classify_quality.py`
- **Description:** For multi-span clips, run the branch gates per span; if spans agree → single label plus span count; if they disagree → payload blocker naming each span's verdict. Add a lighter per-rep consistency check for single-movement clips: flag a rep whose defining landmark never reaches the movement's threshold as `unmeasured` with a reason (Plan 1's 4.2), rather than silently scoring it under the wrong movement. No per-rep re-labelling beyond span level (keeps `reps.csv` contract).
- **Estimated Tokens:** 45000
- **Dependencies:** Task 5.1
- **Steps:** Add a `classify_spans` entry point; `analyze_clip` refuses on disagreement via the existing `_empty`/blocker machinery.
- **Acceptance Criteria:** Mixed synthetic fixture (`squat_clip` + `bar_clip`) produces the blocker, not a label; single-movement fixtures unchanged; classification cost is O(spans × T).

#### Task 5.3: Replace ad-hoc confidences with a margin-to-threshold statement
- **Location:** `barra/classify.py:485-564`, `Classification.confidence`, `label()`
- **Description:** Keep a number for the UI but relabel it: compute `confidence` as a bounded margin `min(1, max(0, (v − t)/(hi − t)))` and add a `certainty: "margin-to-threshold"` field so it is never mistaken for a probability. Keep the `certain >= 0.65` gate on the margin.
- **Estimated Tokens:** 12000
- **Dependencies:** none
- **Steps:** Rename semantics, keep the key for backward-compat, update reason strings.
- **Acceptance Criteria:** Unit test asserting the value derives deterministically from `(peak, OVER_BAR, scale)`, bounded in [0,1], no NaN path from an unmeasured feature.

### Phase 6: Taxonomy coverage for the measurable subset — P2
**Goal**: Add the geometrically honest subset of the 5-most-cited-errors lists per track; declare the rest unmeasured rather than fake them.

#### Task 6.1: Push-up, dip, pull-up detectors
- **Location:** `barra/faults_taxonomy.py` (new `push_up()`, `dip()`, `pull_up()` + shared geometry helper), `barra/synthetic.py` (new error modes), `data/calisthenics/faults.csv`, `docs/CORE.md`
- **Description:** Measurable now, each signal/threshold pinned before firing results are seen: push-up `sagging hips` (hip sags below the shoulder-ankle line by > threshold, vertical, azimuth-tolerant), `head position` (nose above the shoulder-ankle line); dip `too deep` (elbow angle at bottom < 90°, reuse `_angle`), `bounce at bottom` (no near-zero-velocity frame within ±3 frames of the turnaround — |vel| at turn vs the ascent's own p90); pull-up `no active hang` (elbow angle < 150° at rep start), `too fast` (concentric_s < 0.5× the set's own median — INVARIANT). Deliberately NOT measured and declared: elbows-flared-90° (needs top-down), arm-curl/lat engagement, grip type, wrist loading, lumbar rounding, gaze.
- **Estimated Tokens:** 100000
- **Dependencies:** Phases 1, 2, 3
- **Steps:** Implement the three classifiers; add them to `CLASSIFIERS`/`TRACK_FAILURES`; remove their `muscle_up` fallback (call the shared bar block explicitly). Add synthetic error modes with magnitudes fixed in the same commit as the thresholds. Register deliberate-fault clips in `data/calisthenics/faults.csv` via `validate_faults --emit-candidates` → watch → label.
- **Acceptance Criteria:** Each new detector: ≥60% detection on its induced synthetic reps, FPR ≤20% on clean synthetic sets, no firing on clean reps of the 8 real clips (null check recorded). Deliberate-fault corpus: ≥1 expected-positive clip per shipped fault (`python -m barra.validate_faults` exit 0); faults with no clip are listed INCONCLUSIVE. `docs/CORE.md` gains a "measured vs declared-unmeasured" table mapping every `tecnicas-errores-comunes.md` entry to its status.

#### Task 6.2: Hold-path additions (planche protraction, scapular elevation signal)
- **Location:** `barra/holds.py` (`_hold_metrics`), `barra/faults_taxonomy.py` (`front_lever`, `planche`)
- **Description:** Add `shoulders_over_hands` (median shoulder-above-hands over the hold; planche protraction proxy) to hold metrics and a `no protraction` planche failure; add an experimental `scapular elevation` signal (ear-to-shoulder distance compression p05 vs standing baseline) gated to holds and marked experimental in docs until the deliberate-clip loop validates it.
- **Estimated Tokens:** 40000
- **Dependencies:** Task 6.1
- **Steps:** Extend `_hold_metrics`; wire into both classifiers; keep `TRACK_FAILURES` exhaustive.
- **Acceptance Criteria:** Hold fixture with sagging/piked geometry still classified by existing tests; new signals present in `unmeasured` when occluded. Null: clean front-lever synthetic hold fires nothing.

## Testing Strategy
- Keep and extend the invariant suite (`python -m unittest discover -s tests`); re-establish the green baseline in the correct `.venv` (mediapipe present) before using it as a behaviour-preserving gate. Every fix lands with parametric fixtures in the existing style.
- **Label-free validation per fix** (the load-bearing part): synthetic invariant tests via `barra/synthetic.py` (generated marks make counts/boundaries exact); **reword-invariance** and boundary-value tests for the fault contract; **prefix-invariance** for classification; **camera-motion nulls** (azimuth-ramp + noise → 0 invented reps); deliberate-fault clips via `validate_faults`; null-distribution checks on the 8 real clips' clean reps (fires count against `MAX_ACCEPTABLE_FPR=0.20`, detection must clear `MIN_ACCEPTABLE_DETECTION=0.60`); phone-parity via `tests/test_threshold_parity.py`; two-phone reliability (`docs/QUALITY.md` §2).
- Docs (`docs/CORE.md`, `docs/FINDINGS.md`, `docs/QUALITY.md`) updated in the same commit as each behaviour change; the synthetic-only caveat on all synthetic-derived claims is preserved.

## Risks
- **F1 changes live squat fault lists** ("dead hang on every squat" was at least consistent day to day). Mitigation: ship a docs note and a one-release deprecation window logging the old behaviour; golden tests pin the new semantics.
- **Phase 4 roll normalization may not move 0011** if its motion is azimuth/pitch, not roll; the wrist-wrist "bar axis" is undefined for rings, single-arm hangs, and single-side pair mode. Mitigation: flag-gate it (only when roll range > ~5°), skip in single-side mode, and check the 0011 reconciliation result before claiming the pain point addressed; scope it to segmentation only so `test_rotation_is_not_removed` holds.
- **Synthetic detectors measure the noise model, not reality.** Mitigation: keep the synthetic-only caveat; the deliberate-fault corpus is thin (one clip/fault minimum), so several new thresholds are INCONCLUSIVE on real footage at ship time — state it, never "validated".
- **View gating depends on a biased azimuth estimator** (`R_true` underestimated when never filmed near-frontally). Mitigation: gate PLANAR faults only when the view is *knowable*; prefer `declared_bin`/`view`; run both estimated and declared to expose disagreement.
- **Squat depth signal and the synthetic generator are not independent** (both built around a 25-35° shank range); a pitched camera or heel plate could shift the standing baseline. Mitigation: add a pitched-camera test on the squat track; state the residual risk in docs.

## Rollback Plan
- Each phase lands as an independent commit series; revert with `git revert` without touching others (Phases 2-6 depend only on the unmeasured-pattern and thresholds module, which are additive).
- Structured fault fields are additive payload keys; the regex readers in `faults.py`/`Cues.kt` are kept one release as a documented fallback, so reverting the server alone restores the old contract.
- Behaviour-preserving refactors (thresholds module, per-span amplitude with single-span fallback) are gated by before/after golden runs (`barra selftest` segmentation and `validate_faults` counts must be identical pre/post; if not, revert and document the divergence).
- Roll-normalization and fatigue re-admission are flag-gated; a bad real-world outcome is a one-line disable plus revert, with traces (`barra explain --replay`) showing which pass admitted each rep.
- `out/reps.csv` is never re-derived downstream, so any segmentation regression is user-correctable in the interim and `out/ingest_log.csv` preserves rejection reasons.

## Edge Cases
- Clips shorter than one `ANCHOR_WINDOW_S` window (classify and `active_mask` fall back to whole-clip; scoped features must not change this path).
- All-NaN/below-floor confidence for any new signal (three-valued: unmeasured, never a default).
- `lockout_pct` exactly at the 85.0 boundary; Python `.0%` rounding at x.5 percents; fps 0 or missing (`ingest.py:425` defaults 30).
- Side-on occlusion / single-side pair mode: elbow angles exist only for the visible arm; `bent arms`/`no active hang` must handle one-sided data.
- Mixed clips and camera-bin swings mid-clip (Phase 5 blocker); a span shorter than `min_rep_s` inside an otherwise good clip.
- Holds passing through the horizontal band transiently (skin-the-cat) — `hold_attempts` run-trimming must not claim them.
- Knee-raise clips with knees unseen early (`knee_excursion` NaN → knee_raise must fail loud, not fall through to `pull_up`).
- Roll normalization when the wrist pair is in single-side mode (bar axis undefined → skip, log in trace).
- Pistol with the free leg occluded; deep pistols vs the old depth-confounded `heel_raise`.
- User-edited `out/reps.csv` rows with empty `view`/`declared_bin` — gating falls back to estimation, then to unmeasured.

## Open Questions
- Is 0011's camera motion roll (fixable via bar-axis normalization) or azimuth/pitch (not addressable by it)? Resolvable only by running the Phase 4 probe; the undercounting claim for 0011 is contingent.
- Should `momentum` (swing > 0.4) fire from FRONTAL bins where fore-aft kip is foreshortened but lateral sway is real, or only from SAGITTAL? Needs one deliberate kip clip per bin.
- Does the app team want `unmeasured` surfaced in the UI ("not checked") or only in the payload? Affects whether `Cues.kt` changes are one release or two.
- Squat depth: absolute drop (≥ 0.45 of standing hip height) or a hip-knee-ankle angle convention (thigh below horizontal)? The angle convention is more standard and view-robust in sagittal but adds a second planar-gated quantity; decide before pinning.