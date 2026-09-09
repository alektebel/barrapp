# Movement recognition and technique-specific error detection

Implementation plan · 8 September 2026

## 1. Objective

Improve the actual Barrapp video pipeline so it identifies the movement, finds the relevant repetitions or holds, and reports specific, observable errors in the correct phase of each technique. Verify improvements on real footage and preserve evidence for every result.

The target is a movement-conditioned, multi-label assessment system: one repetition can exhibit several errors, and a missing or unsuitable camera view must produce an unobservable result rather than a clean result.

Deliver this in two stages:

1. Correct and validate the existing geometric pipeline and its optional vision pass.
2. Evaluate learned movement and error models against that baseline, introducing them only where held-out results justify the change.

This document records the current implementation state and the remaining work. It does not claim that a CUBIST model has been trained, integrated, or deployed.

## 2. Current architecture and evidence

The production entry point is `server/process.py::process_job`. Its measurement call, `analyze_clip`, performs pose extraction, movement classification, segmentation, metrics, scoring and fault classification. The report then passes through optional text/vision enrichment and artifact generation.

| Responsibility | Current implementation |
|---|---|
| Pose extraction and replay | `barra/pose/`, `barra/posecache.py` |
| Movement definitions and geometric recognition | `barra/movements.py`, `barra/classify.py` |
| Standard and relaxed repetition detection | `barra/ingest.py` |
| Per-repetition measurements | `barra/metrics.py` |
| Measurement availability and viewpoint gates | `barra/evidence.py` |
| Technique-specific fault rules | `barra/faults_taxonomy.py` |
| Baseline quality proxy | `barra/quality.py` |
| Video cuts and stills | `barra/frames.py` |
| Optional multimodal assessment | `server/vision.py` |
| Traces and browser inspection | `barra/trace.py`, `tools/debugweb/` |
| Existing fault evaluation | `barra/validate_faults.py` |

### Baseline actually run

- The full test suite passed: **238 tests**, before the changes described below.
- All eight root-level sample videos were run through the real `analyze_clip` path using existing cached keypoints, with automatic movement selection and no exercise hints.
- Original payloads were saved in `out/pipeline-improvement/*-before.json`.
- Contact sheets were extracted and inspected for clips 0010, 0014, 0019 and 0020. These are useful evidence, but sparse stills are not a complete manual annotation of every repetition.
- This baseline exercised the measurement pipeline; it did not rerun the pose model, upload to AWS, or invoke an external vision model.

| Clip suffix | Baseline detection | Baseline reps | Observed issue or role |
|---|---|---:|---|
| 0010 | muscle-up | 2 | Whole-rep arm-straightness rule fires during a movement that requires elbow flexion. |
| 0011 | hanging knee raise | 1 | Preserve recognition while checking segmentation under camera rotation. |
| 0012 | muscle-up | 1 | Night footage; retain as a difficult visibility case. |
| 0014 | muscle-up | 2 | One counted interval, 22.61–25.16 s, shows standing/walking around the rig rather than a muscle-up. |
| 0017 | unknown | 0 | Static/inverted hold negative control for repetition counting. |
| 0018 | unknown | 0 | Poor hand visibility; preserve abstention unless new evidence supports recognition. |
| 0019 | pull-up | 1 | Attempt/swing footage requires temporal review; do not assume a completed rep or force an unknown label from the older documentation alone. |
| 0020 | push-up | 19 | “Stall” fires on 17 repetitions; phase timing is also reversed. |

The older counts in `docs/CORE.md` differ from this baseline. Update documentation only after the final replay, and distinguish historical results from current ones.

### Changes already made in the working tree

These changes are implemented but **not yet fully validated together**:

