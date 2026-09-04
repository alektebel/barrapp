# APK build + GitHub upload status

Snapshot: 2026-09-04. The debug APK is built and verified; the GitHub upload
is **not yet done** because there is no GitHub credential on this machine.

## 1. The APK

- **Path**: `app/build/outputs/apk/debug/app-debug.apk`
- **Size**: 11 MB (debug-signed with the auto-generated debug keystore)
- **Baked base URL** (from `app/build/generated/source/buildConfig/debug/com/barrapp/BuildConfig.java`):

```java
public static final String API_BASE_URL = "https://gogtzcttw6.execute-api.eu-west-1.amazonaws.com";
```

This points the phone at the live `sam-app` stack (`eu-west-1`), the custom API
served by the Lambda functions (see `docs/AWS_RUNBOOK.md`).

## 2. Rebuild it later

This machine had no Java or Android SDK. I installed them user-local (no root):

- **JDK 17** (Temurin): `$HOME/.jdks/jdk-17.0.20.1+1`
- **Android SDK**: `$HOME/Android/Sdk` (cmdline-tools `latest`, platform `android-35`,
  build-tools `35.0.0`, platform-tools). `local.properties` was created with
  `sdk.dir=/home/diego/Android/Sdk`.

Build command:

```bash
cd /home/diego/Documents/Development/barrapp
export JAVA_HOME="$HOME/.jdks/jdk-17.0.20.1+1"
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
./gradlew assembleDebug
```

## 3. GitHub upload — blocked, needs your credential

`gh` is logged out, there is no `GH_TOKEN`, no git credential helper, and no SSH
key. The git remote is HTTPS, so push/release cannot succeed without auth.

To enable the upload, run **one** of:

```bash
gh auth login              # browser / device flow
# or
export GH_TOKEN=<fine-grained PAT>   # scopes: repo, releases: write on alektebel/barrapp
```

After auth, create the GitHub Release and attach the APK:

```bash
gh release create v1.0.0 \
  app/build/outputs/apk/debug/app-debug.apk \
  --repo alektebel/barrapp \
  --title "1.0.0" \
  --notes "AWS-connected build of the new app (see docs/AWS_RUNBOOK.md and docs/RELEASE.md).
Deploy: sam-app live in eu-west-1. Worker fixes: libGL.so.1 + pandas. App pointed at the live API."
```

## 4. Pending decisions (from the session)

1. **Destination** — GitHub Release asset (recommended) vs. committing the code +
   APK to the repo. Release was the plan.
2. **Auth method** — `gh auth login`, or a `GH_TOKEN` read from the environment.
3. Optional follow-up: the worker writes traces to the read-only `/opt/barra` layer,
   so `barra explain --replay <traceId>` may not find server-side traces; the app
   still works, only the replay is affected (see `docs/AWS_RUNBOOK.md` §6.1).

## 5. Where the code changes live (uncommitted)

- `gradle.properties` — debug + release now point at the live ApiUrl.
- `server/Dockerfile` — installs OpenCV/MediaPipe runtime libs (fixes `libGL.so.1`).
- `server/requirements-worker.txt` — `opencv-contrib-python` (not headless) + `pandas==2.2.3`.
- `.gitignore` — `data/calisthenics/videos/**` scrape exclusion.
- `docs/AWS_RUNBOOK.md`, `docs/RELEASE.md` — updated/added.
