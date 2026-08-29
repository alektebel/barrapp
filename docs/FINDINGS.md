# Findings

## 1. Camera azimuth dominates the deviation signal

Run it yourself: `python scripts/viewpoint_sensitivity.py`

The experiment uses the synthetic subject, so the numbers are a property of
projecting a 3D body onto a 2D image and of the chosen error magnitudes — not
of any real lifter and not of any pose estimator. The projection geometry,
though, is not in doubt, so the conclusion transfers.

Deviation of one clean rep from another, in torso-lengths:

| Condition | Deviation | vs noise floor |
|---|---|---|
| Same technique, same 10° viewpoint (**noise floor**) | 0.0255 | 1.0× |
| Same technique, camera moved **+2°** | 0.0327 | 1.3× |
| Same technique, camera moved **+4°** | 0.0436 | 1.7× |
| Same technique, camera moved **+6°** | 0.0565 | 2.2× |
| Same technique, camera moved **+10°** | 0.0903 | 3.5× |
| Same technique, camera moved **+15°** | 0.1299 | 5.1× |

Deliberate technique errors, camera held fixed:

| Induced error | Deviation | vs noise floor |
|---|---|---|
| `excess_forward_lean` | 0.0802 | 3.2× |
| `shallow_depth` | 0.0607 | 2.4× |
| `knee_travel` | 0.0434 | 1.7× |
| `knee_valgus` | 0.0318 | 1.2× |
| `lateral_shift` | 0.0317 | 1.2× |

**A 10° camera move produces a larger deviation than every one of the five
induced errors.** A 10° move sits comfortably inside the spec's 20°-wide
`SAGITTAL` bin. Even a 2° move exceeds the weakest error signal.

### What follows

1. **The bin widths in the spec are too coarse for this metric.** Being in the
   same bin does not make two reps comparable. `SAGITTAL` spans 0–20°, and the
   within-bin viewpoint variation it permits swamps technique.
2. **Camera repeatability is the binding constraint**, not pose accuracy, not
   the alignment algorithm, not the template. Mark the tripod position on the
   floor. That single act buys more than any modelling change available here.
3. **The reference set inherits this trap.** Two failure modes, both observed
   on the synthetic run:
   - Reference reps all at one azimuth → tight null → **92% false positive
     rate** on held-out clean reps filmed a few degrees away.
   - Reference reps spanning 8–18° → null wide enough to absorb the viewpoint
     variation → **25% detection rate**; four of five induced errors fall
     inside it.

   Neither passes the section 8 verdict rule. Widening the reference set to
   cover viewpoint variation does not solve the problem, it moves it.
4. **One camera cannot assess all errors.** `knee_valgus` and `lateral_shift`
   are frontal-plane motions and score at 1.2× the noise floor from a sagittal
   camera — essentially invisible. This is geometry, not a tuning problem.

### The honest summary

On synthetic data, where the ground truth is exact and the only noise is what
we injected, the method as specified does not clear its own verdict bar. The
cause is identified and it is not subtle: uncontrolled camera azimuth.

That is a falsification of the *protocol*, not necessarily of the *idea*. The
testable prediction is that with the camera locked to a marked position, the
within-bin viewpoint term shrinks toward zero, the null tightens to the
rep-to-rep noise floor, and `excess_forward_lean` and `shallow_depth` become
separable while the frontal-plane errors remain invisible from the side.

**That prediction has not been tested on real footage.** Testing it is what
`data/videos/` is for.

## 2. Cross-session tracking

The cross-session null holds out a whole session and rebuilds the template from
the other days. On synthetic data the inflation is ~1.0×, because the simulated
subject has no session-to-session drift — the model has no such term. That
number is therefore a check that the machinery works, and says nothing about
real training.

On real footage the inflation ratio is the number that answers "can we track
progress between sessions":

- **Ratio near 1.0** — sessions are interchangeable, and a change larger than
  the cross-session p95 is real.
- **Ratio well above 1.0** — the tool cannot tell a technique change from
  yesterday's camera placement, and any between-session claim is unfounded
  until camera repeatability improves.

The report computes and states this. It does not assume an answer.