- [x] Correct concentric/eccentric durations for descending-first movements: push-up, dip, squat and pistol squat.
- [x] Assess their ascent on the return phase, including the server’s smoothness input and median concentric calculation.
- [x] Share stall detection between the evidence and quality layers; exclude the outer 10% of displacement so normal endpoint deceleration is not automatically a stall.
- [x] Change the muscle-up “bent arms” predicate to use elbow extension near the top, rather than the percentage of the whole repetition spent straight-armed.
- [x] Make the relaxed segmentation pass retain the fixed-hand requirement.
- [x] Correct the image-coordinate sign in pistol-squat recognition and require both feet to be observed before claiming single-leg stance.
- [x] Add failing regressions before fixes. The focused phase/fault/classifier run passed **54 tests**; a subsequent classifier/phase run passed **36 tests** after the pistol change. These are overlapping selections, not additive test totals.
- [x] Rerun the full suite after all changes: **288 tests passed** (2026-09-08; 238 at baseline, 50 added for phases, the coverage gate, the rule registry, artifacts, vision validation and the runner).
- [x] Repeat all eight real clips and compare their payloads to the baseline: `scripts/evaluate_technique_pipeline.py --mode cached`, run `out/technique-eval/20260908-201439-cached-after3/`. Results in section 12.
- [x] Run selected videos with fresh pose extraction through `process_job`: 0010 (muscle-up) and 0020 (push-up), run `out/technique-eval/20260908-202200-fresh-fresh-mu-pu/`. Results in section 12.

The repository already contained uncommitted app, classifier, ingestion and debugger work before this task. Preserve it and review the final diff by hunk. No deployment has been performed.

## 3. Target output contract

Keep current fields compatible with the Android client. Add structured information rather than requiring the client to infer errors from prose.

Each assessment should identify:

- Movement family and, when supported, technique variant.
- Repetition or hold ID and its time boundaries.
- Phase: setup, lowering, lifting, transition, support/lockout, or hold.
- Stable error ID and human-readable name.
- Assessment state: `observed`, `not_observed`, or `unobservable`.
- Evidence: primitive, value, unit, threshold, comparison and supported interval.
- Availability reason: tracking loss, unsuitable view, unsupported variant, or insufficient temporal evidence.
- Source and version: geometric rule, learned model, or advisory vision observation.

Example proposed record:

```json
{
  "rep": "r2",
  "exercise": "muscle_up",
  "variant": "unspecified",
  "errorId": "muscle_up.incomplete_support_extension",
  "name": "bent arms",
  "phase": "support",
  "status": "observed",
  "intervalS": [12.9, 13.1],
  "evidence": {
    "primitive": "top_elbow_deg",
    "value": 145.0,
    "threshold": 160.0,
    "comparison": "<",
    "unit": "deg"
  },
  "source": "geometry"
}
```

The example is illustrative, not a measured result from a sample clip. Rule margins must not be presented as probabilities. Learned confidence needs held-out calibration before it can be described probabilistically.

## 4. Work package A — finish phase and segmentation correctness

### A1. Consolidate phase semantics

1. Define phase boundaries centrally from the movement profile and `(start, turn, end)`.
2. Reuse them in metrics, evidence, quality, artifact extraction and tracing.
3. Audit every consumer of `concentric_s`, `eccentric_s`, `tempo_ratio`, `start_elbow_deg`, `bottom_elbow_deg` and `transition_s`.
4. Scope transition measurements to movements that actually have the relevant transition.
5. Review range/lockout semantics separately for pull-ups, muscle-ups, dips and push-ups. A single fraction of arm reach does not establish the same endpoint standard for all four.
6. Record the assessed phase and window beside each fault in the trace.

**Acceptance:** asymmetric synthetic timing cases identify the correct phase; known normal bending during a muscle-up is not classified as a whole-rep straight-arm failure; ascending movement timing does not regress.

### A2. Validate the stall correction

1. Test smooth cycles, interior pauses, reversals, short repetitions, tracking gaps and multiple frame rates.
2. Keep the new endpoint exclusion convention in `config.py` and record it in provenance.
3. Compare the old/new stall evidence on all sample repetitions.
4. Inspect flagged windows in the source video before describing any removed alert as a confirmed false positive.
5. Ensure a real mid-ascent pause still fires. Fewer alerts alone is not success.

**Acceptance:** smooth synthetic turnarounds stay clear, interior stalls remain detectable, and the explanation and structured fault use the same measurement.

### A3. Keep rescue physically consistent

1. Apply the same anchor and observation validity requirements to both segmentation paths.
2. Centralize shared validity checks to avoid future divergence.
3. Emit candidate, rejection and final acceptance events distinctly; do not leave an early “accepted” rescue trace looking like a final retained rep.
4. Review mount, dismount, walking, swing, partial-rep and occlusion cases.
5. Preserve useful rejected-candidate evidence in the debugger.

