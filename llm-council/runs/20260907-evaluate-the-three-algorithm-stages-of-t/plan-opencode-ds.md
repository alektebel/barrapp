# Plan

## Overview
Evaluate the three-stage barra measurement core — rep detection, movement classification, fault classification — by reading the code against its own documented contracts, severity-rank the concrete weaknesses, and hand back a prioritized, non-ML fix plan where every fix carries a no-label validation strategy. Findings are recorded below as the SHA-1 ordered severity ranking that drives the phase priority; no code changes are proposed for implementation here, only what each change fixes, where it happens, and how it would be proven "right" (or honestly marked unmeasured) without ground-truth labels.

Ranked findings (severity ∝ impact on measured truth / trust, weighted by fragility):
- **H1 (measured-but-wrong): PLANAR faults run without view gating.** `faults_taxonomy.py:pistol_geometry` and `metrics.py:METRIC_SPEC`'s `PLANAR` set compute `knee_valgus` (image-x deviation), `torso_lean` (hip−shoulder x gap), `heel_raise` regardless of declared camera view; `docs/FINDINGS.md` #1 already shows a 10° azimuth move exceeds every induced error and frontal-plane errors are ~1.2× noise from a sagittal camera. The docstring admits it (`faults_taxonomy.py:201` "only mean something from a consistent camera side") but the dispatch never enforces it.
- **H2 (fragile contract): fault presence is regex-parsed off human prose.** `faults.py:35-38` and `app/.../Cues.kt:27-42` both `re.search(r"lockout (\d+)% of full")` / `"hang (\d+)% of full"` / `"% of the ascent made no progress"` on component `why` strings produced by `barra/quality.py`. Any prose rewording silently drops the fault; the same regex and literal live in two languages.
- **H3 (fragility/duplication): ~20 magic constants in three places.** `SWING_TORSO 0.4`, `LOCKOUT_MIN 0.85`, `HANG_MIN 0.75`, `CONTROLLED_TEMPO 0.70`, `STALL_RATE 0.20` are duplicated across `faults.py`, `faults_taxonomy.py`, and `Cues.kt`; the phone and harness must move in lockstep or disagree.
- **H4 (undercount = data loss): Stage 1 dies on camera-rotation sets.** `0011` (knee raise, camera rotating) is recognised but 0 reps: `active_mask` requires the anchor (`wrist`) to hold within `MAX_BAR_TRAVEL 0.80` over a 3 s window, which camera panning violates; `ingest.py:282-286` then computes `rest=p15 / apex=p97` over only the surviving active frames, and the `0.35×amplitude` prominence gate (`ingest.py:292`) sits above every real turnaround. Undercounts are the "safe" direction but cost data points.
- **H5 (wrong semantics): `classify_failures` routes squat/pull_up/dip/push_up into `muscle_up`'s fault set.** `faults_taxonomy.py:291-295` gives a squat "lockout / dead hang / control / stall / bent arms / poor transition" — terms that do not apply — and the exercise-specific top-5 errors from `tecnicas-errores-comunes.md` (squat: valgus/depth/heel-raise/butt-wink/gaze; push-up: sagging/elbow-flare/half-range/head/wrist; dip: too-deep/bounce/shrug/torso) are never measured at all.
- **M-1 (structural): one movement per clip.** `classify.py:371` classifies the whole clip; no per-rep movement, so a mixed clip or a camera that swings bins cannot be measured.
- **M-2 (bias): `max_half_rep_s=4.0` clips slow rep boundaries.** `ingest.py:341-347` caps each `walk` at `max_half`; a >8 s slow negative is boundary-shortened (mis-measured, not rejected).
- **L-1 (cosmetic/UX): ad-hoc confidences.** `classify.py:485-564` emits 0.70–0.98 heuristics that read as probabilities but are margins-to-threshold, shown to the user and used by `certain >= 0.65`.

## Scope
- **In**: the three stages (barra/ingest.py, barra/classify.py, barra/faults.py, barra/faults_taxonomy.py, barra/movements.py, barra/metrics.py, barra/holds.py + app/.../Cues.kt + server/process.py), the documented rationale in docs/CORE.md, docs/FINDINGS.md, docs/QUALITY.md, and the fault list in tecnicas-errores-comunes.md; severity-rank and verify findings; produce a prioritized fix plan with file paths and a label-free validation method per fix.
- **Out**: no implementation, no ML/learned classifier, no new labelled-corpus dependency, no cross-subject claims, no change to the "measurable set" contract (out/reps.csv remains the user-edit handoff, never re-derived).

