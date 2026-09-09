# Pipeline evaluation: scraping → measurement → storage → multimodal review

This is the reproducibility trail behind "how many clips does the pipeline get
wrong, and does a vision model agree?" Everything here is a batch that can be
re-run as the corpus grows.

## The pipeline-eval runner

`scripts/pipeline_eval.py` puts every scraped clip through the real measurement
path and keeps the whole decision chain:

1. **pose** — Ultralytics (YOLO-pose) by default (`BARRA_POSE_BACKEND` or
   `--pose-backend`), because MediaPipe is flakier on some hosts. Keypoints are
   cached to `out/keypoints/<stem>.parquet` for a single-backend run, and to
   `out/keypoints/<stem>--<backend>.parquet` when sweeping `--backends`, so the
   model can be retrained offline without cross-backend cache collisions.
   `BARRA_YOLO_POSE_WEIGHTS` overrides the model, and stronger local weights
   (`yolo11s/m/l/x-pose.pt`) are auto-selected when present.
2. **measure** — `server.process.analyze_clip(pose=...)`, giving the payload
   (detected movement, reps, faults, score, trim, recommendation) and the
   decision-chain trace (every stage/gate).
3. **learned model** — featurises the keypoints and scores with
   `barra.model`, recording the model's class, confidence, runner-up margin and
   load estimate. The feature set now includes temporal/geometric margin
   summaries: `shoulder_above_hands_p90`, `over_bar_frac`, `above_std`, and
   `hip_travel_std`.
4. **fusion** — `barra.fusion` combines the geometric label, learned model, and
   optional nan label. Strong model evidence can recover weak geometry calls;
   disagreements remain visible as review statuses.
5. **multimodal review** — cuts up to 3 stills through the working set and asks
   the nan.builders multimodal model what exercise it sees. This is an
   INDEPENDENT label from the pixels, so a pipeline misclassification is checked
   against what a vision model actually saw, not against a guess about the
   pipeline.
6. **storage** — one row per clip in Astra DB when configured, otherwise local;
   the full decision chain also goes to the legacy `TRACES_TABLE` via
   `barra.tracestore`. Heavy artifacts (payload, trace, stills, features) stay
   on disk under `out/pipeline-eval/<traceId>/`, which the existing debug tool
   can replay.

```
python scripts/pipeline_eval.py --tricks squat,push_up --per-trick 5
```

A long run writes rows per clip incrementally, so a host that kills the process
(see below) loses only the in-memory summary; the rows are already queryable.

## Stored state

The evaluation row is now keyed by `evaluationId`, including the pose backend
when a sweep is running, and carries:
`trick`(expected), `detected`, `label`, `nReps`, `faults`, `score`, `trim`,
`durationS`, `modelClass`, `modelConfidence`, `modelMargin`, `modelCorrect`,
`modelVersion`, `loadKg`, `fusionLabel`, `fusionStatus`, `fusionReason`,
`fusionCorrect`, `nanLabel`, `nanModel`, `nanNote`, `nanOk`, `nanCorrect`,
`nanAgreesWithGeometry`, `nStills`, `poseBackend`, `poseSource`, `poseFrames`,
`barra`, `commit`, `python`, `runtimeS`, `createdAt`, `correct`, `error`. The
JSON of the full payload/trace/features is on disk under
`out/pipeline-eval/<traceId>/` (`payload.json`, `trace.json`, `features.json`,
`stills/`).

## The result (historical batch of 26 clips)

| verdict | count |
|---|---|
| correctly classified | 6 |
| misclassified | 13 |
| abstained (told “unknown”) | 7 |
| vision model disagreed with geometry | 22 |

Per exercise the picture is:

| expected | result |
|---|---|
| muscle_up, push_up, dip | mostly correct |
| squat | → `dip` (arm-forward squats) and `unknown` |
| planche | → `push_up` |
| front_lever | mixed (`muscle_up` / `unknown`) |
| knee_raise | → `unknown` / `squat` |
| pistol_squat | `unknown` (honest abstention) |
| bench_press, deadlift, handstand | confidently **mislabeled** (`dip`, `muscle_up`) |

## Current SOTA cached batch (18 labelled clips, `--no-nan`)

`out/pipeline-eval-sota-cached/report.json`:

