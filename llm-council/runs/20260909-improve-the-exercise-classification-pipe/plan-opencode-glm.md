I have now read the codebase thoroughly (classifier, movements, evidence, model, runners, tests, catalog, manifest, eval reports). Here is the plan.

# Plan

## Overview
Make `barra/classify.py` abstain honestly instead of confidently mislabeling: convert its decisive per-branch evidence to three-valued verdicts (observed / not-observed / unobservable-with-reason) with knowable-feet gating for the dip/push-up/squat family, add named abstention guards for shapes the pipeline does not measure (inverted, supine, hinge), fix the measured squat→dip, planche→push_up and front_lever→muscle_up confusions, then grow the cached-keypoint corpus to all ~167 scraped clips and retrain the numpy MLP with an abstention threshold — verified by the existing suite, a baseline-diffing `scripts/pipeline_eval.py`, and the reviewed 8-clip manifest run.

## Scope
- In:
  - `barra/classify.py` — feet/body-line evidence becomes three-valued; dip/push-up/planche/front-lever/squat branch gates; new abstention guards (inverted, supine, hinge); new features (`inverted_frac`, `hinge_frac`, `knee_over_hip` already exists, `feet_carried_frac`, `hip_ankle_min`).
  - `server/process.py` — early honest abstention when the DECLARED exercise resolves to a `measurable: false` catalog row (`barra/exercises.py`).
  - `scripts/pipeline_eval.py` — record `detectedReason`/`certainty`/abstention buckets, expected-outcome accounting for unmeasurable tricks, `--summary-out`/`--baseline` diff mirroring `evaluate_technique_pipeline.diff_against_baseline`.
  - `barra/model.py`, `scripts/train_model.py` — model abstention threshold, deterministic k-fold metrics, full-corpus training.
  - `tests/` — new fixtures per abstention path; updates to `tests/test_dip_squat_abstention.py`.
  - `docs/PIPELINE-EVAL.md`, `docs/MODEL.md` — updated measured results.
- Out:
  - No new movements added to `barra/movements.py` (bench/deadlift/handstay stay unmeasured by design; no fault rules for them).
  - No pose-backend changes; no mediapipe work (`BARRA_POSE_BACKEND=ultralytics` stays pinned).
  - Vision (nan) labels stay advisory review signals; they never veto geometry or become ground truth.
  - No DynamoDB schema changes; no Android/Kotlin changes.

## Phases
### Phase 0: Baseline snapshot before any classifier change
**Goal**: capture current behavior so later phases can prove improvements and catch regressions.

#### Task 0.1: Snapshot eval baselines
- Location: `scripts/pipeline_eval.py`, `out/pipeline-eval/`, `out/pipeline-improvement/`
- Description: run the unchanged pipeline over the 26 clips with cached keypoints (`--no-nan` for determinism) and save per-clip summaries as the corpus baseline; confirm the reviewed-8 baseline at `out/pipeline-improvement/*-before.json` still diffs.
- Estimated Tokens: 12000
- Dependencies: none
- Steps:
  - Add `--summary-out <dir>` to `scripts/pipeline_eval.py` writing one `<trick>/<stem>.json` summary (`trick`, `detected`, `detectedReason`, `nReps`, `modelClass`, `detected==unknown`) plus a `baseline.json` index.
  - Run `python scripts/pipeline_eval.py --no-nan --per-trick 3 --summary-out out/pipeline-eval/baseline-2026-09/`.
  - Verify `out/pipeline-improvement/` contains `<stem>-before.json` for the 8 reviewed clips (re-save with the current code if stale).
- Acceptance Criteria:
  - `out/pipeline-eval/baseline-2026-09/` holds one summary per clip and `baseline.json`; re-running is idempotent.
  - `python scripts/evaluate_technique_pipeline.py --mode cached --baseline out/pipeline-improvement` completes and emits `diff-vs-baseline.json` with zero changed clips before any code change.

### Phase 1: Honest abstention for what the pipeline cannot measure
**Goal**: bench press, deadlift, handstand, machine work, and other unmeasurable inputs return `unknown` with a named reason, never a confident wrong movement.

