# Plan

## Overview
Make the geometric classifier (`barra/classify.py`) abstain honestly (return `unknown` with a named reason) instead of confidently returning a wrong label, fix the three genuinely-fixable confusions (squat→dip, planche→push_up, front_lever→muscle_up) using already-computed, view-gated geometry, route unmeasurable catalogue movements to an early, declared-exercise abstention, and grow/retrain the learned second-opinion model (`barra/model.py`) on the cached corpus so it separates more classes and abstains rather than fabricating. All changes stay in the existing numpy/torch/ultralytics/mediapipe/opencv core, remain offline, and lean on the existing test suite plus a baseline-diffing evaluation runner.

## Scope
- **In**: `barra/classify.py` (abstention gates + fixed confusion branches), `barra/evidence.py` (view-assisted `View` threading; keep offline), `barra/model.py` (margin/support abstention in `model_classify`), `server/process.py` (declared-unmeasurable early abstention), `barra/movements.py` (only if a new measured profile is warranted; likely none), `scripts/train_model.py` (corpus growth, more classes), `scripts/pipeline_eval.py` (baseline snapshot/diff), tests.
- **Out**: any new third-party dependency; any cloud model in the measurement core; changing the reviewed `sample_manifest.json`; tuning thresholds against the reviewed manifest; auto-detecting equipment/extraneous movements (deadlift/bench_press) purely from geometry without a declared exercise.

## Phases

### Phase 1: Honest-abstention framework (foundation)
**Goal**: Give the classifier and the server the machinery to say `unknown` with a reasoned cause, and gate planar detection on a knowable camera view, without changing any label decision yet.

#### Task 1.1: Thread a `View` into `classify()` and gate planar geometry
- Location: `barra/classify.py` (`classify` signature, `features` doc, the front_lever/planche branches), `barra/evidence.py` (`View`, `UNKNOWN_VIEW`, `estimate_view`).
- Description: Add an optional `view: View | ViewInput | None = None` parameter to `classify(kp, trace=None, fps=30.0, view=None)`. Internally build a `barra.evidence.View` (via `UNKNOWN_VIEW` when `None`, `declared_view` when a bin string, else the supplied object) and expose `view.shows("sagittal")` to the horizontal-body branches. All existing call sites (`server/process.py:445`, `tests`) pass nothing → `UNKNOWN_VIEW`, so planar (`body_line_deg`, `horizontal_frac`, `legs_lifted_frac`-in-horizontal-context) gates **abstain** rather than guess when the view is unknowable. This directly implements "gated on a knowable camera view for planar quantities."
- Estimated Tokens: 1400
- Dependencies: none
- Steps:
  1. Import `UNKNOWN_VIEW`, `declared_view` from `barra.evidence`; add `View` typing adapter in `classify.py`.
  2. Add `view = _coerce_view(view)` and a `_sagittal = view.shows("sagittal")` helper at the top of `classify`.
  3. Where the front_lever / planche body-line tests use `body_line_deg`/`horizontal_frac`, require `_sagittal` before accepting them; otherwise skip to the "hold/abstain" outcome (Phase 3 uses this hook).
  4. Record `view_bin`, `view_knowable`, `view_why` in the trace gate step.
- Acceptance Criteria:
  - `barra/classify.py` imports cleanly; `classify(kp)` and `classify(kp, fps)` behave exactly as before (no view → `UNKNOWN_VIEW`).
  - A new unit test (in `tests/test_abstention.py`) asserts that with `view=UNKNOWN_VIEW` a synthetic horizontal-hold clip yields `unknown` (or a hold-reject), never `push_up`/`muscle_up`; with a knowable `view` and the correct geometry it classifies as `planche`/`front_lever`.

#### Task 1.2: Declared-unmeasurable early abstention in the server
- Location: `server/process.py` (`analyze_clip`, at/around the `requested` block ~line 103 and before `classify` ~line 445).
- Description: When `exercise` is a declared catalogue entry (not `auto`) and `barra.exercises` marks it `measurable: false`, return the empty/unknown payload immediately with a named blocker — do not run geometry and do not let a deadlift/bench_press/handstand fall into the dip/muscle_up/push_up branch. Because the app always sends the athlete's chosen exercise, this is the guaranteed fix for the "unmeasurable movement reported as a confident wrong movement" class.
- Estimated Tokens: 900
- Dependencies: Task 1.1
- Steps:
  1. After `requested` is computed and before `classify`, do `ex = exercises.get(requested)`.
  2. If `ex is not None and not ex.measurable`: `tr.reject("measurement", ...)` and `return _empty(requested, [f"barra cannot measure {ex.name_en or requested}: the catalogue marks it not measurable"], detected=None, ...)`. Guard with `try/except` so a catalogue error never sinks a job.
  3. Keep auto-mode behaviour unchanged (no declared entry → geometry runs).