## 3. What this tool still cannot tell you

Even with a green validation run:

- It measures **distance from your reference shape, with no direction**. A rep
  that deviates because you fixed something scores exactly like a rep that
  deviates because you broke something. "Improvement" is not a quantity this
  tool computes.
- It never says **why** a rep deviated. A per-joint deviation vector localises
  a difference; it does not explain it.
- It is **self-referential by construction**. If your reference reps embed a
  technique fault, the fault becomes the standard and its absence gets flagged.

## 4. One occluded limb blinds a paired landmark, and does it silently

The most damaging class of bug in this project is not a wrong number. It is a
**confident answer produced from a measurement nobody took**, and pose
estimation manufactures those.

Landmarks come in left/right pairs, and the obvious way to use a pair is the
midpoint of the two with the minimum of their confidences. That is wrong in a
specific and common case: **side-on**, which is the angle most of these
movements are supposed to be filmed from. The far arm is behind the near one,
so the estimator reports the far wrist at 0.06 confidence and the near one at
0.42. Taking the minimum declares the hands unseen for the entire clip.

Measured across the eight sample clips, the pair-visibility distribution is
bimodal and the split is geometric rather than accidental:

| camera | both sides seen | clips |
|---|---|---|
| square to the athlete | 0.68 – 1.00 | 4 |
| side-on | 0.00 – 0.49 | 4 |

Nothing lands in between. A camera is either roughly square or roughly
side-on, and the far limb is either visible or it is not.

### Why the failure was invisible

The blindness itself is recoverable — the athlete just gets told the clip is
unmeasurable. What made it dangerous is what happened downstream. With the
wrists unseen, every arm-based feature evaluated to NaN, and the classifier
asked `not articulated`, which a NaN satisfies. **A branch that should have
required evidence that the arms stayed still was satisfied by the absence of
any evidence about the arms at all** — and a muscle-up filmed side-on was
reported as a squat, with a confidence of 0.78.

Three rules came out of this, and all three are now enforced by tests:

1. **Use the visible side.** In a sagittal view both hands are on the same bar
   within a few pixels, so the near one is not a compromise — it is the better
   estimate. The midpoint is used only when the pair is genuinely seen together.
2. **Choose once per clip, never per frame.** Switching mid-clip moves the
   reference point by half the pair's separation, and every switch reads
   downstream as motion. This alone had rejected a real muscle-up rep on 0.812
   torso-lengths of hand travel against a limit of 0.80 — thrown away by a
   tenth of a percent, on movement that never happened.
3. **Never let a missing measurement satisfy a condition.** "Measured and
   false" and "never measured" are different facts and need different code
   paths. Collapsing them into one boolean is what produced the squat.

### The general lesson

Keypoint confidence is per-landmark, but the *decisions* are about
relationships between landmarks. A relationship is only as observable as its
worst-observed end, and code that reduces a pair to one number throws away
exactly the information needed to know whether the reduction was safe.

## 5. Absence of movement is not a small amount of movement

A 23-second inverted hold was classified as a pull-up with two reps, invented
out of drift. The hold satisfies every condition a bar movement has: the hands
are fixed (0.02 torso-lengths of travel — steadier than any real set), the
body hangs below them, and the shoulders drift just enough to look articulated.

The obvious defence — a minimum range of motion — does not work. The hold and
a deliberately shallow pull-up both sweep about 0.65 torso-lengths, so no
threshold on total range separates them without rejecting real partial reps.

What separates them is **time spent parked**, not distance travelled. A hold
stays within a fifth of a torso-length of one position for most of the clip; a
set keeps leaving that band:

| clip | parked fraction |
|---|---|
| inverted hold | 0.62 |
| jump-to-bar attempts | 0.33 |
| hanging knee raise | 0.49 |
| shallow pull-up (synthetic) | 0.37 |
| muscle-up sets | 0.04 – 0.16 |

The threshold sits at 0.55, deliberately close to the hold rather than in the
middle of the gap. The costs are not symmetric: a set wrongly called a hold
reports "not measurable", while a hold wrongly accepted invents repetitions
that then enter the athlete's history as data.