#### Task 1.1: Declared-exercise abstention via the catalog
- Location: `server/process.py`, `barra/exercises.py`, `tests/test_server_payload.py`
- Description: in `analyze_clip` (server/process.py:476-486), after `resolve(chosen)`, look up `exercises.get(chosen)`; if the row exists and `measurable` is False (bench_press, deadlift, barbell_squat, machines, weighted variants), return `_empty` with a named blocker ("<id> is not measurable from video — coaching content only"), `detected=None`, and `abstained: "declared-unmeasurable"`. Never fires for `exercise="auto"`.
- Estimated Tokens: 15000
- Dependencies: Task 0.1
- Steps:
  - Add `barra/exercises.measurable_by_id(exercise_id) -> bool | None` (None = not in catalog).
  - Gate in `analyze_clip` before the hold/rep path; record `tr.reject("declared unmeasurable", exercise=chosen)`.
  - Unit test following `tests/test_server_payload.py` patterns: `exercise="bench_press"` → empty payload with the blocker; `exercise="dip"` unaffected.
- Acceptance Criteria:
  - `analyze_clip(clip, exercise="bench_press")` never returns a measured movement, count, or score; the blocker names the catalog row.
  - `python -m unittest tests.test_server_payload` and full suite stay green; reviewed-8 baseline diff unchanged (no reviewed clip declares an unmeasurable exercise).

#### Task 1.2: Geometric abstention guards for undeclared unmeasurable shapes
- Location: `barra/classify.py` (`features`, `classify`), `tests/test_classify_abstention.py` (new)
- Description: three REJECT-only guards placed before the bar branches, each three-valued (fires only when its landmarks were measurably seen; otherwise does not fire and downstream abstention still applies):
  - **inverted** (`handstand` family): new feature `inverted_frac` = share of frames with hips above shoulders by > 0.3 torso and wrists below hips; >= ~0.5 → `unknown` "inverted support — not a measured movement".
  - **supine press** (`bench_press` family): `knee_over_hip >= KNEES_UP` AND `body_line_deg >= 60` AND hands not overhead → `unknown` "supine pressing geometry — not measured" (push-up keeps knees at hip height; knee_raise keeps a vertical body).
  - **hinge** (`deadlift`/row family): feet planted, median `torso_tilt >= 40°`, wrists below hips → `unknown` "hinge pattern — not measured" (squat torso tilt sits far below; verify the gap on cached keypoints before shipping).
- Estimated Tokens: 30000
- Dependencies: Task 0.1
- Steps:
  - First measure: script a throwaway pass over `out/keypoints/*.parquet` to print the proposed features per trick; place each threshold in the measured gap (comment the numbers, codebase style).
  - Implement features + guards with `tr.reject(...)` recording value vs threshold; every guard returns `Classification("unknown", 0.0, <named reason>)`.
  - New `tests/test_classify_abstention.py`: synthetic handstand/supine/hinge fixtures → `unknown` with the named reason; parallel fixtures for real dip/squat/push_up/knee_raise prove the guards do NOT fire on them (regression guards).
- Acceptance Criteria:
  - Each guard: fires on its synthetic family fixture, does not fire on the 11 measured-movement fixtures in `tests/test_classify_quality.py`.
  - Full suite green; corpus re-run (Task 4.1) shows bench_press/deadlift/handstand clips moving from misclassified to abstained, and no dip/push_up/squat/knee_raise clip newly abstained.

### Phase 2: Fix the three measured confusions (three-valued redesign)
**Goal**: settle squat-vs-dip, planche-vs-push_up, front_lever-vs-muscle_up with knowable-view evidence; abstain where the deciding measurement is ambiguous.