**Acceptance:** 0014’s walking interval is not retained as a measured muscle-up. Recovery of true reps must be assessed separately; do not relax the hand gate merely to increase counts.

## 5. Work package B — improve movement and variant recognition

### B1. Strengthen the geometric baseline

1. Finish validation of the pistol sign/visibility fix with real pistol footage.
2. Evaluate left/right mirroring, image scaling and hidden-foot cases.
3. Test confusion pairs: pull-up/muscle-up, dip/push-up, squat/pistol, knee raise/pull-up, front lever/other hangs, and planche/push-up.
4. Test additions of walking/rest before and after the same set.
5. Ensure hold classification requires sustained evidence; a transient horizontal posture should not by itself establish a hold.
6. Separate movement recognition from completion: a failed muscle-up attempt is not necessarily a completed pull-up.
7. Introduce an explicit ambiguity/unsupported result where the evidence cannot choose a technique.

### B2. Represent variants explicitly

Start with variants whose error definitions differ materially: strict versus kipping pull-up/muscle-up, and full versus tuck/straddle holds. Audit current aliases before treating them as equivalent.

Use a declared variant when available and label it as declared. Do not silently infer intent from one posture. Until variant inference is validated, keep variant-dependent observations neutral—for example, report visible swing without assuming it violates an unspecified technique standard.

**Acceptance:** recognition is tested without filename/title/session-label leakage. Variant uncertainty cannot silently activate the wrong fault taxonomy.

## 6. Work package C — strengthen technique-specific error evidence

### C1. Turn the taxonomy into an explicit rule registry

For each error define its movement/variant, phase, primitives, view requirements, minimum observation coverage, threshold and correction template. Preserve current display labels during migration, with stable IDs underneath.

Audit existing rules for unsupported causal claims. In particular, bent elbows do not by themselves demonstrate poor scapular retraction/protraction; ankle displacement is not direct heel tracking. Name the observable condition or mark the intended assessment unsupported.

### C2. Make availability first-class

1. Enumerate all applicable checks for the selected technique.
2. Evaluate each as observed, not observed or unobservable.
3. Require sufficient confident samples within the actual phase window.
4. Check that a short visible fragment cannot stand in for a fully tracked phase.
5. Avoid treating an empty fault list as a clean result when the relevant checks were blocked.
6. Audit pose plausibility gating so unusable measurements cannot produce authoritative fault labels even when the score is withheld.
7. Keep camera-dependent quantities explicitly gated; a projected 2D angle is not a validated 3D joint angle.

### C3. Add time-localized evidence

Attach the window that produced each value. Whole-repetition summaries should retain whole-repetition scope; do not fabricate a precise error onset from one aggregate. Add persistence/hysteresis only where validation shows that it removes jitter without hiding brief genuine errors.

**Acceptance:** every fired rule is reproducible from its trace, missing evidence remains unknown, and the mobile client renders the same structured verdict as the backend.

## 7. Work package D — improve the optional video/vision technique pass

The current vision implementation receives mostly turning-point stills. Its prompt refers to measurements, but `technique_note` currently receives artifacts without the measurement payload. That is insufficient context for phase-aware error analysis.

### D1. Provide complete representative phase sequences

1. Select early, middle and late repetitions under a fixed frame budget.
2. Sample start, mid-first-phase, turn, mid-second-phase and end for selected reps.
3. For holds, sample onset, sustained hold and exit instead of inventing repetition phases.
4. Label every frame with its repetition, phase and source-video timestamp.
5. Preserve correct label-to-image correspondence when individual frame reads fail.
6. Include measured movement, variant status, boundaries, primitives and unobservable/view-blocked checks in the request.
7. Record selected timestamps in the artifact trace for reproducibility.

### D2. Request and validate structured observations

Ask for per-technique error observations with evidence-frame references, phase, state and a short visible description. Permit abstention. Restrict responses to valid movement/error IDs and known frame/rep references.

Keep these as separately sourced advisory observations; do not overwrite geometric measurements, rep counts or calibrated scores. Record disagreement with the geometric movement label for review.

Do not call pose estimates “ground truth” in the prompt. Explicitly prohibit claims about unseen phases, forces, muscle activation or camera-hidden joints. Sparse stills cannot reliably establish precise timing or count fast repetitions.

