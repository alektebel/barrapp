# Background completion for clip uploads ("segundo plano")

Status: proposal. Nothing here is implemented yet.
Scope: the Android app (`app/`). The server already does the heavy work.

## The problem in one paragraph

A clip's upload and its wait for the report run inside `BarrappViewModel`'s
`viewModelScope`. That scope is tied to the app process. The app posts an
ongoing "Analyzing your clip" notification, but there is **no foreground
service and no WorkManager job** driving the work, so Android is free to
suspend the network or kill the process while the user is in another app.
When that happens the upload simply stops; it only resumes the next time the
app is opened. The user cannot reliably "start the upload, put the phone down,
and get a notification" — which is exactly what `ProcessingNotifier`'s own
docstring promises.

## What happens today (verified in the current tree)

- **Work is started and owned by the ViewModel.** `BarrappViewModel.init`
  creates a `Channel<String>` queue and launches `consumeQueue()`
  (`app/src/main/java/com/barrapp/BarrappViewModel.kt:86`, `:152`, `:597`).
  `consumeQueue` pulls a work id and calls `runWork`.
- **`runWork` does everything:** create job, resumable multipart upload,
  `submit`, then polls `GET /v1/jobs/{id}` up to 240 times (`:776`) at ~10 s
  intervals — up to ~40 minutes. `uploadResumable` persists each part + etag
  (`:655`) so it can resume.
- **The notification is not a foreground service.** `ProcessingNotifier`
  (`app/src/main/java/com/barrapp/notify/ProcessingNotifier.kt`) posts an
  `IMPORTANCE_LOW`, `setOngoing(true)` notification. It is only a notification:
  it does not raise the process priority.
- **The manifest declares no service and no FGS permission.**
  `app/src/main/AndroidManifest.xml` has `INTERNET` and `POST_NOTIFICATIONS`
  only; there is no `<service>` and no `FOREGROUND_SERVICE*` permission. The
  `<application>` uses the default `Application` class.
- **WorkManager is already a dependency** (`androidx.work:work-runtime-ktx:2.10.0`,
  `app/build.gradle.kts:128`) and is used by `WeeklyReviewWorker`.

## What already works, and is worth keeping

The design is already close to resumable; only the execution lifetime is wrong.

- **Durable queue:** `WorkStore` (`app/src/main/java/com/barrapp/data/WorkStore.kt`)
  persists every work, its status, its multipart `uploadId`, and the parts +
  etags already accepted, to `filesDir/works.json`.
- **Resume on launch:** `init` re-enqueues works that were active
  (`resumed`, `BarrappViewModel.kt:116-153`).
- **Network watcher:** a default-network callback re-enqueues work paused mid
  upload (`BarrappViewModel.kt:156-161`), and `PauseUpload` (`:607`, `:759`)
  marks a work `connecting` instead of failing it.
- **Result recovery:** `syncHistory()` pulls `/v1/history` and records any
  finished job the phone has not seen (`BarrappViewModel.kt:174-188`), so a
  result produced while the app was dead is not lost.
- **The server finishes on its own.** Once `POST /v1/jobs/{id}/submit` returns,
  the Lambda completes regardless of the device. The app only needs to stay
  alive to (a) finish uploading and (b) poll and notify.

So the real requirement is narrow: **keep the upload + poll alive across the
user leaving the app, and notify on completion.**

## Requirements (acceptance criteria)

1. Starting a clip and then pressing Home / locking the screen / switching apps
   must not stop the upload, and must not require reopening the app.
2. If the network drops (tunnel, airplane mode), the work must wait and
   auto-resume without the user reopening the app, and without re-uploading
   parts already accepted.
3. A persistent notification must show progress through the stages, and a
   result/failure notification must appear when it finishes.
4. If the OS kills the process anyway, reopening the app must resume from the
   last accepted part and must still surface a result the server produced.
5. No regressions: `WorkStore` remains the source of truth; the ViewModel UI
   state (`works`, `analysis`, calendar) keeps working.

## Options

### Option A — Foreground Service wrapping the existing queue

