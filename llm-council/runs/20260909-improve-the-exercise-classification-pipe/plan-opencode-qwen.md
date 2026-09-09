I'll start by thoroughly understanding the codebase, then produce a comprehensive implementation plan.



# Plan

## Overview
The geometric classifier in `barra/classify.py` confidently mislabels exercises when its required geometry is absent, occluded, or ambiguous. This plan introduces a structured abstention system (the `UnknownReason` enum), tightens hold-vs-rep discrimination for planche/front_lever, disambiguates squat-vs-dip using arm-forward signals, adds an exercise measurability gate so unmeasurable exercises are abstained, and grows the learned classifier from 7 to 13 classes with proper corpus coverage. The project's core principle — measure what you can, abstain honestly, never report a fabricated verdict — becomes enforced structurally.

## Scope
- **In**: `barra/classify.py` (decisions, abstention, measurability gate), `barra/evidence.py` (planar-gated primitives, `view_blocked` propagation), `barra/movements.py` (resolve coverage for unmeasurable classes), `barra/model.py` (13-class MLP), `scripts/train_model.py` (expanded training), `scripts/pipeline_eval.py` / `scripts/evaluate_technique_pipeline.py` (abstention metrics), `tests/` (new abstention tests, updated existing tests), `data/evaluation/sample_manifest.json` (evaluation only), `data/calisthenics/metadata.csv` (evaluation only)
- **Out**: Server code (`server/process.py`, `server/vision.py`) — abstention flows through existing return paths. No new dependencies. No changes to `data/` files (read-only evaluation). No changes to `barra/rules.py`, `barra/config.py`, `barra/exercises.py`, `barra/skills.py`.

## Phases

### Phase 1: Abstention Infrastructure
**Goal**: Give the geometric classifier a structured way to return `unknown` with a named, explainable reason, so callers can distinguish "not this exercise" from "cannot measure".

#### Task 1.1: Define `UnknownReason` enum and abstention return contract
- **Location**: `barra/classify.py`
- **Description**: Create an enum covering every reason the classifier cannot produce a confident label, and a return-type convention for the classifier function that always carries abstention reason when the verdict is unknown.
- **Estimated Tokens**: 4000
- **Dependencies**: None
- **Steps**:
  - Add `class UnknownReason(Enum):` with members: `ANKLE_VISIBILITY`, `FEET_OBSCURED`, `VIEW_BLOCKED`, `ANCHOR_UNCERTAIN`, `REP_OR_HOLD_AMBIGUOUS`, `REQUIRED_SIGNAL_MISSING`, `BODY_NOT_HORIZONTAL`, `INSUFFICIENT_MOVEMENT`, `TOO_MANY_CONFLICTING_SIGNALS`, `CAMERA_AZIMUTH_UNKNOWN`, `LANDMARK_LOW_CONFIDENCE`
  - Change `classify()` return signature to `(label: str, score: float, reason: str | None)` — `reason` is `None` for a confident label, `UnknownReason` value (string) for abstention
  - Add `classify(video_path, fps=None) -> tuple[str, float, str | None]` helper that wraps frame extraction
  - Add internal `_abstain(reason: UnknownReason) -> tuple[str, float, str | None]` that returns `("unknown", 0.0, reason.value)`
- **Acceptance Criteria**:
  - `UnknownReason` has at least 11 members covering all current and projected abstention reasons
  - `classify()` always returns a 3-tuple; existing callers that only use `result[0]` continue working (backward compatible)
  - `pytest barra/classify.py` (import test) passes