#### Task 2.1: Squat vs dip — knowable feet
- Location: `barra/classify.py` (`features`, squat branch ~line 711, dip branch ~line 722), `tests/test_dip_squat_abstention.py`, `tests/test_split_stance.py`
- Description: compute a three-valued feet verdict: `planted` (existing stable-window gate), `carried` (ankles seen >= MIN_SEEN but window travel > ANCHOR_FIXED — feet move with the set, as a dip's dangling feet do), `unknowable` (seen below MIN_SEEN in window and clip). Add `hip_ankle_min` = minimum hip-over-lower-ankle during the set (in torso-lengths; reuse `evidence.hip_above_lower_ankle` logic). Rules:
  - squat branch: accept `rigid_arms or articulated` when feet are knowably planted AND hips collapse toward them (`hip_ankle_min` below a measured threshold) — this captures arm-forward squats.
  - dip branch: require feet `carried`; if feet are `unknowable` keep the existing abstention; if feet are planted but hips do NOT collapse, abstain as ambiguous dip-or-squat.
  - Update `tests/test_dip_squat_abstention.py`'s dip fixture to a physically consistent carried-feet dip (current fixture has planted feet and hips below them — that is squat geometry) while keeping its `!= unknown` spirit; add cases: planted+arm-forward → squat, carried → dip, partial feet (seen but unstable, hips collapsing) → squat, partial feet (seen, not collapsing) → abstain.
- Estimated Tokens: 40000
- Dependencies: Task 0.1, Task 1.2
- Steps:
  - Measure `hip_ankle_min` and ankle window travel on cached squat/dip clips; place `HIP_ANKLE_COLLAPSE` and carried thresholds in the gaps; document measured values in comments.
  - Implement; run the suite; update the two affected fixtures with justification comments.
  - Re-run corpus batch for squat (9 clips) and dip (8 clips) via `scripts/pipeline_eval.py --tricks squat,dip --no-nan`.
- Acceptance Criteria:
  - The measured arm-forward squat clips no longer return `dip`: they return `squat` (planted+collapsing) or `unknown` (ambiguous) — zero `dip` labels remain on squat tricks.
  - All dip-trick clips still classify `dip` or abstain with the named reason; `tests/test_dip_squat_abstention.py` green; `tests/test_split_stance.py` and `tests/test_classify_quality.py` unchanged-green (pistol/split precedence untouched).

#### Task 2.2: Planche vs push_up — knowable feet on the floor
- Location: `barra/classify.py` (planche branch ~line 578, dip/push_up branch ~line 722, hold gate ~line 596), `tests/test_classify_quality.py` or new `tests/test_hold_routes.py`
- Description: push_up now requires positive evidence the feet are `planted` on the floor behind the hands (ankles seen, below shoulders, stable). If the body is horizontal (`body_line_deg >= 70`) and hands are below with feet `carried` or `unknowable`, the planche/push-up split is not decidable: return `unknown` naming it ("planche or push-up — the feet were not knowably on the floor"). Add a hands-below hold route: `anchored and hands_below_frac >= 0.35 and parked >= HOLD_FRAC and body_line_deg >= 70` → planche when legs are measured lifted (`legs_lifted_frac >= 0.5`), otherwise `unknown` hold (a static push-up support is not planche evidence).
- Estimated Tokens: 30000
- Dependencies: Task 2.1 (shares the feet verdict)
- Steps:
  - Measure `legs_lifted_frac`, `body_line_deg`, `parked_frac`, feet verdict on the 13 cached planche clips and 15 push_up clips; set thresholds in the gaps.
  - Implement the branch changes and the hold-on-hands route before the dip/push_up branch.
  - Synthetic tests: planche with unseen ankles → `unknown` (not push_up); planche with measured carried legs → `planche`; static push-up support → `unknown` hold; dynamic push_up fixture (existing) still `push_up`; hold-gate regression (`test_a_hold_is_not_a_set`) still green.
- Acceptance Criteria:
  - No planche-trick clip is labeled `push_up`; each returns `planche` or an abstention naming the ambiguity.
  - All push_up-trick clips that were correct stay correct; `tests/test_classify_quality.py::test_push_up_is_a_dip_lying_down` stays green.

#### Task 2.3: Front lever vs muscle_up — horizontal body, not vertical hang
- Location: `barra/classify.py` (front_lever branch ~line 565, pull/muscle_up branch ~line 629), tests in `tests/test_hold_routes.py`
- Description: the lever branch currently gates on the whole-clip median `body_line_deg`, so clips with a vertical hanging setup/prefix fall through to `muscle_up` once the shoulders peak above the hands. Replace the median with `horizontal_frac` over the anchored window (share of frames with body line >= 70) and add an anti-fallthrough guard: when `horizontal_frac` >= measured threshold AND `hands_overhead_frac >= 0.35`, the clip is a lever family hold — return `front_lever` (or `unknown` if the body line is mixed) and never emit `muscle_up`/`pull_up` from it; a muscle-up clip has a vertical hang throughout, so its `horizontal_frac` is near 0.
- Estimated Tokens: 30000
- Dependencies: Task 2.1
- Steps:
  - Measure `horizontal_frac` (anchored-window) on the 10 cached front_lever clips vs 14 pull_up + 8 muscle_up clips; place the threshold in the gap; document it.
  - Implement the branch change; keep `runner_up="pull_up"` on the lever decision.
  - Synthetic tests: lever-with-vertical-prefix fixture → `front_lever`; muscle_up fixture (`bar_clip(clearance=0.5)`) → still `muscle_up`; mixed body line → `unknown` with reason.
- Acceptance Criteria:
  - No front_lever-trick clip is labeled `muscle_up`; each returns `front_lever` or abstains with the named reason.
  - All muscle_up/pull_up clips that were correct stay correct; `tests/test_classify_quality.py::test_muscle_up_when_the_shoulders_clear_the_bar` and the prefix-invariance tests in `tests/test_segmentation_invariants.py` stay green.

### Phase 3: Grow and retrain the learned model
**Goal**: the second opinion separates more classes and abstains when unsure, trained on the whole cached corpus.

#### Task 3.1: Complete the keypoint cache for the corpus
- Location: `scripts/pipeline_eval.py`, `out/keypoints/`
- Description: run `pipeline_eval.py` in trick batches (`--tricks <t> --per-trick 20 --no-nan`) over all 167 metadata clips (~141 without cached keypoints) so `out/keypoints/<stem>.parquet` covers every clip; the runner writes rows incrementally so a host kill loses only the summary. Batch the 16 tricks into runs under the ~16-minute sandbox kill.
- Estimated Tokens: 15000
- Dependencies: Phase 1 (guards), Phase 2 (fixes) — so the cache is built once with final geometry
- Steps:
  - Batch runs per trick family; monitor `poseCached` failures.
  - Verify coverage: `out/keypoints` count vs metadata row count; record the delta in `docs/PIPELINE-EVAL.md`.
- Acceptance Criteria:
  - >= 90% of metadata clips have cached keypoints; any misses listed with reasons in the doc.

#### Task 3.2: Model abstention + full-corpus retrain
- Location: `barra/model.py` (`model_classify`), `scripts/train_model.py`, `tests/test_model.py`, `models/`, `docs/MODEL.md`
- Description: raise `--per-trick` default to cover all clips (20), keep `--no-live`; add deterministic 5-fold class-stratified CV to `train_model.py` metrics (small-n holdout of 0.6 on 23 clips is luck, not evidence); add an abstention to `model_classify`: if top probability < `MODEL_ABSTAIN` (0.40, constant in `barra/model.py`), return `exercise="unknown"` with the margin preserved. Extend `FEATURE_NAMES` with the Phase-1/2 features; bump `version` to "1.1"; retrain to `models/exercise_model.npz`.
- Estimated Tokens: 25000
- Dependencies: Task 3.1
- Steps:
  - Implement CV + abstention with tests (abstention unit test in `tests/test_model.py`; CV determinism).
  - Retrain; check per-class precision/recall WITH support in `models/model_metrics.json`; classes with support 1 are labeled inconclusive in the doc.
  - Update `docs/MODEL.md` (feature list, abstention semantics, per-class table).
- Acceptance Criteria:
  - `model_classify` returns `unknown` under threshold with unchanged probability vector; tests green.
  - Trained model covers >= 8 classes with support >= 3; metrics file records CV mean accuracy with fold spread; the model remains advisory (`payload["model"]`), never overriding `detected`.

### Phase 4: Whole-corpus verification and docs
**Goal**: prove the improvements and no regressions, then record them.

#### Task 4.1: Corpus evaluation with expected-outcome accounting
- Location: `scripts/pipeline_eval.py`, `out/pipeline-eval/report.json`
- Description: extend the report: for tricks in `MOVEMENTS` (alias-resolved) the target stays `correct`; for unmeasurable tricks (deadlift, bench_press, handstand, human_flag, back_lever, barbell_squat) the target is `honestAbstention` (detected == unknown); a confident label on an unmeasurable trick is `fabricated` (the metric that must go to 0). Add `--baseline <dir>` producing `diff-vs-baseline.json` (reusing the diff shape of `scripts/evaluate_technique_pipeline.py:172`): flag every flip — previously-correct→unknown, previously-correct→mislabel, previously-abstained→confident-label.
- Estimated Tokens: 25000
- Dependencies: Tasks 1.1-3.2
- Steps:
  - Implement accounting + diff + runner tests in `tests/test_evaluate_runner.py` style (pure dict fixtures, no network/DynamoDB).
  - Run the full corpus (`python scripts/pipeline_eval.py`); diff against `out/pipeline-eval/baseline-2026-09/`.
  - Review every flip: regressions must be fixed or individually justified in `docs/PIPELINE-EVAL.md`.
- Acceptance Criteria:
  - `fabricated` == 0 across the corpus; measured-trick accuracy strictly improves vs baseline; zero unexplained previously-correct→wrong flips; report written with per-trick tables.
  - Reviewed-8 manifest: `python scripts/evaluate_technique_pipeline.py --mode cached --baseline out/pipeline-improvement` — movement labels for the reviewed clips match `sample_manifest.json` movement fields (alias-resolved), including `VID-...-WA0017` (`unknown`) and `WA0018` (abstention).

#### Task 4.2: Full test-suite pass and doc updates
- Location: `tests/`, `docs/PIPELINE-EVAL.md`, `docs/MODEL.md`
- Description: run `python -m unittest` and `pytest` (both entry points the repo supports); update both docs with the measured before/after numbers, threshold provenance (measured gaps), and the environment caveat.
- Estimated Tokens: 15000
- Dependencies: Task 4.1
- Steps:
  - `python -m unittest discover -s tests -v`; `pytest tests -q`.
  - Rewrite the "result" tables in `docs/PIPELINE-EVAL.md` from the new report; update `docs/MODEL.md`.
- Acceptance Criteria:
  - Both runners exit 0; docs contain the new measured tables and no stale claims.

## Testing Strategy
- Unit (synthetic keypoints, no videos): every abstention guard and every re-gated branch gets a fires-on-fixture and a does-not-fire-on-neighbors fixture; `tests/test_dip_squat_abstention.py`, new `tests/test_classify_abstention.py`, `tests/test_hold_routes.py`, `tests/test_model.py` additions.
- Invariants: `tests/test_segmentation_invariants.py` must stay green (walk-in prefix cannot change a label; NaN never satisfies a branch — extend it with one test that the new guards also refuse on NaN evidence).
- Runner tests: pure-dict fixtures for the new `correct`/`honestAbstention`/`fabricated` buckets and the baseline diff (`tests/test_evaluate_runner.py`).
- Corpus: `python scripts/pipeline_eval.py --no-nan` over all clips; per-trick tables in the report; `--baseline` diff for flips.
- Reviewed baseline: `scripts/evaluate_technique_pipeline.py --mode cached --baseline out/pipeline-improvement`; metrics vs `data/evaluation/sample_manifest.json`.
- Entry points: `python -m unittest` and `pytest` both green.

## Risks
- **Thresholds tuned on the 26 currently-cached clips generalize poorly to the full 167.** Mitigation: Phase 1.2/2.x measures every threshold on the cached corpus and documents the gap before coding; Task 4.1 re-runs the whole corpus; thresholds live in `barra/classify.py` constants with measured-gap comments (never silently edited), and `provenance` fingerprints the source.
- **Honesty can mask recall regressions**: converting a previously-correct label into an abstention looks like "no misclassification" while losing a real answer. Mitigation: the baseline diff counts every previously-correct→abstained flip as a regression to be individually justified; the report separates `correct`, `honestAbstention`, and `fabricated` so abstention cannot inflate the headline.
- Self-critique: **the dip fixture redesign (Task 2.1) changes an existing test's geometry, and the `hip_ankle_min` discriminator is only sound if real dip footage really carries its feet** — if scraped dip clips hold perfectly still legs, `carried` misfires and dips flip to abstain; the plan catches this via the Task 2.1 corpus re-run, but if the measured gap between "planted" and "carried" ankle travel is narrow on real dips, this task may degrade dip recall for squat-recall, and the fallback (accept abstention on both) should be re-decided against the corpus rather than pushed through.
- Self-critique: **the supine/hinge/inverted guards are exactly the kind of negative pattern-matching that can quietly eat valid movements**: a deep bodyweight squat with a pronounced forward lean, or a knee-raise filmed from an angle that drops `body_line_deg`, could trip the supine or hinge guard and turn a correct label into an abstention. The does-not-fire-on-neighbors tests reduce but do not eliminate this, because they are synthetic; only the full-corpus diff (Task 4.1) is real evidence, and the plan has no quantitative criterion for how many guards-firing-on-measured-movement frames is acceptable — it relies on zero-flip review, which is labor and could be shortcut under time pressure.
- Self-critique: **the learned model's per-class support stays small even after full-corpus training** (split_squat/bulgarian have 1 clip each; scraped clips share per-trick camera styles), so the model can learn camera artifacts as class signal; CV folds split clips randomly, not by source, so fold accuracy overstates generalization. The plan mitigates by keeping the model advisory and reporting support, but does not attempt source-stratified folds — a known weakness, not a fix.
- **Sandbox kills long runs (~16 min; mediapipe SIGKILLs; ultralytics required).** Mitigation: batched, resumable `pipeline_eval.py` runs (rows persist incrementally); `--no-nan` for offline determinism; `--no-live` training.
- **DynamoDB unavailability** during eval. Mitigation: `_put` already degrades to a print; on-disk `out/pipeline-eval/` artifacts remain the source for the local report and baseline.

## Rollback Plan
- All changes are Python-source only, in separate phases: `git revert` the phase's commits (Phase 2's three tasks are independent branches over `classify.py`; revert individually).
- Models are build artifacts: restore the prior `models/exercise_model.npz`/`model_metrics.json` or retrain from `out/model_features/features.csv` at any time; nothing else consumes the .npz except `barra.model.load_default`, which degrades to None.
- Baselines are read-only snapshots: re-running against `out/pipeline-eval/baseline-2026-09/` and `out/pipeline-improvement/` always re-derives the diff; if a change must ship, rerun eval and update docs rather than editing baselines.
- DynamoDB rows are keyed per clip and overwritten by re-runs; a rollback run rewrites them with the reverted program stamps (`barra`/`commit` in every row).

