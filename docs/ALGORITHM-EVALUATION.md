# Algorithm Evaluation: Three Stages of the Barra Measurement Core

## Executive Summary

Three algorithm stages were audited against their source code, the documented design rationale (docs/CORE.md, docs/FINDINGS.md, docs/QUALITY.md), the test harness (137 invariant tests), the fault validation harness (barra/validate_faults.py), the synthetic fixture generator (barra/synthetic.py), the Android mirrored thresholds (app/src/Cues.kt), and the literature coverage gaps (tecnicas-errores-comunes.md). Five severity-1 findings, five severity-2 findings, and four severity-3 findings were identified. Every finding names the file and mechanism at fault. Every proposed improvement states how it would be validated WITHOUT ground-truth labels (synthetic invariant tests, deliberate-fault clips, null-distribution checks, the existing selftest harness).

Severity definitions:
- **S1 — Critical**: Causes wrong output (missed reps, misclassification, spurious faults) that silently enters the athlete's data.
- **S2 — Significant**: Reduces measurement coverage or reliability in common but recoverable conditions.
- **S3 — Moderate**: Friction, technical debt, or edge cases that affect less common paths.

---

# STAGE 1 — Rep Detection / Segmentation

## Finding 1.1: Camera rotation produces zero-count clips for sagittal-plane movements (S1)

**File**: `barra/ingest.py`, lines 225–401 (`segment_reps_verbose`), specifically the `find_peaks` + amplitude-gate logic at lines 292, 300–303, 314, 317–396.
**Mechanism**: When the camera rotates through the set (clip 0011, knee raise), the tracking signal becomes a superposition of the real movement (knees-to-bar excursion) and the camera-induced rotation of the entire skeleton. The amplitude (p97 − p15 over active frames) stays small because both the peak and rest shift with the rotation. The prominence threshold (`0.35 × amplitude` at line 292) is therefore low, but the peak itself rarely reaches `0.6 × amplitude` (line 319) because the signal is noise-dominated. No turnaround clears the gate, and the function returns empty.

**Root cause**: The tracking signal does not separate rotation from the movement axis. The project's design choice (docs/CORE.md: "rotation is not removed") is correct for the deviation score (torso lean is signal), but here it means any azimuth change within the clip injects low-frequency noise that destroys the peak-finding geometry.

**Validation strategy**:
- **Synthetic invariant test**: In `barra/synthetic.py`, add a `camera_rotation_deg` parameter that applies a per-frame azimuth offset to the 3D→2D projection. Generate a set of N=3 knee raises with rotation angles of 0°, 5°, 10°, 15°, 20°. The test asserts that the segmenter recovers all 3 reps at 0° and degrades gracefully (not zero-count, but with reduced count) as rotation increases. The degradation curve is the validation: we expect a soft cliff at ~10°, which identifies the failure boundary.
- **Deliberate-fault clip**: Inject a known sinusoidal rotation profile into an existing synthetic set and verify that the count drops and the rejection reasons match the expected failure mode.

**Fix proposal**: Compute a rotation-invariant envelope for the signal before peak-finding. The envelope is `max(local_min, local_max)` or a rolling-window detrending that removes the low-frequency azimuth component while preserving the high-frequency rep turnarounds. The detrending window should be tied to `movement.min_rep_s` (so a 0.7s window for knee raise removes rotation but not the rep). This adds one O(N) rolling-window pass per movement and is CPU-bounded.

## Finding 1.2: Rescue pass has no coverage test (S2)

**File**: `barra/ingest.py`, lines 496–604 (`_rescue_candidates`), line 607–632 (`rescue_reps`).
**Mechanism**: `_rescue_candidates` is the last-resort segmenter. It lowers the prominence threshold from 0.35× to 0.15×, uses MAD-based gradient validation, and requires 60% observed frames. The test suite has `tests/test_rescue.py` (80 lines), but it tests only idealised sine-wave signals (`_humps` helper). Real pose signals have bursty confidence, occlusion gaps, and anchor drift that sine waves don't reproduce. The rescue pass acceptance rate on real clips (documented in CORE.md: clips 0010, 0012 undercounted) cannot be verified by the current test harness.

