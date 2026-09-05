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

## What a movement is for

The measurement core says what a rep did. `scripts/scrape_techniques.py`
collects what a rep is *for* - cues, common faults, muscles - from openly
licensed sources, with the licence and the record kept on every line, and
`barra technique muscle_up` prints it. The app shows the same card under a
session and under the next step on the Plan page, labelled as quoted rather
than measured. Attribution: [`data/techniques/ATTRIBUTION.md`](data/techniques/ATTRIBUTION.md).

```bash
python scripts/scrape_techniques.py        # free-exercise-db, wger, Wikipedia
barra technique                            # what is documented
```

A clip that holds still is a result now, not a refusal: a dead hang, a lever,
a handstand, a plank get named and timed. What was and was not verified on
real footage, and what to do next: [`docs/NEXT.md`](docs/NEXT.md).

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
