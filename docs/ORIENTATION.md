# Clips filmed upside down, in the dark or half out of frame

Two production clips (2026-10-28) that were measured wrongly or not at all:

| Job | What it was | What the pipeline did |
|---|---|---|
| `f31bf9cfc335` | Dips, phone upside down | geometry said muscle-up, the classifier back lever, vision hanging leg raise; vision decided; six reps of a leg raise were scored 66 |
| `0329d314fe5a` | Pull-ups at night, only the legs in frame | 0 reps; "no stretch of this clip shows the athlete on the apparatus" - nothing the athlete could act on |

A phone upside down writes the same container rotation (`rotate 90`) as a correct
clip, so there is no metadata to correct: the picture itself is inverted.

## What now happens (`barra/orientation.py`, `server/process.py`)

1. **Cheap look, free.** `suspect_inverted` reads the keypoints already estimated:
   the nose more than half a torso below the hips in >= 70 % of readable frames.
   Horizontal bodies (levers, planche, human flag, push-ups) and anything with the
   head above the hips never trip it. Corpus: 6 of 264 cached clips.
2. **Second look, only for suspects.** The clip is turned 180 degrees (ffmpeg),
   posed again, and read by geometry and the learned classifier (`decide`):
   * turn when the two **agree on a movement only once turned** (the dips clip:
     dip + dip, against muscle-up / back lever as filmed);
   * or, when the classifier is unsure as filmed (names handstand / back lever at
     < 0.7), reads an ordinary movement >= 0.5 once turned (gain >= 0.1) **and the
     vision model names that same movement**;
   * otherwise the clip stays as filmed (`uncertain` / `ambiguous`). Pose alone
     cannot tell a handstand, an inverted hang or a back lever from a person filmed
     upside down; the code never turns on pose alone.
3. A turned clip is measured turned, the payload says so (`orientation`, a Spanish
   note in `notes`), and the worker stores the clip turned too so the replay
   matches (`trim_clip(..., rotate=180)`).

## Fusion (`barra/fusion.py`)

When geometry, the classifier and vision all name different movements **and the
pose is not trustworthy** (an inversion left unresolved, darkness, body out of
frame) the exercise is not claimed (`three-way-disagreement-abstain`, the
`movement_unconfirmed` blocker, `countStatus: unmeasured`). On a clean pose a
three-way split still lets vision decide: that is the measured policy (vision
right 21/25 when the other two split).

## Framing warnings (`framing_issues`)

Spanish, each one says what to do: `framing_dark` (mean luma < 30; the two night
clips measure 15, the corpus median is 104), `framing_legs_only`,
`framing_no_athlete`, `orientation_suspect`. On an unmeasured clip they replace the
generic "no stretch ... on the apparatus" blocker; on a measured one they are
`notes`.

## Measured (local, `models/` as in production)

* Real dips clip, as filmed + vision "Hanging Leg Raise": turned, **dip** by
  geometry + classifier, `orientation: rotated`, no wrong score. 0 reps (56 % of
  frames tracked in the dark: `framing_dark`).
* Pull-up corpus clip turned 180 on purpose, vision "pull-ups": turned back,
  3 reps, score 89 (original untouched: 3 reps, 90).
* Corpus clips the pose marks suspect (back lever, planches, handstand): none
  turned.
* Not detected by design: horizontal bodies (turning a push-up 180 degrees leaves
  it horizontal).
