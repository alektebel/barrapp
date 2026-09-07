The evaluation is complete. I've written the full findings report and prioritized improvement plan to `docs/EVALUATION_FINDINGS.md`.

**Summary of what was produced:**

**Findings catalog** — 7 concrete weaknesses, severity-ranked:

| ID | Severity | Finding |
|----|----------|---------|
| 1.1 | S1 | Rescue pass is binary fallback — never runs when standard finds 1-2 reps, causing undercounting |
| 1.2 | S1 | Amplitude inflation from non-rep motion in `active_mask` raises prominence gate above turnarounds |
| 1.3 | S2 | Camera rotation through a set corrupts `_pair()` fallback, producing zero reps |
| 1.4 | S2 | Interpolated peak = instant rep rejection; brief pose loss at turnaround kills otherwise valid reps |
| 2.1 | S1 | One-movement-per-clip means mixed clips are entirely unmeasurable |
| 2.2 | S2 | Confidence scores (0.70-0.98) are uncalibrated heuristics, not probabilities |
| 3.1 | S1 | Bar faults (lockout, hang, stall) detected via regex on prose strings — fragile text contract |
| 3.2 | S1 | Most `tecnicas-errores-comunes.md` errors (squat valgus/heel raise, push-up sagging/elbow flare, dip bounce) are never measured |
| 3.3 | S2 | PLANAR metrics (swing, etc.) computed identically regardless of viewpoint — meaningless from frontal view |
| 3.4 | S2 | Thresholds duplicated in 3 files (`faults.py`, `faults_taxonomy.py`, `Cues.kt`) with no import link |
| 3.5 | S2 | "Control" fault has two overlapping definitions (phone penalty vs tempo ratio) that may disagree |
| 3.6 | S3 | No dedicated push-up fault classifier — maps to generic `muscle_up()` |
| 3.7 | S3 | No bounce detection for dip |

**6 prioritized improvement phases** (P1-P6), each with:
- File locations and line references
- Step-by-step implementation plan
- Validation strategy (synthetic invariant tests, deliberate-fault clips, null-distribution checks)
- Acceptance criteria
- At least one "Self-critique" bullet calling out concrete weaknesses in the proposed fix

**Testing strategy** covering invariant tests, deliberate-fault tests, null-distribution tests, real-footage validation, and regression tests.

**Rollback plan** — every change is revertible without model retraining since nothing is learned.