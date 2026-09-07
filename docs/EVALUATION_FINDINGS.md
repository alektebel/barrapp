# Measurement Core Evaluation: Findings & Prioritized Improvement Plan

## Overview

This report evaluates the three algorithmic stages of the barra measurement core — rep segmentation, movement classification, and fault classification — identifying concrete weaknesses with severity rankings and proposing prioritized, philosophy-aligned improvements. Each finding names the file and mechanism at fault; each proposed fix states its validation strategy without ground-truth labels. The project's philosophy is fixed: geometric rules that fail loudly, no learned classifiers, no labelled footage, CPU-only Lambda.

## Scope

**In scope:**
- Rep detection/segmentation in `barra/ingest.py`, `barra/movements.py`
- Movement classification in `barra/classify.py`, `barra/movements.py`
- Fault/error classification in `barra/faults.py`, `barra/faults_taxonomy.py`, `barra/metrics.py`
- Threshold management and duplication (`barra/config.py`, `barra/faults.py`, `barra/faults_taxonomy.py`, `app/src/main/java/com/barrapp/Cues.kt`)
- Viewpoint sensitivity in `barra/viewpoint.py`, `barra/metrics.py`
- Validation harness in `barra/validate_faults.py`, `barra/synthetic.py`, `tests/`

**Out of scope:**
- Android app UI/recommendation logic (only threshold audit)
- Lambda deployment, pose estimation backend, LLM prose generation
- New exercise types (ring dips, rows, etc.)
- ML/interview-based coaching features

## Phases

### Phase 0: Findings Inventory

**Goal**: Catalog every concrete weakness with file, mechanism, severity, and evidence.

#### Task 0.1: Severity-ranked findings catalog

- Location: This report
- Description: Synthesize findings from code reading across all three stages into a single severity-ranked catalog.
- Estimated Tokens: 3000
- Dependencies: None
- Steps:
  - Group findings by stage (segmentation, classification, fault, cross-cutting)
  - Assign severity: S1 (data loss / wrong answers), S2 (silent degradation / fragility), S3 (opportunity)
  - For each finding, name the file, line range, and mechanism at fault
  - Classify as "measured-but-wrong" vs "never-measured"
- Acceptance Criteria:
  - Every finding traces to a specific file and line(s)
  - Severity assignments distinguish false-negatives (undercounting) from silent misclassification
  - Coverage gap table maps every documented error from `tecnicas-errores-comunes.md` to measured/never-measured

## Findings Catalog

### STAGE 1 — Rep Detection/Segmentation

#### Finding 1.1 (S1 — Undercounting): Rescue pass is a binary fallback, not a complement

- **File**: `barra/ingest.py:607-631`
- **Mechanism**: `_rescue_candidates` only executes when the standard pass returns zero accepted reps. If the standard pass finds 1-2 reps but misses others, the missed reps are silently lost.
- **Evidence**: `docs/CORE.md` documents clip 0010 (3 muscle-ups, 2 counted), 0012 (2 muscle-ups, 1 counted), 0011 (0 reps from camera rotation), 0014 (reps rejected via anchor test). The rescue pass's `rescue_reps` function is unreachable when any rep passes.
- **Class**: measured-but-wrong (standard pass works but is not exhaustive)

#### Finding 1.2 (S1 — Undercounting): Amplitude inflation from non-rep motion in `active_mask`

- **File**: `barra/ingest.py:268-269` (active_mask call), `barra/ingest.py:282-284` (amplitude)
- **Mechanism**: `active_mask` identifies frames where the anchor is stationary. If the approach walk puts wrists >0.80 torso-lengths apart (documented in docstring as "5 torso-lengths apart"), the amplitude (apex - rest) inflates proportionally. Since prominence = 0.35 * amplitude, the threshold rises above genuine turnarounds.
- **Evidence**: Docstring at line 268-269 describes this exact failure mode. `ANCHOR_FIXED=0.80` in `classify.py:48` sets the same threshold as `MAX_BAR_TRAVEL=0.80` in `movements.py` — the threshold that causes rejection in Stage 1 is the threshold that defines "anchored" in Stage 2, but the active_span detection in Stage 1 has no windowed check like Stage 2 does.
- **Class**: measured-but-wrong (amplitude measured correctly but inflated by non-rep frames)

#### Finding 1.3 (S2 — Fragility): Camera rotation through a set produces zero reps

- **File**: `barra/ingest.py` (active_mask), `barra/movements.py` (`_pair`)
- **Mechanism**: When the camera rotates during a rep set (clip 0011, knee raise), the `MIN_PAIRED_FRAC=0.55` decision in `_pair()` falls back to near-side-only tracking. Combined with the active_mask's fixed anchor assumption, the signal becomes too noisy for any turnaround to clear the 0.35 prominence gate.
- **Evidence**: `docs/CORE.md` reports "0011 (knee raise, camera rotating through the set) recognized but 0 reps." The rescue pass also fails because velocity MAD is elevated by the rotating signal.
- **Class**: measured-but-wrong (signal exists but is corrupted by camera motion)