### D3. Harden response handling and evaluate providers

1. Validate JSON types and required fields; malformed output must degrade cleanly.
2. Replace loose numeric/substr parsing in count/verdict helpers with schema validation.
3. Make disagreement and partial-repetition handling explicit instead of automatically taking a larger count.
4. Compare the configured model and one alternative on exactly the same reviewed cases.
5. Track invalid-response rate, unsupported-claim rate, false alerts, latency and cost.

**Current limit:** no complete vision endpoint configuration was present in the inspected process environment, so no external model call has been verified in this task. Do not claim a live comparison until one succeeds.

## 8. Work package E — evaluate learned recognition and error models

### E1. Data and evaluation design

1. Audit `data/calisthenics/metadata.csv` against files actually present. Its README describes a larger corpus, but that inventory has not been verified in this task.
2. Check dataset/model licenses before training or redistribution.
3. Add a reviewed, versioned manifest with movement, variant, rep boundaries, per-error intervals, observable/unobservable status, camera view and reviewer confidence.
4. Include positive, clean, ambiguous and unsupported examples. Existing model outputs are annotation suggestions, never ground truth.
5. Split by athlete and source recording; keep crops and re-encodes of the same recording in one split.
6. Freeze a held-out test set before tuning. Report denominators and uncertainty; under-supported classes remain inconclusive.

Extend the current clip-level `expected`/`forbidden` fault harness to support per-repetition and temporal labels. Also ensure fault counts and usable-rep counts refer to the same accepted population.

### E2. Movement backbone comparison

Evaluate:

- Current geometric recognizer.
- A pose-sequence model such as SkateFormer or DeGCN.
- Frozen V-JEPA 2.1 features plus a trained classification head.
- InternVideo-Next under the same data/split budget.

Start with frozen features before expensive end-to-end fine-tuning. Benchmark total processing cost including decoding and pose extraction, not only classifier inference.

### E3. CUBIST-inspired error model

Use the research pattern rather than claiming an unverified drop-in integration:

1. Encode the video, optionally with a pose stream.
2. Predict movement and phase boundaries.
3. Route to movement/variant-specific multi-label error heads.
4. Retain individual error probabilities and temporal evidence.
5. Apply calibrated thresholds and abstention per error.
6. Generate explanations from the structured detections and taxonomy.

Compare RGB-only, pose-only and fused variants on identical splits. Report both oracle routing with the true movement and end-to-end routing with the predicted movement, so routing failures are visible.

Do not transfer multiview/EMG benchmark results to the single-phone setting. Verify CUBIST code/checkpoint availability and reproducibility before deciding whether to adapt the implementation or reproduce the architecture.

**Promotion rule:** select models using held-out movement/error performance, coverage, false alerts and deployment cost. A higher general action-recognition score or more fluent feedback is insufficient.

## 9. Work package F — reproducible real-pipeline verification

Create `scripts/evaluate_technique_pipeline.py` as a deterministic evaluation runner with explicit modes:

- **Cached pose:** run the real `analyze_clip` path repeatedly while holding extraction fixed.
- **Fresh pose:** invoke the actual extraction/processing path in isolated subprocesses.
- **Optional vision:** use a named configured endpoint and retain validated responses separately.

Write JSON/CSV summaries, full payloads, traces, model/config provenance and failures into a new run directory. Never overwrite baseline evidence or annotations.

### Verification sequence

1. Run the full test suite.
2. Replay all eight sample clips against saved before-payloads.
3. Manually review changed detection/count/error windows.
4. Run a broader movement-balanced subset of available corpus videos.
5. Run at least one fresh muscle-up and one fresh push-up through `process_job`; compare with cached results and explain differences.
6. Verify the local upload → processing → JSON contract and Android-compatible response shape.
7. Exercise missing/invalid video, lost pose, unsupported movement, unknown view, unavailable provider and malformed model output.
8. Run AWS verification only as a separate, recorded deployment step; local success is not evidence that the deployed worker changed.

### Metrics

