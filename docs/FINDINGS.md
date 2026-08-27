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
