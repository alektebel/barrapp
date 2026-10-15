"""Rep-to-rep variation: how far each rep sits from its own set.

The set's consistency (amplitude and tempo CV) says whether the athlete was
even; it does not say WHICH rep broke the pattern. The replay needs the rep,
so each one is compared with the median of its own set - the athlete's own
reference, no population norm - and marked when it sits past the configured
share. Nothing here feeds a score; it locates moments worth watching.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from .config import THRESHOLDS

# Fewer reps than this and a median is just one of the reps.
MIN_REPS_FOR_MEDIAN = 3


def _relative(values: Sequence[Optional[float]]) -> list[Optional[float]]:
    known = [float(v) for v in values if v is not None and np.isfinite(v)]
    if len(known) < MIN_REPS_FOR_MEDIAN:
        return [None] * len(values)
    median = float(np.median(known))
    if median <= 1e-9:
        return [None] * len(values)
    return [None if v is None or not np.isfinite(v) else round(float(v) / median - 1.0, 3)
            for v in values]


def rep_variation(amplitudes: Sequence[Optional[float]],
                  durations: Sequence[Optional[float]],
                  thresholds=THRESHOLDS) -> list[dict]:
    """One `{amplitude, tempo, outlier}` per rep, in rep order.

    `amplitude` and `tempo` are the rep's value over the set median, minus
    one (0.3 = 30 % more than the median rep); None when the set is too short
    to have a median or the rep's value is missing.
    """
    if len(amplitudes) != len(durations):
        raise ValueError("amplitudes and durations must describe the same reps")
    amp = _relative(amplitudes)
    tempo = _relative(durations)
    out = []
    for a, t in zip(amp, tempo):
        outlier = ((a is not None and abs(a) > thresholds.rep_amplitude_outlier)
                   or (t is not None and abs(t) > thresholds.rep_tempo_outlier))
        out.append({"amplitude": a, "tempo": t, "outlier": bool(outlier)})
    return out


def consistency_band(consistency: Optional[dict], thresholds=THRESHOLDS) -> Optional[str]:
    """"estable" / "irregular" from the set CVs, None when there are none."""
    if not consistency:
        return None
    cvs = [consistency.get(k) for k in ("amplitudeCV", "tempoCV")]
    cvs = [c for c in cvs if c is not None]
    if not cvs:
        return None
    return "estable" if max(cvs) <= thresholds.set_steady_cv else "irregular"


def spans_as_seconds(spans: Sequence[tuple[int, int]], fps: float) -> list[dict]:
    """Inclusive frame spans as ordered `{startS, endS}` dicts."""
    if fps <= 0:
        return []
    return [{"startS": round(a / fps, 2), "endS": round((b + 1) / fps, 2)}
            for a, b in sorted(spans) if b >= a]
