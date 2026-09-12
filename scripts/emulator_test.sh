#!/usr/bin/env bash
# Boot an Android emulator, install the app, and capture screenshots + UI dump.
# Use this on a machine where $HOME/.android is writable (normal dev machine).
#
#   scripts/emulator_test.sh [apk]
#
# Requires: Android SDK (ANDROID_HOME), a system image, JAVA_HOME, and KVM.
# Writes: out/emulator/*.png (screenshots) and out/emulator/*.xml (UI dump).
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
JAVA_HOME="${JAVA_HOME:-$HOME/.jdks/jdk-17.0.20.1+1}"
export ANDROID_HOME JAVA_HOME
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

APK="${1:-dist/barrapp-1.1.0-debug.apk}"
AVD="${AVD:-testphone}"
IMG="system-images;android-35;google_apis;x86_64"
OUT="out/emulator"
mkdir -p "$OUT"

# 1. Create the AVD if it does not exist.
if ! emulator -list-avds | grep -qx "$AVD"; then
  echo "no" | avdmanager create avd -n "$AVD" -k "$IMG" -d pixel_6
fi

# 2. Boot headless (no window, software GPU, snapshots off).
echo "booting $AVD ..."
emulator -avd "$AVD" -no-window -no-audio -no-boot-anim \
  -no-snapshot -gpu swiftshader_indirect &
EMU_PID=$!

adb wait-for-device
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  sleep 2
done
echo "booted."

# 3. Install and launch.
adb install -r "$APK"
adb shell am start -n com.fitness.barrapp/.MainActivity
sleep 6

# 4. Screenshot each screen + dump the view hierarchy.
adb exec-out screencap -p > "$OUT/00-home.png"
adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 || true
adb pull /sdcard/ui.xml "$OUT/00-home.xml" >/dev/null 2>&1 || true

echo "screenshots + ui dumps -> $OUT"
echo "next: adb shell input swipe ... to navigate, then re-run the capture."

# Leave the emulator running for interactive testing; stop it with:
#   adb emu kill
echo "emulator pid $EMU_PID running (stop: adb emu kill)"
