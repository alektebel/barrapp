# The first classification model

`barra/model.py` is the first *learned* model for exercise type and added load,
and the first thing in the project that is trained rather than derived.

The geometric classifier (`barra/classify.py`) draws its boundaries by hand on
measured geometry and remains the interpretable answer — it states the
measurement behind every label, and fusion never erases it. It is no longer the
*authoritative* one. Measured out of fold on the 198-clip corpus:

| detector | accuracy |
| --- | --- |
| vision read of the frames | 0.907 |
| learned model | 0.576 |
| geometric rules | 0.227 |
| geometric rules, confidence ≥ 0.85 | 0.200 |

Geometry is the weakest detector by a factor of two, and its confidence is
*anti*-correlated with being right — so the old policy, which let geometry veto
the others above a 0.85 confidence gate, was handing the veto to geometry's
worst answers. Fusion scored 0.409 while its own learned input scored 0.576.

`barra/fusion.py` now ranks detectors by that measurement: agreement first
(two detectors naming the same movement ran at 0.861), then the most reliable
detector that has an answer. Fusion states its status (`majority`,
`geometry-model-agree`, `vision-decides`, `model-decides`, `geometry-only`,
`abstain`) so downstream UI/reports can show the disagreement rather than
silently blending evidence.

| arrangement | before | after |
| --- | --- | --- |
| geometry + learned (shipped) | 0.409 | **0.571** |
| geometry + learned + vision | 0.394 | **0.848** |

## What it is

A one-hidden-layer softmax classifier (numpy-only, deterministic seed, Adam)
over the clip-level features in `barra.kinematics.full_features()`. It has no
new geometry — it learns which feature values belong to which movement.

That vector is the 36 geometric names the thresholds use
(`barra.model.FEATURE_NAMES`: n_frames, shoulder-above-hands percentiles, hip
travel, body line, arms/legs straight fractions, single-leg stance,
split-stance heights) plus the ~70 kinematic names `barra.kinematics` adds
(joint-angle ranges, flexed/extended fractions, periodicity, landmark
visibility) — 106 in all. A model carries the names it was trained on, and
`server/process.py` computes whatever those names require, so widening the
vector does not silently feed the model a NaN for every name the geometric
detector never computed.

Two heads:

* **classifier** — `model_classify(model, features)` → the movement, the margin
  to the runner-up, and the whole probability vector, so a consumer sees how
  far from the boundary the call was rather than reading a bare label.
* **load** — `model_load(model, features)` → the athlete's added load.

The server embeds both per clip under `payload["model"]`:

```
detected   <- the geometric classifier (authoritative, interpretable)
model      <- the learned model + its load estimate (second opinion)
```

## The load model, honestly

Barra **cannot see added load** in a 2D pose: a weighted pull-up looks like a
pull-up. The load head knows its ceiling, so with no labelled loads it predicts
the bodyweight baseline (`0 kg`) and says so in `note` — never a confident
guess. Load is therefore **captured** by the athlete (`Goals.loadKg`) and stored
beside the measurement, and the model's estimate is a stocktake the phone can
show as "estimated", not an override.

Its real value comes with a labelled set: `train_load` fits an OLS line on
labelled clips. Until then it is honest, not silent.

## Training

```bash
python scripts/train_model.py                     # the measured corpus
python scripts/train_model.py --window none       # untrimmed clips, on purpose
python scripts/train_model.py --augment 1         # one view per clip
```

The corpus, the technique windows, the features and the fold discipline all
come from `scripts/classify_eval.py`, so the shipped model is the model the
eval measured. Clips are every video under `data/calisthenics/videos/` whose
keypoints are cached, labelled by their directory; the vision sidecars under
`data/calisthenics/labels/` supply the technique window each clip is trimmed
to.

The reported accuracy is out-of-fold, with folds assigned by clip so no
augmented view of a test clip is ever trained on. The model that ships is then
refit on every clip and is deliberately given no score of its own. Model +
metrics land in `models/exercise_model.npz` + `model_metrics.json`.

A clip with no cached keypoints is skipped rather than posed mid-training:
pose is paid once, in `scripts/extract_keypoints.py`, which runs each clip in
its own subprocess so one OOM costs that clip and not the batch.

## Reading the results

`model_metrics.json` reports holdout accuracy and per-class precision/recall
**with support**. A class with support 1 is inconclusive, not 100% — the same
warning the technique evaluation uses. `heldOut.accuracy` is the number to
quote; `shippedFit` deliberately carries no accuracy of its own, because the
model that ships has seen every clip.

## Honesty rules it holds

* It is a competitor signal, never the only one. `detected` still carries the
  interpretable geometric reason and fusion status; the model can only replace a
  weak auto-detected label when the margin is clear enough to name the case.
* Class probabilities sum to 1 and are labelled as model output, not certainty.
* The load head says "baseline" when it has no data.
* Per-class numbers carry their support, so nobody reads a single-clip 100% as
  evidence.
