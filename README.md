# barrapp

Phone films a set. AWS measures it. The phone shows the numbers.

Package id for Play: `com.alektebel.barrapp`.

## Local

```bash
source scripts/env.sh
./gradlew assembleDebug
python3 server/local_server.py
```

Install `app/build/outputs/apk/debug/app-debug.apk`. The phone must be on the same Wi-Fi. Restart the server after pulling; it now requires `X-Device-Id`.

## AWS and Play Store

Step-by-step: [`docs/AWS.md`](docs/AWS.md). Store listing: [`docs/PLAY.md`](docs/PLAY.md). Privacy text to host: [`docs/privacy.md`](docs/privacy.md).

Release bundle (after AWS `ApiUrl` is in `gradle.properties`):

```bash
source scripts/env.sh
./gradlew bundleRelease
# app/build/outputs/bundle/release/app-release.aab
```

## The app

Three questions, then a home screen: training calendar on the left, the session
in the middle, progress and a coach on the right. Add a clip and it is trimmed to
the exercise, the movement is recognised, reps are counted, and each gets a
baseline quality proxy. What each screen does and — importantly — what was and
was not verified: [`docs/APP.md`](docs/APP.md).

## The measurement core

The `barra/` Python package is what the server runs: pose extraction, rep
segmentation, per-rep metrics, and the leave-one-out null distribution that
stops a number being reported without a yardstick. It is documented separately
in [`docs/CORE.md`](docs/CORE.md), with the two findings that shape the whole
design in [`docs/FINDINGS.md`](docs/FINDINGS.md) and
[`docs/PROGRESS.md`](docs/PROGRESS.md).

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install -e ".[mediapipe]"
python -m unittest discover -s tests      # 137 invariant tests
```

## Batch-evaluating the pipeline against a vision model

`scripts/pipeline_eval.py` runs every scraped clip through the measurement
pipeline, keeps each clip's intermediate state and the program/model that
produced it (`barra-pipeline-eval` in DynamoDB, traces in `TRACES_TABLE`,
payloads/traces/stills on disk under `out/pipeline-eval/`), and asks a
nan.builders multimodal model what it *sees* — an independent label from the
pixels, to check the geometry against. It is how "how many does it get wrong"
is answered with evidence, not a guess:

```bash
BARRA_POSE_BACKEND=ultralytics python scripts/pipeline_eval.py \
    --tricks squat,push_up,dip --per-trick 3
```

Results and the improvements it drove (squat/dip abstention, model retrained on
the corpus) are in [`docs/PIPELINE-EVAL.md`](docs/PIPELINE-EVAL.md).

## The exercise catalogue, and the first learned model

The app's exercise catalogue (`data/exercises/catalog.json`, loaded by
`barra/exercises.py`) names the gym's common movements and, for each, the five
mistakes a coach corrects most. The split it keeps is the one the whole tool is
built on: a `measurable` row names a real `ruleId` barra reports from footage;
a `catalog-only` row (rows, curls, machines) is teaching content, honestly
marked, never reported as a measurement. `sentadilla búlgara`
(`bulgarian_split_squat`) and `split_squat` are measurable.

Alongside the geometric classifier there is now a first **learned** model
(`barra/model.py`, documented in [`docs/MODEL.md`](docs/MODEL.md)) that
classifies the exercise type and estimates added load from the same clip
features. It is a second opinion, never a replacement: the server ships both,
and the model's load estimate says "baseline" when it has no labelled data
(barra cannot see weight in a 2D pose; the athlete captures it).

```bash
python scripts/train_model.py --no-live           # retrain on cached keypoints
python scripts/train_model.py                     # retrain, posing new clips
```

## Does it recognise the right movement?

Seven of the eight sample clips, checked by watching each one and comparing
against what the classifier says with no labels and no hints. The eighth is a
real muscle-up that barra declines to name because the athlete's hands are
above the top edge of the frame — it says so, and says to tilt the camera up,
rather than guessing. Full table and the two findings behind it:
[`docs/CORE.md`](docs/CORE.md).

```bash
python scripts/demo_sessions.py        # classify, describe and report, end to end
```

## Does the quality score measure anything?

Movement quality has no ground truth, so "accuracy" is unfalsifiable — but
*validity* is testable without a single label, because the experiments carry
their own answers. A set taken to failure orders its own reps; two phones on
one set give you a noise floor; a deliberate fault is a label you own.

```bash
barra validate-quality --protocol   # what to film, and why
barra validate-quality              # the verdict on the clips you have
```

Currently it fails, for reasons worth reading before trusting any score:
[`docs/QUALITY.md`](docs/QUALITY.md).

## What it says about technique, and what it refuses to say

Every technique error is a rule in `barra/rules.py` with a stable id
(`muscle_up.incomplete_support_extension`), the phase it is read in, the
primitive and the threshold. For each rep the payload carries every rule's
verdict — `observed`, `not_observed`, or `unobservable` with the reason (camera
angle, too little of the phase tracked, a joint never seen) — so an empty fault
list can be told apart from a rep nothing could be checked on. The phone
renders that distinction rather than "clean".

Payloads carry `measurementVersion` (currently 2). The phase semantics and the
stall rule changed between 1 and 2, so a score from an older payload is not
comparable rep for rep with a new one; `provenance.measurement` names the
conventions in force. The evaluation runner replays the sample clips and diffs
them against the saved baseline:

```bash
python scripts/evaluate_technique_pipeline.py --mode cached   # fixed keypoints
python scripts/evaluate_technique_pipeline.py --mode fresh VID-....mp4   # real pose
```

Plan, results and what is still open:
[`docs/TECHNIQUE-PIPELINE-IMPLEMENTATION-PLAN.md`](docs/TECHNIQUE-PIPELINE-IMPLEMENTATION-PLAN.md).

## When a number looks wrong

Every stage records what it measured, what it required, and where in the clip
it looked, so any result can be traced back to the evidence behind it:

```bash
barra explain data/videos/YOUR-CLIP.mp4      # the whole decision chain
barra explain --replay 260828-221455-4f8a59  # a run the server did earlier
```

The trace id shown in the app's Diagnostics screen is the same id the server
logged and the same one on disk, so you are never guessing which run you are
looking at. How the chain fits together, and the two real defects it has
already caught: [`docs/DEBUGGING.md`](docs/DEBUGGING.md).

To see it on the video instead of in ASCII — skeleton over the pixels, the
signal, and every rejection at the second it happened — open the browser
debugger:

```bash
python tools/debugweb/server.py      # -> http://127.0.0.1:8091
```

It reads only traces the pipeline wrote, so anything it shows is the pipeline's
own answer, not the tool's. Its guide, and the local/AWS end-to-end checks that
prove the whole `upload → measure → JSON` path:
[`tools/debugweb/README.md`](tools/debugweb/README.md).