- Acceptance Criteria:
  - `analyze_clip(clip, exercise="bench_press")` returns `exercise="bench_press"`, `detected=None`, a blocker naming "not measurable", `n_reps=0`.
  - Same for `deadlift`, `handstand`; `squat`/`push_up` still run geometry.
  - A unit test added in `tests/test_server_payload.py` (or a new `test_declared_abstention.py`) covers this without a video (mock `pose`/`classify` so no geometry runs).

#### Task 1.3: Pure-auto abstention fallback hardening
- Location: `barra/classify.py` final `unknown` fallback (~line 799) and the existing named-reason rejects.
- Description: Ensure the "no branch matched" fallback names the closest candidates and returns `unknown`/`0.0` (already the pattern), and that `runner_up` is always the honest alternative (e.g. a handstand candidate is `runner_up="push_up"` only when the geometry genuinely entertained it). No new dependency.
- Estimated Tokens: 500
- Dependencies: Task 1.1
- Steps:
  1. Audit every `return Classification("unknown", ...)` and confirm the reason names the condition and the runner-up names the plausible alternative.
  2. Confirm no `unknown` path returns a non-zero confidence.
- Acceptance Criteria:
  - Every `unknown` return has `confidence == 0.0` and a non-empty `reason`.
  - A test asserts `classify(...).certain is False` for every `unknown` result.

---

### Phase 2: Fix squat→dip (planted-feet / hip-travel discriminator)
**Goal**: Stop arm-forward squats (feet partly visible, so the current never-seen-feet guard does not fire) being reported as `dip`.