| Layer | Required measurements |
|---|---|
| Movement | Macro-F1, confusion matrix, coverage and unknown/unsupported behavior |
| Segmentation | Count error, false retained reps, missed reps, boundary error |
| Errors | Per-error precision/recall/F1, false alerts per rep, observable coverage |
| Timing | Interval overlap and boundary error on temporally labelled errors |
| Calibration | Reliability of learned confidence; report abstention alongside accuracy |
| Runtime | Decode, pose, recognition, assessment and total latency; memory and API cost |
| Contracts | Trace/payload consistency, valid JSON, client compatibility |

Set numerical shipping thresholds before held-out evaluation, separately for each supported error. Do not select thresholds by maximizing results on the eight debugging clips.

## 10. Integration, rollout and completion criteria

1. Preserve existing fields and add versioned assessment fields.
2. Update Android models/API parsing and cues only after the backend contract is covered by tests.
3. Show unobservable checks and advisory disagreements without implying that missing checks passed.
4. Version changed measurement semantics: corrected timing and stall rules can alter scores, so historical scores require reprocessing or a comparability warning.
5. Keep a selectable baseline implementation for learned-model comparisons and rollback.
6. Package and test the worker dependencies and model assets before deployment.
7. Document actual results, remaining unsupported movements and known camera limitations.

The first implementation milestone is complete when the existing-pipeline corrections pass the full suite, real before/after evidence is recorded, fresh extraction succeeds on representative clips, and the local API contract remains intact. Learned-model integration is a subsequent milestone with its own dataset and performance gates.

## 11. Immediate next actions

1. ~~Rerun the full suite after the current working-tree edits.~~ Done: 288 passed.
2. ~~Produce and review `*-after.json` for all eight sample clips.~~ Done: section 12.
3. ~~Centralize shared phase/segmentation validity logic and resolve any trace inconsistencies.~~ Done: `barra/phases.py`, `ingest.candidate_checks`.
4. ~~Implement phase-sequence artifacts and evidence-grounded vision requests.~~ Done: `barra/frames.py`, `server/vision.py`. No live vision call has been made (no endpoint configured); the request builder and response validation are covered by tests only.
5. ~~Add the reproducible evaluation runner and reviewed corpus manifest.~~ Done: `scripts/evaluate_technique_pipeline.py`, `data/evaluation/sample_manifest.json`.
6. ~~Complete fresh-pose and local API verification.~~ Done: section 12.
7. Begin the learned-model comparison only after the corrected baseline and labels are stable. **Not started.** Blocked on: no cached keypoints for the 166-clip corpus (fresh pose is ~13 s per short clip with ultralytics), and frame-by-frame labels exist for none of the eight sample clips.
8. Review the two rescue-path removals (0011, 0019) frame by frame; see section 12.
9. Decide whether the mediapipe backend is still a supported estimator on this host: it is killed by SIGKILL while creating `PoseLandmarker`, before any Python exception. `process_job` and the runner fall back to ultralytics, and the payload now names the backend that produced the keypoints (`poseBackend`, `provenance.poseBackendUsed`).

## 12. Results of the first milestone (2026-09-08)

What was built, in the order of the work packages. Every item below is in the working tree; nothing has been committed or deployed.

**A. Phases and segmentation.** `barra/phases.py` is the single definition of `rep / setup / lowering / lifting / support / turnaround / transition / hold / onset / sustained / exit` from the movement profile and `(start, turn, end)`. `metrics.rep_metrics`, `evidence.rep_evidence`, `process.analyze_clip`, `holds.hold_attempts` and `frames.technique_artifacts` read it. The muscle-up transition is narrowed to the frames inside the bar-plane band (`THRESHOLDS.bar_plane_band`) and reported as such: on 0010 r1 it is 3.67–3.92 s, where the raw table would have said 2.12–5.92 s. `ingest.candidate_checks` applies length, observed fraction, anchor travel and rest posture to both segmentation passes; rescue candidates are traced as candidate → reject/accept with the number and the limit. The rest-posture check (`THRESHOLDS.rest_side_tolerance`) is what removes 0014's walking interval: it rested with the shoulders 0.86 torso-lengths above the hands.

**B. Variants.** `barra.rules.KNOWN_VARIANTS` (strict/kipping for pull-up and muscle-up; full/tuck/straddle for the front lever and planche). A variant travels with the job (`variant` on `POST /v1/jobs`, local and AWS), is normalised by `normalise_variant`, and is reported as `{name, source}`; an unknown declaration is reported back as `unspecified` with the word kept beside it, never applied. A rule written for one variant is left out under another and flagged `variantDependent` when none was declared.

