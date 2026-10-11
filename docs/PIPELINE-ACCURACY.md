# How accurate is the pipeline?

Measured 2026-09-10 on `data/calisthenics/` (movement) and re-measured
2026-09-13 after the fault-layer changes below. Reproduce with:

```bash
python scripts/classify_eval.py                    # movement classification
python scripts/fault_eval.py --min-reps 2          # technique faults (ships today)
python scripts/fault_eval.py                       # any-rep baseline (labelling parity)
```

Reports land in `out/classify-eval/report.json` and `out/fault-eval/report.json`.

---

## 1. Naming the movement

252 clips, 17 classes, scored out of fold. Folds are assigned by clip, so no
augmented view of a test clip is ever trained on.

| detector | accuracy | macro-recall | abstains |
| --- | --- | --- | --- |
| vision read alone | 0.890 | 0.891 | 0% |
| **fusion + vision (ships today)** | **0.817** | **0.812** | 0% |
| fusion, geometry + learned (pre-2026-09-13) | 0.556 | 0.547 | 1% |
| learned model | 0.548 | 0.542 | 0% |
| geometric rules, all classes | 0.246 | 0.207 | 21% |
| geometric rules, classes they implement | 0.346 | 0.319 | 20% |

Production auto-detect now passes `locate_exercise`'s `detected_exercise` into
`fuse_detection` as the vision vote. That call was already paid for trimming;
reusing the name costs no extra network round-trip. Athlete-declared movements
are unchanged — fusion only runs when the exercise is `auto`.

Accuracy and macro-recall track each other, so no detector's score is propped
up by the large classes. The learned model over six seeds is 0.556 ± 0.013;
single-seed figures in the report will vary by about that much.

### Per-class recall, fusion + vision

| movement | recall | | movement | recall |
| --- | --- | --- | --- | --- |
| deadlift | 14/14 · 1.00 | | back_lever | 10/12 · 0.83 |
| planche | 14/14 · 1.00 | | pull_up | 15/20 · 0.75 |
| push_up | 15/15 · 1.00 | | bulgarian_split_squat | 13/18 · 0.72 |
| dip | 24/26 · 0.92 | | handstand | 7/10 · 0.70 |
| bench_press | 11/12 · 0.92 | | barbell_squat | 8/12 · 0.67 |
| front_lever | 10/11 · 0.91 | | split_squat | 11/20 · 0.55 |
| knee_raise | 17/19 · 0.90 | | squat | 4/10 · 0.40 |
| human_flag, muscle_up, pistol_squat | 0.85 | | | |

The two worst classes are the two that are genuinely entangled.
`squat` / `barbell_squat` differ only by a barbell, which 2D keypoints cannot
see. `split_squat` / `bulgarian_split_squat` differ by whether the rear foot is
elevated — and the corpus labels themselves get that wrong: eight clips filed
as `split_squat` are described by their own caption as "rear foot elevated on a
bench".

### What limits this number

About 9% of the corpus is filed under the wrong movement, because the label is
the search query a scraper used. On clips where the vision read disagrees with
the directory, the out-of-fold pose model — which never saw the vision label —
sides with vision 47% of the time and with the directory 29%. Correcting only
the eight clips where two independent detectors agree against the directory
moves the vision read from 0.907 to 0.951 on the earlier corpus.

`scripts/label_disputes.py` writes a review sheet of every disputed clip with
the evidence for each; `classify_eval.py` reads a human `verdict` column as
truth. Nothing auto-corrects — a label proposed and accepted by the detector
being scored is the model marking its own homework.

---

## 2. Naming the technique fault

109 clips fault-labelled against the rule table's own vocabulary, 55 rules
across 10 movements, 273 judged clip-rule pairs. This is the first measurement
the fault layer has ever had.

### Before / after (2026-09-13)

| configuration | precision | recall | accuracy | F1 | fire rate |
| --- | --- | --- | --- | --- | --- |
| 2026-09-10 baseline (any rep, shared lockout) | **0.146** | **0.595** | 0.473 | 0.234 | 55.3% |
| threshold splits only (pull-up lockout, hold arms) | 0.154 | 0.541 | 0.535 | 0.240 | 47.6% |
| **ships today: splits + min-2-rep consensus** | **0.190** | **0.514** | **0.637** | **0.277** | **36.6%** |

What changed in code:

1. **`fault_min_reps = 2`** — clip-level `failures` / `primaryFault` /
   recommendations require the same error on at least two judged reps (or
   every rep on a one-rep / hold set). Per-rep assessments stay full detail.
2. **`pull_up_lockout_pct = -27.6`** — pull-ups no longer share the muscle-up
   support bar (`lockout_min * 100 = 85`), which always fired.
3. **Hold-specific arm bars** — `front_lever_arms_straight_frac = 0.25`,
   `planche_arms_straight_frac = 0.35` so those rules sit inside the measured
   range instead of always firing.
4. **`primaryFault`** — payload field ranked by normalised exceedance among
   consensus faults, so coaching can show one cue instead of the wall of alarms.

Outside-range dead thresholds dropped from 5 → 3. Remaining always-fire /
never-fire cases (`planche.piked_body`, `planche.bent_knees`,
`push_up.hip_sag`) need labelled positives before further retuning — blind
sweeps on clean footage trade recall for agreement and can make pooled
precision worse.

| metric (ships today) | value | |
| --- | --- | --- |
| **recall** — real faults caught | **0.514** | 19/37 |
| **precision** — of what fired | **0.190** | 19/100 |
| accuracy — agreement either way | 0.637 | |
| base rate — faults actually present | 13.6% | 37/273 |
| how often the rules fired | 36.6% | 100/273 |

