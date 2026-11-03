"""Detect the working-set window before classify / count / faults.

Stage 1 of the cascade: find WHEN the athlete is working. Classification and
rep counting must run inside this window so walking to the bar, hanging idle,
or putting on a belt cannot become a pull-up.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from . import schema as S
from .joint_periodicity import joint_periodicity
from .kinematics import _periodicity
from .movements import midpoint, pair_confidence, robust_torso

MIN_CONF = 0.3
# Oscillation amplitude (torso lengths) that counts as "working".
MIN_AMP = 0.12
# Autocorrelation strength that counts as periodic work.
MIN_PERIOD = 0.35
# Hysteresis: ~0.5 s of consecutive frames to enter/leave WORK.
HYST_S = 0.5
# Merge WORK islands closer than this.
MERGE_GAP_S = 3.0
# Pad back before first WORK so the first half-rep is not cut.
LEAD_S = 1.0


@dataclass
class WorkingSet:
    start: int
    end: int
    spans: list[tuple[int, int]] = field(default_factory=list)
    setup: list[tuple[int, int]] = field(default_factory=list)
    source: str = "whole-clip"
    confidence: float = 0.0
    evidence: dict = field(default_factory=dict)

    def as_dict(self, fps: float) -> dict:
        fps = float(fps) or 30.0
        return {
            "startS": round(self.start / fps, 3),
            "endS": round(self.end / fps, 3),
            "startFrame": int(self.start),
            "endFrame": int(self.end),
            "spansS": [[round(a / fps, 3), round(b / fps, 3)] for a, b in self.spans],
            "setupS": [[round(a / fps, 3), round(b / fps, 3)] for a, b in self.setup],
            "source": self.source,
            "confidence": round(float(self.confidence), 3),
            "evidence": self.evidence,
        }


def _anchored(kp: np.ndarray) -> np.ndarray:
    """Hands roughly fixed (same idea as classify.anchored_mask)."""
    lw = kp[:, S.KP_INDEX["left_wrist"], :2]
    rw = kp[:, S.KP_INDEX["right_wrist"], :2]
    lc = kp[:, S.KP_INDEX["left_wrist"], 2] >= MIN_CONF
    rc = kp[:, S.KP_INDEX["right_wrist"], 2] >= MIN_CONF
    torso = robust_torso(kp)
    out = np.zeros(len(kp), dtype=bool)
    # Per-frame travel vs a local median of wrist position.
    for side, conf in ((lw, lc), (rw, rc)):
        ok = conf.copy()
        if ok.sum() < 8:
            continue
        med = np.nanmedian(side[ok], axis=0)
        travel = np.linalg.norm(side - med, axis=1) / torso
        out |= ok & (travel < 0.55)
    return out


def _feet_planted(kp: np.ndarray) -> np.ndarray:
    """Ankles near the clip's floor level → standing / walking.

    A pure hang puts every ankle at the same height, so "near the floor
    percentile" would mark the whole clip planted. Require the hands NOT to
    be overhead (wrist above shoulder) before calling the feet planted.
    """
    la = kp[:, S.KP_INDEX["left_ankle"]]
    ra = kp[:, S.KP_INDEX["right_ankle"]]
    torso = robust_torso(kp)
    ys = []
    for a in (la, ra):
        ok = a[:, 2] >= MIN_CONF
        if ok.any():
            ys.append(a[ok, 1])
    if not ys:
        return np.zeros(len(kp), dtype=bool)
    floor = float(np.percentile(np.concatenate(ys), 95))
    planted = np.zeros(len(kp), dtype=bool)
    for a in (la, ra):
        ok = a[:, 2] >= MIN_CONF
        near = ok & (np.abs(a[:, 1] - floor) / torso < 0.12)
        planted |= near
    # Overhead hang: wrists above shoulders → feet are not load-bearing.
    wr = midpoint(kp, "left_wrist", "right_wrist")
    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_CONF
    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_CONF
    hanging = w_ok & s_ok & ((sh[:, 1] - wr[:, 1]) / torso > 0.05)
    planted &= ~hanging
    return planted


def _energy(kp: np.ndarray, fps: float) -> np.ndarray:
    """Per-frame work energy from the main bar / hip signals."""
    torso = robust_torso(kp)
    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    wr = midpoint(kp, "left_wrist", "right_wrist")
    kn = midpoint(kp, "left_knee", "right_knee")
    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_CONF
    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_CONF
    k_ok = pair_confidence(kp, "left_knee", "right_knee") >= MIN_CONF

    shoulder_above = np.where(w_ok & s_ok, (wr[:, 1] - sh[:, 1]) / torso, np.nan)
    knee_above = np.where(k_ok & h_ok, (hip[:, 1] - kn[:, 1]) / torso, np.nan)
    hip_above = np.where(w_ok & h_ok, (wr[:, 1] - hip[:, 1]) / torso, np.nan)

    n = len(kp)
    win = max(8, int(2.5 * fps))
    energy = np.zeros(n, dtype=float)
    for series in (shoulder_above, knee_above, hip_above):
        for i in range(n):
            a = max(0, i - win // 2)
            b = min(n, i + win // 2 + 1)
            chunk = series[a:b]
            finite = chunk[np.isfinite(chunk)]
            if finite.size < 8:
                continue
            amp = float(np.percentile(finite, 95) - np.percentile(finite, 5))
            peak, _ = _periodicity(chunk, fps)
            score = 0.0
            if np.isfinite(amp) and amp >= MIN_AMP:
                score = amp
            if np.isfinite(peak) and peak >= MIN_PERIOD:
                score = max(score, float(peak))
            energy[i] = max(energy[i], score)
    return energy


def _islands(mask: np.ndarray) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        out.append((i, j - 1))
        i = j
    return out


def _merge(spans: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    if not spans:
        return []
    spans = sorted(spans)
    out = [spans[0]]
    for a, b in spans[1:]:
        pa, pb = out[-1]
        if a - pb <= gap:
            out[-1] = (pa, max(pb, b))
        else:
            out.append((a, b))
    return out


def find_working_set(kp: np.ndarray, fps: float,
                     vision_window: tuple[float, float] | None = None,
                     ) -> WorkingSet:
    """Return the best working-set span for this clip."""
    fps = float(fps or 30.0) or 30.0
    n = len(kp)
    if n < 8:
        return WorkingSet(0, max(0, n - 1), source="whole-clip", confidence=0.0,
                          evidence={"reason": "too_short"})

    energy = _energy(kp, fps)
    anchored = _anchored(kp)
    planted = _feet_planted(kp)
    # Absolute MIN_AMP saturates on real clips (energy p95 often 1.7–4.0), so
    # nearly the whole clip looked like WORK. Gate relative to this clip's
    # own energy ceiling so idle hang / walk-in drop out. 0.5×p95 was too
    # harsh (71b4 kept only the walk-in and named a split_squat); 0.25× keeps
    # the real set without swallowing the whole clip.
    finite_e = energy[np.isfinite(energy)]
    energy_p95 = float(np.percentile(finite_e, 95)) if finite_e.size else 0.0
    amp_gate = max(MIN_AMP, 0.25 * energy_p95) if energy_p95 > 0 else MIN_AMP
    # Work: enough energy, preferably hands fixed, and not just standing still.
    work_raw = (energy >= amp_gate) & anchored & ~planted
    # Also accept high energy even if anchorage is noisy (oblique dips).
    work_raw |= (energy >= max(amp_gate * 1.25, MIN_AMP * 1.5, 0.25)) & ~planted

    hyst = max(2, int(HYST_S * fps))
    work = work_raw.copy()
    # Fill short holes and drop short blips.
    for a, b in _islands(work_raw):
        if (b - a + 1) < hyst:
            work[a:b + 1] = False
    for a, b in _islands(~work):
        if (b - a + 1) < hyst and a > 0 and b < n - 1 and work[a - 1] and work[b + 1]:
            work[a:b + 1] = True

    spans = _merge(_islands(work), gap=max(2, int(MERGE_GAP_S * fps)))
    setup = _islands(anchored & ~work)

    evidence: dict = {
        "energyP95": energy_p95,
        "ampGate": float(amp_gate),
        "anchoredFrac": float(anchored.mean()),
        "plantedFrac": float(planted.mean()),
        "nSpans": len(spans),
    }
    try:
        periods = joint_periodicity(kp, fps)
        evidence["drivers"] = [
            p.name for p in periods
            if np.isfinite(p.strength) and p.strength >= 0.30
        ][:4]
    except Exception:  # noqa: BLE001
        pass

    if not spans:
        return WorkingSet(
            0, n - 1, spans=[], setup=setup, source="whole-clip",
            confidence=0.15, evidence={**evidence, "reason": "no_work_span"},
        )

    # Keep every span with substantial energy (not only the single peak) so a
    # mid-clip rest does not silently drop a later set (8493 lost 41–59 s).
    best = max(spans, key=lambda ab: float(energy[ab[0]:ab[1] + 1].sum()))
    best_e = float(energy[best[0]:best[1] + 1].sum())
    keep = [ab for ab in spans
            if float(energy[ab[0]:ab[1] + 1].sum()) >= 0.25 * best_e]
    if not keep:
        keep = [best]
    evidence["keptSpans"] = len(keep)
    # Pad back at most LEAD_S, but stop at idle/setup (no energy / planted).
    lead = max(1, int(LEAD_S * fps))
    first = min(keep, key=lambda ab: ab[0])
    start = first[0]
    for i in range(1, lead + 1):
        idx = first[0] - i
        if idx < 0 or planted[idx] or energy[idx] < amp_gate * 0.5:
            break
        start = idx
    end = max(ab[1] for ab in keep)

    source = "geometry"
    confidence = 0.55 + 0.35 * min(1.0, float(energy[best[0]:best[1] + 1].mean()) / 0.5)
    if vision_window is not None:
        vs, ve = vision_window
        vf0 = int(max(0, vs * fps))
        vf1 = int(min(n - 1, ve * fps))
        if vf1 > vf0:
            inter0 = max(start, vf0)
            inter1 = min(end, vf1)
            union0 = min(start, vf0)
            union1 = max(end, vf1)
            inter = max(0, inter1 - inter0 + 1)
            union = max(1, union1 - union0 + 1)
            iou = inter / union
            evidence["visionIoU"] = round(iou, 3)
            if iou >= 0.5:
                pad = int(0.5 * fps)
                start = max(0, inter0 - pad)
                end = min(n - 1, inter1 + pad)
                source = "geometry+vision"
                confidence = min(0.95, confidence + 0.15)
            else:
                evidence["visionDisagree"] = True
                confidence = max(0.25, confidence - 0.15)

    return WorkingSet(
        start=int(start), end=int(end), spans=spans, setup=setup,
        source=source, confidence=float(confidence), evidence=evidence,
    )