#### Finding 1.4 (S2 — Fragility): Peak must be observed (not interpolated) to be accepted

- **File**: `barra/ingest.py:319-323`
- **Mechanism**: If the turnaround frame itself has pose confidence < 0.35 (the `min_conf` floor), it is treated as unobserved and the rep is rejected. Brief pose loss at the exact turnaround — a common failure mode for fast muscle-ups — kills the rep entirely.
- **Evidence**: Line 323: `if not valid[turn_frame]: reject`. No fallback: the rep is not rescued even if surrounding frames form a clear hump.
- **Class**: measured-but-wrong (signal around the turnaround is sufficient but ignored)

#### Finding 1.5 (S2 — Fragility): Anchor travel test (`MAX_BAR_TRAVEL=0.80`) is too aggressive

- **File**: `barra/ingest.py:342-346`, `barra/movements.py:212`
- **Mechanism**: `anchor_travel` measures total wrist (or ankle) travel across a candidate rep using 95th-5th percentile spans. A value > 0.80 torso-lengths rejects the rep. Clips where the athlete's grip shifts, the bar wobbles, or the camera pans slightly during the set (0014) get rejected.
- **Evidence**: `docs/CORE.md`: "0014's reps rejected via the anchor test." The same 0.80 threshold is used for `ANCHOR_FIXED` in `classify.py:48` for movement classification, where it operates in a 3-second window. The segmenter applies it to the full rep duration.
- **Class**: measured-but-wrong (the signal is valid but travel exceeds a single threshold)

### STAGE 2 — Movement Classification

#### Finding 2.1 (S1 — Data loss): One movement per clip — mixed clips produce no measurement

- **File**: `barra/classify.py:371` (cascade order), `barra/classify.py:371-595` (full cascade)
- **Mechanism**: The `classify()` function returns on the first matching movement. A clip with two different exercises (e.g., pull-ups followed by dips) is classified as a single movement. Neither the per-rep segmentation nor the downstream metrics receive the correct movement label for all reps.
- **Evidence**: Comment at line 371 and docstring explicitly state one movement per clip. The validation harness (`validate_faults.py`) cannot flag this: it measures what the segmenter produced under the wrong movement label.
- **Class**: never-measured (the system has no concept of mixed clips)

#### Finding 2.2 (S2 — Fragility): Confidence scores are ad-hoc heuristics

- **File**: `barra/classify.py:100-107`, `barra/classify.py:468-507`
- **Mechanism**: Muscle-up and pull-up confidence uses `0.70 + margin * constant` where margin is clamped to [0, 1] with denominator 0.35. Front lever, planche, knee_raise, squat, dip, push_up all have fixed confidence (0.72-0.80). These are not calibrated probabilities — they are arbitrary numbers that happen to exceed the `certain` threshold of 0.65.
- **Evidence**: Docstring at line 95-98: "Confidence is heuristic (0.70-0.98) — the gap is wide, so the threshold doesn't need to be precise."
- **Class**: measured-but-wrong (confidence is reported but not calibrated)

#### Finding 2.3 (S2 — Fragility): Pull-up/muscle-up split uses only peak height

- **File**: `barra/classify.py:485-507`
- **Mechanism**: The `OVER_BAR=0.12` threshold on `shoulder_above_hands_p95` distinguishes muscle-up from pull-up. This single metric has no temporal consistency check — if the pose estimator briefly jumps (noise spike at the turnaround), a pull-up could become a muscle-up or vice versa.
- **Evidence**: The split is a sign test on a single percentile, with no verification that the shoulder stayed over the bar for a minimum duration or that the transition was kinematically smooth.
- **Class**: measured-but-wrong (metric exists but is vulnerable to pose noise at the decision boundary)

### STAGE 3 — Fault/Error Classification

#### Finding 3.1 (S1 — Fragility): Regex-parsed why-strings couple bar faults to prose output

- **File**: `barra/faults.py:15-18`, `barra/faults.py:82-93`
- **Mechanism**: `lockout`, `dead_hang`, and `stall` are detected by regex matching on the prose `why` strings in `components[range].why` and `components[smoothness].why`. This couples the fault detection to the exact text format produced by `barra/quality.py`. Any formatting change, locale shift, or wording update silently breaks fault detection.
- **Evidence**: Regex patterns: `r"lockout (\d+)% of full"`, `r"hang (\d+)% of full"`, `r"% of the ascent made no progress"`. These parse text produced by a different module. The same coupling exists in the Android app (`Cues.kt` line 73-81).
- **Class**: measured-but-wrong (faults are detected but through a fragile text contract)

