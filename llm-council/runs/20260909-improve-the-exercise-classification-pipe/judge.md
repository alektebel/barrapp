I'll start by exploring the codebase to verify the technical claims in the plans before evaluating them.Let me read the remaining key files to verify the plans' technical claims.Now let me examine the scripts, server, and docs to verify the evaluation/pipeline claims.Let me examine the server, config, tests, and data to verify the remaining claims.Let me check the tests directory, the manifest, and data structure to verify the remaining claims.Let me examine the corpus metadata and the baseline-evaluation script.I have enough context to evaluate the plans. Let me verify one final detail about the existing test fixtures and feature count.The evaluation is complete. Here is my judge report.

# Judge Report

## Scores
- Plan 1: 7.0/10
- Plan 2: 8.7/10
- Plan 3: 6.3/10

## Comparative Analysis

**Scope fit.** The dominant stated bug — 57 of 168 metadata clips (34%) are movements the geometry does not measure (deadlift 14, barbell_squat 10, bench_press 8, human_flag 10, back_lever 9, handstand 6) yet are currently confidently mislabelled. Plan 2 is the only plan that closes this *in auto mode* (where `scripts/pipeline_eval.py` and any auto caller pass `exercise="auto"` and still run geometry): it adds three-valued REJECT-only guards (inverted = handstand, supine = bench, hinge = deadlift). Plan 1 explicitly defers the auto hole (self-critique 2, open question) — a real gap. Plan 3 relies on `_measurable()` + the model, which is not robust and risks misclassifying bench/deadlift as squat-like or dip-like.

**Design fit.** Plan 3 is the weakest here. It proposes an `UnknownReason` enum + 3-tuple return, but the codebase **already** has a three-valued, reason-carrying `Classification` dataclass with `.exercise/.confidence/.reason/.runner_up/.certain` (barra/classify.py:125) and every existing abstention already returns `Classification("unknown", 0.0, <reason>)`. Plan 3's refactor is churn that breaks the existing convention. Plan 3 also proposes adding `bench_press/deadlift/handstand` to `barra/movements.py` with `is_measurable=False` — this violates the documented separation (`movements.py` = *what barra CAN measure*; `exercises.py`/catalog = *what the app shows*, `measurable` flags live there). Adding them would break `resolve()`/`movement.origin`/`tracking_signal()` invariants. Plan 2 explicitly keeps them out of `movements.py`, which is correct.

**Fix quality (the three confusions).** Plan 2's three-valued feet verdict (planted / carried / unknowable) is the most principled discriminator for squat-vs-dip *and* planche-vs-push-up; it also correctly identifies the existing dip fixture as physically inconsistent (planted feet + hips below them *is* squat geometry) and fixes it. Plan 1's `hip_travel` discriminator is feasible (already computed, line 451) and simple, but alone it can't distinguish a "carried" foot (dip) from a "planted" foot (squat) unless it shells out to feet evidence anyway. Plan 3's arm-angle/relative-travel features are untested against real data (self-acknowledged). For front_lever vs muscle_up, Plan 2's anchored-window `horizontal_frac` correctly handles the vertical-hang-prefix fall-through that Plan 1 and Plan 3 do not address.

**View gating.** The review manifest's 8 clips are all `view: UNKNOWN`, so pure view-gating (Plan 1) would abstain planche/front_lever even when fixable — it is honest but fails the "genuinely fixable" requirement. Plan 2 reconciles this: gate on knowable view *for the deciding quantity*, but place thresholds in measured gaps so a genuinely sagittal clip still gets detected; abstain only when the data cannot support the plane.

**Model growth.** Requirement 3 favours more classes. Plan 3's 13-class / 37-feature growth is ambitious but overfits (support-1 classes, 168 clips); Plan 1 adds an `unknown` self-abstaining class + margin/support abstention; Plan 2 keeps the model advisory with a deterministic 5-fold CV and a 0.40 abstain threshold and does **not** pollute `movements.py`. The best synthesis: predict the unmeasured movements as *model* classes (labels come from the metadata `trick` column, not `movements.py`), merge low-support classes, and keep ablation on margin+support.

