# Releasing barrapp

Updated 2026-09-04. The release flow is: commit the code, tag it, and publish a
GitHub Release with the debug APK attached. `gh` is authenticated on this
machine (as `alektebel`), so uploads and pushes work directly.

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