## Phases

### Phase 1: Single source of thresholds + kill the prose-regex contract (H2, H3)
**Goal**: Make the phone, the harness, and the taxonomy agree on one set of numbers read from one place, and drive faults from numeric payload fields instead of human prose.

#### Task 1.1: Unify the fault thresholds behind one module
- **Location**: `barra/faults.py`, `barra/faults_taxonomy.py`, delete the duplicated literals in `app/.../Cues.kt`; `server/process.py` (payload surface); `barra/validate_faults.py`.
- **Description**: Move `SWING_TORSO`, `LOCKOUT_MIN`, `HANG_MIN`, `CONTROLLED_TEMPO`, `STALL_RATE` (and `STRAIGHT_ARM/LEG`, `HORIZONTAL/STRICT_HORIZONTAL`, `PIKE`, `PISTOL_DEPTH`, `PISTOL_VALGUS`) into `barra/config.py`; `faults.py` and `faults_taxonomy.py` import them; `server/process.py` emits a `thresholds` object in the payload; `Cues.kt` reads thresholds from the payload instead of hardcoding `0.4/85/75`.
- **Estimated Tokens**: 250
- **Dependencies**: none
- **Steps**:
  1. Add a frozen dataclass `THRESHOLDS` in `barra/config.py` with the shared bar-fault numbers and their human label/unit, so one import is the source of truth.
  2. Replace literals in `faults.py`, `faults_taxonomy.py`, `quality.py` (`CONTROLLED_TEMPO`, `STALL_RATE`) with imports.
  3. In `server/process.py` return `"thresholds": {...}` next to `"reps"`; in `Cues.kt` read `analysis.thresholds` (default to current constants only if the field is absent) and drop the hardcoded literals.
- **Acceptance Criteria**:
  - `python -c "import barra.faults, barra.faults_taxonomy, barra.quality, barra.config as c; assert barra.faults.LOCKOUT_MIN==barra.faults_taxonomy.LOCKOUT_MIN==c.THRESHOLDS.lockout_min"` (a new invariant test asserts the three agree).
  - A payload produced by `process.py` reproduces `rep_faults` purely from payload numbers with zero regex (see 1.2).

#### Task 1.2: Replace prose-Regex fault derivation with numeric fields
- **Location**: `barra/faults.py:35-63`, `barra/quality.py` (component `why`/`value`), `app/.../Cues.kt:26-43`, `server/process.py`.
- **Description**: Add structured keys the component already computes — `range.lockout_pct`, `range.hang_pct`, `smoothness.stalled_frac` — to the payload components; have `rep_faults` and `Cues.kt` read those numbers against the unified thresholds. Keep the human `why` strings for display only (never parsed).
- **Estimated Tokens**: 180
- **Dependencies**: 1.1
- **Steps**:
  1. In `process.py`, when building each rep's `components`, attach `value`-carried numerics: `lockout_pct`, `hang_pct`, `stalled_frac`.
  2. Rewrite `rep_faults` (`faults.py`) to use `_value(comp, "lockout_pct")` etc. and `values_for_rep`/`classify_failures` path in `faults_taxonomy.py` to read the same numbers; delete `_LOCKOUT_RE/_HANG_RE/_STALL_RE`.
  3. Mirror in `Cues.kt`: read `it.value` numerics, drop the `Regex("lockout (\\d+)% of full")` etc.
- **Acceptance Criteria**:
  - **Reword-invariance (label-free):** a unit test rewrites the `why` string (e.g. `"lockout 72% of full"` → `"top reached 72% of reach"`) and asserts `rep_faults`/`repFaults` output is identical — proving a prose change can never silently silence a fault.
  - Existing `test_server_payload.py` still passes.

### Phase 2: Make Stage 1 survive camera motion and rotation (H4, M-2)
**Goal**: Keep the "fail loudly" honesty, but stop treating camera-rotation/drift as a rep-killing anchor violation so clips like 0011 measure instead of vanishing.

