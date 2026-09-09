# Releasing barrapp

Updated 2026-09-08. Two flows: a GitHub Release with the APK attached (section
1, for side-loading) and the Play Console internal-testing track (section 3,
for the first batch of testers). `gh` is authenticated on this machine (as
`alektebel`), so uploads and pushes work directly.

## 0. Signed release build (APK + AAB)

```bash
cd /home/diego/Documents/Development/barrapp
export JAVA_HOME="$HOME/.jdks/jdk-17.0.20.1+1"
export ANDROID_HOME="$HOME/Android/Sdk"
./gradlew --offline testDebugUnitTest --tests 'com.barrapp.PayloadContractTest' \
    --tests 'com.barrapp.LogicTestSuite' lintDebug assembleRelease bundleRelease
```

- `app/build/outputs/apk/release/app-release.apk` - signed with the release
  key (`keystore/barrapp-release.jks`, read via `keystore.properties`; both
  are git-ignored). Side-loadable; the one to hand to testers outside Play.
- `app/build/outputs/bundle/release/app-release.aab` - the one Play Console
  takes. Play cannot install an AAB directly; it builds the APKs it serves.
- Both bake `barrapp.apiUrlRelease` from `gradle.properties` into
  `BuildConfig.API_BASE_URL`. Check it before every build.
- Verify the signature: `apksigner verify --print-certs <apk>` must show
  `CN=barrapp, OU=barrapp, O=alektebel, C=ES`. Play rejects a bundle signed
  with a different key than the first upload.
- Bump `versionCode` in `app/build.gradle.kts` before every upload; Play
  refuses a code it has already seen. `versionName` is what testers read.

Copies land in `dist/` as `barrapp-<versionName>-release.{apk,aab}` (git-ignored).

## 1. Release flow

1. Build the APK (section 2 below).
2. Copy it to `dist/` with the version in the name, e.g.
   `dist/barrapp-1.0.5-debug.apk`.
3. Tag and push:

   ```bash
   git tag v1.0.5 && git push origin v1.0.5
   ```

4. Create the GitHub Release with the APK attached:

   ```bash
   gh release create v1.0.5 dist/barrapp-1.0.5-debug.apk \
     --repo alektebel/barrapp --title 1.0.5 --notes "..."
   ```

   If the release already exists and only the asset needs (re)attaching:

   ```bash
   gh release upload v1.0.5 dist/barrapp-1.0.5-debug.apk --clobber --repo alektebel/barrapp
   ```

5. Verify: `gh release view v1.0.5 --repo alektebel/barrapp` - the `asset:` line
   must list the APK.

## 2. Rebuild the APK

Machine-local toolchain (no root, installed under `$HOME`):

- **JDK 17** (Temurin): `$HOME/.jdks/jdk-17.0.20.1+1` - java is **not** on PATH,
  so `JAVA_HOME` must be exported in every new shell.
- **Android SDK**: `$HOME/Android/Sdk` (cmdline-tools `latest`, platform
  `android-35`, build-tools `35.0.0`, platform-tools). `local.properties` points
  at it with `sdk.dir=/home/diego/Android/Sdk`.

Build command:

```bash
cd /home/diego/Documents/Development/barrapp
export JAVA_HOME="$HOME/.jdks/jdk-17.0.20.1+1"
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
./gradlew assembleDebug
```

Output: `app/build/outputs/apk/debug/app-debug.apk` (debug-signed with the
auto-generated debug keystore), ~11 MB.

The APK bakes the API base URL at build time (from
`app/build/generated/source/buildConfig/debug/com/barrapp/BuildConfig.java`):

```java
public static final String API_BASE_URL = "https://gogtzcttw6.execute-api.eu-west-1.amazonaws.com";
```

This points the phone at the live `sam-app` stack (`eu-west-1`), the custom API
served by the Lambda functions (see `docs/AWS_RUNBOOK.md`).

## 3. First batch of testers (Play Console, internal testing)

Internal testing is the right track for a first batch: up to 100 testers by
e-mail, no review queue, a build is live minutes after upload, and the same
release can be promoted to closed/open testing later without rebuilding.

Before the upload, the backend the app talks to must serve the payload the
app was built for. `measurementVersion: 2` (per-rep `assessments`, `variant`,
`assessment.checks`) comes from `server/process.py` on this branch; the
deployed `sam-app` worker predates it. Deploy the worker first
(`docs/AWS_RUNBOOK.md` §6, `sam build && sam deploy` under `newgrp docker`),
then `curl "$ApiUrl/health"`. The app degrades cleanly against the old worker
(rep cards fall back to the flat fault list and say "measurement v1") but the
point of this batch is the new checks, so do not skip this.

1. **Play Console → the app (`com.fitness.barrapp`) → Testing → Internal
   testing → Create new release.**
2. **App signing.** First upload only: accept Play App Signing. Play keeps its
   own signing key; `keystore/barrapp-release.jks` becomes the *upload key*.
   Every later AAB must be signed with this same upload key - back it up off
   this machine now (`keystore/` and `keystore.properties` are git-ignored on
   purpose).
3. **Upload** `dist/barrapp-1.3.0-release.aab` (versionCode 18). Release name
   is prefilled from `versionName`; release notes are what testers see in the
   Play update card - two or three lines, e.g.
   "Every technique check now says whether it was seen, clean, or could not be
   judged - and why. Declare strict/kipping and the camera side before you
   pick a clip. Flagged errors show the phase and the seconds they happened."
4. **Testers tab → Create email list.** Paste the testers' Google account
   e-mails (comma-separated). Save, tick the list, save changes. Copy the
   **opt-in link** shown at the bottom ("How testers join your test").
5. **Review release → Start rollout to Internal testing.** No store review
   for this track; the build is available once processing finishes
   (typically under 15 minutes).
6. **Send testers** the opt-in link. Each tester opens it while signed in to
   the Google account you listed, taps *Become a tester*, then installs from
   the Play link on that page (or searches Play if the listing is already
   public - it is not, yet). Updates arrive through Play like any other app.
7. **App content** must be complete before *any* track can roll out, even
   internal: privacy policy URL (host `docs/privacy.md`, see `docs/PLAY.md`),
   data safety form, ads declaration, content rating, target audience. Play
   blocks the rollout button until these are done.

Side-loading fallback (tester without a Google account on the phone, or the
Play listing not yet set up): send `dist/barrapp-1.3.0-release.apk` directly
(GitHub Release per section 1, or any file transfer). It is signed with the
release key, so it upgrades in place over an earlier release-signed install,
but **not** over a debug-signed one - those must be uninstalled first, which
loses the local calendar cache (the measurements themselves are on the
server and reload on sign-in).

Ask the testers for three things: the session's `run <trace-id>` line from
the bottom of the rep list whenever a number looks wrong, a clip they filmed
side-on and one front-on so the "could not be checked" reasons can be
verified, and whether the standard they declared came back on the session
page.