#### Task 1.2: Wire abstention through `features()` — propagate `view_blocked` state
- **Location**: `barra/classify.py`, `barra/evidence.py`
- **Description**: `features()` currently produces raw floats. Several features (ankle depth, split geometry, body line angle) depend on landmark visibility and planar knowledge. When a landmark is occluded, the feature value must carry that state so the classifier can reason about it.
- **Estimated Tokens**: 6000
- **Dependencies**: Task 1.1
- **Steps**:
  - In `features()`, for each measurement that depends on ankle/foot visibility, attach a boolean `_visible` companion alongside the float value
  - Add a `_feature_state` dict (parallel to the feature dict) that maps each feature name to `"measured"`, `"unmeasured"`, or `"view_blocked"`
  - The view estimate (`estimate_view` from `evidence.py`) is already computed by the pipeline; thread the view bin into `features()` and mark planar features as `view_blocked` when the view is not SAGITTAL or when the planar plane doesn't match
  - Ensure `ankle_travel` and `split_depth` carry visibility state; when ankles are below `MIN_SEEN` coverage, mark them `view_blocked` rather than `unmeasured`
  - Do NOT change `features()` output shape for existing code — the float dict is unchanged, the state dict is additional
- **Acceptance Criteria**:
  - `features()` returns both the existing float dict (unchanged shape) and a `_feature_state` dict
  - Ankle-dependent features marked `view_blocked` when ankle coverage < `MIN_SEEN` (0.40)
  - Existing tests in `tests/` that call `features()` continue to pass (dict shape unchanged)
  - `barra/evidence.py` view estimation is imported and usable

#### Task 1.3: Add `_measurable()` — exercise pre-classification gate
- **Location**: `barra/classify.py`
- **Description**: Before running the exercise classification decision tree, check whether the clip exhibits the *bare minimum* geometry for any exercise. If the clip is a static frame with near-zero movement across all landmarks (or has no body-line at all), return `unknown` immediately with reason `INSUFFICIENT_MOVEMENT` or `REQUIRED_SIGNAL_MISSING`.
- **Estimated Tokens**: 5000
- **Dependencies**: Task 1.2
- **Steps**:
  - Create `_measurable(kp, fps)` function that checks:
    1. At least one of: wrist travel, ankle travel, shoulder travel > 0.05 torso-lengths (some movement happened)
    2. If body is horizontal (body_line_deg > 70), hands are either overhead (pull/hang) or below (push/planche)
    3. If body is vertical, hands are either fixed (bar work) or moving (body work)
  - If none of these minimal patterns are detectable, return `("unknown", 0.0, UnknownReason.REQUIRED_SIGNAL_MISSING.value)`
  - This catches bench_press (hands stationary at chest height, no bar geometry), deadlift (body vertical with hands moving away from body), handstand (body vertical, hands not fixed, no downward travel)
- **Acceptance Criteria**:
  - `_measurable()` returns `False` for clips where all landmark travels < 0.05 torso-lengths AND no body-line angle exists
  - Existing exercise clips (squat, dip, push_up, etc.) return `True`
  - Bench_press, deadlift, handstand return `False` with appropriate reason
  - No regression on the 8 reviewed root clips

### Phase 2: Fix Known Misclassifications
**Goal**: Fix the specific, genuinely fixable confusions: squat→dip, planche→push_up, front_lever→muscle_up.