**Validation strategy**:
- **Synthetic with realistic noise**: Extend `barra/synthetic.py` to produce pose-signal-level noise: confidence bursts that drop to 0 for 3–5 consecutive frames (simulating occlusion), random 2–4 pixel landmark jitter that translates to 0.05–0.10 torso-length signal jitter, and slow anchor drift (0.02 torso-lengths/frame, simulating camera shake). Run the rescue pass on N=20 synthetic sets with known rep boundaries and report recall/precision. The test must pass recall ≥ 0.80 at the standard pass and rescue pass combined.
- **Null-distribution check**: Run the rescue pass on N=20 synthetic "standing" clips (no movement, just pose noise). Zero candidates must be accepted. This is already asserted in `test_rescue.py:test_pure_noise_finds_nothing` but not under pose-level noise.

**Fix proposal**: Build a synthetic signal generator that operates at the pose-signal level (not the raw keypoint level) and produces the three noise types above. This generator plugs into the existing `_rescue_candidates` test without modifying the segmenter. Add recall/precision benchmarks as part of the invariant test suite.

## Finding 1.3: Anchor travel threshold `MAX_BAR_TRAVEL=0.80` is duplicated and untested as a group (S2)

**File**: `barra/movements.py` line 235 (`MAX_BAR_TRAVEL = 0.80`), `barra/classify.py` line 49 (`ANCHOR_FIXED = 0.80`).
**Mechanism**: The value 0.80 appears in two places with slightly different semantics: one gates the per-rep anchor travel in the segmenter (line 365–376), the other gates the windowed wrist travel in the classifier (classify.py line 385). They happen to match today, but there is no test that asserts this invariant. A future change to one without the other silently desynchronises segmentation from classification.

**Validation strategy**:
- **Invariant test**: Add `tests/test_anchor_consistency.py` that reads both constants and asserts equality. The test runs on import, so it fails at startup if they diverge.
- **Existing harness**: No new harness work needed beyond the import-time assertion.

**Fix proposal**: Define `ANCHOR_FIXED` in a single module (e.g., `barra/config.py`) and import it from both `movements.py` and `classify.py`. The constant is already a candidate for centralisation alongside all the other magic numbers (see Finding 2.1).

---

# STAGE 2 — Movement Classification

## Finding 2.1: No per-rep movement classification (S1)

**File**: `barra/classify.py`, `server/process.py` lines 376–391.
**Mechanism**: `classify()` runs once per clip and returns a single exercise label. If a clip contains two different exercises (e.g., the athlete films a set of pull-ups, then switches to knee raises), the entire clip is measured under the wrong exercise. The rep segmenter then applies the wrong movement profile (wrong signal, wrong origin), producing meaningless metrics downstream. The classifier's confidence score (0.70–0.98) is ad-hoc with no calibration against a held-out set — it is a heuristic distance from the decision boundary, not a probability.

**Validation strategy**:
- **Synthetic mixed clip**: In `barra/synthetic.py`, add a `make_mixed_set` function that concatenates N1 reps of exercise A with N2 reps of exercise B into a single keypoint sequence. Run `classify()` on the concatenated clip and assert that it returns one of the two exercises (not a third). This doesn't fix the limitation but quantifies the failure mode.
- **Deliberate-fault test**: Verify that a mixed pull-up + knee-raise clip is never classified as dip or push-up (impossible class). The failure should be "unknown" or one of the two actual classes.

**Fix proposal**: This is a scope limitation, not a bug per se. The project's contract is one-exercise-per-clip. The fix is to make the contract explicit in the server payload (add `single_exercise_asserted=True` or `None`) and document that mixed clips are unmeasurable. No code change needed; update the docs and the app's error messaging.

## Finding 2.2: Squat has no dedicated fault taxonomy (S2)