**Still mostly false alarms, but less so:** precision 0.146 → 0.190, fire rate
cut by a third, recall down modestly. The layer is better for a coaching app
that should not cry wolf on every demo clip; it is not yet a reliable fault
detector.

### Structural defects behind that number

Needs no labels — it is a property of the geometry and the footage, measured
over 131 clips (2026-09-10; threshold Outside-range count updated 2026-09-13).

| | count |
| --- | --- |
| rules that could not be evaluated on a single clip | 13/55 |
| rules firing on ≥50% of the clips they can judge | 25/55 |
| rules whose threshold sits outside the range their primitive ever measures | 3/55 |

Eleven of the thirteen dead rules share one cause: "unsuitable view, camera
oblique". The view estimator bins 68% of the corpus as `OBLIQUE` against a
`SAGITTAL` gate of 0–20°, while clips whose caption explicitly says "side view"
measure a median azimuth of 32°. That is a lead on 13 clips of evidence, not a
verdict, and the gate has not been moved.

The remaining rules with no decision in them after the 2026-09-13 splits:

| rule | test | measured range | result |
| --- | --- | --- | --- |
| `planche.piked_body` | < 150 | 68.8 .. 135.8 | always fires |
| `planche.bent_knees` | < 0.6 | 0.00 .. 0.29 | always fires |
| `push_up.hip_sag` | > 0.12 | 0.035 .. 0.111 | never fires |

Fixed by the splits (no longer outside-range):
`pull_up.incomplete_lockout`, `front_lever.bent_arms`, and the planche arm bar
now sit inside their measured ranges. Blind retunes of `planche.piked_body` /
`bent_knees` on this clean corpus cut recall harder than they helped precision,
so they were left alone pending real fault footage.

### The honest limit on tuning

Twenty of the 32 measurable rules have never seen a labelled instance of the
fault they exist to catch, because this corpus is people doing it right. Their
false-alarm rate is known; their recall is **unknown, not good**. The pooled
0.595 is carried by the twelve rules that had positives.

No amount of tuning on clean footage can establish recall. On an all-clean
sample the threshold that "agrees" best is whichever one never fires — which is
the rule being deleted by arithmetic, and it would score 100%. `fault_eval.py`
refuses proposals that catch zero labelled instances for exactly this reason.

---

## 3. Would reporting ONE fault be better?

Yes, and the data says how much. Ranked by how far past threshold a fired rule
sits, in units of that primitive's own spread:

| strategy | top-1 correct | |
| --- | --- | --- |
| fire everything (today) | 0.146 precision | 22/151 |
| random pick among fired rules | 0.273 | 6/22 |
| **ranked by normalised exceedance** | **0.318** | 7/22 |
| oracle — best of what fired | **0.682** | 15/22 |

Two readings, and the second matters more.

**Reporting one fault roughly doubles precision for free** — 0.146 to 0.318,
with no change to detection at all. An average of 2.0 rules fire per clip, so
the wall of alarms is not even large; it is just mostly wrong.

**But the ranking is doing almost nothing.** 0.318 against a random baseline of
0.273 is barely a signal, while the oracle sits at 0.682. The correct fault is
usually *among* the ones that fired — the pipeline simply cannot tell which.
That is expected: ranking by "how far past threshold" is meaningless when the
threshold itself is arbitrary, and five of them have no decision in them.

So the gain is not in picking one. It is in having something that can rank, and
distance-from-an-uncalibrated-threshold is not it.

There is also a floor under all of this: **on 14 of the 36 clips that carry a
real fault, the rules fired on nothing at all.** Selection strategy cannot help
there; that is 39% of faulted clips where the geometry has nothing to say.

---

## 4. Where this leaves the architecture

**Movement naming now uses vision when auto-detecting.** 0.817 fused vs 0.556
without it. Geometry still measures; vision joins the vote via the locate pass.

**Fault selection is still the better remaining use of multimodal models.**
Geometry's failure is judgement: it can compute `lockout_pct` precisely and
cannot tell whether that is the thing worth saying. `primaryFault` is a first
step (one cue, consensus-gated). A vision ranker (`scripts/rank_faults.py`)
exists but needs human fault labels before its accuracy can be claimed — every
fault number above still uses the vision read as ground truth, so scoring a
vision detector against it would be circular.

---

## 5. What would move these numbers

Ranked by value against cost.

1. **Collect footage of faults / human labels.** Twenty rules cannot have their
   recall measured at all until clips exist where the fault is present. This
   blocks honest threshold tuning and any claim about a vision fault ranker.
2. **Adjudicate the disputed movement labels.** ~9% of the corpus is misfiled;
   the review sheet and the override path already exist. Worth roughly four
   points at the top of the stack and it improves training targets.
3. **Check the view gate.** Eleven dead rules share one cause; the `SAGITTAL`
   0–20° bin looks too tight against footage described as side-on. Needs more
   viewpoint ground truth than 13 clips before the threshold moves.
4. **Retune the three remaining outside-range rules** once positives exist —
   not before. Blind sweeps on clean demos cut recall.
5. **More clips per class.** The pose path is corpus-bound: Adam, weight decay,
   width, ensembling, augmentation and per-segment temporal features have all
   been swept, and the best honest configuration is 0.556 without vision.
6. **Accept that some pairs are undecidable from 2D pose.** `barbell_squat` vs
   `squat` differs by an implement the keypoints cannot see. That part of the
   gap needs an object detector, not a better classifier.
