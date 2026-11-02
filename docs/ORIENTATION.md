# Clips filmed sideways, upside down, or half out of frame

## Production miss-classes

### 2026-10-28 (pose-only inversion)

| Job | What it was | What the pipeline did |
|---|---|---|
| `f31bf9cfc335` | Dips, phone upside down | geometry said muscle-up, the classifier back lever, vision hanging leg raise; vision decided; six reps of a leg raise were scored 66 |
| `0329d314fe5a` | Pull-ups at night, only the legs in frame | 0 reps; "no stretch of this clip shows the athlete on the apparatus" — nothing the athlete could act on |

A phone upside down writes the same container rotation (`rotate 90`) as a correct
clip, so there is no metadata to correct: the picture itself is inverted.

### 2026-11-02 (IMU rotation + free-text vision)

| Job | What it was | What the pipeline did (commit `a606a6b`, pre-fix) |
|---|---|---|
| `93ebbf6e4894` | Front-lever pull progression, legs vertical (Eric Flag station) | geometry `bulgarian_split_squat` (sideways pose); locate free-text `pull-up`; fusion `vision-decides` → scored 3 kipping pull-ups. Phone sent `videoRotation: 180`, `upright: false`. |
| `cc61dc871b9d` | Inverted curls (biceps) | geometry `muscle_up` @ 0.98; locate free-text `leg raise (lying/hanging leg raise on dip station)`; fusion promoted the prose slug → unsupported, 0 reps. Phone sent `videoRotation: 270`. |
| `31e6fc884110` | L-sit / hanging leg raise on dip bars | geometry `unknown`; locate free-text `inverted hanging leg raise (dip bar)`; fusion `vision-decides` → freeform id, unsupported, 0 reps. `videoRotation: 270`. |
| `a9884573d367` | Dips (same station, same sideways phone) | geometry `bulgarian_split_squat`; vision `dips`; fusion `vision-decides` → scored 13 dips with `needsConfirmation`. Orientation was wrong; the name happened to be right. |

Root causes shared with the October clips, plus two new ones: the worker
ignored `deviceOrientation.videoRotation`, and locate's open-vocabulary
`detected_exercise` was used as a fusion vote. All four jobs above ran on
`a606a6b`. Fix deployed as `c1590bf` / image `worker-20261102-222453`
(2026-11-02 ~21:28Z); the four clips were requeued on that image.

## What now happens

### 1. IMU rotation before pose (`resolve_device_rotation`, `rotate_clip`)

When the job carries `deviceOrientation.videoRotation` in `{90,180,270}`, the
worker turns the clip **before** pose and vision (`server/process.py`
`measure_job`). For 90/270 it scores both turns on a few stills and keeps the
upright one: after a phone re-encode the gallery tag is often the *complement*
of what the pixels need (job `a038d832f870`, weighted dips → muscle_up: claimed
270 left the athlete upside down; 90 classified as dip). The payload records
`orientation: {rotatedBy, status: rotated, source: imu, evidence}` and a
Spanish `orientation_rotated` note. The stored trim is turned the same way so
replay matches the skeleton.

### 2. Pose-based 180° confirmation (`barra/orientation.py`)

Still available for clips with no IMU field:

1. **Cheap look.** `suspect_inverted`: nose more than half a torso below the
   hips in ≥ 70 % of readable frames. Horizontal bodies never trip it.
2. **Second look** only for suspects: turn 180°, re-pose, `decide` whether
   geometry + classifier agree only once turned.

### 3. Vision vote is the movement tree, not locate prose

- `locate_exercise` — trim window only.
- `name_movement` — walks `barra/movement_tree` and returns a skill id for
  fusion (`server/vision.py`).
- `skill_from_locate_label` — safety net; refuses prose with punctuation /
  long clauses.

### 4. Fusion refuses freeform names (`barra/fusion.py`)

A label that is not a measured movement, a skill id, or a known model-only
class (`deadlift`, `bench_press`, `barbell_squat`) is **no vote**. Locate
strings like `leg raise (lying/hanging…)` no longer invent exercise ids.

When geometry, model and vision all disagree **and** `pose_reliable=False`,
fusion abstains (`three-way-disagreement-abstain`).

### 5. Confirmation before scoring a disputed vision win

`needs_confirmation` flags `detectors_disagree` when status is
`vision-decides` and geometry named something else. `analyze_clip` then
returns `movement_unconfirmed` / `countStatus: unmeasured` with
`suggestedExercise`, instead of scoring the disputed name
(regression for `93ebbf6e4894`).

### 6. Catalog

- Skill `inverted_curl` (unsupported) and tree options `biceps_curl` /
  `pike_pull` under `hang_what`, so those movements can be *named* cleanly.
- Spanish capture notes: `orientation_rotated`, `orientation_suspect`,
  `framing_dark`, `framing_legs_only`, `framing_no_athlete`,
  `movement_unconfirmed`.

## Job create

`POST /v1/jobs` stores `deviceOrientation` (via `_to_ddb` so floats become
Decimal) and optional `recentMovements`. Without the IMU field the worker
cannot straighten the clip up front.

## Tests

- `tests/test_orientation.py` — pose inversion / framing / three-way abstain
- `tests/test_missclass_nov2.py` — IMU snap, freeform refusal, disagreement
  gate, locate-prose safety net