**C. Rule registry and availability.** `barra/rules.py` holds every rule as a record: stable movement-scoped id, phase, primitive, comparison, threshold (a `THRESHOLDS` field, never a literal), observable, correction. `faults_taxonomy` derives its public API from it; the debug web's fault spec reads the same registry. `assess()` returns observed / not_observed / unobservable per rule; a rep whose pose is implausible or barely tracked is unobservable everywhere and fires nothing. `Evidence.add` gates on phase coverage (`min_phase_coverage` 60 %, `min_phase_samples` 3) with a reason string; `Evidence.windows` prints where each primitive was read. Payload: `reps[].assessments`, `reps[].phases`, `reps[].assessmentBlocked`, `assessment.checks`, `variant`, `measurementVersion` = 2 (`provenance.measurement` carries the semantics). `faults[]` and `failures[]` are unchanged and remain the observed subset. The "bent arms" cue text was wrong ("at the bottom"); it now reads "Press out to straight arms at the top of every rep" in both the registry and `Cues.kt`.

**D. Vision pass.** `frames.technique_artifacts` samples early/middle/late reps × start / mid-first / turn / mid-second / end (holds: onset / sustained / exit), each `Still` labelled with rep, phase, moment and source timestamp, alignment-safe when a frame read fails, and recorded in the trace. `vision.technique_note(art, report)` sends the measured report with the stills, asks for JSON observations keyed by registry `errorId`, and `validate_observations` drops anything naming an unknown rule, rep, frame, phase or status, counting drops by reason. Counts and verdicts are parsed by schema (`parse_count`, `parse_verdict`); `reconcile_counts` claims no count when two models disagree by more than one, and `analyze_clip` now rejects such a result in the trace instead of using it. **No live call was made**: no endpoint is configured on this host.

**F. Runner and manifest.** `scripts/evaluate_technique_pipeline.py --mode cached|fresh|vision` writes payloads, traces, `summary.json/csv`, `diff-vs-baseline.json`, `metrics.json` (against the manifest), `manifest-audit.json`, `provenance.json` and `failures.json` into a fresh, never-overwritten run directory. Fresh mode runs `process_job` in a subprocess per clip and retries with the next pose backend pinned when the worker dies by signal. `data/evaluation/sample_manifest.json` labels the eight clips with `reviewMethod` and `reviewerConfidence` on every row; only contact-sheet review exists, so most `reps` are `null`.

### Replay of the eight clips (cached keypoints, run `20260908-201439-cached-after3`)

| Clip | Detected | Reps before → after | Faults before → after | Assessment |
|---|---|---:|---|---|
| 0010 | muscle_up | 2 → 2 | stall 2 → 1; bent arms 2 → 2 (now from the 0.17 s support window, elbows 146° / 114°) | Windows unchanged. Bent-arms is now a top-phase check and still fires: the lockout percentage (76 %, 62 %) agrees the top was not pressed out. Whether that is true has not been reviewed frame by frame; the manifest requires only that the check be support-scoped, which it is. |
| 0011 | knee_raise | 1 → **0** | – | The single rep (2.17–5.83 s) is now rejected by the anchor check the rescue pass used to skip: the wrists travel 2.28 torso-lengths in the image. The whole skeleton translates with them, which is camera motion or walking; the pipeline cannot tell from keypoints alone. Recognition is preserved as required. **Needs frame-by-frame review** before this is called a fix or a regression. |
| 0012 | muscle_up | 1 → 1 | unchanged | – |
| 0014 | muscle_up | 2 → **1** | stall/dead hang/bent arms/lockout/momentum each −1 | The 22.61–25.16 s walking interval is gone (rest posture: shoulders 0.86 above hands). The retained rep is unchanged. Acceptance for A3 met. |
| 0017 | unknown | 0 → 0 | – | Negative control holds. |
| 0018 | unknown | 0 → 0 | – | Abstention holds. |
| 0019 | pull_up | 1 → **0** | stall/lockout/momentum −1 each | Rep 4.67–6.57 s rejected by the anchor check (wrist travel 2.23) after the rescue pass found it; the shoulders never rise above the hands (−0.15), so the baseline's scored pull-up (75) was a completed rep the footage does not show. Consistent with the manifest's "attempt or swing"; not asserted as ground truth. |
| 0020 | push_up | 19 → 19 | **stall 17 → 0**, control 1 → 0; lockout 3 → 3 | Count and windows unchanged. Session score 55 → 56. `hip_sag` is unobservable on all 19 reps (hips 5 % tracked; view UNKNOWN), reported as such rather than as clean. |