Create a `Service` that, on start, calls `startForeground()` with the existing
`processing` notification and runs the queue consumer (moved out of the
ViewModel into a process-level engine). Stop it when no work is active.

- **Pros:** smallest conceptual change; reuses `ProcessingNotifier`, `runWork`
  and `uploadResumable` almost as-is; the notification is now legitimate and the
  process is high-priority; polling for tens of minutes is fine.
- **Cons:** a foreground service still dies with the process (it improves
  priority, it does not guarantee survival); it does not wait for network on
  its own — the network callback lives in the ViewModel, so if the app is dead
  there is nothing to resume the work. Started from a user action, so the
  Android 12+ "no FGS from background" rule is satisfied.
- **Verdict:** good if we also move the network watcher into the service.

### Option B — WorkManager `CoroutineWorker` (recommended)

Move the upload + submit + bounded polling into a `CoroutineWorker` enqueued
with `NetworkType.CONNECTED`. During transfer, call `setForeground(...)` with
the `processing` notification. The worker is the durable driver; the ViewModel
becomes a UI observer of `WorkStore` and of WorkManager state.

- **Pros:** survives process death and reboot (WorkManager persists work);
  waits for network and retries by itself, so requirement 2 holds even with the
  app dead; system-managed backoff; `WorkStore` stays the record. This is the
  standard, robust answer for "upload then wait for a server job".
- **Cons:** larger refactor — `runWork` / `uploadResumable` must be extracted
  from `BarrappViewModel` into a shared engine callable from the Worker;
  `ProcessingNotifier` is reused but driven from the Worker; WorkManager
  constraints/foreground types need care on Android 14+.
- **Verdict:** the right target. It is the only option that keeps the promise
  when the process dies, which is the actual failure the user hit.

### Option C — Hybrid

WorkManager worker as the durable driver, promoting itself to a foreground
profile during the active transfer, plus a thin service if a specific OEM needs
it. Do **not** build this first; Option B with `setForeground` already covers
the foreground-notification requirement.

## Recommended design (Option B, in phases)

### Phase 1 — Extract an app-scoped engine (no behavior change)

Move the queue ownership out of the ViewModel:

- New `com.barrapp.work.UploadEngine` object (or a class held by an
  `Application` subclass) owns the `Channel<String>` and the
  `consumeQueue` / `runWork` / `uploadResumable` code currently in
  `BarrappViewModel`.
- New `BarrappApp : Application` (register it via `android:name=".BarrappApp"`
  in the manifest) creates the engine and exposes the connectivity callback.
- `BarrappViewModel` keeps `works`/`analysis`/calendar state and simply
  observes `WorkStore` + engine events. Its `_state` updates on done/failed
  move into a callback the engine invokes.
- Do this first, on its own PR, with the ViewModel still the only caller, so
  the refactor is behavior-preserving and the test suite stays green.

### Phase 2 — Drive the engine from WorkManager

- Add `UploadWorker : CoroutineWorker`.
- Enqueue unique work per local work id
  (`enqueueUniqueWork("upload-$id", ExistingWorkPolicy.KEEP, request)`), with
  `Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()`.
- `doWork()`: load the work from `WorkStore`; if it is already done/failed,
  return `Result.success()`. Otherwise run the engine's `runWork` for that id.
  Return `Result.retry()` on transient failure (WorkManager applies backoff);
  `Result.success()` when done or permanently failed.
- While uploading/polling, call `setForeground(ForegroundInfo(id, notification,
  FOREGROUND_SERVICE_TYPE_DATA_SYNC))` so the notification shows and the OS
  keeps it running.
- The existing connectivity watcher is no longer required for resume (the
  constraint handles it) but can stay for UI responsiveness.

### Phase 3 — Manifest and permissions

```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />
<!-- already present -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

<application android:name=".BarrappApp" ...>
    <service
        android:name="androidx.work.impl.foreground.SystemForegroundService"
        android:foregroundServiceType="dataSync"
        tools:node="merge" />
</application>
```

- Android 14 (API 34): the FGS type must be declared and the matching
  permission held. `dataSync` is the correct type for an upload.