#### Task 2.1: Fix squat→dip with arm-forward signal and ankle-visibility guard
- **Location**: `barra/classify.py`
- **Description**: The current dip detection fires when hands are fixed and body is below hands. For arm-forward squats, the arms are held at roughly shoulder height throughout (no vertical travel relative to torso), which distinguishes them from dips where shoulders travel vertically relative to hands.
- **Estimated Tokens**: 5000
- **Dependencies**: Task 1.2
- **Steps**:
  - Add measurement in `features()`: `shoulder_hand_relative_travel` — the vertical travel of shoulders relative to hands (shoulder_y travel minus wrist_y travel, in torso-lengths). For dips, this is large (>0.30); for arm-forward squats, this is near zero (<0.10).
  - Add `arm_angle_frac` — mean angle of upper arm (shoulder-wrist line) from vertical, measured at the frame with maximum hip depth. For arm-forward squats, angle is <45° from horizontal; for dips, angle is <30° from vertical.
  - In the dip detection branch (currently #10, between squat and push_up), move dip detection *after* the squat detection (currently #9). Squat check: planted + rigid arms + hip_travel >= 0.35 + (`ankle_visibility` >= `MIN_SEEN` OR `shoulder_hand_relative_travel` < 0.15 OR `arm_angle_frac` > 40°). The OR handles both "feet visible so we can confirm squat" and "feet hidden but arms held forward so it's not a dip".
  - Only after squat is rejected: dip detection (anchored + articulated + hands_below_frac > 0.80 + body_below_hands >= 0.25).
  - Keep the existing ankle-visibility guard that was added in a prior fix but strengthen it: ankle coverage < MIN_SEEN AND shoulder_hand_relative_travel >= 0.15 → abstain with `ANKLE_VISIBILITY` reason.
- **Acceptance Criteria**:
  - Arm-forward squat clips classified as `squat` (not `dip`)
  - Real dip clips still classified as `dip` (no regression)
  - The 8 reviewed root clips maintain or improve classification
  - `scripts/evaluate_technique_pipeline.py` shows squat→dip errors eliminated on corpus

#### Task 2.2: Fix planche→push_up with tighter hold-vs-rep discrimination
- **Location**: `barra/classify.py`
- **Description**: Planche holds that have slight body sway or micro-movements don't pass the `HOLD_FRAC` threshold and fall through to the rep classification branch where they match push_up (shoulders moving, body horizontal-ish, arms bending slightly from fatigue). The fix: detect the "hold" pattern earlier in the decision tree and give it higher priority, with a secondary "low-confidence hold" path.
- **Estimated Tokens**: 5000
- **Dependencies**: Task 1.1
- **Steps**:
  - In `features()`, add `shoulder_steady_frac` — fraction of window where shoulder vertical travel is < 0.10 torso-lengths (hands are the reference, shoulders shouldn't move much in a planche).
  - Add `arm_angle_stability` — fraction of window where elbow angle variance is < 15° (arms are rigidly supporting, not bending rhythmically).
  - Move the "Hold rejection" branch (#3 in current code) to BEFORE the muscle_up/pull_up branch and BEFORE the dip/push_up branch. Current hold rejection only handles "hands overhead" — extend it:
    - Hold if: `parked_frac >= HOLD_FRAC` AND (`hands_overhead_frac > 0.35` OR `body_line_deg > 70`) — this catches both overhead hangs and horizontal holds.
    - If `parked_frac` is between `HOLD_FRAC * 0.7` (0.385) and `HOLD_FRAC` but `shoulder_steady_frac > 0.6` and `arm_angle_stability > 0.5`, still call it a hold but with lower confidence.
    - A "low-confidence hold" returns `("unknown", 0.35, "REP_OR_HOLD_AMBIGUOUS")` — the model might still help, but the geometric classifier abstains.
  - If the hold branch rejects (not a hold), then the rep branches (muscle_up, dip, push_up) proceed normally.
- **Acceptance Criteria**:
  - Static planche clips classified as `unknown` (not `push_up`)
  - Dynamic planche (tuck-to-straddle transitions) still classified correctly as `planche`
  - Real push_up clips still classified as `push_up` (no regression)
  - `scripts/evaluate_technique_pipeline.py` shows planche→push_up errors eliminated

#### Task 2.3: Fix front_lever→muscle_up with body-plane and hold priority
- **Location**: `barra/classify.py`
- **Description**: Front lever clips where the body is horizontal but slightly angled (tuck front lever, or body not perfectly parallel) may not pass the `body_line_deg >= 70` check for front_lever. They also may not register as a "hold" because of micro-movements. They fall through to the muscle_up detection branch (anchored + articulated + hands overhead) which is wrong — a front lever has zero vertical shoulder travel (anchored), while a muscle_up has significant upward shoulder travel (transition).
- **Estimated Tokens**: 5000
- **Dependencies**: Task 1.2, Task 2.2
- **Steps**:
  - The current front_lever check (#1) is: anchored + hands_overhead > 35% + body_line_deg >= 70. This is correct for pure front lever.
  - Add a second, looser front_lever check *before* muscle_up: anchored + hands_overhead > 25% + body_line_deg >= 60 + `parked_frac >= HOLD_FRAC * 0.6` → classify as `front_lever` (tuck or straddle variant).
  - The key disambiguation from muscle_up: muscle_up requires `peak_above_hands >= OVER_BAR` (shoulders rise above hands). Front lever never has this signal (body hangs below hands). Keep this as the primary filter: if `peak_above_hands < OVER_BAR` AND body is horizontal → it's front_lever, not muscle_up.
  - If front_lever's loose check fires but `parked_frac` is low (< 0.33), return `("unknown", 0.40, "REP_OR_HOLD_AMBIGUOUS")` — the classifier sees a horizontal hang but can't confirm it's held.
  - Only if the body is NOT horizontal (body_line_deg < 60) and `peak_above_hands >= OVER_BAR` → proceed to muscle_up detection.
- **Acceptance Criteria**:
  - Front lever clips (tuck, straddle, straight) classified as `front_lever` (not `muscle_up`)
  - Real muscle_up clips still classified as `muscle_up` (no regression)
  - The 8 reviewed root clips maintain classification
  - `scripts/evaluate_technique_pipeline.py` shows front_lever→muscle_up errors eliminated

### Phase 3: Learned Classifier Growth
**Goal**: Grow the learned classifier from 7 classes (support=1 per class) to 13+ classes covering all exercises in the corpus, so it can serve as a meaningful second opinion where the geometric classifier abstains.

#### Task 3.1: Expand movement coverage and alias resolution for unmeasurable exercises
- **Location**: `barra/movements.py`
- **Description**: The learned classifier needs to know about classes it might predict. Currently, only 11 movements are defined. Bench press, deadlift, and handstand are not in the movement list (correctly — they can't be measured geometrically). The classifier should still be able to predict them as classes so it can "know" what they look like and separate them from the exercises it *can* measure.
- **Estimated Tokens**: 3000
- **Dependencies**: None
- **Steps**:
  - Add `bench_press`, `deadlift`, `handstand` to the 11 movements list with `is_measurable=False` flag
  - Update `resolve(name)` to recognize aliases for these new classes: bench_press → ["bench", "bench_press", "flat_bench", "chest_press"]; deadlift → ["deadlift", "dead_lift", "rdl", "conventional_deadlift"]; handstand → ["handstand", "hand_stand", "hs", "wall_handstand"]
  - Add `is_measurable` property to movement definitions — `True` for the original 11, `False` for bench_press, deadlift, handstand
  - Update `tracking_signal()` to return `None` for non-measurable movements (no signal is tracked)
  - Add `KNOWN_MEASURABLE` and `KNOWN_ALL` sets for quick classification
- **Acceptance Criteria**:
  - `resolve("bench")` → bench_press movement; `resolve("rdl")` → deadlift movement
  - `resolve("handstand")` → handstand movement
  - `movements["bench_press"].is_measurable` is `False`
  - `resolve("unknown_movement")` still causes SystemExit with known list
  - No regression on existing movement resolution tests

#### Task 3.2: Engineer new features for bodywork exercises
- **Location**: `barra/classify.py`, `barra/model.py`
- **Description**: The current 32 features are optimized for bar-based and ground-based calisthenics (dip, pull_up, squat). Handstand and bench_press need different features: body orientation stability, head position, arm extension angle, and lack of bar-relative geometry.
- **Estimated Tokens**: 5000
- **Dependencies**: Task 3.1
- **Steps**:
  - In `features()`, add new features:
    - `head_steady_frac` — fraction of window where head position variance < 0.05 torso-lengths (handstand: head is stationary; push_up: head moves)
    - `arm_extension_deg` — mean elbow angle across frames (handstand: ~170-180°; push_up: 90-160° oscillating)
    - `nose_mouth_ratio` — ratio of nose-to-ear distance to mouth-to-ear distance (face-on vs side-on camera helps identify handstand from the front)
    - `body_verticality` — complement of body_line_deg (1.0 = perfectly vertical; handstand: >0.95)
    - `bar_relative_present` — boolean feature indicating whether bar-relative geometry exists (True for bar exercises, False for handstand/bench)
  - Update `FEATURE_NAMES` in `barra/model.py` to include the new features (total ~37)
  - Ensure all new features default to sensible NaN-free values when landmarks are absent (e.g., `bar_relative_present=False` when no hands-overhead geometry)
- **Acceptance Criteria**:
  - New features are measurable for all exercises in the corpus
  - `len(FEATURE_NAMES) == 37` (or the actual new count)
  - No feature defaults to a value that would cause the model to confidently predict wrong (all absent-feature values use `_NAN = -50.0`)
  - `barra/classify.py` `features()` output dict has 37 entries

#### Task 3.3: Retrain the learned classifier on the full corpus (13 classes)
- **Location**: `scripts/train_model.py`, `barra/model.py`
- **Description**: The current model has 7 classes with support=1 per class — essentially memorizing, not learning. The full corpus (~168 clips across 14 movements) provides enough samples to train a meaningful model. Key challenges: class imbalance (push_up and pull_up will dominate), and the model being a single hidden layer with 24 units (may be insufficient).
- **Estimated Tokens**: 8000
- **Dependencies**: Task 3.2
- **Steps**:
  - Update `scripts/train_model.py` to:
    1. Load features from metadata.csv + sample_manifest.json (existing behavior)
    2. Filter to clips where the movement label resolves to a KNOWN movement via `barra/movements.resolve()`
    3. Group by resolved movement name and compute per-class sample counts
    4. Apply stratified sampling: if a class has < 3 samples, either oversample (repeat) or merge with a similar class (e.g., bench_press + deadlift → `bodywork` class; handstand → `handstand` with minimum 3 samples or excluded if < 3)
    5. Train softmax MLP with: hidden layer 32 units (up from 24), dropout=0.3 (numpy manual implementation), inverse-frequency weighting with cap at 5:1 ratio
    6. Run hyperparameter search: try hidden sizes [16, 24, 32, 48], dropout [0.0, 0.2, 0.3], learning rates [0.01, 0.05]
    7. Select best model by validation accuracy + per-class macro-F1
  - In `barra/model.py`, update `ExerciseModel.predict()` to:
    - Return class with max probability AND the probability value
    - If max probability < 0.5, return `("unknown", 0.0)` — the model abstains when uncertain
    - This makes the model a *honest* second opinion, not a confident wrong answer
  - Output: `models/exercise_model_v2.npz`, `model_metrics_v2.json`, updated feature cache
  - Keep old model as `models/exercise_model.npz` (do not overwrite) — the evaluation diff will compare v2 against the baseline
- **Acceptance Criteria**:
  - Model trained on all 13+ classes (or merged equivalents)
  - Validation accuracy > 0.60 (improvement from 0.60 on 7 classes with support=1)
  - Per-class accuracy > 0.30 for classes with >= 3 samples
  - Model abstains (returns `unknown`) when max probability < 0.5
  - Old model file preserved at `models/exercise_model.npz`
  - `scripts/train_model.py --no-live` reproduces the same model from cached keypoints

#### Task 3.4: Wire model abstention into the server pipeline
- **Location**: `server/process.py`, `barra/model.py`
- **Description**: The server's `analyze_clip()` currently uses the model prediction as a confidence score alongside the geometric classifier. The new model abstention must integrate cleanly — when the model returns `unknown`, it should not override the geometric classifier's verdict.
- **Estimated Tokens**: 3000
- **Dependencies**: Task 3.3, Task 1.1
- **Steps**:
  - In `server/process.py`, after geometric classification and before model classification, check if geometric classifier returned `unknown`:
    - If geometric says `unknown` with reason `REQUIRED_SIGNAL_MISSING` (from Task 1.3) → the model might still help (e.g., bench_press has no bar geometry but the model can recognize it from body position). Try model prediction.
    - If geometric says `unknown` with reason `VIEW_BLOCKED` or `ANKLE_VISIBILITY` → keep geometric's `unknown` — the model can't fix missing geometry either.
    - If geometric returns a confident label → use it as primary, model prediction as secondary signal (existing behavior).
  - When model also says `unknown` (max prob < 0.5), the final verdict is `unknown` with the geometric reason (or "geometric_unknown + model_uncertain" combined).
  - When model disagrees with geometric classifier: record the disagreement in the payload's `model_disagreement` field (existing mechanism). Do NOT override geometric.
  - Update payload structure if needed — add `geometric_reason` field to carry the `UnknownReason` through the pipeline.
- **Acceptance Criteria**:
  - `bench_press` clips classified as `bench_press` when the model predicts it (geometric abstains, model helps)
  - `handstand` clips classified as `handstand` when the model predicts it
  - Model disagreement is recorded but never overrides geometric classification
  - Server payload includes `geometric_reason` when geometric classifier abstains
  - `test_server_payload.py` passes with updated payload structure

### Phase 4: Evaluation and Testing
**Goal**: Verify all changes with the existing test suite, the evaluation pipeline, and new abstention-specific tests.

#### Task 4.1: Update existing tests and fix any regressions
- **Location**: `tests/`
- **Description**: The changes to `classify.py` (new return type, new features, new decision paths) will break existing tests. Fix all of them.
- **Estimated Tokens**: 8000
- **Dependencies**: All prior tasks
- **Steps**:
  - Update `tests/test_classify_quality.py` — expected classifications for known clips to match new behavior (squat stays squat, planche abstains, front_lever stays front_lever)
  - Update `tests/test_features.py` (or equivalent) — expect 37 features instead of 32, new feature names present
  - Update `tests/test_model.py` — expect model to have 37 inputs and 13+ outputs
  - Update `tests/test_dip_squat_abstention.py` — extend to test arm-forward-squat case (new test case)
  - Update `tests/test_evaluate_runner.py` — expect abstention counts in eval output
  - Ensure `python -m unittest` / `pytest` passes with zero failures
- **Acceptance Criteria**:
  - All existing tests pass after updates
  - New test cases cover: arm-forward squat, planche abstention, front_lever disambiguation, bench_press/deadlift/handstand model-assisted classification
  - No test overfits to specific clip labels — tests check behavior, not hardcoded outcomes

#### Task 4.2: Update evaluation pipeline to measure abstention quality
- **Location**: `scripts/pipeline_eval.py`, `scripts/evaluate_technique_pipeline.py`, `docs/PIPELINE-EVAL.md`
- **Description**: The existing evaluation scripts measure correct classification and misclassification. They need to also measure honest abstention (true positive for `unknown` labels on unmeasurable exercises) and distinguish abstention types.
- **Estimated Tokens**: 5000
- **Dependencies**: Task 4.1
- **Steps**:
  - In `scripts/pipeline_eval.py`, add abstention metrics:
    - `true_abstention`: geometric `unknown` on clips where `movement` in manifest is `unknown` or unmeasurable (bench_press, deadlift, handstand)
    - `false_abstention`: geometric `unknown` on clips where movement is a known, measurable exercise
    - `model_rescue`: geometric `unknown` + model confident prediction matches ground truth
  - In `scripts/evaluate_technique_pipeline.py`, add `abstention_quality()` function that computes:
    - True abstention rate: true_abstention / (true_abstention + false_abstention + misclassified)
    - Model rescue rate: model_rescue / (true_abstention + model_rescue)
  - Update baseline comparison (`diff-vs-baseline`) to include abstention metrics
  - Update `docs/PIPELINE-EVAL.md` with new evaluation methodology
- **Acceptance Criteria**:
  - `scripts/pipeline_eval.py` outputs abstention metrics alongside correct/misclassified counts
  - `scripts/evaluate_technique_pipeline.py` produces diff against saved baseline including abstention columns
  - Baseline saved at `out/baseline_v1.json` (or equivalent path)
  - Bench_press, deadlift, handstand classified as `unknown` by geometric alone (true abstention)
  - No regression: the 8 reviewed root clips maintain or improve classification

#### Task 4.3: Corpus-wide evaluation and regression check
- **Location**: `scripts/pipeline_eval.py`
- **Description**: Run the full evaluation on the corpus (~168 clips from `data/calisthenics/videos/` plus 8 reviewed clips) and verify that: (a) known exercises are not mislabeled, (b) unmeasurable exercises are abstained, (c) abstention rate on unmeasurable exercises approaches 100%.
- **Estimated Tokens**: 3000
- **Dependencies**: Task 4.2
- **Steps**:
  - Run `scripts/pipeline_eval.py` on all clips in `data/calisthenics/videos/` and `VID-*.mp4` root clips
  - Run `scripts/evaluate_technique_pipeline.py` with `--baseline out/baseline_v1.json`
  - Check confusion matrix: no non-zero entries for bench_press→dip, bench_press→muscle_up, deadlift→dip, deadlift→muscle_up, handstand→dip, handstand→muscle_up
  - Check that planche→push_up and front_lever→muscle_up confusion cells are zero or reduced
  - Check that squat→dip confusion cell is zero
  - Document results in `docs/PIPELINE-EVAL.md` with comparison table
- **Acceptance Criteria**:
  - All confusion-matrix cells for unmeasurable→measurable exercises are zero (geometric abstention works)
  - planche→push_up confusion cell is zero (or reduced by >50% if some dynamic planche clips are ambiguous)
  - front_lever→muscle_up confusion cell is zero
  - squat→dip confusion cell is zero (or reduced from current level)
  - Overall correct classification rate improves or stays same (no regression)

## Testing Strategy
- **Unit tests**: All files in `tests/` must pass via `python -m unittest discover` or `pytest`. New tests in `tests/test_abstention.py` cover: UnknownReason enum members, `_measurable()` for each exercise type, `features()` returns 37 features, `classify()` returns 3-tuple.
- **Integration tests**: `tests/test_e2e_pipeline.py` verifies end-to-end processing of a clip through classification → model → server payload. Updated to expect new payload structure.
- **Model tests**: `tests/test_model.py` verifies model loads, predicts, abstains when uncertain. New test: model on held-out set achieves >0.60 accuracy.
- **Evaluation**: `scripts/pipeline_eval.py` runs on full corpus, outputs per-clip traces. `scripts/evaluate_technique_pipeline.py` diffs against baseline, produces confusion matrix with abstention columns.
- **Regression guard**: The baseline saved at `out/baseline_v1.json` contains all 8 reviewed root clip results. Every PR must diff against this baseline and fail if any reviewed clip's classification regresses (correct→misclassified or correct→abstained becomes incorrect).

## Risks
- **Feature explosion with small corpus**: Adding 5 new features (37 total) to a single-layer MLP trained on ~168 clips risks overfitting. The model may memorize rather than generalize. Mitigation: use dropout=0.3, weight decay, and validate that per-class accuracy is not just training accuracy. If validation accuracy doesn't improve over 7-class model, revert to 7 classes but add abstention in the decision layer.
- **Self-critique: The arm-forward-squat fix (Task 2.1) relies on `shoulder_hand_relative_travel` and `arm_angle_frac`, which were not validated on real data. If the feature correlation between squats and dips is weaker than hypothesized, the fix may not eliminate the confusion. Plan: add a validation step in Task 4.2 that checks these features on a subset of arm-forward squat clips. If they don't separate, fall back to a simpler guard: if feet coverage is low AND the dip decision would fire, check whether the body is descending (hip_y increasing) — a dip has shoulder descent, a squat with arms-forward does not.**
- **Self-critique: The learned classifier's ability to distinguish bench_press from squat/dip depends entirely on whether the pose keypoints capture the bar position and torso angle. In many webcam-style clips, the bar is out of frame or the subject is too far from camera. If keypoints for bench_press clips look identical to squat keypoints (both show vertical torso with hip movement), the model cannot separate them. Plan: treat bench_press as a "merged" class with deadlift (both are ground-based bar exercises with no bar-relative geometry), and only predict this merged class when the model is confident. This reduces the number of classes but increases per-class support.**
- **View estimation failure**: The `estimate_view()` function in `evidence.py` relies on shoulder-width ratios. If the camera is frontal (shoulders parallel), the view estimate is UNKNOWN, which would mark all planar features as `view_blocked`. This could cause cascading abstentions. Mitigation: treat UNKNOWN view as "not blocklisted" rather than "all blocked" — only block features that explicitly require a known plane (knee_valgus requires frontal, torso_lean requires sagittal).
- **Hold-vs-rep ambiguity is not binary**: Some exercises genuinely have ambiguous hold/rep boundaries (e.g., a slow, controlled push_up with a 1-second pause at the top). The plan's "low-confidence hold" path returns `unknown`, which is correct but may reduce recall. This is an acceptable trade-off per the project's principle.

## Rollback Plan
- **Classifier changes**: Each phase's changes are additive (new enum members, new features, new decision branches). A single commit per phase can be reverted via `git revert`. The geometric classifier's decision tree structure means only the branches affected by each task need to be reverted.
- **Model changes**: The old model (`models/exercise_model.npz`) is preserved. Reverting `scripts/train_model.py` and `barra/model.py` to use the old model is a single-file revert. The new model is saved as `models/exercise_model_v2.npz`.
- **Test changes**: If tests break in unexpected ways, the baseline saved at `out/baseline_v1.json` can be restored from git, and the evaluation pipeline will flag regressions.
- **Breaking change mitigation**: The classifier return type change (3-tuple) is backward-compatible — existing code that unpacks `label, *_ = classify(...)` continues to work. The new `_feature_state` dict is additional, not replacing the existing float dict.

## Edge Cases
- **Camera angle extremes**: Side-on camera (90° azimuth) makes hand height comparisons unreliable. The `estimate_view()` function should return `OBLIQUE` and the classifier should treat height-dependent features (body_below_hands, shoulder_above_bar) as `view_blocked`.
- **Clips with no body visible**: If fewer than 5 landmarks are visible in >50% of frames, `features()` should return early with `unknown` and reason `LANDMARK_LOW_CONFIDENCE`.
- **Clips with multiple people**: If pose estimation detects multiple bodies, the classifier should process the largest body (highest landmark count) and note in the payload that multi-body was detected.
- **Very short clips (< 1 second)**: With a 3-second sliding window for anchor detection, clips shorter than 1 second may have insufficient data for any classification. Return `unknown` with reason `INSUFFICIENT_MOVEMENT`.
- **Clips that transition between exercises**: e.g., a person does a dip then a push_up. The current single-label classifier can only produce one label. The plan does not address this (out of scope). The classifier will produce the most dominant label. If the transition is 50/50, both the geometric and learned classifier may disagree — the model disagreement record captures this.
- **Clips with occluded hands**: If hands are occluded (e.g., holding weights, hands behind back), bar-relative measurements fail. The `view_blocked` state should propagate to all bar-relative features, and the classifier should abstain rather than guess.
- **Model predicting unmeasurable exercise when geometric disagrees**: If the geometric classifier says `squat` and the model says `bench_press`, the geometric verdict stands. The model's prediction is recorded as `model_suggestion: bench_press` with `model_confidence: 0.72` and `model_disagreement: true`. The final payload carries both.

## Open Questions
- **What is the minimum corpus size per class needed for the model to be useful?** With ~168 clips across 14 movements, many classes have < 5 samples. Should we merge similar classes (e.g., all standing bar exercises → `bar_standing`, all horizontal holds → `horizontal_hold`) to improve model reliability, accepting coarser predictions?
- **Should the server's vision model second opinion be used when the geometric classifier abstains?** Currently vision is a "last resort" for count estimation. Using it for classification would add cost (cloud call) which violates the offline constraint. However, if the vision model is cached or available locally, it could serve as a tiebreaker when both geometric and learned classifier abstain.
- **How should the system handle clips from data/calisthenics/ that have incorrect `trick` labels in metadata.csv?** The evaluation resolves labels via `movements.resolve()`, but if the ground truth is wrong, the evaluation metric is wrong. This is a data quality issue, not a code issue — but the plan assumes metadata.csv labels are correct for training the model.