#### Finding 3.2 (S1 — Coverage): Most tecnicas-errores-comunes.md errors are unmeasured

- **File**: `barra/faults_taxonomy.py` (fault classifiers), `tecnicas-errores-comunes.md` (source errors)
- **Mechanism**: The `muscle_up()` classifier (used for plain squat, pull-up, dip, push_up) provides only 5 generic bar faults (momentum, lockout, hang, control, stall). Squat-specific errors (knee valgus, insufficient depth, heel raise, lumbar rounding, gaze) are only checked in `pistol_squat()` — not for plain squats. Push-up errors (sagging hips, elbow flare, chest depth, head position) are not measured anywhere.
- **Evidence**: Coverage gap table: squat has only partial lockout/hang detection (no depth check, no valgus, no heel raise); push_up has only lockout via muscle_up fallback (no body_line sagging, no elbow angle, no chest-to-floor check).
- **Class**: never-measured (these errors have no geometric proxy in the current code)

#### Finding 3.3 (S2 — Fragility): PLANAR metrics applied regardless of viewpoint

- **File**: `barra/metrics.py` (PLANAR metrics), `barra/faults_taxonomy.py` (`pistol_geometry`), `barra/viewpoint.py`
- **Mechanism**: `swing`, `shoulder_asal_smmmetry`, and `turn_asymmetry` are computed from image x/y coordinates regardless of the declared or estimated viewpoint. From a frontal view, swing (which is fore-aft body motion) produces near-zero values. From a sagittal view, the same motion produces maximum values. The `pistol_geometry` function computes `knee_valgus` and `torso_lean` from lateral image coordinates — valid from frontal view but meaningless from side view. The viewpoint binning in `viewpoint.py` exists but is not integrated into the fault classification pipeline.
- **Evidence**: `docs/FINDINGS.md` Finding 1: "A 10-degree camera azimuth move displaces the normalised skeleton more than any of 5 deliberately induced errors." PLANAR metrics are computed identically in `metrics.py` with no view-gating.
- **Class**: measured-but-wrong (values are computed but semantically wrong for certain viewpoints)

#### Finding 3.4 (S2 — Fragility): Threshold duplication with no single source of truth

- **File**: `barra/faults.py` (SWING_TORSO=0.4, LOCKOUT_MIN=0.85, HANG_MIN=0.75), `barra/faults_taxonomy.py` (same constants redefined), `app/src/main/java/com/barrapp/Cues.kt` (same constants redefined again), `barra/config.py` (different config constants)
- **Mechanism**: `SWING_TORSO=0.4`, `LOCKOUT_MIN=0.85`, `HANG_MIN=0.75` appear in both `faults.py` and `faults_taxonomy.py`. The Android app `Cues.kt` redefines the same values (lines 17-20, 26-30). There is no import between any of these files — each is an independent copy. A change to one without the others silently desynchronizes the system.
- **Evidence**: Direct grep confirms identical constant definitions in three files. The comment at `faults_taxonomy.py` says "must agree with faults.py" but there is no enforcement mechanism.
- **Class**: never-measured (the risk is in the gap between copies, not in the values themselves)

#### Finding 3.5 (S2 — Fragility): Control fault is inconsistently defined

- **File**: `barra/faults.py:87-91` (control via `penalties[control].value > 0`), `barra/faults_taxonomy.py` (`muscle_up` uses `tempo_ratio < CONTROLLED_TEMPO`), `barra/quality.py` (tempo ratio computation)
- **Mechanism**: In `faults.py`, control is a binary flag from the phone's penalty system. In `faults_taxonomy.py`, control is measured via `tempo_ratio < 0.70`. These two mechanisms use different signals and different thresholds. The same rep could be flagged as "control" by one mechanism but not the other.
- **Evidence**: `faults.py` reads `rep["penalties"][control].value > 0` (phone-computed). `faults_taxonomy.py` recomputes from bar signal. No reconciliation.
- **Class**: measured-but-wrong (two overlapping definitions that may disagree)

#### Finding 3.6 (S3 — Opportunity): No fault for push-up body sagging

- **File**: `barra/faults_taxonomy.py` (no `push_up()` classifier — falls back to `muscle_up()`)
- **Mechanism**: `push_up` maps to the generic `muscle_up()` classifier which checks bar-specific faults (momentum, lockout, hang, control, stall) but has no body-line sagging detection. Push-up sagging is the #1 cited technique error in `tecnicas-errores-comunes.md` but is completely unmeasured.
- **Evidence**: Line dispatch in `faults_taxonomy.py` at the fallback: `if track in ("squat", "pull_up", "dip", "push_up"): return muscle_up(values)`. Plain squat and push_up share the same 5-bar-fault classifier.
- **Class**: never-measured

