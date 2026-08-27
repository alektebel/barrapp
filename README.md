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
python -m unittest discover -s tests      # 36 invariant tests
```