**File**: `barra/faults_taxonomy.py` lines 283–296. `CLASSIFIERS` dict only has `front_lever`, `planche`, `muscle_up`, `pistol_squat`. Lines 293–294 route `pull_up`, `dip`, `push_up`, and `squat` to `muscle_up(values)` — the generic five-fault set.
**Mechanism**: Squat is measured by the system (it's one of the six `MEASURED` skills in `barra/skills.py`), has its own movement profile in `movements.py`, but shares the bar-movement fault set with pull-up/dip/push-up. The literature in `tecnicas-errores-comunes.md` lists five common squat errors: knee valgus, insufficient depth, heel raise, lumbar rounding (butt wink), and gaze. Only insufficient depth is already covered by the `range` component. The other four are completely unmeasured.

**Validation strategy**:
- **Synthetic fault clips**: Extend `barra/synthetic.py`'s `make_rep` with error types `knee_valgus` (already exists), `butt_wink` (add a lumbar flexion term to the torso angle at depth), `heel_raise` (raise the ankle y relative to the hip), and `gaze_up` (raise the nose y). Run the full pipeline and assert that the new classifiers fire on the induced error and stay quiet on clean reps.
- **Deliberate-fault clips**: Record N=5 reps of each induced error with a known camera angle and validate against the new thresholds.

**Fix proposal**: Add a `squat(values)` classifier in `faults_taxonomy.py` that checks:
1. `knee_valgus` from `pistol_geometry()` applied to the squat's standing-side leg (reuses existing code, already computed for pistol).
2. `butt_wink` — detect lumbar flexion at bottom depth by checking the angle at the spine joints (nose-to-hip line deviates from shoulder-to-hip line by > 15° at the rep bottom).
3. `heel_raise` — the ankle-y does not reach ground level at the squat bottom (requires the ankle to be at or below the lowest ankle position in the clip by more than 0.10 torso-lengths).
4. `gaze_up` — the nose y rises above the shoulder y at the top of the rep (> 0.05 torso-lengths).

These are all geometric, threshold-based, and independent of camera azimuth (vertical measures). Validation: synthetic clips with induced errors + null-distribution check (clean reps get zero faults).

## Finding 2.3: Push-up fault coverage is empty (S2)

**File**: `barra/faults_taxonomy.py`, `tecnicas-errores-comunes.md` (push-up row).
**Mechanism**: Push-up shares the bar-movement fault set (muscle_up's five faults). But the five most-cited push-up errors per the literature are: sagging hips, elbows flared 90°, half range, head position, wrist loading. Of these:
- Half range → covered by `range` component (already works).
- Sagging hips → not measured. The body-line angle from shoulder-to-hip is computed but never exposed as a push-up-specific fault.
- Elbows flared 90° → not measurable with COCO-17 (elbow x-coordinate relative to shoulder is a planar measure, requires frontal view).
- Head position → nose height relative to spine line could approximate this.
- Wrist loading → not measurable (no hand geometry beyond wrist position).

**Validation strategy**:
- **Synthetic sagging**: In `barra/synthetic.py`, add a `sagging_hips` error that shifts the hip y upward by 0.15 torso-lengths at mid-rep. Run the full pipeline and verify the new classifier fires.
- **Null-distribution**: Clean push-up synthetic sets must produce zero sagging faults.

**Fix proposal**: Add a `push_up(values, kp, start, turn, end)` classifier in `faults_taxonomy.py` that:
1. Checks `sagging_hips`: at the midpoint of the rep, the hip is more than 0.12 torso-lengths above the shoulder (shoulder is below hip in push-up geometry). This uses the body-line geometry already computed in `holds.py`'s `_hold_metrics`.
2. Reports `head_position`: nose_y relative to shoulder_y at rep bottom > 0.05 torso.
3. Reuses the existing `range` fault for half-range.

Validation: synthetic invariant test + deliberate-fault clips.

## Finding 2.4: Dip fault coverage gap — bounce and scapula (S2)

**File**: `barra/faults_taxonomy.py`, `tecnicas-errores-comunes.md` (dip row).
**Mechanism**: Dip shares the bar-movement fault set. Literature cites: too deep, bounce at bottom, shrugged scapulae, inconsistent torso angle, loading weight too soon.
- Too deep → could be measured by checking if the shoulder drops below the wrist by > 0.30 torso-lengths (exceeds arm reach).
- Bounce at bottom → the signal's second derivative at the bottom is negative and large (the rep accelerates upward immediately after reaching bottom, less than 0.2s pause). Requires the signal's derivative, which is available from the cleaned signal.
- Scapulae → not measurable with COCO-17 (no shoulder-blade landmarks).
- Torso angle inconsistency → the shoulder_tilt variance across the rep exceeds a threshold. This is already computed in `metrics.py` line 227 (`shoulder_tilt`) but never exposed as a dip fault.

**Fix proposal**: Add a `dip(values, signal, start, turn, end)` classifier:
1. `too_deep`: peak_height < -0.30 (shoulder below wrist).
2. `bounce_at_bottom`: signal derivative at turnaround < -threshold AND transition_s < 0.15s.
3. `inconsistent_torso`: `shoulder_asymmetry` at bottom > 0.10 torso-lengths.

Validation: synthetic clips with induced bounce (signal second derivative test) + clean dip null check.

## Finding 2.5: Confidence scores are uncalibrated heuristics (S3)

**File**: `barra/classify.py`, lines 426–564.
**Mechanism**: Confidence is set as `0.70 + 0.28 * margin` (muscle_up), `0.70 + 0.25 * margin` (pull_up), `0.78` (dip, push_up, squat), `0.80` (knee_raise), `0.72` (front_lever, planche), `0.74` (pistol). These are linear functions of distance from the decision boundary, not calibrated probabilities. A confidence of 0.98 means the shoulders are 0.40 torso-lengths above the bar — well clear of any realistic pull-up — but the number itself has no statistical meaning. A confidence of 0.78 for dip/push_up/squat has the same value regardless of whether the classification was edge-case or unambiguous.

**Validation strategy**:
- **Calibration test**: Generate N=100 synthetic clips per exercise spanning the full clearance range from −0.50 to +1.00 torso-lengths. Bin by confidence (0.70–0.75, 0.75–0.80, 0.80–0.85, 0.85–0.90, 0.90–0.95, 0.95–1.00). In each bin, compute the fraction correctly classified. These fractions should approximate the confidence values (e.g., clips binned at 0.85 should be correct ~85% of the time). Currently they will not be.

**Fix proposal**: Option A (preferred, no ML): Replace heuristic confidence with a simple decision-boundary distance metric: `distance = |measured_value - threshold| / typical_within-class_spread`. Report distance as a number and let the UI decide what "high confidence" means. This is still deterministic, geometric, and requires no training data. Option B: Add a calibration step that maps the current confidence values to observed correctness rates on synthetic data, producing a lookup table. This is still static and doesn't require labels, but it makes the confidence honest about what it measures.

---

# STAGE 3 — Fault / Error Classification

## Finding 3.1: faults.py uses regex on human-readable strings (S1)

**File**: `barra/faults.py`, lines 35–37 and 49–58.
**Mechanism**: The five bar faults (`momentum`, `lockout`, `dead hang`, `control`, `stall`) are detected by parsing English strings from the `components` list in the server payload. For example, `range` component's `why` field contains `"lockout 82% of full"` and `_LOCKOUT_RE = re.compile(r"lockout (\d+)% of full")` extracts the number. This is fragile: if the quality module's wording changes (even a whitespace change), the regex silently stops matching and the fault disappears without any error. The same pattern exists in `app/src/main/java/com/barrapp/Cues.kt` lines 26–32, duplicating the regex on the Android side.

**Validation strategy**:
- **Deliberate-fault test**: Run the fault extraction on a known-good payload (from `barra/process.py`'s analysis of a clip with a known lockout fault). Then mutate the `why` string slightly (add trailing space, change "lockout" to "LOCKOUT", remove the number) and assert that the fault detection either still fires or raises an error. Currently it does neither — it silently produces an empty list.
- **Null-distribution check**: Run on N=20 clean synthetic reps. Zero lockout/hang faults must fire.

**Fix proposal**: Replace the string-parsing pattern with structured data. Instead of embedding numbers in human-readable strings, the quality module (`barra/quality.py`) should emit a structured `range_faults` dict with numeric fields (`lockout_pct`, `hang_pct`) that both Python and Kotlin read directly. This removes the regex layer entirely. The Android code (`Cues.kt`) would read `rep.components[i].range.lockoutPct` instead of parsing `why`. Validation: the existing `test_server_payload.py` must assert that these structured fields exist and have numeric types.

## Finding 3.2: ~20 magic constants duplicated across barra/config.py, barra/faults.py, barra/faults_taxonomy.py, and Cues.kt (S1)

**File**: `barra/config.py` (FLAG_PERCENTILE, MAX_ACCEPTABLE_FPR, etc.), `barra/faults.py` (SWING_TORSO=0.4, LOCKOUT_MIN=0.85, HANG_MIN=0.75), `barra/faults_taxonomy.py` (same SWING_TORSO, LOCKOUT_MIN, HANG_MIN plus HORIZONTAL=70.0, PIKE=150.0, PISTOL_DEPTH=0.55, PISTOL_VALGUS=0.12, CONTROLLED_TEMPO=0.70, STALL_RATE=0.20), `barra/classify.py` (ANCHOR_FIXED=0.80, ARTICULATION=0.20, BELOW_HANDS_DIP=0.25, KNEES_UP=0.10, HOLD_BAND=0.20, HOLD_FRAC=0.55, OVER_BAR=0.12), `barra/quality.py` (CONTROLLED_TEMPO=0.70, STALL_RATE=0.20, STRONG=73, SOLID=47, SHAKY=20), `barra/metrics.py` (PLAUSIBILITY_MARGIN=1.20, REACH_BAND=(0.60, 1.90)), `app/src/main/java/com/barrapp/Cues.kt` (the same thresholds repeated in Kotlin).

**Mechanism**: Thresholds are defined in the file where they are first needed, not in a single source of truth. `SWING_TORSO` appears in `faults.py` (line 31), `faults_taxonomy.py` (line 36), and implicitly in the Android code (line 22: `if (it.value > 0.4)`). `CONTROLLED_TEMPO` is in `faults_taxonomy.py` (line 39) and `quality.py` (line 51) with value 0.70 in both. If one is changed and the other is not, the Python pipeline and the Android app produce contradictory results for the same data. The Android code also embeds the regex patterns from `faults.py` (lines 27–31 in Cues.kt), creating a second axis of duplication.

**Validation strategy**:
- **Invariant test**: Define a set of "canonical thresholds" in `barra/config.py` and add a test that imports every other module and asserts that the local constants match the canonical ones. If any module defines its own copy with a different value, the test fails at import time.
- **Deliberate-fault test**: Run the full pipeline on a clip where a fault is induced, then verify that the Android-side fault extraction (unit test in `app/src/`) on the same payload produces identical fault lists.

**Fix proposal**: Centralise all thresholds into `barra/config.py` (or a new `barra/thresholds.py`). Import from there in all consumer modules. In Kotlin, generate the threshold values from a shared JSON or proto file, or use a build script that copies values from a single source of truth. The invariant test suite gains one new test module that validates cross-language consistency.

## Finding 3.3: PLANAR metrics applied without view gating (S1)

**File**: `barra/faults_taxonomy.py`, `pistol_geometry()` function (lines 197–242); `barra/metrics.py`, `METRIC_SPEC` (lines 37–50).
**Mechanism**: `pistol_geometry()` computes `knee_valgus` (lateral knee deviation), `torso_lean` (backwards lean), and `heel_raise` (ankle height). These are all PLANAR quantities that require a consistent frontal or posterior camera angle. The function is called from `server/process.py` line 507 when `movement.name == "pistol_squat"`, but there is no check that the viewpoint bin is appropriate for PLANAR measurements. When the camera is side-on (SAGITTAL bin), the lateral knee deviation reads as if the knee were collapsed even when it is not, because the knee's x-coordinate is dominated by the camera's azimuth. `docs/FINDINGS.md` (Finding 1) documents that a 10° camera azimuth move displaces the normalised skeleton more than any of 5 deliberately induced technique errors.

**Validation strategy**:
- **Synthetic invariant test**: Generate N=10 pistol squat synthetic sets at azimuth 0° (pure sagittal, side-on) and N=10 at azimuth 85° (frontal). Induce knee valgus in exactly 5 of the sagittal sets. The PLANAR faults must be UNKNOWN (not fired, not false-positive) in the sagittal sets and correctly fire in the frontal sets.
- **Null-distribution check**: Run `pistol_geometry()` on N=20 clean pistol sets at azimuth 0°. All PLANAR fault values must be reported as NaN or UNKNOWN.

**Fix proposal**: Gate PLANAR fault detection on the viewpoint bin. In `server/process.py`, before calling `pistol_geometry()`, check that the rep's `declared_bin` is in `{"FRONTAL", "OBLIQUE"}` (not SAGITTAL or UNKNOWN). If the bin is inappropriate, set the PLANAR fault values to NaN and report the failure reason in the trace. The fault classifier must treat NaN as "not measured" (not "not faulty") — this is already the project's three-valued logic principle but is not enforced in the PLANAR path.

## Finding 3.4: Fault validation harness lacks synthetic coverage (S3)

**File**: `barra/validate_faults.py`, `data/calisthenics/` corpus.
**Mechanism**: The fault validation harness (`barra/validate_faults.py`) operates on a corpus of real clips (`data/calisthenics/`) with human-labelled `expected` and `forbidden` faults. The harness works well for the clips that exist in the corpus but cannot cover faults that have no labelled clips yet. The harness reports "INCONCLUSIVE" for any fault with zero labelled clips, which is honest but doesn't help the developer know whether a new fault detector works. There is no synthetic fallback: if you add a new fault detector, you cannot validate it without waiting for the corpus to grow.

**Validation strategy**:
- **Synthetic fault injection**: In `barra/synthetic.py`, add error-induction parameters for each fault (momentum/swing, lockout, dead hang, control/ tempo, stall). Run the fault extraction pipeline on N=20 clean and N=20 error-inducted synthetic reps. The harness asserts that faults fire on error clips and stay quiet on clean ones. This is the existing selftest harness extended to the fault layer.
- **Deliberate-fault clips**: For each new fault detector, generate synthetic clips with known error magnitudes spanning the full threshold boundary (just below, at, and just above). Verify the detection curve.

**Fix proposal**: Add `barra/validate_faults_synthetic.py` (or extend `barra/synthetic.py`) that runs the full fault extraction pipeline on synthetic clips with induced errors and checks detection rates. This module is part of the invariant test suite and runs with `python -m unittest discover -s tests`. It does not require any real footage.

---

# Prioritised Improvement Plan

## Phase 1: Fix Silent Failures (2–3 weeks)

### 1.1: Centralise thresholds
- **Location**: `barra/config.py`, `barra/faults.py`, `barra/faults_taxonomy.py`, `barra/classify.py`, `barra/quality.py`, `barra/metrics.py`, `app/src/main/java/com/barrapp/Cues.kt`
- **What**: Move all magic constants to `barra/config.py`. Create a `Thresholds` dataclass. Import everywhere.
- **Test**: Invariant test `tests/test_thresholds_consistent.py` asserts that all modules' local copies match `config.py` values. Android side: add unit test `CuesThresholdTest` that reads the same thresholds from a shared JSON and verifies equality with Python.
- **Why first**: This is a single structural change that prevents future drift and unblocks the other fixes (they all require knowing the current value of a constant).

### 1.2: Replace regex-based fault extraction with structured data
- **Location**: `barra/quality.py` (range_component, smoothness_component), `barra/faults.py`, `server/process.py`, `app/src/main/java/com/barrapp/Cues.kt`
- **What**: Instead of embedding numbers in `why` strings, emit structured fields. `range_component` returns `{"lockout_pct": 82.0, "hang_pct": 71.0, "why": "..."}`. `faults.py` reads from the dict, not the string. Android reads from the same JSON structure.
- **Test**: `tests/test_fault_structure.py` asserts that every fault can be extracted from the structured fields and that the regex layer is gone. `test_server_payload.py` asserts the structured fields exist in the payload schema.
- **Why second**: This fixes the most brittle coupling in the system (regex on strings).

### 1.3: Add rotation-tolerant signal processing for Stage 1
- **Location**: `barra/ingest.py`, `barra/movements.py`, `barra/synthetic.py`
- **What**: Add a rolling-window detrending pass before `find_peaks` in `segment_reps_verbose`. The window is tied to `movement.min_rep_s * 2` (removes rotation but not rep turnarounds).
- **Test**: Synthetic test in `tests/test_rotation_tolerance.py`: generate knee-raise and pull-up sets with camera rotation of 0°–20°. Assert that the segmenter recovers ≥ 80% of reps at 10° rotation and that the degradation curve is smooth (no step-function drop from zero to full count).
- **Why second**: This directly addresses the most visible user complaint (zero-count clips with rotating camera).

## Phase 2: Expand Taxonomy Coverage (2–3 weeks)

### 2.1: Add squat fault classifier
- **Location**: `barra/faults_taxonomy.py` — new `squat(values)` function.
- **What**: Faults: knee_valgus (reuses `pistol_geometry`), butt_wink (spine flexion at bottom), heel_raise (ankle elevation at bottom), gaze_up (nose above shoulder).
- **Test**: Synthetic errors in `barra/synthetic.py`: add `butt_wink`, `heel_raise`, `gaze_up` error types. `tests/test_squat_faults.py` validates detection on induced clips and zero faults on clean clips.
- **Why first in Phase 2**: Squat is the most common exercise and has the widest coverage gap per `tecnicas-errores-comunes.md`.

### 2.2: Add push-up fault classifier
- **Location**: `barra/faults_taxonomy.py` — new `push_up(values, kp, start, turn, end)` function.
- **What**: Faults: sagging_hips (mid-rep hip above shoulder by > 0.12 torso), head_position (nose above shoulder at bottom by > 0.05 torso).
- **Test**: Synthetic `sagging_hips` error + clean push-up null check.
- **Why second**: Push-up is the second most common exercise.

### 2.3: Add dip fault classifier
- **Location**: `barra/faults_taxonomy.py` — new `dip(values, signal, start, turn, end)` function.
- **What**: Faults: too_deep (shoulder below wrist), bounce_at_bottom (acceleration at turnaround), inconsistent_torso (shoulder_asymmetry > 0.10).
- **Test**: Synthetic `bounce` signal pattern + clean dip null check.
- **Why third**: Dip is less common than squat/push-up but the faults are measurable from the existing signal.

### 2.4: Gate PLANAR metrics on viewpoint bin
- **Location**: `server/process.py` line 507 (where `pistol_geometry` is called), `barra/faults_taxonomy.py` (defensive NaN in PLANAR fields).
- **What**: Before calling `pistol_geometry()` or applying PLANAR faults, check the viewpoint bin. If SAGITTAL or UNKNOWN, set PLANAR values to NaN and record the reason in the trace.
- **Test**: `tests/test_planar_gating.py` runs pistol synthetic sets at 0° and 85° azimuth and asserts PLANAR faults are UNKNOWN at 0° and detectable at 85°.

## Phase 3: Improve Reliability & Testing (1–2 weeks)

### 3.1: Synthetic signal-level noise test for rescue pass
- **Location**: `barra/synthetic.py`, `tests/test_rescue.py`
- **What**: Add pose-signal-level noise to synthetic sets: confidence bursts, landmark jitter, anchor drift. Extend `_rescue_candidates` test to use these noisier signals.
- **Test**: Recall/precision benchmarks on N=20 synthetic sets under noise.

### 3.2: Fault detection synthetic harness
- **Location**: New file `barra/validate_faults_synthetic.py`
- **What**: Run full fault extraction on synthetic clean and error-inducted reps. Check that faults fire correctly and stay quiet on clean data.
- **Test**: Part of the invariant test suite. `python -m unittest discover -s tests` must pass.

### 3.3: Confidence calibration (decision-boundary distance)
- **Location**: `barra/classify.py`
- **What**: Replace ad-hoc confidence values with a geometric distance metric. `confidence = clip(0, 1, distance / expected_spread)`. The expected spread is derived from within-class variation on synthetic data.
- **Test**: Calibration test on N=100 synthetic clips per exercise spanning the full range. Verify that higher-confidence clips are more likely correct.

---

## Risk Summary

1. **Self-critique 1**: The proposed rotation-tolerant signal processing (1.3) assumes that rotation is a low-frequency component separable from the rep signal by a rolling-window detrend. This is true for smooth rotation but may fail if the camera rotates rapidly (e.g., the operator spins the phone 90° mid-set). The detrend window is tied to `movement.min_rep_s * 2`, which for pull-ups is 1.4s — if the rotation happens within 0.7s, it could be partially removed along with the rep turnarounds. Mitigation: the detrend should be applied only if the signal's power spectral density shows a peak in the low-frequency band; otherwise, fall back to the current behaviour. Test: synthetic clips with step-function rotations (instant 90° shifts) to verify no false positives.

2. **Self-critique 2**: The threshold centralisation (1.1) may break existing user expectations if some thresholds were intentionally modified by users who edit the source files. The `config.py` already has a fingerprinting mechanism for its own constants (`validate` checks that `config.py` hasn't changed), but extending this to all threshold files means any user who edits `faults.py` thresholds will see a test failure at startup. Mitigation: the invariant test should compare against the canonical values OR the local values if a `THRESHOLDS_OVERRIDE=1` env var is set. This preserves the opt-out for power users.

3. **Self-critique 3**: Adding squat/push-up/dip fault classifiers (2.1–2.3) expands the output surface of the pipeline. The Android app (`Cues.kt`) already has a fixed `CUES` map with 5 entries. Adding new fault types means the UI layer needs to be updated too, or the new faults will be measured in Python but silently discarded on the phone. This is a cross-platform coordination problem that the threshold centralisation (1.1) partially addresses but doesn't fully solve. Mitigation: the Android fault list should be a lookup table keyed by fault name, so adding a new fault to the Python taxonomy automatically produces a cue if the Android CUES map has an entry for it, and silently ignores it if not.

4. **Self-critique 4**: The PLANAR-gating fix (2.4) may reduce fault coverage for pistol squats if most users film from the side (which is the recommended angle for most bar movements). This means many pistol squats will have all PLANAR faults reported as UNKNOWN, which is honest but may frustrate users who want feedback. Mitigation: the error message should explicitly say "knee valgus cannot be measured from this angle — film from the front for this check" rather than silently suppressing the faults. The squat classifier (2.1) does not have this problem because knee_valgus for squats can be measured from any angle if the feet are visible (it's a lateral deviation of the knee from the hip-ankle line, which is approximately frontal-plane even from oblique angles).

---

## Rollback Plan

All changes are additive (new functions, new test files, new structured fields). Rollback is:
1. Revert the git commit.
2. No migration needed: the structured payload fields are optional — the Python parser falls back to regex if the structured field is absent (for N=1 transition period), and the Android app falls back to parsing `why` strings if the structured field is absent.
3. The invariant test that checks threshold consistency can be disabled by removing it from the test suite without affecting runtime code.

---

## Edge Cases

1. **Mixed-exercise clips**: A clip containing pull-ups then knee raises will be classified as one exercise and the wrong movement profile will be applied to the second half. This is a known limitation of the "one exercise per clip" contract. The fix is to make the contract explicit in the output (not a code change).

2. **Side-on squat**: A squat filmed from the side (recommended) cannot have PLANAR faults measured (knee valgus, butt wink lateral component). The squat classifier must fall back to the measurable faults (depth via range component) and report PLANAR faults as UNKNOWN.

3. **Very short clips**: Clips shorter than `movement.min_rep_s` for any rep are not tested by the current codebase. If the segmenter produces a rep from a sub-minimum clip, the metrics and fault classifiers will run on it but the results are unreliable. The segmenter's `min_dist` parameter (line 291) should reject reps shorter than `movement.min_rep_s * 0.5` even if the peak-finding geometry is satisfied.

4. **NaN propagation**: Three-valued logic on NaN is a project principle, but `pistol_geometry()` returns `np.nan` when landmarks are occluded, and the fault classifiers may or may not handle NaN correctly. The defensive fix is to add `np.nan` checks at the top of every classifier function.

---

## Open Questions

1. **Which azimuth range is safe for PLANAR measurements?** The viewpoint system produces bins (SAGITTAL 0–20°, OBLIQUE 20–65°, FRONTAL 65–90°). PLANAR faults should only be reported from FRONTAL or OBLIQUE, but what is the minimum azimuth for reliable knee_valgus measurement? This needs measurement on synthetic data with varying valgus magnitudes and azimuths.

2. **Can the detrend window be movement-adaptive?** The proposed 1.4s window for pull-ups may be too long for push-ups (min_rep_s=0.5s, window=1.0s) where the rotation component could overlap with the rep signal. Should the window be `max(movement.min_rep_s * 2, 1.0s)` to ensure it always removes at least one full rotation cycle?

3. **Is the Android CUES map a bottleneck?** Adding new fault types means the Android app needs updates to display new cues. If the Android release cycle is slow, new Python faults will be silently ignored on the phone. A shared fault-cue registry (JSON file in the repo, consumed by both Python and Kotlin) would solve this.

4. **Should confidence be exposed to the user?** The confidence values are currently internal. Exposing them to the user (e.g., "we're 92% sure this is a pull-up") could be misleading if the calibration is off (Finding 2.5). The confidence calibration fix would enable this, but the product decision should be made independently.