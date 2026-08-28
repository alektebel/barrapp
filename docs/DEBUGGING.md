# Why did it do that?

Every number this project reports can be traced back to the evidence that
produced it and the threshold it was compared against. Nothing here is a
logging convenience — it is the difference between a wrong answer you can fix
and a wrong answer you can only shrug at.

The rule the code follows: **a stage that rejects something must say what it
measured, what it required, and where in the clip it looked.** "No reps found"
is not a reason. This is:

```
[segment]
   107ms  x the hands were not on anything fixed
            wrist_travel = 1.163
            max_travel = 0.8
            window_s = [22.61, 25.89]
```

That is a number, a threshold, and a timestamp you can scrub to.

## The one command

```bash
barra explain data/videos/YOUR-CLIP.mp4
```

It runs the same pipeline the server runs, with tracing on, and prints the
decision chain: probe → pose → classify → segment → metrics → quality → result.

```
trace 260828-222217-1a74eb  ·  VID-20260827-WA0010.mp4

[classify]
   244ms -> the shoulders finish above the hands
            peak_above_hands = 0.9471
            over_bar_threshold = 0.12
            confidence = 0.98
[segment]
   244ms -> accepted
            window_s = [2.37, 7.92]
            turnaround_s = 5.87
[result]
   247ms -> mean of the reps that could be scored
            exercise = muscle_up
            session_score = 78
            band = solid

  trace written to out/traces/260828-222217-1a74eb.json
  34 entries · 0 rejections · 0 errors
```

| flag | |
|---|---|
| `--show decisions` | the choices only (default) |
| `--show all` | every step, including the ones that went fine |
| `--show problems` | only rejections and errors |
| `--exercise pull_up` | force a movement instead of detecting one |
| `--fresh` | re-run pose estimation instead of reusing cached keypoints |
| `--list` | recent traces on disk, with rejection and error counts |
| `--replay <id>` | print a trace written earlier — **including one from the server** |

Cached keypoints make the loop usable: 78 seconds becomes 1.3. The trace says
when it reused them, because a trace that silently mixed a fresh run with an
old pose would be worse than none.

## Following one number from the phone back to the code

This is the whole point of the chain. A user says "it gave me 43 and that's
wrong":

1. **On the phone**, open Diagnostics: the ⓘ in the header, then
   **Diagnostics** at the bottom of the privacy screen. It shows
   the last trace id, the provenance stamp, and the literal command to run.
2. **Tap Copy report.** It is a paste-able block: device, API base, Android
   build, and the last 120 events — uploads, failures, timeouts, completions —
   with no personal data in it.
3. **On the server**, every job writes its trace and logs one line:
   ```
   [barra] job=job-abc123 trace=260828-221455-4f8a59 exercise=muscle_up reps=2 score=78 rejections=0 errors=0
   ```
4. **Replay it:**
   ```bash
   barra explain --replay 260828-221455-4f8a59
   ```

The id in the app, in the server log, in the payload and on disk is the same
id. You never have to guess which run you are looking at.

## Provenance: which build produced this?

Every payload carries a stamp — code commit (with a `+dirty` suffix when the
tree was modified), Python, platform, and the pose model **hashed rather than
named**, because mediapipe ships new weights under the same filename.

> A score that moved because the build moved is not a score that moved because
> the athlete did.

Since this project's entire claim is self-referential — today's reps compared
against your own earlier ones — an unnoticed model swap would masquerade as
progress. The hash is what makes that detectable.

## Diffing two runs

Traces are JSON under `out/traces/`, one file per run, so:

```bash
barra explain clip.mp4 --show all > before.txt
# change something
barra explain clip.mp4 --show all > after.txt
diff before.txt after.txt
```

That is how you find what a change actually altered, rather than what you
believed it would alter. Two defects were found exactly this way — see below.

## What tracing has already caught

Worth recording, because it is the argument for the whole exercise.

- **A rejection that contradicted its own evidence.** A clip was turned away
  with "hands not fixed" printed directly above `wrist_travel = 0.27` against a
  threshold of `0.80`. The real cause was a visibility gate the message never
  mentioned. A trace that misreports its reason is worse than no trace: it
  sends you to read the wrong code.
- **Whole-clip statistics on clips that are not all exercise.** People walk to
  the bar, do a set, and walk away. Statistics over the whole video are then
  partly about the walking, which is the loud part — on one clip the approach
  put the wrists 2.99 torso-lengths apart while the reps never moved them past
  0.02. One level down it was worse: the amplitude that sets the turnaround
  threshold spanned the walking too, so the bar rose above every real rep.
  Three muscle-ups read as zero, and the rejections named the candidates the
  walking produced rather than the reps it had hidden.

Both are fixed. Both were invisible before there was a trace, because the
pipeline's output in each case was a perfectly calm "0 reps".

## What tracing did NOT do

It did not make every clip produce a number. Two clips in the sample corpus
still measure zero reps, and the trace says precisely why: one has no
turnaround clearing the noise at 38% wrist visibility; the other has a
candidate whose hands travel 1.16 torso-lengths.

That second threshold was checked rather than assumed. Accepted muscle-up reps
in the same corpus travel 0.14, 0.22 and 0.52, so the 0.80 limit sits well
clear of real reps and well below the rejected candidate. The rejection is
correct, and the threshold stays. Tuning it until a number appeared would have
invented reps nobody did — which is the failure this project exists to avoid.

**A visible zero with a reason is a result. A number with no yardstick is not.**

## In the app

`EventLog` is a bounded ring buffer (120 entries) written on every upload,
failure, lost connection, timeout, completion and delete. Levels are
INFO/WARN/ERROR. It survives navigation, it is capped so it cannot grow without
bound, and `report()` renders it with the device and server context needed to
act on it.

The trace id travels with the analysis into `SessionStore` and is stored with
the day, **keyed by job id** rather than as a parallel list — so deleting one
clip cannot silently shift the rest by one and hand you the wrong run. A day
recorded weeks ago can therefore still be replayed against the exact run that
produced its score, provided the trace file is still on the server. The id also
appears in small type under the session itself, so it can be read off without
opening Diagnostics at all.

## Adding tracing to new code

```python
from .trace import NullTrace, Trace

def my_stage(data, trace: Trace | None = None):
    tr = trace or NullTrace()
    tr.stage("my_stage")
    tr.step("measured", value=x, threshold=LIMIT)   # what you saw
    if x > LIMIT:
        tr.reject("the thing", "why, in words", value=x, threshold=LIMIT)
        return None
    tr.decision("accepted", "why", value=x)
    return result
```

Two rules:

- **`NullTrace` has the same interface and records nothing**, so no call site is
  ever guarded by `if trace is not None`. Tracing that is conditional at the
  call site gets skipped exactly where it is needed.
- **Record the threshold next to the value.** A value alone tells you what
  happened; the pair tells you whether it should have.

Numpy scalars are coerced explicitly on the way in — `np.float64` subclasses
`float`, so an `isinstance` check passes it straight through and writes
`np.float64(8.43)` into your JSON.