#### Task 2.1: Decouple the active-span and amplitude gates from absolute in-image anchor travel
- **Location**: `barra/ingest.py:active_mask` (166-208) and `segment_reps_verbose` amplitude block (282-286); `barra/movements.py:anchor_travel`.
- **Description**: The anchor-stillness test and the `rest=p15/apex=p97` amplitude are polluted by camera pan, which is the dominant signal on rotation sets. Replace the absolute-anchor test with a **relative-articulation** criterion: a frame is "active" when the anchor moves much less than the body it is supposed to be (anchor travel vs hip/torso travel ratio), not when the anchor is still in absolute image space. Then robustly detrend the tracking signal's baseline (remove a slow moving-median floor, not the rep-scale oscillation) before computing `rest/apex/amplitude`, so a camera-induced baseline drift cannot inflate amplitude and sink the prominence gate.
- **Estimated Tokens**: 400
- **Dependencies**: none
- **Steps**:
  1. Add a helper that computes anchor travel **relative to the body** (`anchor_travel / robust_travel_of_torso_or_hip`) for the active window; set the active gate on that ratio, keeping `MAX_BAR_TRAVEL` as a sanity ceiling rather than the primary test.
  2. In `segment_reps_verbose`, detrend `sig` with a wide moving-median floor (window ≥ 2× `min_rep_s`) and compute `rest/apex/amplitude` on the detrended signal, while keeping reported boundaries on the original (aligned) signal.
  3. Keep all documented rejections but re-order so a candidate is rejected for *real* reasons (untracked turnaround, interpolated frames) before the anchor test, and the anchor test now emits "camera moved too much for an in-image anchor" rather than "not on a fixed bar" when relative articulation is fine.
- **Acceptance Criteria**:
  - **Camera-motion null (label-free):** synthetic clip = a static hang with a per-frame azimuth ramp (0→30°) plus noise; assert `segment_reps_verbose` returns 0 reps after the fix (it currently can return spurious or none; both are acceptable, the point is it must not *invent* reps — assert 0 invented).
  - **Clean/rotation control:** the existing `synth_bar_clip` (test_movements.py:21) at `bar_drift=0.8` after the fix still returns the expected `n_reps`; add a variant with a rotating camera and assert the real reps survive where before they were all rejected.
  - Add these to `tests/test_rescue.py` or a new `tests/test_camera_motion.py`; run `python -m unittest discover -s tests`.

