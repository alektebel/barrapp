# The first classification model

`barra/model.py` is the first *learned* model for exercise type and added load,
and the first thing in the project that is trained rather than derived.

The geometric classifier (`barra/classify.py`) draws its boundaries by hand on
measured geometry and is still the interpretable, verified answer. The model is
a **second opinion**: it learns the same boundaries from labelled footage and
extends what the rules never covered, and the server ships both so a report can
say which produced the label and how far apart they were.

`barra/fusion.py` now makes that second opinion useful in auto mode. It keeps
geometry authoritative when geometry is confident, but lets a clear learned-model
margin recover weak geometric calls. Fusion states its status
(`geometry-strong`, `model-overrides-weak-geometry`, `majority`, `abstain`, …)
so downstream UI/reports can show review rather than silently blending evidence.

## What it is

A one-hidden-layer softmax classifier (numpy-only, deterministic seed) over the
clip-level geometric features `barra/classify.features()` already computes. It
has no new geometry — it learns which feature values belong to which movement.
The full vector for all movements is `barra.model.FEATURE_NAMES` (n_frames,
shoulder-above-hands percentiles, hip travel, body line, arms/legs straight
fractions, single-leg stance, split-stance heights, and temporal summaries such
as `shoulder_above_hands_p90`, `shoulder_above_hands_over_bar_frac`,
`shoulder_above_hands_std`, `hip_travel_std`).

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
python scripts/train_model.py                     # live pose (needs a pose backend)
python scripts/train_model.py --no-live           # cached keypoints only (deterministic)
python scripts/train_model.py --tricks squat,push_up --per-trick 12
```

Labels come from `data/calisthenics/metadata.csv` (scraped corpus) and
`data/evaluation/sample_manifest.json` (the eight reviewed clips, whose pose is
already cached). Features are cached to `out/model_features/features.csv`, so a
rerun costs nothing. The model + metrics land in
`models/exercise_model.npz` + `model_metrics.json`.

`--no-live` exists because live pose extraction (mediapipe) can be killed by a
constrained host; a clip with no cached keypoints is then skipped rather than
polluting the corpus.

## Reading the results

`model_metrics.json` reports holdout accuracy and per-class precision/recall
**with support**. A class with support 1 is inconclusive, not 100% — the same
warning the technique evaluation uses. The checked-in model is trained on the
small reviewed set and is intentionally a first model; it is a starting point,
not a verdict. `docs/TECHNIQUE-PIPELINE-IMPLEMENTATION-PLAN.md` and
`data/evaluation/sample_manifest.json` describe the reviewed corpus it draws on.

## Honesty rules it holds

* It is a competitor signal, never the only one. `detected` still carries the
  interpretable geometric reason and fusion status; the model can only replace a
  weak auto-detected label when the margin is clear enough to name the case.
* Class probabilities sum to 1 and are labelled as model output, not certainty.
* The load head says "baseline" when it has no data.
* Per-class numbers carry their support, so nobody reads a single-clip 100% as
  evidence.
