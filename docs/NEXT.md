# What to do next, and why the detection is where it is

Written September 2026, after the personality pass, the hold vocabulary and
the technique ledger landed. Three sections: what only you can do, how the
exercise detection should improve and in what order, and the honest view of
what this commit did not verify.

## 1. Things only you can do

**Build it.** The Compose toolchain cannot be fetched in the sandbox
(`maven.google.com` redirects to `dl.google.com`, which the network policy
blocks). The Kotlin in this commit was parsed by the real compiler, linted for
missing imports, and its Android-free parts were executed (`tools/run_logic_tests.sh`,
875 checks). It was not compiled against androidx. The first real build will
find whatever that tier cannot: a Compose signature that moved, a modifier on
the wrong scope. Run it and read the first error before reading anything else.

```bash
source scripts/env.sh && ./gradlew assembleDebug
```

**Run the technique scraper with a network that reaches wger and Wikipedia.**
The sandbox reached GitHub only, so `data/techniques/techniques.json` carries
one source (free-exercise-db, public domain) and 23 skills. The other two
sources are implemented and covered by parser tests on fixtures, not against
the live endpoints. The hanging knee raise, five of the six measured skills'
Wikipedia summaries, and every lever and planche entry are waiting on this:

```bash
python scripts/scrape_techniques.py                 # all three text sources
python scripts/scrape_techniques.py --transcripts   # plus CC YouTube captions, needs yt-dlp
python -m unittest tests.test_techniques            # then re-check the ledger
```

Then copy the compact form into the app, which `scripts/scrape_techniques.py`
does not do on its own because the asset is a product decision, not a build
artefact: the block at the end of the "Techniques" section of `docs/APP.md`
shows the shape.

**Film the four clips the hold vocabulary has never seen.** It was checked
against exactly one real hold (the inverted hang, which it now names and times
at 11 s) and one real non-hold (the jump-to-bar attempts, which it still
refuses). Every other entry - lever, handstand, plank, L-sit, support - is
tested on synthetic bodies only. Ten seconds each of a dead hang, a tuck front
lever, a wall handstand and a plank, side-on, whole body in frame, would tell
you which rules survive a pose estimator. Expect the handstand to be the
first casualty: BlazePose was not trained on inverted people and the sample
inversion had its torso flattened from roughly 30 degrees to 6.

**Keep the tripod mark.** Nothing in this commit changes the finding that
camera azimuth dominates the deviation signal. It is still the binding
constraint, and still the cheapest thing to fix.

## 2. How the exercise detection should improve, in order

The classifier is a hand-written decision tree over geometric features with
fixed thresholds. That was the right call with eight clips and no labels, and
it still is; the improvements below keep it explainable and make it wrong less
often, roughly in the order of evidence per hour of work.

**2.1 Classify the anchored window, not the clip.** `features()` measures
hand-height fractions and articulation over the whole clip, then finds the
best anchored window separately. A clip with a 30-second walk and a
10-second set is classified on features that are two-thirds walking. Compute
every hanging/support feature inside the maximal contiguous anchored stretch
(the window `_best_window` already finds, extended while the wrists stay
within the anchor band), and report the stretch in the trace. This is the
change most likely to move 0014 (walk, muscle-ups, walk) from "recognised,
zero reps" to "recognised, reps counted", and it costs no new data.

**2.2 Score hypotheses instead of falling through branches.** Every branch
returns a fixed confidence (0.78 for a dip whether the legs were 26% or 90%
below the hands), and the runner-up is hard-coded. Compute a margin for each
movement from its own gates - distance from each threshold, in threshold
units, through a soft step - rank them, and let "unknown" mean "two
hypotheses within a small margin of each other" as well as "no branch
matched". Same rules, same thresholds, honest confidences, and the runner-up
becomes the actual second-best rather than a guess. The trace already
records every gate's value and threshold, so this is arithmetic over data it
has.

**2.3 A labelled evaluation set, from the scraped clips.** `data/calisthenics`
now has 36 openly licensed clips across ten tricks, filtered by title. Run the
classifier over all of them, write the result beside the trick label in a CSV,
and watch the ones that disagree. That is the first confusion matrix this
project can have, and it is the yardstick for 2.1 and 2.2: neither should
land without a before/after on it. `tools/visual_assess.py` and
`barra/validate_faults.py` are the starting points.

**2.4 Temporal segmentation for mixed clips.** Split the clip at changes of
anchor (hands leave the bar, feet leave the floor) and classify each segment.
A clip of pull-ups then dips becomes two results, not one wrong one. The
segmenter's `anchor_travel` already sees the transitions.

**2.5 Grip and chin-up.** Pronated versus supinated grip is visible in the
image only through the forearm rotation, which COCO-17 keypoints do not
carry. Do not promise chin-ups from this pose backend; if the distinction
matters, it needs hand landmarks, which MediaPipe can produce and the schema
does not yet accept.

**2.6 A learned classifier, last.** Only once 2.3 exists and has more than a
few hundred labelled segments. Train it on the same geometric features the
rules use, so a wrong answer is still explainable in the trace; keep the
rules as the fallback that fails loudly. A model trained on 36 clips would
memorise the lighting.

## 3. What this commit did not verify

- The Compose UI is unbuilt (section 1). The processing animation was
  verified geometrically in a browser with the same formulae and screenshotted
  at four phases and four stages in both themes; the Kotlin port is a line-for-
  line transcription of that maths, and has not been seen on a device.
- Hold recognition on real footage: one true positive, one true negative.
  That is not a validation; it is a smoke test.
- The technique ledger's cues and faults are *mined* by sentence shape from
  instruction text. "Begin with a movement swinging your legs backward" is
  filed as a fault for the kipping muscle-up because it contains "swinging".
  The app labels every line as quoted, and the ledger keeps the source, but
  the mining is a heuristic and will misfile more as sources grow.
- The wger and Wikipedia fetchers ran only against fixtures.
- The launcher icon mipmaps were rendered with PIL from the same geometry as
  the adaptive vector; the two have not been compared on a launcher.