#### Finding 3.7 (S3 — Opportunity): No bounce detection for dip

- **File**: `barra/faults_taxonomy.py` (muscle_up classifier), `barra/metrics.py`
- **Mechanism**: Dip bounce at bottom is a #1 cited error in `tecnicas-errores-comunes.md`. The current code measures transition time and tempo but has no elasticity/bounce detection. A bounce would not be distinguished from a controlled descent with a pause at bottom.
- **Evidence**: No velocity-second-derivative (acceleration spike at bottom) check exists in any fault classifier.
- **Class**: never-measured

## Prioritized Improvement Plan

### Priority P1: Eliminate regex coupling for bar faults (Finding 3.1)

**Severity**: S1 | **Impact**: Prevents silent fault detection failure | **Effort**: Low

#### Task 1.1.1: Extract numeric values from quality.py components directly

- **Location**: `barra/faults.py`, `barra/quality.py`
- **Description**: Instead of regex-parsing prose strings, read the numeric `range_component` values (lockout_pct, hang_pct) directly from the structured quality output. The quality scoring already computes these — `faults.py` should read them as numbers, not parse them from text.
- **Estimated Tokens**: 2000
- **Dependencies**: None
- **Steps**:
  - Identify the numeric fields in quality.py output that encode lockout/hang percentages
  - Modify `rep_faults()` in `faults.py` to read `components[range].lockout_pct` as a float
  - Do the same for `stall` — read from a numeric smoothness metric rather than parsing prose
  - Add a test that validates the numeric field exists and is in expected range
  - Remove regex patterns from `faults.py`
- **Acceptance Criteria**:
  - `faults.py` no longer imports `re`
  - Regex-free tests pass (deterministic numeric comparison)
  - `validate_faults.py` results unchanged on known clips

**Validation**: Synthetic invariant test — create synthetic reps with known lockout/hang percentages via `barra/synthetic.py`, run pipeline, verify faults fire/never fire at the exact numeric thresholds. Deliberate-fault clips: modify a synthetic rep's `lockout_pct` to 0.50, verify "lockout" fires; set to 0.95, verify it does not.

**Self-critique**: This assumes the numeric fields in quality.py's output are stable and well-named. If the quality module renames fields or changes the structure (which it has in the past — the "control is penalty" fix was a structural change), this coupling simply moves to a new boundary. The fix should include a schema assertion that validates the presence and type of these fields.

### Priority P2: Centralize threshold configuration (Finding 3.4)

**Severity**: S2 | **Impact**: Prevents silent desynchronization between server and Android | **Effort**: Low-Medium

#### Task 2.1.1: Create a shared fault thresholds module

- **Location**: `barra/config.py` (extend), `barra/faults.py` (import), `barra/faults_taxonomy.py` (import), `app/src/main/java/com/barrapp/Cues.kt` (Android migration)
- **Description**: Define all fault thresholds in a single location with clear names and documentation. Python imports from `config.py`. Android receives thresholds via API response or a versioned config endpoint.
- **Estimated Tokens**: 3000
- **Dependencies**: Task 1.1.1 (regex removal must happen first — otherwise thresholds are embedded in text parsing)
- **Steps**:
  - Create a `FAULT_THRESHOLDS` dataclass in `config.py` with: `SWING_TORSO`, `LOCKOUT_MIN`, `HANG_MIN`, `CONTROLLED_TEMPO`, `STALL_RATE`, `STALL_FRAC_MIN`
  - Replace all direct constant definitions in `faults.py` and `faults_taxonomy.py` with imports from `config.FAULT_THRESHOLDS`
  - Add a module-level `_assert_thresholds_consistent()` that validates no constant is defined outside config
  - For Android: add a `GET /v1/config/fault-thresholds` endpoint to `server/api/process.py` that returns the same JSON as `FAULT_THRESHOLDS`
  - Update `Cues.kt` to fetch thresholds from the API rather than hardcoding them
- **Acceptance Criteria**:
  - Zero constant definitions for SWING_TORSO, LOCKOUT_MIN, HANG_MIN outside `config.py`
  - Import grep confirms `from barra.config import` or `from barra import config` in both `faults.py` and `faults_taxonomy.py`
  - Android config endpoint returns the same JSON structure
  - New test: if a threshold is changed in config, a unit test verifies both `faults.py` and `faults_taxonomy.py` use the new value

**Validation**: Null-distribution check — run the threshold-audit test on 100 synthetic clean reps; verify that no false fault fires from measurement noise alone. Then deliberately perturb each threshold by ±10% and verify that the fault detection rate changes monotonically (not erratically) — confirming each threshold has a clear, directional effect.

**Self-critique**: Moving Android thresholds to an API endpoint introduces network latency and version drift risk. The Android app must cache and version the config. Also, the API endpoint itself becomes a single point of failure — if the server returns stale thresholds, the Android app silently desynchronizes. A better approach may be versioned threshold bundles baked into app releases with a server-side validation that the installed version matches the expected thresholds. This adds release-cycle coupling.

