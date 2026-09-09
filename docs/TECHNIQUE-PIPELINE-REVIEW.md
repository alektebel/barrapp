# Barrapp technique pipeline review

Reviewed: 2026-09-08. Scope: current working tree, including uncommitted changes.

## Verdict

The pipeline has improved, but correctness and evaluation gaps prevent calling it optimal. Fix movement-specific measurement semantics and evidence validation before investing in a larger recognition model. End-to-end speed remains unbenchmarked in this review.

## Findings, in priority order

### 1. High: pull-ups inherit a muscle-up support requirement

`barra/rules.py:131` defines incomplete lockout as shoulders reaching above the hands, and `barra/rules.py:223` applies that shared rule to pull-ups. `barra/evidence.py:558` computes the percentage from peak shoulder height. A pull-up does not require an above-bar straight-arm support, so this can label a valid movement with an inappropriate error.

The generic range component has the same problem (`barra/quality.py:110`). Directly calling it with full hang depth 1.0, arm reach 1.0, and peak shoulder height -0.05 yields range **0.5**, with “hang 100% of full, lockout 0% of full.” This reproduces the scoring semantics; it is not a claim that those two measurements alone prove a complete pull-up.

**Fix:** define range endpoints separately for each movement. Pull-up completion requires its own visible criteria and camera requirements; muscle-up support extension remains separate. Audit squat, dip and push-up scoring for the same shared assumptions. Verify complete, partial and unobservable examples per movement.

### 2. Medium: pistol depth has no evidence producer

`barra/rules.py:311` consumes `pistol_depth`. `barra/evidence.py` declares that primitive, but the repetition extractor emits only `squat_depth` at line 637. Consequently, the pistol depth check cannot become measurable through this extractor even with usable tracking.

**Fix:** implement a supporting-leg-specific depth measurement with leg identity, visibility requirements and phase boundaries. Do not simply rename bilateral squat depth without checking the lifted leg's effect. Add observable shallow/deep and occluded-leg cases.

### 3. Medium: vision observations can cite the wrong rep or no image

`server/vision.py:223` validates membership in global sets of frames, reps and phases, without validating their relationships.

Reproduced using the existing vision test fixtures: an observed pull-up lockout error for **r2**, phase **transition**, citing **f1.jpg** (r1/setup), passes with zero rejection counts. An observed error with an empty frame list also passes. r2 was not selected for stills in that fixture.

**Fix:** validate against the exact images successfully sent. Require visual evidence for positive observations; require frame-to-rep and phase compatibility, including the rule's permitted phases. Allow explicit abstention without supporting frames. Ensure rejected observations cannot reappear as unsupported claims in the prose. Vision remains advisory today, which limits but does not eliminate the user-facing impact.

### 4. Medium: cached pose identity is only a filename stem

`barra/posecache.py:47` maps videos to `<stem>.parquet`. Directly comparing cache paths for `/tmp/a/clip.mp4` and `/tmp/b/clip.mp4` returns equality. Replacing a clip with another file of the same name also leaves the old cache eligible. The cached table does not establish the source content or estimator configuration.

**Fix:** use source content and estimator/configuration fingerprints, retain source FPS and dimensions, and reject mismatched metadata. Provide a migration path for existing caches. This finding concerns cached/debug/evaluation runs; the live path estimates pose independently.

### 5. Medium: the evidence does not establish general detection quality

The manifest reports perfect movement accuracy on seven reviewed clips, but classes have tiny support, and `unknown` combines abstention cases. Only four clips have reviewed rep counts; error checks are sparse targeted assertions rather than a labeled positive/negative corpus. Knee-raise output fell from one rep to zero in replay, which needs video review before being called an improvement. The questionable pull-up clip also fell from one to zero.

**Fix:** label temporal boundaries and per-error present/absent/unobservable states, distinguish abstention from actual unknown movement, and split by athlete/session. Report per-class recall, per-error precision/recall, measurable coverage and false warnings per rep. Keep these eight clips as smoke tests, separate from a held-out benchmark.

## Performance opportunities

- `server/process.py:115` generates text prose before the vision pass; a successful vision note replaces that prose at line 147. With both providers enabled this incurs work whose prose is discarded. Use deterministic fallback prose and request text generation only if needed, or define useful non-overlapping outputs.
- The main vision request and second opinion run sequentially (`server/process.py:145,160`). Consider making the second opinion conditional on uncertainty or asynchronously available. Benchmark quality before removing it.
- `barra/evidence.py` recomputes full-clip torso, joint angles and other series for each rep before slicing. Precompute immutable clip features once, then measure phase windows. Profile before prioritizing this over pose extraction.
- Cached evaluation starts its timer after `load_or_estimate` (`scripts/evaluate_technique_pipeline.py:69–71`). It does not establish decode/pose/API/vision latency; cache misses may estimate pose outside that timer. Add separate stage timings, cache-hit status, peak memory, provider latency and total wall time. Measure fresh runs on the deployment hardware before selecting a faster pose backend or sampling rate.

No numeric speedup is claimed for these proposed changes.

## Verification performed

- Python suite: **288 passed in 3.61 seconds**.
- Actual analyzer replay: `.venv/bin/python scripts/evaluate_technique_pipeline.py --mode cached --out out/pipeline-review`.
- Results: `out/pipeline-review/20260908-234116-cached/`; eight payloads, zero runner failures, five changed from baseline.
- Direct diagnostics reproduced the range calculation, invalid vision evidence acceptance and filename cache collision described above.

| Clip suffix | Previous output | Current output | Interpretation |
| --- | --- | --- | --- |
| 0010 | 2 muscle-ups | 2 muscle-ups | Rep count retained; phase-scoped support assessments present |
| 0011 | 1 knee raise | 0 knee raises | Lost segmentation coverage; needs review |
| 0012 | 1 muscle-up | 1 muscle-up | Count retained |
| 0014 | 2 muscle-ups | 1 muscle-up | Previously identified walking interval removed |
| 0017 | unknown, 0 reps | unknown, 0 reps | Abstention retained |
| 0018 | unknown, 0 reps | unknown, 0 reps | Poor-tracking abstention retained |
| 0019 | 1 pull-up | 0 pull-ups | Candidate rejected; correctness not established |
| 0020 | 19 push-ups, 17 stall warnings | 19 push-ups, 0 stall warnings | Endpoint-related warning regression improved |

This review used cached keypoints through the actual analyzer. It did not rerun fresh pose estimation, call a remote vision provider, or measure a full upload-to-phone workflow. Passing tests and removing warnings are useful regression evidence, not a measured improvement in overall error-classification accuracy.

## Recommended implementation order

1. Correct movement-specific range and completion rules; wire pistol depth.
2. Enforce visual evidence relationships and cache identity.
3. Review the clips that lost reps, then expand the labeled benchmark.
4. Instrument fresh end-to-end processing and eliminate measured redundant work.
5. Compare learned movement/error models against the corrected baseline using the same held-out examples.

The broader architecture, model experiments and rollout plan are in [TECHNIQUE-PIPELINE-IMPLEMENTATION-PLAN.md](TECHNIQUE-PIPELINE-IMPLEMENTATION-PLAN.md).
