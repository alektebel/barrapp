# Is the quality score measuring anything?

Not *is it right*. There is nothing to be right against. Movement quality has
no ground truth — two competent coaches disagree about the same rep — so a
labelled corpus teaches one person's aesthetic and calls it truth. That is
precisely the move that makes every "98% accurate" claim in this market
unfalsifiable.

The answerable question is **validity**: does the number respond to things it
should, and stay still for things it should not? That is testable with no
labels at all.

```bash
barra validate-quality              # run the checks on the clips you have
barra validate-quality --protocol   # what to film, and why
```

## The four checks, in the order that makes each one interpretable

**1. Ceiling** — a component that never varies cannot measure. Free: it is a
property of scores already computed.

**2. Reliability** — film one set from two phones. Same reps, so the same
score. **The disagreement between them IS the noise floor**, and every other
result is judged against it. Without this there is no scale, and a difference
smaller than repeat-measurement noise is not a difference. Same rule the
deviation scoring already follows: no number without its null.

**3. Degradation** — a set taken to failure **orders its own reps**. Rep 1 is
the best the athlete has; the last is the worst. Nobody labels that — the
structure of the set does. If quality does not fall as failure approaches, it
is not tracking quality. One such clip is worth more than a hundred labelled
reps.

**4. Sensitivity** — film a set at deliberate half range, and one deliberately
jerky. You created the fault, so you own the label. The drop has to clear the
noise floor from (2).

A check that cannot discriminate says **INCONCLUSIVE** and why. That is not the
harness failing — a set that was never hard cannot test whether the score
notices fatigue, and reporting FAIL there would be the harness overreaching.

## What it says about the score today

Run against the eight sample clips:

```
 x CEILING       FAIL
      Control sits at its ceiling in 86% of reps; range was measurable in
      no rep of VID-20260827-WA0020 (19 reps) - 40% of the weight vanished
      from those scores.

 - RELIABILITY   NOT RUN      no repeat-filmed set on record
 ? DEGRADATION   INCONCLUSIVE rep times did not slow (-6% across the set),
                              so this set was not near failure
 - SENSITIVITY   NOT RUN      no deliberately degraded set on record
```

Three things follow, and none of them need a single label:

- **`control` is saturated.** It is `clip01(tempo / 0.70)`, so any descent at
  least 0.70× the ascent scores 1.0 — which was 86% of reps. A 25%-weight
  component sitting at its ceiling contributes a constant.
- **`range` was unmeasurable for the whole push-up clip**, so 40% of the weight
  silently vanished and the score was renormalised without saying so. The
  headline 94 was built from two components, one of which was constant.
- **The scale is compressed.** All 22 scored reps land in 76–100.

A score living in the top quarter of its range cannot detect a change of any
size, labelled or not. Fixing that comes before collecting anything.

## Why not just label reps?

- **Whose ground truth?** Inter-rater reliability on movement quality is poor.
  You would learn one aesthetic and call it measurement.
- **Labels do not fix the camera.** [Finding 1](FINDINGS.md) is that a 10°
  camera move exceeds every technique error we induced. A model trained on
  perfect labels inherits that intact and becomes confidently wrong.
- **Volume.** Rep-level supervised learning wants thousands of labelled reps.
  This corpus has 22 scored ones.
- **It breaks the self-reference.** The whole design compares you against your
  own past. A population-trained quality model quietly reintroduces a norm.

**If you do want human judgement**, never ask for ratings. Ask for **pairwise
comparisons** — *which of these two reps is better?* People are far more
reliable at ordering than at scoring, and a few hundred comparisons recover a
latent scale that thousands of absolute ratings would not.

## Declaring what you filmed

`data/videos/validation.csv`:

```
video,role,pair,note
CLIP_A,normal,setA,first phone
CLIP_B,repeat,setA,second phone - same set
CLIP_C,failure,,taken to failure
CLIP_D,degraded:range,,deliberate half range
CLIP_E,degraded:tempo,,deliberately jerky
```

Two rows sharing a `pair` must be the **same set**, or the noise floor measures
your training instead of the camera.

## The conventions in the harness

Stated because they are conventions, not discoveries:

| | | |
|---|---|---|
| `FATIGUE_SLOWDOWN` | 0.10 | A set whose reps did not slow by 10% was probably not near failure. Borrowed from velocity-based training, where velocity loss across a set is the standard proxy for proximity to failure. |
| `MIN_REPS_FOR_TREND` | 8 | Below this a rank correlation says almost nothing. |
| `SATURATED_FRAC` | 0.80 | A component at one value in this share of reps is contributing a constant. |

## One thing to expect

Fixing the dynamic range will probably **lower** your scores and make the app
look worse. That is the correct direction. A score that reads 94 for everything
is flattering and useless.
