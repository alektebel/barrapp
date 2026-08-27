# Tracking progress between sessions

## The problem with the deviation score

Stages 4-5 produce a full-skeleton deviation score with a leave-one-out null.
It is the right instrument for "is this rep different from my reference reps",
and it is the wrong instrument for "am I better than last month", for a reason
measured in [`FINDINGS.md`](FINDINGS.md): a few degrees of camera movement
displaces the normalised skeleton more than a deliberate technique error does.
Between sessions the camera always moves. Sometimes it moves to the other side
of the athlete.

So `barra progress` does not use it. It uses scalar metrics chosen for how much
of that fragility they avoid, and it labels each one with what it survives:

| Class | Survives | Example |
|---|---|---|
| `INVARIANT` | any camera, any distance, any side | concentric duration, transition time, rep count |
| `SCALED` | camera distance, not camera angle | range of motion, lockout height |
| `PLANAR` | only one camera side | left/right asymmetry, swing |

Timing is the workhorse. It costs nothing in comparability and, for a
muscle-up, the time spent crossing the plane of the bar is the part that fails
first.

## The yardstick

The same discipline as stage 5, moved onto scalars. A difference between two
session medians means nothing until you know how much the number moves from rep
to rep *inside* one session. That within-session spread, pooled across sessions,
is the null.

A change is called **supported** only when all of:

1. both sessions have at least 3 usable reps,
2. the change exceeds 2x the pooled within-session spread,
3. the metric is comparable between those two sessions.

Gate 3 has three parts, each of which caught something real on this project's
own footage:

- **viewpoint** - a length foreshortens off-axis, so a length from one bin is
  not the same quantity as a length from another.
- **camera side** - front and back are mirror images. Comparing a left shoulder
  against a right one is not a measurement.
- **scale drift** - the torso-length divisor is itself estimated from the pose.
  On the muscle-up footage the same athlete's arm:torso ratio came out 1.09 in
  one clip and 0.78 in another. The ruler changed, so no length measured with it
  is comparable. This gate is easy to forget and quietly invalidates everything
  downstream of it.

When a change is not supported, the tool says which gate stopped it.

## Confidence is not accuracy

The most expensive lesson in this repository.

Handed a small, distant, motion-blurred subject, mediapipe returned **0.9
keypoint confidence while tracking a man walking toward the camera with his
hands at his hips**. The wrist-referenced signal duly recorded a magnificent
muscle-up: shoulders 1.9 torso-lengths above the "bar". Every
confidence-weighted quality score waved it through, because the model was
confident, it was simply confident about the wrong thing.

Two geometric checks catch this, and neither asks the model how sure it is:

- **The anchor must stay put.** A bar does not move. Measured over real reps the
  wrists travel 0.04-0.43 torso-lengths across a rep, handheld camera included;
  over a subject walking around the rig, 1.1-4.8. An order of magnitude apart.
- **The athlete must be shaped like the athlete.** The shoulders cannot rise
  further above the hands than the arms are long. Checked against reach measured
  *in the same clip*, so numerator and denominator share a divisor and the test
  holds even when the divisor is wrong.

## Persistent memory

`out/` is scratch and is rebuilt every run. `profile/` is committed and
accumulates:

```
profile/subject.json     anatomy and calibration, with history
profile/sessions.jsonl   append-only, one record per video ever ingested
profile/reps.parquet     per-rep metrics for every rep ever measured
```

Records are keyed by a hash of the video's own bytes, so re-ingesting is
idempotent, renaming a file does not orphan its history, and re-encoding is
detected as a new observation rather than silently overwriting an old one.

Clips that produced **no** usable rep are recorded too, with the reason. That is
the more valuable half of the ledger: it is what tells you a session was wasted
and why, and a profile that only remembers successes cannot give that feedback.

```bash
barra remember    # fold this run into profile/
barra progress    # compare every session the profile holds
```

## What it cannot tell you

- It measures **distance and duration, not quality**. A rep that changed because
  you fixed something and a rep that changed because you broke something look
  identical. "Better" is only assigned where a metric has an agreed direction
  (a faster transition, less swing), and never inferred from the deviation score.
- It never says **why**.
- Rep counts are counts of *detected* reps. A rep filmed badly enough is not in
  the data, and the ledger records that separately rather than counting it as
  a rep you did not do.