## Edge Cases
- Night footage (`VID-...-WA0012`, difficult-visibility): guards must abstain, not mislabel; keypoints sparse.
- Side-on views: far-limb occlusion → `midpoint`/`pair_confidence` single-side fallback; feet verdicts must respect `MIN_SEEN` (NaN never satisfies a branch — `test_a_missing_measurement_never_satisfies_a_branch`).
- Inverted holds (`WA0017`, reviewed `unknown`): inverted guard must keep this `unknown` (it already is; guard must not change it to a label).
- Walk-in/walk-out prefixes: windowed anchoring already scopes bar quantities; new feet/hinge features must use the same windowed discipline or prefix-invariance tests break.
- Bulgarian rear foot on a bench reading as a carried leg: existing documented limit (classify.py ~line 676) — split branch still requires both ankles below the standing hip; abstain otherwise.
- Mixed body line (front-lever attempt filmed mid-pull): abstain `unknown` naming "body line mixed", never `muscle_up`.
- A clip where the declared exercise disagrees with the detected movement: declared-unmeasurable abstention wins for declared rows; for measurable declared rows the detection disagreement stays a recorded trace note (existing behavior).
- Machine/seated work: supine/hinge guards cover bench/row families; anything else falls to the existing final `unknown` branch — verify on the corpus that no machine clip earns a confident label.

## Open Questions
- Does the `carried`-feet verdict separate real dip clips from real arm-forward squats on the scraped corpus (Task 2.1 measures first)? If the gap is too narrow, the fallback is abstain-on-both-ambiguity, which must be re-agreed against the report rather than shipped silently.
- Should `human_flag`/`back_lever` clips (unmeasured, in corpus) get their own named abstention reasons via a dedicated guard, or ride the generic fall-through `unknown`? (Deferred to Phase 1.2 measurement: if they currently draw confident labels, add the guard; if they already abstain, leave them.)