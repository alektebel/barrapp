# Drop your videos here

One file per **set**. Everything downstream keys off the set, because camera
position is fixed within a set and is the single largest source of spurious
deviation (see `docs/FINDINGS.md`).

## Naming

```
YYYY-MM-DD__<exercise>__set<NN>.<ext>
```

Examples:

```
data/videos/2026-08-27__squat__set01.mp4
data/videos/2026-08-27__squat__set02.mp4
data/videos/2026-09-03__squat__set01.mp4
```

Supported extensions: `.mp4 .mov .m4v .avi .mkv`

The date prefix becomes the `session_id`. That matters: two reps recorded the
same day are not independent evidence about a training block, and the
cross-session null distribution is built by holding out whole sessions.

If you cannot rename your files, copy `sessions.example.csv` to
`sessions.csv` in this directory and fill it in instead:

```csv
video,session_id,exercise,set_index
IMG_4471,2026-08-27,squat,1
IMG_4472,2026-08-27,squat,2
```

`video` is the filename without its extension. Two more columns are worth
filling in, because the estimates they override are the least reliable part of
the pipeline:

```csv
video,session_id,exercise,set_index,bin,view
VID-20260827-WA0010,2026-08-14,muscle_up,1,FRONTAL,posterior
```

- `exercise` &mdash; `squat`, `muscle_up`, `pull_up`, `dip`. **Not optional in
  practice**: a muscle-up is measured about the bar and a squat about the hips,
  and analysing one with the other's geometry produces numbers that look fine
  and mean nothing. An unknown name is an error, not a silent default.
- `bin` &mdash; `SAGITTAL`, `OBLIQUE`, `FRONTAL`. Overrides the automatic
  azimuth estimate, which is unreliable for movements that pitch the torso
  (a muscle-up does, badly) and says so when it fails to calibrate.
- `view` &mdash; `anterior` (filmed from the front), `posterior` (from behind),
  `left`, `right`. Front and back are mirror images, so left/right metrics are
  never compared across them.

## How to film

These are not style preferences. Each one is here because getting it wrong
makes the measurement worse in a way the tool can detect but cannot fix.

| Requirement | Why |
|---|---|
| **Tripod, and mark its position on the floor** | A 2 degree change in camera azimuth already moves the normalised skeleton more than a deliberate knee-valgus error does. This is the single most important line in this table. |
| **Same spot every session** | Progress tracking across sessions is only possible if the camera is in the same place. Tape an X on the floor for the tripod and another for the lifter. |
| **Camera at roughly hip height** | Keeps perspective distortion consistent between reps. |
| **Side-on, whole body in frame including feet** | Ankles anchor the leg model. A cropped foot destroys the rep. |
| **One person in shot** | The pose backend takes the largest detection as the subject. A spotter walking through the frame will be picked up. |
| **Even lighting, uncluttered background** | Keypoint confidence drives the joint weights; a dark or busy scene silently down-weights the joints you care about. |
| **60 fps if your phone offers it** | More frames per rep means finer phase resolution. 30 fps works. |
| **Do not move or re-frame mid-set** | The set is the unit of viewpoint estimation. |
| **Fill the frame with the athlete** | The single biggest cause of unusable footage so far. A distant subject gets confident, wrong keypoints — 0.9 confidence on a man walking around the rig. Closer is better than higher resolution. |
| **Keep the whole rep in frame, including the top** | A muscle-up clip that loses the athlete at lockout yields zero reps, not a partial one: everything a rep asserts is anchored to the turnaround. |
| **Trim to the working sets** | A 40-second clip that is mostly setup and walking is mostly noise to segment through. |

### Bar movements specifically

| Requirement | Why |
|---|---|
| **Hands must be visible on the bar** | The bar is the reference frame. If the wrists are lost, nothing downstream has an origin. |
| **Same side every session** | Front and back are mirror images. Alternating between them makes every symmetry metric incomparable. |
| **Film from far enough back to keep the lockout in frame** | ...but close enough that the athlete is large. This tension is real; err toward closer and tilt up. |

## How many

For a first run that can actually be validated:

- **At least 3 usable reps per session** before any between-session comparison
  is possible at all. This is the floor, not the target.
- **At least 8 clean reps** in one viewpoint bin, to build a template at all.
- **At least 12** clean reps total, so 30% can be held out for the false
  positive rate without dropping below 8 reference reps.
- **Clean reps from two or more different days**, or the cross-session null
  cannot be computed and no claim about progress between sessions is possible.
- **3 to 5 reps of each deliberate error** you want to test, filmed from the
  same marked camera position.
- A few clean reps filmed deliberately at the **edge of the bin** (about
  18 degrees off, if you are working sagittally) to see what viewpoint drift
  alone costs you.

## Errors to induce

Pick errors you can produce on purpose and repeatably, and name them yourself.
The tool never interprets the names. Suggestions, filmed as separate sets:

- `excess_forward_lean`
- `shallow_depth`
- `knee_travel`
- `knee_valgus` — note this is a frontal-plane error and is close to invisible
  from a sagittal camera; film a frontal set too if you want to test it
- `heel_lift`
- `lateral_shift`

Load them the same as your clean sets. An error performed at 40% of your
working weight is a different movement, not the same movement done wrong.

Nothing in this directory is committed to git except this README.