### Priority P3: Fix rescue pass coverage (Finding 1.1)

**Severity**: S1 | **Impact**: Recovers undercounted reps on camera-rotation and fatigued sets | **Effort**: Medium

#### Task 3.1.1: Make rescue pass complement the standard pass

- **Location**: `barra/ingest.py:607-631` (`rescue_reps`), `barra/ingest.py:255-560` (`segment_reps_verbose`)
- **Description**: Change `_rescue_candidates` from a binary fallback to a complement pass that runs after the standard pass and accepts candidates that were rejected for non-fatal reasons (e.g., anchor travel just over 0.80, peak was interpolated but surrounding frames are solid).
- **Estimated Tokens**: 4000
- **Dependencies**: None (but should follow P1 so that threshold changes in config propagate)
- **Steps**:
  - Modify `segment_reps_verbose` to call `_rescue_candidates` unconditionally, passing it the standard pass's rejected candidates
  - Rescue pass should only re-examine candidates that were rejected for specific, recoverable reasons (interpolated peak, anchor travel borderline)
  - Rescue pass should use a higher rejection threshold for the overall set — if the standard pass found >= 3 reps, the rescue pass should only add reps that are clearly stronger than the weakest standard rep
  - Document the new rescue pass behavior and update tests
  - Add tests for the scenarios in `docs/CORE.md`: 3 muscle-ups/2 counted, camera-rotation set
- **Acceptance Criteria**:
  - Rescue pass adds reps without increasing false positive rate on synthetic clean data
  - The 3 documented undercounting cases from `docs/CORE.md` are resolved or explained
  - `test_rescue.py` gains new test cases for rescue-after-standard
  - No regression on existing 137 invariant tests

**Validation**: Deliberate-fault clips — inject synthetic reps into clean signals at varying amplitudes (0.3x, 0.5x, 0.7x of the prominence threshold) and verify that the rescue pass recovers them. Use the existing synthetic rep generator (`barra/synthetic.py`) to produce sets with controlled undercounting scenarios. Also: run on clips 0010, 0011, 0012, 0014 from the documented test corpus and verify rep counts match ground truth (manual count from video).

**Self-critique**: The rescue pass has already been designed as a binary fallback by deliberate choice (to avoid compounding false positives from two segmenters). Relaxing this to a complement pass increases the risk of false positives from noise. The fix must be conservative: rescue should only accept candidates that the standard pass almost accepted (e.g., peak was 0.55*amplitude vs the 0.60 requirement), not completely new peaks. A better long-term solution is a unified segmenter with tiered confidence rather than two separate passes, but that is out of scope for a P1 fix.

### Priority P4: Viewpoint-gate PLANAR metrics (Finding 3.3)

**Severity**: S2 | **Impact**: Eliminates false fault detection from frontal-view PLANAR measurements | **Effort**: Medium

#### Task 4.1.1: Add viewpoint-based exclusion flags to PLANAR metrics

- **Location**: `barra/metrics.py` (PLANAR metric computation), `barra/faults_taxonomy.py` (`pistol_geometry`), `barra/viewpoint.py`
- **Description**: Before computing PLANAR metrics, check the viewpoint bin. If the bin is FRONTAL or UNKNOWN, set PLANAR metrics to NaN and emit a structured reason. Similarly, `pistol_geometry()` should reject computation if the viewpoint is not frontal/posterior (where lateral deviations are meaningful).
- **Estimated Tokens**: 3500
- **Dependencies**: Task 2.1.1 (threshold centralization — the exclusion rules should reference a central config)
- **Steps**:
  - Add a `VIEWPORT_FLAGS` dataclass to `config.py`: `PLANAR_METRICS_BLOCKED_BIN = ["FRONTAL", "UNKNOWN"]`, `PISTOL_GEOMETRY_REQUIRED_BIN = ["SAGITTAL", "OBLIQUE"]`
  - Modify PLANAR metric computation in `metrics.py` to read the viewpoint bin and set values to NaN if blocked
  - Modify `pistol_geometry()` in `faults_taxonomy.py` to accept a viewpoint parameter and return NaN if not appropriate
  - Update downstream consumers (`faults.py`, `faults_taxonomy.py`) to treat NaN as "not measured" (already the philosophy: three-valued logic on NaN)
  - Add tests verifying PLANAR metrics are NaN for frontal views and valid for sagittal views
- **Acceptance Criteria**:
  - PLANAR metrics (swing, shoulder_asymmetry, turn_asymmetry) are NaN when viewpoint is FRONTAL or UNKNOWN
  - `pistol_geometry()` returns NaN when viewpoint is not frontal/posterior
  - Faults that depend on NaN values are not flagged (NaN does not satisfy any comparison)
  - New tests in `tests/` verify viewpoint-dependent NaN behavior
  - No regression on existing tests (sagittal clips still produce valid PLANAR metrics)