#### Task 2.1: Reclassify hands-below + large hip-travel as squat, not dip
- Location: `barra/classify.py` dip/push_up branch (lines ~722–777), constant near `BELOW_HANDS_DIP` (~line 76).
- Description: In the `below >= BELOW_HANDS_DIP` path, order the decision: (1) if the feet were never clearly seen → keep the existing `unknown` abstention (already present); (2) else if `hip_travel` is finite and `>= hip_travel_min` (a squat's hips move ~0.6 torso-lengths against planted feet) → classify `squat` with the reason naming planted feet + arms held forward; (3) else → classify `dip` (feet hang with the body, so `hip_over_ankle` stays ~constant and `hip_travel ≈ 0`). `hip_travel` is already in `features()`. Add a constant `SQUAT_HIP_TRAVEL_MIN = 0.35` (mirrors the pistol/squat hip-travel gate).
- Estimated Tokens: 1000
- Dependencies: Task 1.1
- Steps:
  1. Add `SQUAT_HIP_TRAVEL_MIN = 0.35`.
  2. In the dip branch, after the unseen-feet guard, branch on `f["hip_travel"]`; call `tr.decision("squat", ...)` and `Classification("squat", 0.74, reason, f, runner_up="dip")`.
  3. Keep the reason interpretable: name measured `hip_travel` and the planted-feet interpretation.
- Acceptance Criteria:
  - `tests/test_classify_quality.py::test_dip_and_squat` and `test_push_up_is_a_dip_lying_down` stay green (dip fixture keeps hip_travel small).
  - New `tests/test_abstention.py` fixture `arm_forward_squat_clip()` (planted feet, hands fixed-forward below shoulders, hips travelling) → `classify(...).exercise == "squat"`, `runner_up == "dip"`.
  - The existing `test_visible_hanging_feet_still_a_dip` fixture keeps feet hanging with the body so `hip_travel` stays low; its assertion (`!= unknown`) still holds. Update the fixture description, not the reviewed manifest.

---

### Phase 3: Fix planche→push_up, front_lever→muscle_up, and auto-abstain on handstand/inversions
**Goal**: Distinguish horizontal holds (planche/front_lever) from rep movements by legs-lifted + view-gated body-line + parkedness, and route unrecognised inversions to `unknown` instead of a confident rep label.

#### Task 3.1: Recognise horizontal holds before the rep branches
- Location: `barra/classify.py` front_lever (lines ~565–589) and planche branches; add a pre-split hold gate before line 629.
- Description: Strengthen the two existing hold branches so a held planche/front_lever that fails the strict single-threshold body-line test still ends as a hold, not as `push_up`/`muscle_up`:
  - front_lever: `anchored and hands_overhead_frac≥0.35 and (_sagittal and (body_line_deg≥70 or horizontal_frac≥0.5))`; if `_sagittal` is false or geometry is borderline, fall to a hold-reject with the named ambiguity instead of `muscle_up`.
  - planche: `anchored and hands_below_frac≥0.80 and legs_lifted_frac≥0.5 and (_sagittal and (body_line_deg≥70 or horizontal_frac≥0.5))`.
  - Insert a gate before the muscle_up/pull_up split (line ~629): if `parked_frac >= HOLD_FRAC` (a static, not a set) → reject as a hold/`unknown` rather than letting a static front-lever read as `muscle_up`.
- Estimated Tokens: 1300
- Dependencies: Task 1.1
- Steps:
  1. Refactor the front_lever/planche conditions to use a shared `_horizontal = _sagittal and (body_line_deg >= 70.0 or horizontal_frac >= 0.5)` helper.
  2. Insert the parked-hold gate immediately before the muscle_up/pull_up branch (line ~629).
  3. Every new hold/abstain path returns `zero` confidence + a named reason.
- Acceptance Criteria:
  - `tests/test_abstention.py`: `planche_clip()` (knowable view, hands below, legs lifted, body horizontal) → `planche`; the same clip under `UNKNOWN_VIEW` → `unknown` (not `push_up`).
  - `front_lever_clip()` (okay view, hands overhead, body horizontal, parked) → `front_lever`; a parked front-lever with an unknowable view → `unknown` (not `muscle_up`).
  - `test_dip_and_squat`, `test_push_up_is_a_dip_lying_down` stay green.

#### Task 3.2: Legs-lifted gate in the push_up branch (handstand/inversion → unknown)
- Location: `barra/classify.py` push_up branch (lines ~770–777).
- Description: When `below < BELOW_HANDS_DIP` (the push_up candidate), check `legs_lifted_frac`. If the legs are carried off the ground (`legs_lifted_frac >= 0.5`), this is not a push-up: if `_sagittal` and horizontal → `planche`; else → `unknown` (`"hands on the floor but the legs/wrists carried up - an inversion or hold barra does not measure"`, `runner_up="push_up"`). Feet planted (`legs_lifted_frac` low) stays `push_up`. This routes handstands away from a confident `push_up`.
- Estimated Tokens: 700
- Dependencies: Task 1.1, Task 3.1
- Steps:
  1. Add the `legs_lifted_frac` branch inside the push_up outcome.
  2. Confirm `pushup_clip()` (ankles below hips) keeps `legs_lifted_frac` low → still `push_up`.
- Acceptance Criteria:
  - `handstand_clip()` (hands on floor, legs above hips, body vertical, anchored) → `unknown` (not `push_up`), `runner_up="push_up"`.
  - Existing `test_push_up_is_a_dip_lying_down` green.

---

### Phase 4: Grow and retrain the learned classifier, with honest abstention
**Goal**: Turn the weak 7-class 0.6-accuracy model into a better-separated second opinion over more classes, and make it abstain (say `unknown`) instead of forcing a confident wrong class.

#### Task 4.1: Posed/featurised full-corpus cache
- Location: `scripts/pipeline_eval.py`, `out/keypoints/`, `out/model_features/features.csv`.
- Description: Run the cached (offline) pass over the whole corpus so every trick's keypoints are in `out/keypoints/` and its features in `out/model_features/features.csv`, so `train_model.py --no-live` retrains deterministically without a cloud call.
- Estimated Tokens: 600
- Dependencies: none
- Steps:
  1. `BARRA_POSE_BACKEND=ultralytics python scripts/pipeline_eval.py --no-nan` (uses `get_backend("ultralytics")`, caches via `posecache.store`).
  2. Confirm feature cache row count grows to the measured classes (knee_raise 20, push_up 15, pull_up 14, planche 13, pistol_squat 12, front_lever 10, squat 9, muscle_up 8, dip 8, split_squat 1, bulgarian 1).
- Acceptance Criteria:
  - Feature cache and keypoint cache exist for the counted clips; no cloud/vision calls made.

#### Task 4.2: Add margin/support abstention to the model
- Location: `barra/model.py` (`model_classify`, `predict`).
- Description: `model_classify` should return an honest abstention when the model is not sure: if the top-class probability is below `MODEL_ABSTAIN_PROB` (e.g. 0.55) **or** the margin to the runner-up is below `MODEL_ABSTAIN_MARGIN` (e.g. 0.08) **or** the class's holdout support is `< 3`, set `exercise="unknown"` and `abstained=True` with a `reason`. This keeps the model a second opinion that never fabricates a verdict, per project principle.
- Estimated Tokens: 700
- Dependencies: Task 4.1
- Steps:
  1. Add the constants and the abstention check in `model_classify`.
  2. Thread per-class support (from `models/model_metrics.json` or the `train` call) so the abstention can reference it.
  3. Keep `detected` authoritative: the server already ships `model` separately, so an abstaining model is presented as such.
- Acceptance Criteria:
  - `tests/test_model.py` gains a case: a near-flat probability vector returns `exercise="unknown"`, `abstained=True`.
  - The `save/load` roundtrip still passes.

#### Task 4.3: Retrain on more classes + data
- Location: `scripts/train_model.py`, `models/exercise_model.npz`, `models/model_metrics.json`.
- Description: Retrain with the grown cache: raise `--per-trick` for classes with support, add the split_squat/bulgarian classes (or merge them into a `split_squat` family if support stays at 1), and add the measured classes the model currently lacks (pull_up currently has 14 clips but may be missing from the class list). Include unmeasurable clips (deadlift/bench_press/handstand) as a learned `unknown`/`withheld` class so the model can predict abstention. Keep numpy-only, deterministic seed.
- Estimated Tokens: 900
- Dependencies: Task 4.2
- Steps:
  1. Update `train_model.py` to (a) expand `--per-trick`, (b) label unmeasurable clips as a self-abstaining class (e.g. label `"unknown"`) so the model learns to say unknown, (c) report per-class support so classes with support 1 are flagged.
  2. Retrain: `python scripts/train_model.py --no-live --per-trick 20 --epochs 400`.
  3. Review `model_metrics.json` per-class recall; raise support by merging split/bulgarian or gathering more clips; do not treat support-1 classes as evidence.
- Acceptance Criteria:
  - `model_metrics.json` classes cover the measured 11 plus an `unknown`; no class with support 1 is reported as 100%.
  - `tests/test_model.py` stays green; holdout accuracy is reported with support.

---

### Phase 0: Baseline snapshot (do first)
**Goal**: Capture the current state so the improvement is measurable and no regression hides.
- Location: `out/`, `scripts/pipeline_eval.py`.
- Description: Before editing, run the current evaluator on the corpus and save `report.json`/`results.json` to a dated baseline dir (mirroring `scripts/evaluate_technique_pipeline.py`'s `diff_against_baseline`). Then extend `pipeline_eval` with optional `--snapshot <dir>` and `--baseline <dir>` so post-change runs diff per-clip `detected`/`abstained`/`misclassified`.
- Acceptance Criteria:
  - A saved baseline exists; `--baseline` produces a `diff` report (changed/abstained/misclassified counts) without mutating the reviewed manifest or the baseline dir.

## Testing Strategy
- **Unit (fast, offline)**: new `tests/test_abstention.py` with synthetic `(T,17,3)` fixtures: `arm_forward_squat_clip`, `planche_clip`, `front_lever_clip`, `handstand_clip`, `hanging_feet_dip_clip`; assertions per Phase 2/3 acceptance criteria. Extend `tests/test_classify_quality.py` where cheap.
- **Model**: extend `tests/test_model.py` for the abstention; keep `test_train_and_predict`, `test_deterministic`, `save/load` green.
- **Server**: `tests/test_declared_abstention.py` (mock pose) asserting declared-unmeasurable → abstain, declared-measurable → geometry runs; `tests/test_server_payload.py` unchanged.
- **Full suite**: `python -m unittest` (run from `tests/` with the working venv) must stay green before and after each phase.
- **Repeatable evaluation**: `BARRA_POSE_BACKEND=ultralytics python scripts/pipeline_eval.py --no-nan --baseline <snapshot>` and compare `misclassified`, `abstained`, `correct` per trick. Success = unmeasurable tricks (deadlift/bench_press/handstand) move from `misclassified` to `abstained`, the three confusion classes improve TP, and the reviewed 8-clip baseline (`scripts/evaluate_technique_pipeline.py` vs `out/pipeline-improvement`) shows no intended regression.

## Risks
- **View-gating may turn planche/front_lever into `unknown` on real clips** if `estimate_view` often returns `not knowable`. Mitigation: make the hold-reject honest (never mislabel), and bias the eval success metric to "no mislabel" (abstained) over "detected planche" where the view is unknowable; document this in `docs/PIPELINE-EVAL.md`.
- **The `hip_travel` squat reclassification could catch an unusual dip** if its ankles produce a large `hip_over_ankle` spread; robust percentiles already guard against single stray frames. Mitigation: keep the gate at 0.35 (the same as the squat/pistol gates) and cover with a hanging-feet dip fixture.
- **Phase 4's learned `unknown` class can swallow real movements** if the model over-abstains. Mitigation: abstention thresholds are conservative and per-class support is reported; the model stays a second opinion (`detected` is authoritative) so a model over-abstention is a review signal, not a wrong verdict.
- **Self-critique 1**: Phase 3 uses `legs_lifted_frac` and `body_line_deg`, both of which are themselves planar/sagittal quantities that depend on the camera plane; my view-gating falls back to `UNKNOWN_VIEW` which by design makes those abstain, so on many real-facing clips the "fix" degrades to `unknown` for planche/front_lever rather than detecting them. That is a real trade: it satisfies "never mislabel" but not "correctly classify every one," and my plan does not fully resolve the viewpoint problem — the note in `docs/PIPELINE-EVAL.md` says this is genuinely a viewpoint problem, and I am not claiming to have a viewpoint estimator that is more accurate than the existing one.
- **Self-critique 2**: I lean on the declared-exercise abstention (Phase 1.2) for deadlift/bench_press/handstand, but `scripts/pipeline_eval.py` and any "auto" caller pass `exercise="auto"`, so the auto geometry path can still return a wrong label for those tricks unless Phase 3's gates fire. My plan does not fully close the auto-mode hole for deadlift/bench_press (a deadlift genuinely looks squat-like: planted feet + large hip travel + rigid arms), and I am deferring that to the declared-exercise path rather than adding hinge-detection geometry that risks over-fitting to the scraped metadata.

## Rollback Plan
- Each phase is a revertible commit: `git checkout barra/classify.py barra/evidence.py barra/model.py server/process.py scripts/*.py tests/*.py` restores the previous behaviour.
- The learned model is regenerated: `python scripts/train_model.py --no-live --per-trick 12` restores the prior 7-class baseline; keep the prior `models/exercise_model.npz` backed up as `*.bak` before retraining.
- Baselines are never mutated (snapshots are write-only in a dated dir); the reviewed `sample_manifest.json` and `metadata.csv` are untouched, so `scripts/evaluate_technique_pipeline.py` diffs remain valid.

## Edge Cases
- **NaN satisfaction**: every new gate (`hip_travel`, `legs_lifted_frac`, `body_line_deg`, `horizontal_frac`) must `np.isfinite`-check first; a branch is never satisfied by a measurement that was never taken (the codebase's explicit invariant). Add tests where the ankle/hip landmarks are unseen (confidence 0) to confirm the branch abstains.
- **Feet partly visible yet present**: Phase 2 works because `hip_travel` uses robust percentiles over frames where the ankle midpoint was seen, so it does not require a stable planted window — directly the failure described in `docs/PIPELINE-EVAL.md`.
- **Walking prefix/suffix**: the anchored-window scoping already exists; the new gates reuse `on_bar_frac`/`parked_frac`, so adding a standing walk-in cannot flip a hold into a rep (guarded by `tests/test_segmentation_invariants.py`).
- **Zero/very short clips and degenerate torso**: `robust_torso` raises on fully degenerate keypoints; the new gates sit after that, so they never see an unusable skeleton, and the existing `SystemExit` path is preserved.
- **Multi-model vision disagreement**: `nan` label disagreements remain a review signal (`nanAgreesWithGeometry`); the geometry changes must not treat a nan label as ground truth (constraint already encoded in `pipeline_eval.py`).

## Open Questions
- Should `barra/movements.py` gain a new measured profile for `handstand` (it is currently `measurable: false` in the catalogue)? This determines whether handstand is abstained or measured — the task asks for abstention, so I assume no new profile, but a reviewer may want to measure it later.
- Is it acceptable for auto-mode deadlift/bench_press to remain restricted to the declared-exercise abstention, or must auto geometry detect the hinge/barbell (which would need equipment cues not in the current model and risks over-fixing)? This is the one place the plan deliberately does not guarantee "classify every clip."