#### Task 2.2: Bound slow-rep boundary clipping
- **Location**: `barra/ingest.py:341-347` (2nd `walk` loop), and the `max_half_rep_s` default (`ingest.py:160`).
- **Description**: A slow negative that exceeds `max_half` on one leg is boundary-shortened rather than rejected. Make the cap explicit and self-consistent: once the walk reaches `max_half`, stop accumulating but record a `boundary_clipped` marker on the rep; keep `MAX_BAR_TRAVEL` as the loud rejection.
- **Estimated Tokens**: 120
- **Dependencies**: 2.1
- **Steps**: track whether the walk terminated on the cap; surface it in the trace/rep row; do not reject, but make `rep_metrics` able to flag the rep as boundary-uncertain.
- **Acceptance Criteria**: synthetic 12 s negative (beyond 2×4 s) — assert the rep is kept but flagged; assert the boundary is not silently inside the real rest position (compare against the signal's true trough).

### Phase 3: Gate PLANAR fault metrics on declared viewpoint (H1)
**Goal**: Never emit a frontal/sagittal-specific fault from a view that cannot see it; say "unmeasured" instead of a confident wrong fault.

#### Task 3.1: Wire declared view into the fault taxonomy
- **Location**: `barra/faults_taxonomy.py:classify_failures` (283-296) and `pistol_geometry` (197-242); `barra/viewpoint.py:camera_side`/`_bin_of`; `server/process.py:505-509`.
- **Description**: Compute the viewpoint bin/side from the clip (existing `viewpoint.py`) and pass a `view`/`plane` tag into `classify_failures`. For PLANAR quantities — `knee_valgus` (frontal/posterior only), `torso_lean` (sagittal only), `arm swing` (sagittal), `shoulder_asymmetry`/`turn_asymmetry` (`metrics.py:47` PLANAR) — gate the *fault emission*, not the measurement: a sagittal clip must not report "knee valgus"; a frontal clip must not report "leaning back"/"arm swing".
- **Estimated Tokens**: 250
- **Dependencies**: 1.1
- **Steps**:
  1. Add a `requires_view` field on each failure in the taxonomy (or a mapping `failure -> {frontal, sagittal, any}`).
  2. In `classify_failures`, drop a failure whose required view is not declared/estimated (keep it in a separate `unmeasured` list in the payload, not in the "clean" buckets).
  3. Surface `detected.view`/`bin` in the payload and in `Cues.kt` so a cue never names a fault the camera couldn't see (mirrors the QUALITY.md "report INCONCLUSIVE and why" convention).
- **Acceptance Criteria**:
  - **View-gating (label-free, uses existing synthetic generator):** extend `barra/synthetic.py:SETS` with an induced-`knee_valgus` frontal set (azimuth ≈ 88°, as in the existing `err05` clean frontal) and a clean sagittal set; assert `knee_valgus` fires only on the frontal err clip and is "unmeasured" on the sagittal clip. This directly tests the FINDINGS.md #1 "frontal errors invisible from the side" claim as an invariant rather than a known limitation.
  - `python scripts/viewpoint_sensitivity.py` output is unchanged in its conclusion but the taxonomy no longer emits frontal faults from a sagittal view.

### Phase 4: Close per-exercise taxonomy coverage honestly (H5, M-1, L-1)
**Goal**: Stop giving squats lockout/dead-hang faults, and start measuring (or explicitly declining) the top-5 quoted errors per exercise, without inventing a classifier.

#### Task 4.1: Per-exercise fault sets (squat, push-up, dip, pull-up)
- **Location**: `barra/faults_taxonomy.py:CLASSIFIERS` (263-268) and `classify_failures` (283-296); `server/process.py:505-509`; `barra/synthetic.py` + new tests.
- **Description**: Add `squat`, `push_up`, `dip`, `pull_up` classifiers that read existing measured signals and only the ones that apply. Concretely:
  - **squat**: depth (`rom`), knee valgus (per-side image-x deviation, frontal-gated), heel raise (ankle height, frontal-gated), butt-wink/lumbar (hip-pike-like `hip_pike_deg`, sagittal), torso lean. Emit the rest in a `never_measured` note (gaze is not measurable from keypoints — say so).
  - **push-up**: sagging hips/body line (`body_line_deg`), elbow flare (elbow angle), half-range (`rom`), head position (not measurable from keypoints — state it), wrist loading (not measurable — state it).
  - **dip**: too deep (shoulder-below-hands depth), bounce-at-bottom (min velocity spike / `tempo_ratio`), scapular shrug (shoulder elevation relative to hands), torso angle (already a diagnostic).
  - **pull-up**: no-active-hang (`hang_pct`), arm-pulling (elbow flexion during early ascent), kipping (`swing`), cut-range (`hang_pct`+`lockout_pct`), too-fast (`tempo_ratio`).
- **Estimated Tokens**: 500
- **Dependencies**: 3.1 (for the PLANAR gates), 1.1
- **Steps**:
  1. Write per-track classifier functions mirroring the established "threshold on a measured signal" style, pulling the derived numbers `values_for_rep` already produces plus new PLANAR inputs from `synthetic.py`/`metrics.py`.
  2. Update `TRACK_FAILURES` so the phone can render only the failures that track can produce; remove the silent `muscle_up` fallback for squat.
  3. For the quoted errors that keypoints cannot see (gaze, wrist loading, false grip), append them to an explicit `unmeasurable_faults` list in the payload rather than to `failures`, with the reason — honouring the QUALITY.md "never report INCONCLUSIVE as clean" rule.
- **Acceptance Criteria**:
  - **Deliberate-fault clips (label-free):** use `barra/synthetic.py`'s existing squat errors (`shallow_depth`, `knee_valgus`, `knee_travel`, `excess_forward_lean`, `lateral_shift`) and assert: `shallow_depth` fires squat-depth; `knee_valgus` fires only from a frontal view; a clean squat set fires no squat fault. Extend `make_set`/`SETS` with induced push-up (sagging hips via a downward hip offset) and dip (bounce via a spike at the bottom) cases.
  - **Invariant:** a clean control set per movement yields an empty or `never_measured` result, never a wrongly-applied muscle-up fault (e.g. a clean squat must not produce "lockout"/"dead hang"/"poor transition").
  - New tests in `tests/test_classify_quality.py` / a new `tests/test_taxonomy.py`; full suite (`python -m unittest discover -s tests`) green.

#### Task 4.2: Classify per rep, not per clip, for mixed/anisometric clips
- **Location**: `server/process.py:378-392` (detection), `barra/classify.py:371-596`.
- **Description**: Keep whole-clip classification as the headline, but after segmentation run a light per-rep geometric consistency check in `process.py`: if a rep's own window disagrees with the clip's movement signature (e.g. shoulder never crosses the bar in a clip classified muscle_up), mark that rep `unmeasured` with a reason rather than silently scoring it under the wrong movement. This is the minimal step towards per-rep classification without inventing a model; it preserves "declared, not guessed."
- **Estimated Tokens**: 200
- **Dependencies**: 4.1
- **Steps**: reuse the rep-boundary geometric features already computed by `rep_metrics`/`values_for_rep` (e.g. `peak_height`, `lockout_pct`) against the chosen movement's defining condition; if the rep's defining landmark never reaches the movement's threshold, set `rep["measured"]=False` + `rep["reason"]`.
- **Acceptance Criteria**: a synthetic mixed clip (2 pull-ups then 2 muscle-ups in one take) — assert reps whose shoulders never cross `OVER_BAR` are flagged `unmeasured` and do not enter the `muscle_up` score; the clip headline remains the dominant movement. Add to `tests/test_server_payload.py`.

#### Task 4.3: Replace ad-hoc confidences with a margin-to-threshold statement
- **Location**: `barra/classify.py:426-564`, `Classification.confidence`, `label()`/`HUMAN`.
- **Description**: Keep a number for the UI but relabel it. Compute confidence as a bounded margin: `min(1, max(0, (v - t) / (hi - t)))` where `t` is the gate and `hi` a set-of-scale reference, and change the docstring/field name to `certainty_vs_gate` so it is never mistaken for a probability.
- **Estimated Tokens**: 120
- **Dependencies**: none
- **Steps**: rename `confidence` semantics (keep the key for backward-compat, add `"certainty": "margin-to-threshold"`), adjust `certain >= 0.65` to a margin threshold, update the reason strings.
- **Acceptance Criteria**: unit test asserting the value is derived deterministically from `(peak, OVER_BAR, scale)` and is bounded in [0,1]; no NaN path from an unmeasured feature (three-valued logic preserved).

## Testing Strategy
- **Regression (existing):** `python -m unittest discover -s tests` (137 invariant tests) must stay green at each phase; `tests/test_core.py`, `test_rescue.py`, `test_movements.py`, `test_classify_quality.py`, `test_server_payload.py`, `test_validate_quality.py` are the anchors.
- **Threshold harmonisation (1.2):** an import-consistency unit test asserts `faults.py`, `faults_taxonomy.py`, `quality.py`, `config.py` all agree; a `process.py` payload test asserts `rep_faults` can be reproduced from payload numerics with no regex.
- **Reword-invariance (1.2):** change a `why` string, assert fault set identical.
- **Camera-motion nulls (2.1):** synthetic azimuth-ramp + noise → 0 invented reps; clean rotating set → real reps preserved.
- **Slow-rep boundary (2.2):** 12 s negative kept + flagged boundary.
- **View-gating (3.1):** frontal `knee_valgus` fires, sagittal same-error set yields `unmeasured`; uses existing `synthetic.py` azimuth mechanism and `scripts/viewpoint_sensitivity.py`.
- **Deliberate-fault per exercise (4.1):** reuse `synthetic.py:SETS` squat errors + newly induced push-up/dip errors; assert target fault fires and no mis-applied muscle-up fault does.
- **Selftest harness (no labels, by design):** `barra selftest` + `barra all` on synthetic data as a pipeline integrity gate (never as correctness evidence), per `synthetic.py`'s own docstring.
- **Falsifiability per QUALITY.md/CORE.md:** every new failure type states (a) the signal measured, (b) the threshold, (c) the view it requires, (d) that a synthetic deliberate-fault clip must trigger it and a clean clip must not — and the harness reports `INCONCLUSIVE` for any check with no clip rather than `PASS`.

## Risks
- **Self-critique 1 (weakness in the plan):** Phase 2's "relative-articulation" active criterion is a second hand-tuned gate on top of `ANCHOR_FIXED`, and I have not validated that camera translation (subject walking toward the camera) is distinguishable from camera rotation by a relative-motion ratio alone. `anchor_travel / body_travel` can be ~1 for a subject *walking* toward the camera (both anchor and body move together), which could re-admit the exact "person walking around the rig" rejection that `MAX_BAR_TRAVEL` exists to catch — meaning a fix that recovers 0011 could regress 0014. **Mitigation:** keep `MAX_BAR_TRAVEL` as an absolute ceiling (never relax it), add the walk-toward-camera synthetic null (translate the whole projected body with noise; assert 0 reps), and gate the ratio criterion on the anchor-vs-body *angle/direction* (rigid-body coupling) rather than magnitude alone. If that fails, accept the tradeoff and report 0011 as unmeasurable rather than risk 0014.
- **Self-critique 2 (weakness in the plan):** Phase 3's view gating depends on `viewpoint.py`'s self-calibrated azimuth, which `viewpoint.py` itself documents is biased upward when the subject has never been filmed near-frontally (`R_true` underestimated). Gating PLANAR faults on a misbinned azimuth would suppress real faults as "unmeasured" (false-negative) or, worse, pass a frontal fault in a mis-binned sagittal clip. **Mitigation:** emit a fault only when the view is `knowable` (camera_side agreement ≥ 0.70 and the calibration inside `ANATOMICAL_PRIOR_RANGE`), otherwise classify all PLANAR faults as `unmeasured`; require the `declared_bin`/`view` from `sessions.csv` (ingest.py:89) to override estimation, and make the harness run both estimated and declared to expose disagreement.
- **Both risks are intentional and inventory-carrying:** the plan's fixes are only as sound as the gates above; where a gate cannot be proven, the honest output is `unmeasured`, never a confident number — consistent with the fixed philosophy.

## Rollback Plan
- Each task is a localised file change; revert with `git checkout -- <file>` (or `git revert <commit>` per task). No schema/migration is introduced: `barra/config.py` additions are additive, `faults.py`/`faults_taxonomy.py` keep their existing public function signatures, `server/process.py` adds keys without removing existing ones, and `Cues.kt` falls back to current constants when the `thresholds` field is absent. If a phase is reverted, the payload's extra keys (`thresholds`, `unmeasurable_faults`, `unmeasured` flags) are simply ignored by a client that reads only known fields, so a partial rollback cannot poison the app.

## Edge Cases
- **Camera leaves frame / hands above top edge (0018):** classification must remain `unknown`-with-reason; Phase 1/2 must not cause a re-derivation of `out/reps.csv` — already user-editable and never re-derived.
- **NaN / missing measurement:** every new failure threshold uses the existing three-valued logic (`_f` + `_np_isfinite`), so a never-measured quantity can never satisfy a condition; Phase 4's `unmeasurable_faults` must be separate from `failures` to preserve this.
- **Three-valued fault absent ≠ clean:** a fault not emitted from an unsuitable view goes to `unmeasured`, not to the "measured clean" bucket, so the PR's existing `improvementLines` ("the set measured clean") is not shown for an unviewable set.
- **Frontal-plane errors under a sagittal camera:** per FINDINGS.md #1, `knee_valgus`/`lateral_shift` are ~1.2× noise from the side — the fix must default them to `unmeasured`, not to a clean verdict.
- **Multiple sessions/sets in one clip and mixed movements:** Phase 4.2 flags inconsistent per-rep windows; a wholly mixed clip stays "unmeasured / flagged" rather than force-binned.
- **Slow/asymmetric big-ring reps:** `max_half_rep_s` cap now surfaces a boundary marker; a rep wider than the cap is kept but flagged, never silently mis-measured into the history.
- **Camera pans within a set:** the relative-articulation active test (2.1) is designed to keep the real reps; if the pan is severe enough that anchor-vs-body coupling decays, the set is reported `unmeasured` with the pan reason, never invented or miscounted.

## Open Questions
- **Does Phase 2's relative-articulation active gate hold under handheld *translation*,** or only rotation? This needs a walk-toward-camera synthetic null before the ratio gate is trusted; deferring the `MIN_BIN_SHARE`/anchor ceiling decision until that test is written is intentional.
- **Are the commonly-quoted "gaze", "wrist loading", "false grip", "prerequisites", "training fatigue" errors ever in scope?** They are not measurable from COCO-17 keypoints; the plan inventories them as `unmeasurable_faults`, but whether the app should *show* them as unmeasured cues (better honesty) or drop them (less noise) is a product call the spec does not resolve.
- **Should Phase 2's detrend be an option** (`--detrend none|median`) like the existing `--scale per_frame|per_set`, so the default "rotation is not removed" decision stays testable rather than silently changed? Recommend yes, to keep the change falsifiable and reversible.
- **Threshold harmonisation client (Cues.kt) reads server thresholds** — but the server historically also runs the score; if a rep is scored server-side from `quality.py`, is the phone *allowed* to re-derive faults from payload numerics, or is fault-flagging strictly server-authenticated? The plan assumes the latter (phone renders, never decides), which should be confirmed against the app's data model before Phase 1 ships to the phone.