Manifest metrics: movement accuracy 7/7 labelled clips (support 1–3 per class, inconclusive); mean absolute count error 0 on the four clips with a reviewed count; false retained rep on 0014 = false; `push_up.lift_stall` fires on 0/19; `muscle_up.incomplete_support_extension` fires 2/2 from the support phase only.

### Fresh pose through `process_job` (run `20260908-202200-fresh-fresh-mu-pu`)

0010 and 0020 re-estimated with ultralytics (13.5 s and 15.6 s per clip): rep windows identical to the cached run to 0.01 s, same faults, same scores (50, 56). The default backend order was tried first and mediapipe was SIGKILLed twice (creating `PoseLandmarker`); the payload records `poseBackendDied` and `poseBackend: ultralytics`. Because the cache was also produced by ultralytics, this is a reproducibility check of that backend, not a cross-backend comparison.

### Local API contract

`server/local_server.py` on port 8099: `POST /v1/jobs {exercise: auto, variant: strict, view: SAGITTAL}` → `PUT …/video` (0010) → `POST …/submit` → `done` after 11 s. Every top-level and per-rep field `BarraApi.parseAnalysis` reads is present; `variant = {strict, declared}`, `view.bin = SAGITTAL (declared)`, `measurementVersion = 2`, `assessment.checks` has all seven muscle-up rules. Saved as `out/technique-eval/api-contract-VID-20260827-WA0010.json`.

Edge cases through `process_job`, all returning a complete payload with a blocker and no exception: missing file, empty file, non-video bytes, a static hold (unknown movement, 0 checks), an unknown variant (`sticky` → unspecified with the word kept) and an unknown view (`DIAGONAL` → UNKNOWN, `hip_sag` unobservable ×19). Malformed model output and an absent provider are covered by `tests/test_vision_validation.py`.

### Android

`Models.kt` gains `Assessment`, `VisionObservation`, `Variant`, `CheckSummary`; `RepRow.assessments/phases/assessmentBlocked`; `MeasuredFault.errorId/phase/intervalS`; `Analysis.variant/measurementVersion/checks/visionObservations/visionDisagreesOnMovement`. `BarraApi.parseAnalysis` reads them, defaulting to empty on older payloads. `Cues.unmeasuredNote` names the checks that could not be made and why, and `improvementLines` no longer says "measured clean" when no check was made. `:app:compileDebugKotlin` passes offline with JDK 17; the parity test (`tests/test_cues_parity.py`) passes.

### Not done

- Corpus-scale movement evaluation (166 clips in `data/calisthenics`, all present, none with cached keypoints). The runner can do it once keypoints exist; the manifest format is ready for it.
- Any learned model (work package E).
- Live vision comparison (D3.4–5).
- AWS deployment verification.
- Frame-by-frame review of 0011 and 0019 (the two removals) and of 0010's top position.

## Research references

- [CUBIST / MyoMechanix, August 2026 preprint](https://arxiv.org/html/2608.26094v1): movement-conditioned, phase-aware error attribution and compositional assessment.
- [BioCoach, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Ji_From_3D_Pose_to_Prose_Biomechanics-Grounded_Vision-Language_Coaching_CVPR_2026_paper.pdf): visual and kinematic evidence for coaching.
- [FitAQA, August 2026 preprint](https://arxiv.org/html/2608.08736v1): exercise-error taxonomy and separate perception, judgement and localization evaluation.
- [V-JEPA 2.1](https://arxiv.org/abs/2603.14482) and [InternVideo](https://github.com/OpenGVLab/InternVideo): candidate video representations, not verified Barrapp error detectors.
- [Fitness-AQA](https://github.com/ParitoshParmar/Fitness-AQA) and [FitCoach](https://github.com/Qualcomm-AI-research/FitCoach/): task-specific datasets/baselines to assess for reuse.
