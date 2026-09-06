#!/usr/bin/env bash
# End-to-end check on a real phone over adb: fresh user, onboarding, upload,
# measurement, result on screen.
#
# The API-level twin of this is scripts/e2e_pipeline.py, which is the one to
# run in CI. This one exists because a whole class of bug lives only on the
# phone - a screen that never advances, a fabricated placeholder, a work the
# queue forgets - and none of it is visible from the API.
#
#   scripts/e2e_device.sh              # keep the current user, just upload
#   scripts/e2e_device.sh --reset      # wipe to a fresh user first
#
# --reset backs up shared_prefs to out/device-backup-<stamp>/ first. Restoring
# matters: the device id is the only key to the training history on the
# server, and a wipe mints a new one, stranding every past session.
set -uo pipefail

PKG=com.alektebel.barrapp
ACT="$PKG/com.barrapp.MainActivity"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESET=0
[ "${1:-}" = "--reset" ] && RESET=1

pass=0; fail=0
ok()   { echo -e "  \033[32mPASS\033[0m $1"; pass=$((pass+1)); }
bad()  { echo -e "  \033[31mFAIL\033[0m $1"; fail=$((fail+1)); }
check(){ if [ "$1" = "0" ]; then ok "$2"; else bad "$2 — $3"; fi; }

dump() { adb shell uiautomator dump /sdcard/e2e.xml >/dev/null 2>&1; adb shell cat /sdcard/e2e.xml; }
texts(){ dump | grep -oE 'text="[^"]{2,80}"' | sed 's/^text="//; s/"$//'; }

# Centre of the first node whose XML matches $1. Empty when there is none.
tap_match() {
  local node cx cy b
  node=$(dump | tr '<' '\n<' | grep -m1 -- "$1") || return 1
  b=$(echo "$node" | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
  [ -z "$b" ] && return 1
  set -- $(echo "$b" | sed -E 's/\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]/\1 \2 \3 \4/')
  cx=$(( ($1 + $3) / 2 )); cy=$(( ($2 + $4) / 2 ))
  adb shell input tap "$cx" "$cy"
}

works() { adb shell "run-as $PKG cat files/works.json" 2>/dev/null; }

adb get-state >/dev/null 2>&1 || { echo "no device over adb"; exit 1; }
echo "device $(adb devices | sed -n 2p | cut -f1)"

if [ "$RESET" = "1" ]; then
  BK="$ROOT/out/device-backup-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BK"
  for f in barrapp.xml barrapp_sessions.xml barrapp_profile.xml barrapp_goals.xml barrapp_events.xml; do
    adb shell "run-as $PKG cat shared_prefs/$f" > "$BK/$f" 2>/dev/null
    [ -s "$BK/$f" ] || rm -f "$BK/$f"
  done
  echo "backed up shared_prefs -> $BK"
  grep -o 'device_id">[^<]*' "$BK/barrapp.xml" 2>/dev/null | sed 's/^/  old /'
  adb shell pm clear "$PKG" >/dev/null 2>&1
  adb shell am start -n "$ACT" >/dev/null 2>&1; sleep 4
  texts | grep -q "^Privacy$"; check $? "a wiped app starts at the privacy screen" "got: $(texts | head -1)"
  tap_match 'text="I understand — continue"'; sleep 3
  texts | grep -q "STEP 1 OF 3"; check $? "accepting privacy opens onboarding" "got: $(texts | head -1)"

  tap_match 'class="android.widget.EditText"'; sleep 1
  adb shell input text "Diego"; sleep 1
  tap_match 'text="Continue"'; sleep 2
  tap_match 'class="android.widget.EditText"'; sleep 1
  adb shell input text "26"; sleep 1
  tap_match 'text="Continue"'; sleep 2
  texts | grep -q "STEP 3 OF 3"; check $? "onboarding reaches the last step" "got: $(texts | head -1)"
  tap_match 'text="Three or four times a week"'; sleep 1
  tap_match 'text="Continue"'; sleep 3
  adb shell "run-as $PKG cat shared_prefs/barrapp_profile.xml" 2>/dev/null | grep -q 'name="name">Diego'
  check $? "the profile is saved" "no profile written"
else
  adb shell am start -n "$ACT" >/dev/null 2>&1; sleep 4
fi

echo "  … opening the picker"
adb shell input tap 539 2140; sleep 5
dump | grep -qi "Fotos\|Photos\|Videos"
check $? "the upload button opens the video picker" "no picker appeared"

adb shell input tap 540 1350; sleep 2   # first clip, second column
tap_match 'text="Hecho"' || tap_match 'text="Done"' || tap_match 'text="Listo"'
sleep 6

# The newest work is the one this run just started. Judging the whole queue
# instead would fail on any older work left behind by a previous run, which is
# a fact about the queue's history, not about this upload.
newest() {
  works() { adb shell "run-as $PKG cat files/works.json" 2>/dev/null; }
  works | python3 -c "
import json,sys
try: w = json.load(sys.stdin)
except Exception: print('{}'); raise SystemExit
print(json.dumps(w[-1] if w else {}))
" 2>/dev/null
}
field() { echo "$1" | python3 -c "import json,sys;print(json.load(sys.stdin).get('$2',''))" 2>/dev/null; }

BEFORE=$(newest)
WORK_ID=$(field "$BEFORE" id)
[ -n "$(field "$BEFORE" jobId)" ]
check $? "a job was created on the server" "no jobId on the new work: $(echo "$BEFORE" | head -c 160)"
echo "$BEFORE" | grep -qv "unknown job"
check $? "the upload did not die on 'unknown job'" "the work-id/job-id regression is back"

echo "  … measuring (up to 5 min)"
for _ in $(seq 1 50); do
  W=$(newest)
  # Gone from the queue means measured: a finished work becomes a session.
  [ "$(field "$W" id)" != "$WORK_ID" ] && break
  [ "$(field "$W" status)" = "failed" ] && break
  sleep 6
done

W=$(newest)
if [ "$(field "$W" id)" != "$WORK_ID" ]; then
  ok "the work finished and left the queue"
else
  bad "the work finished and left the queue" "still $(field "$W" status): $(field "$W" error)"
fi

sleep 3
SCREEN=$(texts)
echo "$SCREEN" | grep -q "Measuring your set"
if [ $? -eq 0 ]; then
  bad "the app leaves the progress screen when the result arrives"
else
  ok "the app leaves the progress screen when the result arrives"
fi
echo "$SCREEN" | grep -qE "22\.0s clip|91% confident"
if [ $? -eq 0 ]; then
  bad "no fabricated placeholder on screen — found a hardcoded sample value"
else
  ok "no fabricated placeholder on screen"
fi
# The store writes JSON into an XML string, so the quotes arrive escaped.
adb shell "run-as $PKG cat shared_prefs/barrapp_sessions.xml" 2>/dev/null | grep -q "jobIds"
check $? "the session landed in the calendar" "nothing recorded locally"

echo
echo "$SCREEN" | head -8 | sed 's/^/  screen: /'
echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