**Validation**: Synthetic invariant test — generate synthetic reps at azimuths 5° (sagittal), 45° (oblique), 85° (frontal) using `barra/synthetic.py`. Verify: swing is valid (non-NaN) for 5°, NaN for 85°. For the oblique case, verify that the PLANAR metric value is still computed but with reduced reliability (a new "confidence" field). Null-distribution: run 50 frontal-view synthetic reps; verify zero PLANAR-based faults fire.

**Self-critique**: Setting PLANAR metrics to NaN for frontal views is a blunt instrument. A frontal view may still have some lateral information (the athlete's body is not a perfect plane), and NaN = "not measured" means the fault is never evaluated, which is the safe direction but also data-loss. A more nuanced approach would be a viewpoint-reliability scalar (0.0-1.0) that down-weights PLANAR metric contributions without eliminating them. However, that moves toward learned calibration, which conflicts with the philosophy. The NaN approach is philosophically consistent: if the geometry is unreliable, we say "we don't know" rather than guessing.

### Priority P5: Add push-up and squat fault classifiers (Finding 3.2, 3.6)

**Severity**: S2 | **Impact**: Measures the most-cited errors for the two most-common exercises | **Effort**: Medium-High

#### Task 5.1.1: Implement squat-specific fault classifier

- **Location**: `barra/faults_taxonomy.py` (new `squat()` function), `barra/movements.py` (new squat signal features), `tests/`
- **Description**: Create a dedicated `squat()` classifier that checks for knee valgus, insufficient depth, heel raise, and lumbar rounding — the top errors from `tecnicas-errores-comunes.md`. Depth should use the hip-height signal (same as rep segmentation's `hip_height`). Valgus requires frontal-view geometry (same as pistol_squat's `knee_valgus`).
- **Estimated Tokens**: 5000
- **Dependencies**: Task 4.1.1 (viewpoint gating — squat valgus and heel raise are PLANAR/scaled and need viewpoint context)
- **Steps**:
  - Define squat-specific feature extraction: `squat_depth` (hip descent in torso-lengths from standing), `squat_valgus` (lateral knee deviation, PLANAR), `heel_raise` (ankle y-change relative to hip)
  - Implement `squat(values)` with thresholds for each error
  - Register squat in `classify_failures()` dispatch (move squat out of the muscle_up fallback)
  - Add synthetic error modes to `barra/synthetic.py`: `insufficient_depth`, `squat_valgus`, `heel_raise`
  - Write invariant tests
- **Acceptance Criteria**:
  - Squat classifier fires for synthetically induced valgus, shallow depth, and heel raise
  - Squat classifier does not fire on clean synthetic reps (null distribution)
  - Squat is dispatched in `classify_failures()` independently of muscle_up
  - Planar metrics (valgus) are NaN for frontal views
  - No regression on existing fault tests

#### Task 5.1.2: Implement push-up body sagging fault classifier

- **Location**: `barra/faults_taxonomy.py` (new `push_up()` function), `barra/movements.py` (body_line measurement)
- **Description**: Create a dedicated `push_up()` classifier that checks for body sagging (body_line_deg deviating from straight during the concentric), elbow flare (elbow-shoulder-hip angle), and insufficient chest depth.
- **Estimated Tokens**: 4000
- **Dependencies**: None (body_line_deg is already computed in `classify.py:240-246`)
- **Steps**:
  - Use existing `body_line_deg` computation to detect sagging: during the eccentric phase, body_line_deg should stay < 20° (near-vertical) for a straight plank
  - Add elbow flare detection: measure the horizontal distance between elbow and shoulder during the bottom position
  - Add chest depth check: measure wrist-to-chest (sternum) distance at the bottom of the rep
  - Implement `push_up(values)` with thresholds
  - Register push_up in `classify_failures()` dispatch
  - Write tests
- **Acceptance Criteria**:
  - Push-up classifier fires for synthetically sagging reps (induced via depth_profile modification in synthetic.py)
  - Push-up classifier does not fire on clean synthetic reps
  - Push-up is dispatched in `classify_failures()` independently of muscle_up
  - No regression on existing fault tests

**Validation for both tasks**: Deliberate-fault clips using `barra/synthetic.py` with induced errors. Null-distribution: run 50 clean synthetic reps through the new classifiers; zero faults should fire. Invariant: increasing the induced error severity should monotonically increase fault detection rate (not jump erratically).

**Self-critique**: Adding fault classifiers increases the total number of possible faults per rep, which increases the chance of at least one false fault firing on any given rep. The existing philosophy accepts this ("fail loudly" is better than "fail silently"), but the false positive rate needs to be measured. The null-distribution check from the existing validation harness (`validate_faults.py`) is the right tool: if clean reps fire new faults, the thresholds are too sensitive. Also, these classifiers assume the pose estimator can reliably detect elbow angle and sternum position — mediapipe pose (17 keypoints) does not include a sternum landmark, so chest depth would need to be interpolated from shoulder-hip geometry, which reduces reliability.

### Priority P6: Fix anchor travel sensitivity (Finding 1.5)

**Severity**: S2 | **Impact**: Recovers reps rejected by borderline anchor travel (clip 0014) | **Effort**: Low

#### Task 6.1.1: Windowed anchor travel with hysteresis

- **Location**: `barra/ingest.py` (anchor travel check), `barra/movements.py` (`anchor_travel`)
- **Description**: Replace the single-threshold `MAX_BAR_TRAVEL=0.80` check with a windowed check: the rep is valid if any 3-second window within the rep has anchor travel < 0.80. This mirrors the approach used in `classify.py`'s `_best_window()` for movement classification.
- **Estimated Tokens**: 2500
- **Dependencies**: None
- **Steps**:
  - Modify the anchor travel check in `segment_reps_verbose` to use a sliding window
  - Within each rep's `[start, end]` frame range, slide a 3-second window (or shorter if rep < 3s) and compute travel in each window
  - Accept the rep if any window has travel < 0.80 torso-lengths
  - Add a second check: the overall rep travel should still be < 1.20 (to reject walking-around clips)
  - Update `test_movements.py` with a walking-then-rep synthetic case
- **Acceptance Criteria**:
  - Reps with brief anchor drift (grip shift, bar wobble) are accepted
  - Walking-around clips (anchor travel > 2.0 torso-lengths sustained) are still rejected
  - Clip 0014's previously rejected reps are now accepted
  - No regression on existing segmenter tests

**Validation**: Synthetic invariant test — generate clips with anchor travel at 0.75, 0.80, 0.85, 0.95, 1.20, 2.0 torso-lengths. Verify: 0.75 accepted (clear below), 0.85 accepted if windowed travel < 0.80, 2.0 rejected. Deliberate-fault: inject a 1-second wrist drift into a clean rep and verify the rep still passes (drift < 0.80 in a 3s window).

## Testing Strategy

### Invariant tests (existing, extend):
1. Extend `tests/test_rescue.py` with rescue-after-standard tests
2. Extend `tests/test_core.py` with PLANAR metric NaN for frontal views
3. Extend `tests/test_classify_quality.py` with squat and push-up fault tests
4. Add threshold-centralization test: verify all fault thresholds import from config

### Deliberate-fault tests (new):
1. Generate synthetic reps with induced errors at known severity levels (synthetic.py `make_set` with `error` parameter extended to cover squat/push-up errors)
2. Run through the full pipeline
3. Verify fault detection rates change monotonically with error severity
4. Verify zero false faults on clean synthetic reps

### Null-distribution tests (new):
1. Run 50 synthetic clean reps (no errors) through all fault classifiers
2. Verify zero faults fire on any classifier
3. If any fault fires, the threshold is too sensitive

### Deliberate-fault clips (real footage):
1. Run clips 0010, 0011, 0012, 0014 from `docs/CORE.md` through the improved pipeline
2. Compare rep counts against manual video count
3. Verify fault detection is sensible (no impossible fault combinations)

### Regression tests:
1. All existing 137 invariant tests must pass
2. `barra/validate_faults.py` results on the existing manifest must not regress

## Risks

1. **Synthetic data mismatch**: Validation using `barra/synthetic.py` measures performance against the synthetic noise model, not reality. Synthetic data may not capture mediapipe's real failure modes (occlusion patterns, tracking jumps). Mitigation: supplement with real-footage validation on clips 0010-0014 and any additional footage the team has.

2. **Threshold creep**: Adding more fault classifiers (squat, push-up) increases the total fault surface area. More sensors = more chance of at least one false alarm. Mitigation: null-distribution tests are mandatory before each new classifier ships.

3. **Android config sync delay**: If the API-based config approach is used, Android updates lag behind server threshold changes. Mitigation: versioned config bundles with server-side version check. If not feasible, keep hardcoding in Android but add a CI test that compares Android constants against Python config.

4. **Windowed anchor travel complexity**: Adding windowed checks increases computation on CPU-only Lambda. Mitigation: the window size is fixed at 3 seconds (or rep duration if shorter), so the computation is O(n) with a small constant. Profile on Lambda before and after.

5. **NaN propagation surprises**: Setting PLANAR metrics to NaN for frontal views changes the downstream computation — faults that depend on NaN values silently disappear rather than firing. This is intentional (three-valued logic) but may surprise users who expect "fault detected" where none was before. Mitigation: emit a structured reason in the output (`{ "swing": null, "reason": "viewpoint=FRONTAL" }`) so the user understands why the fault was not evaluated.

## Rollback Plan

1. **Threshold changes**: All threshold values remain in code (not learned). Rollback is a single-line revert in `config.py` or the specific constant file. No model retraining needed.

2. **Rescue pass changes**: The rescue pass is a separate function. Rollback is disabling the complement pass by reverting to binary fallback (one conditional change).

3. **Fault classifier additions**: New classifiers are separate functions. Rollback is removing the dispatch entry in `classify_failures()` and the classifier registration. Existing `muscle_up()` fallback continues to work.

4. **PLANAR NaN gating**: Adding NaN returns is safe to revert — the code path before NaN is the same as before. Just remove the `if viewpoint in BLOCKED: return NaN` guard.

5. **Config centralization**: If the API config endpoint causes issues, revert Android to hardcoded thresholds (copy from config.py manually). Python side is backward-compatible (import from config.py instead of local constants is a net addition).

## Edge Cases

1. **Mixed-movement clip with rep segmentation**: If the segmenter correctly segments reps but the clip-level classification assigns the wrong movement, per-rep faults are computed under the wrong movement's fault set. Mitigation: document that mixed clips produce unreliable per-rep faults; no automatic fix without per-rep movement classification (out of scope).

2. **Camera switch mid-session**: If the session spans two camera positions (one sagittal, one frontal), the viewpoint estimator's self-calibration may produce an `UNKNOWN` bin for all clips. PLANAR metrics would all be NaN. Mitigation: per-rep viewpoint estimation instead of session-level. Out of scope for now; document as known limitation.

3. **Pose estimation completely fails for a rep**: If mediapipe returns all-zero or all-NaN keypoints for frames covering the turnaround, `_clean_signal` interpolates and the rep is accepted with high interpolation fraction. The `max_invented_frac=0.4` check limits this, but 40% interpolated is still a lot of data loss. Mitigation: the rep quality score should drop; `MIN_REP_QUALITY=0.55` in `metrics.py` should exclude this rep from comparison.

4. **Very short clips (< 1 rep)**: The `active_mask` function needs a minimum number of frames to compute meaningful anchor travel. If the clip is 2 seconds of a single rep (no rest before or after), the active_mask may be empty. Mitigation: `segment_reps_verbose` should handle the case where `active_mask` returns no True frames by falling back to the full clip.

5. **Single-leg stance on pistol squat with second leg touching**: The `single_leg_stance` feature uses XOR logic on ankle positions. If the second leg briefly touches the ground mid-squat, the ankle may briefly become "below hip," breaking the XOR. Mitigation: windowed ankle check — require single-leg stance in the majority of frames within the rep, not every frame.

6. **Three-valued logic edge cases with NaN**: A condition like `swing > 0.4` with `swing = NaN` returns False in Python (NaN comparisons always return False). But a condition like `swing != swing` (NaN self-comparison) returns True. The code uses `>` and `<` comparisons, so NaN silently fails the condition (correct behavior per philosophy). However, any `== NaN` check would fail. Mitigation: document that all comparisons use `>` or `<`, never `==` or `!=` on metric values.

## Open Questions

1. **Per-rep movement classification**: Should movement be classified per-rep instead of per-clip? This would enable mixed-movement clips but requires solving the "which movement profile to use for signal computation during segmentation" chicken-and-egg problem. Currently, movement is needed before segmentation; moving to per-rep classification inverts this dependency.

2. **Confidence calibration**: The heuristic confidence scores (0.70-0.98) are useful for sorting but not for probabilistic decisions. Could they be calibrated against the synthetic null distribution? This would require accepting that "calibration" is data-dependent, which edges toward the "no labels" constraint — but calibration against synthetic nulls is still geometry-based.

3. **Anchor travel threshold**: Is 0.80 torso-lengths the right threshold for `MAX_BAR_TRAVEL`? The value was chosen empirically to reject walking clips while accepting grip shifts. A data-driven approach would plot the anchor travel distribution on known-clean clips and set the threshold at the 99th percentile of clean data. But this requires clean labeled data, which the project avoids.

4. **Android config strategy**: Should Android thresholds come from the server API, be baked into releases, or be derived from a shared schema (e.g., TypeScript definitions compiled to Kotlin)? Each has tradeoffs in sync reliability and update latency.

5. **Fault overlap**: A rep with both momentum and lockout faults fires two separate faults. The coaching layer (`Cues.kt`) picks the top 3 by frequency. If a clip has 5 reps with varied faults, which faults are "real" and which are noise? The existing approach (frequency ranking) is pragmatic but doesn't distinguish between "fault present on 5/5 reps" (real) and "fault present on 1/5 reps" (possibly noise).