- Android 13+: `POST_NOTIFICATIONS` is already requested at runtime
  (`docs`/Home flow). A denied permission must not block the upload — the work
  still runs, only the notification is silent.
- Android 12+ restricts starting a foreground service from the background.
  WorkManager starts it from the enqueue point (user action) and via the job
  scheduler, which is why Option B is safer than a hand-rolled service here.

### Phase 4 — Completion and notification

- Keep `ProcessingNotifier` as the single notification surface; add a
  `ForegroundInfo`-producing variant and map the server's stage strings to it.
- On `done`/`failed`, post the result/failure notification (already implemented
  in `runWork`) and `stopForeground(STOP_FOREGROUND_REMOVE)`.
- `syncHistory()` stays as the safety net for results produced while no worker
  was alive (e.g. after a force-stop).

## Stage-name mismatch to fix while in here

`ProcessingNotifier.STAGES` is
`Uploading the clip / Finding the exercise / Trimming to the working set /
Counting and measuring the reps`, but the server sends stages like
`receiving the clip`, `opening the clip`, `locating the exercise`,
`scoring the reps` (`server/api/handler.py`, `server/process.py`). The match
falls back to index 0 for anything unknown, so the progress bar is usually
pinned at the first step. Either align the server strings or map them
explicitly in the notifier.

## Risks and edge cases

- **Long poll vs worker limits.** The poll is up to 240 × ~10 s ≈ 40 min. A
  foreground worker can run that long, but Workers on battery/Doze may be
  delayed; keep the server-side `_reap_stale` reaping (>30 min) in mind and
  consider a shorter, backing-off poll.
- **Double execution.** A work could be resumed by both WorkManager and a
  relaunch. Guard with a per-work "running" claim (e.g. an atomic flag in
  `WorkStore` or an in-memory set) and keep `uploadResumable` idempotent (it
  already is by part number).
- **Force-stop.** WorkManager cannot run after the user force-stops the app
  until it is opened again. `syncHistory` covers the result; the upload itself
  resumes on reopen. State this honestly in the UI.
- **Battery optimizations on OEMs.** Some OEMs kill background work; the
  ongoing notification + FGS is the best available mitigation.
- **Notification permission denied.** Upload must proceed silently.
- **`setForeground` timing.** Android requires foreground promotion within the
  worker's start; call it before the first network call.

## Testing plan

- **Emulator, upload started then backgrounded:** press Home, leave for the
  full analysis, confirm the result notification and that `WorkStore` ends
  `done`. Repeat with the screen locked and with the app swiped from Recents.
- **Process death:** `adb shell am kill com.fitness.barrapp` (or swipe-away)
  mid-upload; reopen and confirm resume from the last part, no duplicates.
- **Network loss/resume:** airplane mode mid-upload; confirm status becomes
  `connecting`, then auto-completes when network returns with the app dead.
- **Force-stop:** confirm the work resumes on next open and `syncHistory`
  surfaces a result produced meanwhile.
- **Doze:** `adb shell dumpsys deviceidle force-idle` while polling; confirm the
  foreground worker continues or resumes.
- **Notification permission denied:** confirm the upload still completes.
- **Regression:** the existing app/server tests plus a manual pass over the
  Works list, Session pane, and calendar.

## Suggested PR breakdown

1. **refactor:** extract `UploadEngine` + `BarrappApp`; ViewModel observes. No
   behavior change. Ship and verify.
2. **feat:** `UploadWorker` with network constraint and `setForeground`;
   enqueue on clip pick; retire the ViewModel-owned queue.
3. **chore:** manifest permissions/service, stage-name mapping, notification
   polish.
4. **test:** the manual matrix above + any unit tests for the engine's
   idempotency.

## Open questions

1. Keep Option A (a plain foreground service) as a fallback for OEMs where
   WorkManager foreground is flaky, or commit to WorkManager only?
2. Should the poll be shortened/backed-off now that it can run in the
   background, given the server reaps stale jobs after ~30 min?
3. Do we want a "cancel upload" action from the ongoing notification?
