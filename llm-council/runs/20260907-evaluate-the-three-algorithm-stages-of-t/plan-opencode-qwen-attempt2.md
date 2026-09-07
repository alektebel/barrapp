Now I have a thorough understanding of the codebase. Let me compile the findings report.



The findings report has been written to `docs/ALGORITHM-EVALUATION.md`.

**Summary of what's in the report:**

15 findings across the three stages:

**Stage 1 — Rep Detection (3 findings):**
- F1.1 S1: Camera rotation kills rep detection — the tracking signal superimposes rotation noise on the movement signal, causing zero-count clips (clip 0011 pattern). Fix: rolling-window detrend before `find_peaks`.
- F1.2 S2: Rescue pass tested only on sine waves — real pose noise (occlusion bursts, jitter, drift) is untested. Fix: signal-level noise generator.
- F1.3 S2: `MAX_BAR_TRAVEL=0.80` and `ANCHOR_FIXED=0.80` are duplicated with no consistency test.

**Stage 2 — Movement Classification (5 findings):**
- F2.1 S1: One-exercise-per-clip with no per-rep classification — mixed clips produce wrong movement profiles downstream.
- F2.2 S2: Squat has zero dedicated fault taxonomy — shares the generic 5-fault bar set instead of detecting knee valgus, butt wink, heel raise, gaze.
- F2.3 S2: Push-up fault coverage is empty — sagging hips, head position not measured.
- F2.4 S2: Dip bounce and scapula not measured.
- F2.5 S3: Confidence values are uncalibrated heuristics with no statistical meaning.

**Stage 3 — Fault/Error Classification (4 findings):**
- F3.1 S1: `faults.py` parses English strings with regex — a wording change silently kills fault detection. Android duplicates the same regex.
- F3.2 S1: ~20 magic constants duplicated across 6 Python files + Cues.kt with no consistency test.
- F3.3 S1: PLANAR metrics (knee valgus, torso lean) applied without view-gating — azimuth > technique error effect.
- F3.4 S3: Fault validation harness has no synthetic fallback — new fault detectors cannot be validated until labelled corpus grows.

The report includes a prioritised 3-phase fix plan, self-critique on 4 specific weaknesses of the plan, rollback strategy, edge cases, and open questions.