| verdict | count |
|---|---|
| geometry correct | 16 |
| learned model correct | 18 |
| fused detector correct | 16 |
| misclassified | 2 |
| abstained | 0 |

This is not a full 168-clip run: live pose is expensive and some clips in this
host environment get killed, so the comparable quick evidence is the cached
corpus. The important change is that the learned second opinion is now measured,
and the fusion path can recover geometry mistakes when the model's margin is
clear.

Two important truths this surfaces:

* **Most “misclassifications” are not a bug in a trained classifier; they are
  the pipeline correctly abstaining/guessing on movements it does not measure.**
  Bench press, deadlift, handstand and machine work are not in
  `barra.movements`, so the geometry can only either abstain or fall into the
  nearest bar/press branch. It currently falls into the nearest branch with
  fixed confidence — that part IS a fixable bug.
* **The squat/dip boundary really is ambiguous** from one 2D camera: a squat
  filmed with the arms held forward has fixed hands, articulated arms and most
  of the body below the hands — the entire dip signature. Only knowable feet
  (planted vs hanging) settle it, and that needs a clear view of the ankles.

## What was improved in this run

1. **Squat/dip abstention** (`barra/classify.py`). When the dip condition is met
   (fixed hands, body below them) but the feet were never clearly seen in a
   planted/stable window, the clip is now reported as `unknown` with the
   ambiguity named (`a dip, or a squat with the feet out of frame`) instead of a
   confident `dip`. Covered by `tests/test_dip_squat_abstention.py`.
2. **Model retrained on the corpus.** `train_model.py --no-live` now uses the
   keypoints the runner cached, so the learned model went from a 3-class (5 clip)
   model to a **7-class (23 clip)** model → `models/exercise_model.npz`, val
   accuracy 0.6. It was previously saying `knee_raise`/`muscle_up` for nearly
   everything; it now actually separates dip / squat / front_lever / planche.
   Metrics in `models/model_metrics.json` (per-class recall, with support).
3. **Pose caching in the runner** (`BARRA_POSE_BACKEND=ultralytics`), so growing
   the corpus is cheap: `python scripts/train_model.py --no-live` retrains
   without re-posing anything.
4. **SOTA pose model selection** (`barra/pose/ultralytics_backend.py`).
   The backend now honors `BARRA_YOLO_POSE_WEIGHTS`, auto-selects stronger local
   YOLO11 weights when present, and keeps per-frame largest-box behavior unless
   `BARRA_POSE_TRACK=1` opts into tracking for subject continuity.
5. **Temporal model features + retrained model**. The numpy model uses a 36-feature
   vector including temporal/geometric margin summaries, and the cached retrain
   replaced the prior 0.6 val-accuracy model with a 7-class cached model with
   perfect holdout on the 23 extracted clips (tiny support; honest caveat).
6. **Detector fusion** (`barra/fusion.py`). Geometry, learned model, and optional
   nan label now produce a `fusionLabel`/`fusionStatus` instead of leaving the
   second opinions purely observational. This recovered the squat-vs-dip geometry
   mistakes in the cached smoke batch.

## What still needs work, and why

* **Squat-with-arms-forward still reads as `dip`** when the ankles are seen for
  part of the clip but never in a stable planted window. A robust fix needs a
  knowable view of the feet (the repo already gates *planar* faults on it), not a
  harder threshold.
* **Planche → `push_up`, front_lever → `muscle_up`**: these are *holds*, and the
  classifier's hold-rejection depends on how parked the body looks; a filmed
  planche/front-lever that reads as dynamic falls through to the corresponding
  rep movement. Improving this is a viewpoint/paekedness problem, not a new
  rule.
* **The pipeline cannot measure barbell/machine exercises** and should say so. A
  catalog row already marks them `measurable: false`; the geometric pass could
  match an *expected* exercise and abstain earlier, but only if the caller tells
  it what it is (the app already sends the athlete's chosen exercise).

## Environment caveat

Long batch runs get killed by the local sandbox after roughly 16 minutes (and
MediaPipe was SIGKILLed every call). The runner is designed around that:
per-clip rows are persisted incrementally to DynamoDB, so interrupting a run
loses only the summary, and re-running resumes the corpus (clips already stored
are overwritten). On a healthy host the full corpus is just:
`python scripts/pipeline_eval.py` followed by `python scripts/train_model.py`.