**Conciseness / verbosity.** Plan 3 is the longest and much of it is (a) redundant with existing structures and (b) counterproductive (movement pollution, feature explosion). Plan 2 is thorough, and its verbosity buys value: measured-gap-first threshold discipline, does-not-fire-on-neighbors regression guards, and self-critiques that name real degrades.

## Missing Steps
- **Auto-mode honesty for unmeasurable movements** is the #1 requirement and Plan 1/3 under-serve it. Must add geometric guards (inverted/supine/hinge) or an equivalent that fires when `exercise="auto"`.
- **Anchored-window `horizontal_frac` for front_lever** — Plans 1/3 gate on whole-clip median body line, so a vertical setup/prefix falls through to `muscle_up`/`pull_up`.
- **Fix the physically-inconsistent dip test fixture** (Plan 2 only) and add a not-fire-on-neighbors guard battery (`tests/test_split_stance.py`, `test_segmentation_invariants.py` must stay green).
- **Threshold provenance**: record measured gaps, never silently re-tune after labels are seen (the repo's `validate` fingerprints config).
- **Assert the eval cannot hide a recall regression**: previously-correct→abstained flips must be flagged as flips, not counted as improvement.
- **Reviewed-8 manifest accounting** for the two unmeasured clips `WA0017` (inverted `unknown`) and `WA0018` (abstention) — Plan 2 is the only one that names both.

## Contradictions
- **Plan 3 vs the codebase**: `UnknownReason` enum + 3-tuple duplicate the existing `Classification` contract; adding unmeasured movements to `barra/movements.py` contradicts `movements.py`'s documented role and breaks `resolve()`/tracking invariants.
- **Plan 1 vs its own requirement**: it wants planche/front_lever "fixed" but its view-gating degrades them to `unknown`; its declared-abstention covers only declared-unmeasurable, leaving the auto hole it flags in its open question.
- **Plan 1 vs Plan 2 on squat/dip**: `hip_travel`-only (Plan 1) vs feet-verdict (Plan 2). The feet verdict is a superset — hip collapse is the secondary signal inside the planted case.
- **Plan 3 model classes vs Plan 2 design rule**: adding bench/deadlift/handstand as `movements` (Plan 3) conflicts with keeping them out of `movements.py` (Plan 2); the correct source for model classes is the metadata `trick` label.

## Improvements
- Evaluate plans **only against the actual code state**, not the brief: the model is 7-class/32-feature, `MOVEMENTS` is 11, `FEATURE_NAMES` is 32, and the abstention plumbing already exists via `Classification`. Any plan that assumes a bare 3-tuple or an uninstrumented classifier is off-target.
- Fix the metric that matters: `fabricated` (a confident wrong label on an unmeasurable movement) must go to 0; separate `correct` / `honestAbstention` / `fabricated` so abstention can't inflate the headline.
- Consolidate view-gating with measured-gap placement so a sagittal clip still *detects* planche/front_lever rather than always abstaining.
- Keep the model advisory but let it name unmeasured movements (as `model.classification`, never `detected`), so a handstand/bench clip that geometry abstains on still gets a useful *advisory* suggestion.

## Final Plan

# Plan

## Overview
Make the geometric classifier abstain honestly (return `unknown` with a named `reason`, never a confident wrong label) across the whole corpus, including when the caller is `exercise="auto"`; fix the three genuinely-fixable confusions (squat→dip, planche→push_up, front_lever→muscle_up) with view-gated, three-valued evidence; and grow/retrain the learned second-opinion model so it separates more classes and abstains rather than fabricating — all offline, in the existing numpy/ultralytics core, verified by the current suite plus a baseline-diffing evaluator. The core principle — measure what you can, abstain honestly, never report a fabricated verdict — becomes structurally enforced.

## Scope
- **In**: `barra/classify.py` (three-valued feet verdict, view gating, hold-before-rep reordering, unmeasurable-shape guards, abstention reasons), `barra/evidence.py` (view-assisted `View` threading; primitives & `split_depth` stay planar-gated), `server/process.py` (declared-unmeasurable early abstention), `barra/model.py` (model abstention threshold, deterministic CV, advisory `model.classification`), `scripts/train_model.py` (full-corpus offline retrain, class merge rule), `scripts/pipeline_eval.py` + `scripts/evaluate_technique_pipeline.py` (baseline snapshot/diff, `correct`/`honestAbstention`/`fabricated` buckets), `tests/` (fixtures + regression guards), `docs/PIPELINE-EVAL.md` + `docs/MODEL.md`.
- **Out**: any new third-party dependency; any cloud model in the measurement core; new movements in `barra/movements.py` (bench/deadlift/handstand stay unmeasured by design); changing `data/evaluation/sample_manifest.json` or `data/calisthenics/metadata.csv`; tuning thresholds against the reviewed labels.

## Phases

### Phase 0: Baseline snapshot (do first)
**Goal**: capture current behaviour so every later phase can prove improvement and catch regressions.

#### Task 0.1: Snapshot evaluator baselines
- Location: `scripts/pipeline_eval.py`, `out/pipeline-eval/baseline-<date>/`, `out/pipeline-improvement/`
- Description: run the unchanged pipeline over the corpus with cached keypoints (`--no-nan` for determinism) and save per-clip summaries + a `baseline.json` index; confirm the 8 reviewed clips still diff against `out/pipeline-improvement/*-before.json`.
- Steps:
  - Add `--summary-out <dir>` writing one summary per clip (`trick`, `detected`, `detectedReason`, `nReps`, `modelClass`, `detected==unknown`) plus `baseline.json`.
  - Run `python scripts/pipeline_eval.py --no-nan --summary-out out/pipeline-eval/baseline-<date>/`.
- Acceptance Criteria:
  - One summary per clip + `baseline.json`; idempotent re-run; `evaluate_technique_pipeline.py --baseline out/pipeline-improvement` emits a `diff-vs-baseline.json` with zero changed clips before any code change.

### Phase 1: Honest abstention for unmeasurable movements
**Goal**: bench press, deadlift, handstand, human_flag, back_lever, barbell_squat, and machine work return `unknown` with a named reason — never a confident wrong label — in **both** declared and `auto` mode.

#### Task 1.1: Declared-exercise abstention via the catalog
- Location: `server/process.py`, `barra/exercises.py`, `tests/test_server_payload.py`
- Description: in `analyze_clip` (process.py:476-486), after `resolve(chosen)`, look up `exercises.get(chosen)`; if the row exists and `measurable` is `False`, return `_empty` with a named blocker (`"<id> is not measurable from video — coaching content only"`), `detected=None`, and `abstained: "declared-unmeasurable"`. Never fires for `exercise="auto"`.
- Steps:
  - Add `barra.exercises.measurable_by_id(exercise_id) -> bool | None` (None = not in catalog).
  - Gate before the hold/rep path; `tr.reject("declared unmeasurable", exercise=chosen)`. Guard with `try/except`.
- Acceptance Criteria:
  - `analyze_clip(clip, exercise="bench_press")` never returns a measured movement/count/score; the blocker names the catalog row. `exercise="dip"` unaffected. Full suite + reviewed-8 baseline diff unchanged.

#### Task 1.2: Auto-mode geometric guards for unmeasurable shapes (the critical one)
- Location: `barra/classify.py` (`features`, `classify`), `tests/test_classify_abstention.py` (new)
- Description: three REJECT-only guards placed **before** the bar branches, each three-valued (fires only when its landmarks were measurably seen; never fires on NaN):
  - **inverted** (handstand family): `inverted_frac` = share of frames with hips > 0.3 torso above the shoulders and wrists below hips; ≥ ~0.5 → `unknown` "inverted support — not a measured movement".
  - **supine press** (bench family): `knee_over_hip >= KNEES_UP` AND `body_line_deg >= 60` AND hands not overhead → `unknown` "supine pressing geometry — not a measured movement".
  - **hinge** (deadlift/row family): feet planted, median `torso_tilt >= 40°`, wrists below hips → `unknown` "hinge pattern — not a measured movement". Verify the threshold sits in a measured gap below the squat's tilt before shipping.
- Steps:
  - First measure: script a throwaway pass over `out/keypoints/*.parquet` printing the candidate features per trick; place each threshold in the measured gap and comment the numbers (codebase style).
  - Implement guards returning `Classification("unknown", 0.0, <named reason>, runner_up=<plausible>)`.
  - Add synthetic fixtures that fire each guard, plus parallel fixtures for dip/squat/push_up/knee_raise proving the guards do **not** fire (regression guard).
- Acceptance Criteria:
  - Each guard fires on its family fixture and does not fire on the 11 measured-movement fixtures in `tests/test_classify_quality.py`. Full suite green; corpus re-run (Phase 4) shows bench/deadlift/handstand moving from misclassified→abstained, with no measured movement newly abstained. `fabricated` starts dropping toward 0.

#### Task 1.3: Thread `View` and gate planar quantities
- Location: `barra/classify.py` (`classify` signature, `features` doc), `barra/evidence.py` (`View`, `UNKNOWN_VIEW`, `estimate_view`)
- Description: add `view: View | str | None = None` to `classify`; build a `barra.evidence.View` (`UNKNOWN_VIEW` when None, `declared_view` when a bin string, else the object). Expose `view.shows("sagittal")` to the horizontal-body branches; gate `body_line_deg`, `horizontal_frac`, and `legs_lifted_frac`-in-horizontal-context on it. When the plane is not knowable, do not guess: fall to the honest abstention path (Phase 3 hook), never to a rep label. Existing callers (process.py:445, tests) pass nothing → `UNKNOWN_VIEW`.
- Acceptance Criteria:
  - `classify(kp)`/`classify(kp, fps)` behave exactly as before; a synthetic horizontal-hold clip under `UNKNOWN_VIEW` yields `unknown` (never `push_up`/`muscle_up`); under a knowable sagittal `view` with correct geometry it classifies `planche`/`front_lever`. Record `view_bin`/`view_knowable`/`view_why` in the trace gate step.

### Phase 2: Fix the three measured confusions
**Goal**: settle squat-vs-dip, planche-vs-push_up, front_lever-vs-muscle_up with knowable evidence; abstain only when the deciding measurement is genuinely ambiguous.

#### Task 2.1: Squat vs dip — three-valued feet verdict
- Location: `barra/classify.py` (squat branch ~711, dip branch ~722), `tests/test_dip_squat_abstention.py`, `tests/test_split_stance.py`
- Description: compute a feet verdict — `planted` (stable-window gate), `carried` (ankles seen ≥ `MIN_SEEN` but window travel > `ANCHOR_FIXED` — feet move with the set, as a dip's dangling feet do), `unknowable` (seen < `MIN_SEEN`). Add `hip_ankle_min` = minimum hip-over-lower-ankle during the set (reuse `evidence.hip_above_ankle` logic). Rules:
  - squat branch: accept `rigid_arms or articulated` when feet are knowably planted AND hips collapse toward them (`hip_ankle_min` below a measured threshold) — this captures arm-forward squats.
  - dip branch: require feet `carried`; if `unknowable` keep the existing abstention; if planted but hips do NOT collapse → abstain as ambiguous dip-or-squat.
  - The dip branch's `hip_travel` (already at classify.py:451) is a secondary confirm inside the planted case, not the primary signal.
- Steps:
  - Measure `hip_ankle_min` and ankle window travel on cached squat/dip clips; document measured gaps.
  - Implement; update the dip fixture to a physically consistent **carried-feet** dip (current fixture has planted feet + hips below — squat geometry), keeping its spirit; add planted+arm-forward → squat, carried → dip, partial-feet collapsing → squat, partial-feet not collapsing → abstain.
- Acceptance Criteria:
  - No squat-trick clip is labelled `dip` (zero `dip` on squat tricks); dip clips stay `dip` or abstain with a named reason. `test_split_stance.py`/`test_classify_quality.py` unchanged-green (pistol/split precedence untouched).

#### Task 2.2: Planche vs push_up — knowable feet on the floor
- Location: `barra/classify.py` (planche branch ~578, dip/push_up branch ~722, hold gate ~596), `tests/test_hold_routes.py`
- Description: push_up now requires positive evidence the feet are `planted` on the floor behind the hands. If body is horizontal (`body_line_deg >= 70`) and hands are below with `carried`/`unknowable` feet, the split is not decidable → `unknown` naming it ("planche or push-up — the feet were not knowably on the floor"). Route a hands-below hold before the rep branch: `anchored and hands_below_frac >= 0.35 and parked >= HOLD_FRAC and body_line_deg >= 70` → `planche` when `legs_lifted_frac >= 0.5`, else `unknown` hold (a static push-up support is not planche evidence).
- Steps:
  - Measure `legs_lifted_frac`, `body_line_deg`, `parked`, feet verdict on cached planche/push_up clips; set thresholds in the gaps.
  - Add the holds-on-hands route before the dip/push_up branch; add not-fire-on-neighbors fixtures.
- Acceptance Criteria:
  - No planche-trick clip is labelled `push_up`; each returns `planche` or an abstention naming the ambiguity. push_up-trick clips that were correct stay correct (`test_push_up_is_a_dip_lying_down` green).

#### Task 2.3: Front lever vs muscle_up — horizontal body, not vertical hang
- Location: `barra/classify.py` (front_lever branch ~565, pull/muscle_up branch ~629), `tests/test_hold_routes.py`
- Description: replace the whole-clip median `body_line_deg` gate with an anchored-window `horizontal_frac` (share of anchored frames with body line ≥ 70) so a vertical setup prefix is excluded. Add an anti-fallthrough guard: when `horizontal_frac` ≥ the measured threshold AND `hands_overhead_frac >= 0.35`, the clip is a lever-family hold → `front_lever` (or `unknown` if the body line is mixed); never emit `muscle_up`/`pull_up` from it. A muscle-up has a vertical hang throughout (`horizontal_frac` ≈ 0).
- Steps:
  - Measure anchored-window `horizontal_frac` on cached front_lever vs pull_up + muscle_up clips; place the threshold in the gap.
  - Implement; keep `runner_up="pull_up"`; keep prefix-invariance (walk-in cannot change the label).
- Acceptance Criteria:
  - No front_lever-trick clip is labelled `muscle_up`; muscle_up/pull_up clips stay correct (`test_muscle_up_when_the_shoulders_clear_the_bar`, `test_segmentation_invariants.py` green).

### Phase 3: Grow and retrain the learned model, with honest abstention
**Goal**: the second opinion separates more classes and abstains when unsure, trained offline on the whole cached corpus; it stays advisory and never overrides `detected`.

#### Task 3.1: Complete the keypoint cache for the corpus
- Location: `scripts/pipeline_eval.py`, `out/keypoints/`
- Description: run `pipeline_eval.py` in trick batches (`--tricks <t> --per-trick 20 --no-nan`) over all 168 metadata clips so `out/keypoints/<stem>.parquet` covers every clip; rows persist incrementally so a host kill loses only the summary.
- Acceptance Criteria: ≥90% of metadata clips cached; misses listed with reasons in `docs/PIPELINE-EVAL.md`.

#### Task 3.2: Model abstention + deterministic metrics + full-corpus retrain
- Location: `barra/model.py` (`model_classify`), `scripts/train_model.py`, `tests/test_model.py`
- Description: add an abstention to `model_classify`: if top probability < `MODEL_ABSTAIN` (0.40) OR margin to runner-up < `MODEL_ABSTAIN_MARGIN` (0.08) OR the per-fold support of the predicted class < 3, return `{"exercise": "unknown", "abstained": True, "reason": <which>}` with the probability vector preserved. Add deterministic 5-fold class-stratified CV to `train_model.py` metrics (a single-stratified holdout on 23 clips is luck, not evidence). Extend `FEATURE_NAMES` only with the Phase-1/2 view-safe features actually used by a branch; bump `version` to "1.1". Merge low-support classes (split_squat + bulgarian → `split_squat`; barbell/machine into an `unmeasured` group) so the model can name handstand/bench/deadlift as *model* classes without adding them to `barra/movements.py`. Keep the model in the payload under `model.classification`, never `detected`.
- Steps:
  - Implement CV + abstention with tests (roundtrip, determinism, abstention-on-flat-prob, support-abstention).
  - Retrain `python scripts/train_model.py --no-live`; write per-class precision/recall with support to `models/model_metrics.json`; label support-1 classes inconclusive.
- Acceptance Criteria:
  - `model_classify` returns `unknown` under threshold with the unchanged probability vector; tests green; model covers the merged classes; `payload["model"]` never overrides `detected`.

### Phase 4: Whole-corpus verification and docs
**Goal**: prove improvements and no regressions, then record them.

#### Task 4.1: Corpus evaluation with expected-outcome accounting
- Location: `scripts/pipeline_eval.py`, `scripts/evaluate_technique_pipeline.py`, `out/pipeline-eval/report.json`
- Description: in the report, for tricks in `MOVEMENTS` (alias-resolved) the target is `correct`; for unmeasurable tricks (deadlift, bench_press, handstand, human_flag, back_lever, barbell_squat) the target is `honestAbstention` (detected == unknown); a confident label on an unmeasurable trick is `fabricated` (the metric going to 0). Add `--baseline <dir>` producing a `diff-vs-baseline.json` that flags every flip — previously-correct→unknown, previously-correct→mislabel, previously-abstained→confident-label — so abstention cannot hide a recall regression. Cover `WA0017` (inverted `unknown`) and `WA0018` (abstention) explicitly.
- Steps:
  - Implement buckets + diff + runner tests (pure dict fixtures, no network/DynamoDB) in `tests/test_evaluate_runner.py` style.
  - Run the full corpus; diff against the Phase-0 baseline; review every flip (fix or justify individually in `docs/PIPELINE-EVAL.md`).
- Acceptance Criteria:
  - `fabricated` == 0 across the corpus; measured-trick accuracy strictly improves vs baseline; zero unexplained previously-correct→wrong flips; reviewed-8 manifest movement labels match `sample_manifest.json` (alias-resolved), including `WA0017`/`WA0018`.

#### Task 4.2: Full test suite pass + doc updates
- Location: `tests/`, `docs/PIPELINE-EVAL.md`, `docs/MODEL.md`
- Description: run `python -m unittest discover -s tests -v` and `pytest tests -q`; rewrite the result tables from the new report; document threshold provenance (measured gaps) and the environment caveat.
- Acceptance Criteria: both runners exit 0; docs contain measured before/after tables and no stale claims.

## Testing Strategy
- **Unit (synthetic keypoints, no videos)**: every abstention guard and every re-gated branch gets a fires-on-fixture AND a does-not-fire-on-neighbors fixture, plus a NaN-never-satisfies case (`test_a_missing_measurement_never_satisfies_a_branch`). Extend `test_dip_squat_abstention.py`; new `test_classify_abstention.py`, `test_hold_routes.py`.
- **Invariants**: `test_segmentation_invariants.py` stays green (walk-in prefix cannot change a label; NaN never satisfies).
- **Runner tests**: pure-dict fixtures for `correct`/`honestAbstention`/`fabricated` and the baseline diff.
- **Corpus**: `python scripts/pipeline_eval.py --no-nan`; per-trick tables; `--baseline` diff for flips.
- **Reviewed baseline**: `evaluate_technique_pipeline.py --mode cached --baseline out/pipeline-improvement`.
- **Entry points**: `python -m unittest` and `pytest` both green.

## Risks
- **Thresholds tuned on the 26 cached clips may generalise poorly to the full 168.** Mitigate: measure every threshold on the cached corpus and document the gap before coding; thresholds live in `barra/classify.py` with measured-gap comments; the Phase-4 full-corpus diff is the proof. `validate` fingerprints `config.py`.
- **Honesty can mask recall regressions.** Mitigate: the baseline diff flags every previously-correct→abstained flip for individual justification; the report separates `correct`/`honestAbstention`/`fabricated` so abstention cannot inflate the headline.
- **View-gating may turn planche/front_lever into `unknown` on real clips.** Mitigate: gate only the *deciding* planar quantity; bias the eval metric to "no mislabel" (abstained) over "detected" where the plane is unknowable, and document the viewpoint limitation honestly.
- **Supine/hinge/inverted guards could eat valid movements** (a deep leaning squat, a knee-raise at a bad angle). Mitigate: does-not-fire-on-neighbors tests + full-corpus flip review with a quantitative cap (flips on measured movements reviewed until ≤ 0 unexplained).
- **The learned model learns camera artifacts** (shared per-trick filming style; support-1 classes). Mitigate: report support, never claim accuracy for support-1 classes, keep the model advisory, and abstain under the threshold.

## Rollback Plan
- All changes are Python-source only, one revertible commit per phase; revert the phase's commits (`git revert`) or `git checkout` the touched files to restore prior behaviour.
- Models are build artifacts: restore the prior `models/exercise_model.npz`/`model_metrics.json` (kept as `*.bak` before retraining) or retrain from `out/model_features/features.csv`; nothing else consumes the `.npz` except `barra.model.load_default`, which degrades to `None`.
- Baselines are read-only snapshots: re-running against them always re-derives the diff; never edit them — re-run and update docs instead.
- The reviewed `sample_manifest.json` and `metadata.csv` are never modified, so `evaluate_technique_pipeline.py` diffs stay valid.

## Edge Cases
- **NaN satisfaction**: every new gate must `np.isfinite`-check first; a measurement never taken must never satisfy a branch.
- **Feet partly visible**: Phase-2 works because the feet verdict uses robust percentiles over frames where the ankle was seen; it does not require a stable planted window — exactly the documented failure mode.
- **Walking prefix/suffix**: reuse windowed anchoring so standing/walking frames cannot flip a hold into a rep (`test_segmentation_invariants.py`).
- **Night/footage with sparse keypoints** (`WA0012`): guards abstain, never mislabel.
- **Inverted hold (`WA0017`) and poor-hand-visibility (`WA0018`)**: must stay `unknown` (never become a label).
- **Bulgarian rear foot reading as a carried leg**: split branch keeps requiring both ankles below the standing hip; abstain otherwise (existing documented limit).
- **Machine/seated work**: supine/hinge guards cover bench/row families; anything else falls to the existing named `unknown` branch — verify no machine clip earns a confident label on the corpus.
- **Mixed body line (front-lever mid-pull)**: abstain naming "body line mixed", never `muscle_up`.

## Open Questions
- Does the `carried`-feet verdict separate real dip clips from real arm-forward squats on the scraped corpus? Measure first (Phase 2.1). If the gap is too narrow, fall back to abstain-on-both-ambiguity and re-agree against the report rather than shipping silently.
- Should `human_flag`/`back_lever` get their own named abstention reasons (like the inverted guard) or ride the generic `unknown`? Defer to Phase-1.2 measurement: add a guard if they currently draw confident labels; leave them alone if they already abstain.
- Is it acceptable for the model (as `model.classification`, never `detected`) to be the only path to a useful label on unmeasurable movements in `auto` mode? This is deliberate: geometry abstains honestly, the model offers an advisory suggestion, and the payload says which produced the label.