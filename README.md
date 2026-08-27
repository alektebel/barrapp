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
