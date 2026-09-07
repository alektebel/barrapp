"""One evidence record per rep or hold: what was measured, and what was not.

The fault layer used to read a plain ``dict`` of numbers, and a key that was
missing from it was indistinguishable from a key whose value said the athlete
was fine. Two of the three defaults in the taxonomy were literally
``_f(values.get("arms_straight_frac"), 1.0)`` - absent means perfectly straight
arms - so "bent arms" could not fire on a rep, ever, because nothing on the rep
path produced that key. That breaks the rule the rest of the pipeline keeps: a
missing measurement never satisfies a condition.

So the primitives live here instead, each carrying its own state:

    measured      the number is real and the predicate may read it
    unmeasured    absent, NaN, or the geometry could not produce it
    view-blocked  the number exists but the camera cannot support it

and its own robustness class, the same three the reps already ship with:

    INVARIANT   timing and ratios - unchanged by where the camera stood
    SCALED      lengths in torso-lengths - need scale, not a viewpoint
    PLANAR      only meaningful from one plane (knee valgus is a frontal
                quantity, torso lean a sagittal one), so they are gated on
                the view being knowable at all

The gate matters more than it sounds. docs/FINDINGS.md measured a 10-degree
azimuth change outweighing a deliberately induced error, which means a PLANAR
fault fired from an unknown viewpoint is not a weak signal - it is a coin
flip wearing a number. Blocked is the honest answer.

Nothing here decides whether a rep was good. It decides what a predicate in
faults_taxonomy.py is allowed to look at.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import schema as S
from .movements import midpoint, pair_confidence, robust_torso

# --- robustness classes ------------------------------------------------------
INVARIANT = "INVARIANT"
SCALED = "SCALED"
PLANAR = "PLANAR"

# --- knowability states ------------------------------------------------------
MEASURED = "measured"
UNMEASURED = "unmeasured"
VIEW_BLOCKED = "view-blocked"

MIN_CONF = 0.5


@dataclass(frozen=True)
class Measure:
    """One primitive, with the reason it is or is not usable."""
    name: str
    value: float | None
    state: str
    robustness: str = SCALED
    plane: str = ""          # "sagittal" | "frontal" | "" (no plane needed)
    unit: str = ""

    @property
    def usable(self) -> bool:
        return self.state == MEASURED


@dataclass(frozen=True)
class View:
    """What the camera can and cannot support.

    `bin` is the azimuth bin (SAGITTAL / OBLIQUE / FRONTAL / UNKNOWN) and
    `knowable` says whether the estimate is trustworthy enough to gate a fault
    on. A declared view from sessions.csv beats an estimate; an estimate that
    fails its own sanity checks is not knowable and blocks every PLANAR
    primitive rather than guessing.
    """
    bin: str = "UNKNOWN"
    knowable: bool = False
    side: str = "unknown"       # anterior | posterior | unknown
    agreement: float = 0.0
    ratio: float | None = None  # the R_true the azimuth was inverted with
    theta_deg: float | None = None
    source: str = "none"        # declared | estimated | none
    why: str = "no viewpoint was estimated"

    def shows(self, plane: str) -> bool:
        """Whether a quantity in `plane` can be measured from this camera."""
        if not plane:
            return True
        if not self.knowable:
            return False
        if plane == "sagittal":
            return self.bin == "SAGITTAL"
        if plane == "frontal":
            return self.bin == "FRONTAL"
        return False

    def as_dict(self) -> dict:
        return {"bin": self.bin, "knowable": self.knowable, "side": self.side,
                "agreement": round(float(self.agreement), 3),
                "thetaDeg": (None if self.theta_deg is None
                             else round(float(self.theta_deg), 1)),
                "source": self.source, "why": self.why}


UNKNOWN_VIEW = View()


def declared_view(bin_name: str | None) -> View:
    """The view the session said it was filmed from. Trusted over an estimate:
    a person who wrote SAGITTAL on the session row knows where they put the
    tripod, and the estimator is inverting a sine near its worst conditioning.
    """
    if not bin_name:
        return UNKNOWN_VIEW
    b = str(bin_name).strip().upper()
    if b not in S.BIN_EDGES_DEG:
        return View(bin="UNKNOWN", knowable=False, source="declared",
                    why=f"declared view {bin_name!r} is not a known bin")
    return View(bin=b, knowable=True, source="declared",
                why="declared on the session row")


class Evidence:
    """The primitives one rep or hold offers, and their knowability."""

    def __init__(self, track: str = "", view: View = UNKNOWN_VIEW):
        self.track = track
        self.view = view
        self._m: dict[str, Measure] = {}

    # -- building ------------------------------------------------------------
    def add(self, name: str, value, robustness: str = SCALED,
            plane: str = "", unit: str = "") -> "Evidence":
        v = _finite(value)
        if v is None:
            state = UNMEASURED
        elif plane and not self.view.shows(plane):
            state = VIEW_BLOCKED
        else:
            state = MEASURED
        self._m[name] = Measure(name, v, state, robustness, plane, unit)
        return self

    def add_all(self, values: dict, robustness: str = SCALED, **kw) -> "Evidence":
        for k, v in values.items():
            self.add(k, v, robustness, **kw)
        return self

    # -- reading -------------------------------------------------------------
    def get(self, name: str) -> Measure:
        return self._m.get(name, Measure(name, None, UNMEASURED))

    def measured(self, name: str) -> bool:
        return self.get(name).usable

    def value(self, name: str) -> float | None:
        """The number, or None. None whenever a predicate must not conclude."""
        m = self.get(name)
        return m.value if m.usable else None

    def unmeasured(self) -> list[str]:
        return sorted(n for n, m in self._m.items() if m.state == UNMEASURED)

    def view_blocked(self) -> list[str]:
        return sorted(n for n, m in self._m.items() if m.state == VIEW_BLOCKED)

    def keys(self) -> list[str]:
        return sorted(self._m)

    def as_dict(self) -> dict:
        """Every primitive's value, for the trace. None where not usable."""
        return {n: (m.value if m.usable else None) for n, m in self._m.items()}

    def states(self) -> dict:
        return {n: m.state for n, m in self._m.items()}

    @classmethod
    def from_values(cls, values: dict, track: str = "",
                    view: View = UNKNOWN_VIEW) -> "Evidence":
        """Adapter for callers that still hand over a flat dict of numbers.

        Robustness and plane come from PRIMITIVES, so a dict-built record gates
        PLANAR quantities exactly like one built from keypoints.
        """
        ev = cls(track=track, view=view)
        for name, value in values.items():
            spec = PRIMITIVES.get(name)
            if spec is None:
                ev.add(name, value)
            else:
                ev.add(name, value, spec[0], spec[1], spec[2])
        return ev


# The robustness class, required plane, and unit of every primitive the fault
# layer reads. Anything not listed is treated as SCALED and plane-free.
PRIMITIVES: dict[str, tuple[str, str, str]] = {
    # timing and ratios - the camera cannot change these
    "concentric_s": (INVARIANT, "", "s"),
    "eccentric_s": (INVARIANT, "", "s"),
    "total_s": (INVARIANT, "", "s"),
    "tempo_ratio": (INVARIANT, "", ""),
    "transition_s": (INVARIANT, "", "s"),
    "top_hold_s": (INVARIANT, "", "s"),
    "stalled_frac": (INVARIANT, "", ""),
    "fast_ratio": (INVARIANT, "", ""),
    # lengths in torso-lengths
    "swing": (SCALED, "", "torso"),
    "rom": (SCALED, "", "torso"),
    "travel": (SCALED, "", "torso"),
    "peak_height": (SCALED, "", "torso"),
    "start_depth": (SCALED, "", "torso"),
    "lockout_pct": (SCALED, "", "% of reach"),
    "hang_pct": (SCALED, "", "% of reach"),
    "squat_depth": (SCALED, "", "torso"),
    "pistol_depth": (SCALED, "", "torso"),
    "turn_speed": (SCALED, "", "torso/s"),
    # joint angles
    "start_elbow_deg": (SCALED, "", "deg"),
    "bottom_elbow_deg": (SCALED, "", "deg"),
    "arms_straight_frac": (SCALED, "", ""),
    "legs_straight_frac": (SCALED, "", ""),
    "body_line_deg": (SCALED, "", "deg"),
    "hip_pike_deg": (SCALED, "", "deg"),
    # planar quantities: only from the plane they live in
    "hip_sag": (PLANAR, "sagittal", "torso"),
    "torso_lean": (PLANAR, "sagittal", "torso"),
    "heel_rise": (PLANAR, "sagittal", "torso"),
    "knee_valgus": (PLANAR, "frontal", "torso"),
}


def _finite(x) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


# ---------------------------------------------------------------------------
# Geometry the rep path did not have before
# ---------------------------------------------------------------------------
def _ok(kp: np.ndarray, name: str) -> np.ndarray:
    return kp[:, S.KP_INDEX[name], 2] >= MIN_CONF


def _joint_angle(kp: np.ndarray, a: str, b: str, c: str) -> np.ndarray:
    """Interior angle at b, per frame, NaN where any of the three is unseen."""
    from .classify import _angle
    return _angle(kp, S.KP_INDEX[a], S.KP_INDEX[b], S.KP_INDEX[c],
                  np.ones(len(kp), dtype=bool), MIN_CONF)


def _both_sides(kp: np.ndarray, joint: str) -> np.ndarray:
    """The better-seen side's angle per frame; the mean where both are seen."""
    if joint == "elbow":
        parts = [("{}_shoulder", "{}_elbow", "{}_wrist")]
    else:
        parts = [("{}_hip", "{}_knee", "{}_ankle")]
    series = []
    for side in ("left", "right"):
        a, b, c = (p.format(side) for p in parts[0])
        series.append(_joint_angle(kp, a, b, c))
    stacked = np.vstack(series)
    # A frame where neither side was seen is NaN on purpose; nanmean says so
    # with a RuntimeWarning, which is noise in a Lambda log, so it is done by
    # hand instead.
    seen = np.isfinite(stacked)
    count = seen.sum(axis=0)
    total = np.where(seen, stacked, 0.0).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def _window(n: int, centre: int, half: int) -> slice:
    return slice(max(0, centre - half), min(n, centre + half + 1))


def _med(a: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")


def _pct(a: np.ndarray, q: float) -> float:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.percentile(a, q)) if a.size else float("nan")


def hip_above_ankle(kp: np.ndarray, torso: float) -> np.ndarray:
    """Hip height above the ankles, in torso-lengths, per frame.

    Vertical only, so it survives the camera turning around the athlete: this
    is the reference a squat's depth is measured against, in place of the
    hip-origin `shoulder_above` the bar movements use - which, on a hip-origin
    track, measures the shoulders against the hips and reports the same 1.0
    torso on every rep of every set.
    """
    hip = midpoint(kp, "left_hip", "right_hip")
    ankle = midpoint(kp, "left_ankle", "right_ankle")
    ok = np.minimum(pair_confidence(kp, "left_hip", "right_hip"),
                    pair_confidence(kp, "left_ankle", "right_ankle")) >= MIN_CONF
    out = (ankle[:, 1] - hip[:, 1]) / torso
    return np.where(ok, out, np.nan)


def hip_line_offset(kp: np.ndarray, torso: float) -> np.ndarray:
    """How far the hip sits off the shoulder-ankle line, in torso-lengths.

    Positive = the hips have dropped below the line (the sagging-hips push-up),
    negative = piked up. A sagittal quantity: from head-on the whole body line
    projects to nothing, which is why the primitive is PLANAR.
    """
    sh = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    ankle = midpoint(kp, "left_ankle", "right_ankle")
    ok = np.minimum(
        np.minimum(pair_confidence(kp, "left_shoulder", "right_shoulder"),
                   pair_confidence(kp, "left_hip", "right_hip")),
        pair_confidence(kp, "left_ankle", "right_ankle")) >= MIN_CONF
    ax, ay = ankle[:, 0], ankle[:, 1]
    sx, sy = sh[:, 0], sh[:, 1]
    hx, hy = hip[:, 0], hip[:, 1]
    dx, dy = ax - sx, ay - sy
    length = np.hypot(dx, dy)
    # signed perpendicular distance, then oriented so + is "below the line" in
    # image coordinates (y grows downward)
    cross = (dx * (hy - sy) - dy * (hx - sx))
    off = np.where(length > 1e-6, cross / np.maximum(length, 1e-6), np.nan) / torso
    sign = np.sign(dx)
    sign = np.where(sign == 0, 1.0, sign)
    return np.where(ok, off * sign, np.nan)


def planted_ankle_rise(kp: np.ndarray, torso: float, seg: slice) -> float:
    """How far the planted ankle rises above its own resting height.

    The old heel-raise signal measured the ankle against the HIP, so squatting
    deeper - the athlete's hips coming down - read as the heel coming up. This
    one is self-referenced: the ankle's own lowest position in the rep is the
    floor, and the rise is measured from there, so depth cannot fake it.
    """
    best = float("nan")
    for side in ("left", "right"):
        y = kp[seg, S.KP_INDEX[f"{side}_ankle"], 1]
        ok = kp[seg, S.KP_INDEX[f"{side}_ankle"], 2] >= MIN_CONF
        y = y[ok]
        if y.size < 5:
            continue
        floor = float(np.percentile(y, 90))      # image y grows down: 90th = lowest
        rise = (floor - float(np.percentile(y, 5))) / torso
        best = rise if not np.isfinite(best) else max(best, rise)
    return best


def turn_speed(signal, turn: int, fps: float, half_s: float = 0.15) -> float:
    """Slowest the tracked point moved near the turnaround, in torso/s.

    A rep that reverses under control passes through a near-zero velocity. One
    that bounces out of the bottom never does - the minimum speed in the window
    stays high, which is exactly what this reports.
    """
    sig = np.asarray(signal, dtype=float)
    if sig.size < 3:
        return float("nan")
    half = max(1, int(round(half_s * max(fps, 1.0))))
    v = np.abs(np.diff(sig)) * max(fps, 1.0)
    lo = max(0, turn - half)
    hi = min(len(v), turn + half)
    win = v[lo:hi]
    win = win[np.isfinite(win)]
    return float(np.min(win)) if win.size else float("nan")


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------
def rep_evidence(metrics: dict, arm: float, signal, start: int, turn: int,
                 end: int, fps: float, movement, kp: np.ndarray | None = None,
                 view: View = UNKNOWN_VIEW,
                 median_concentric_s: float | None = None) -> Evidence:
    """Everything the fault predicates for one rep are allowed to read.

    `metrics` is barra.metrics.rep_metrics' values dict; `kp` the clip's
    keypoints, without which the joint-angle and body-line primitives simply do
    not exist - and are recorded as unmeasured rather than assumed healthy.
    """
    from .config import THRESHOLDS

    ev = Evidence(track=movement.name, view=view)
    wrist_origin = movement.origin == "wrist"

    for key in ("concentric_s", "eccentric_s", "total_s", "tempo_ratio",
                "transition_s", "top_hold_s", "rom", "peak_height",
                "start_depth"):
        spec = PRIMITIVES.get(key, (SCALED, "", ""))
        ev.add(key, metrics.get(key), spec[0], spec[1], spec[2])

    # Swing is body travel measured against the movement's origin. On a
    # hip-origin track the origin IS the hips, so the quantity is the hips'
    # distance from themselves - identically zero, and "momentum" could never
    # fire. Not measuring it is the truth; a 0.0 would be a claim.
    if wrist_origin:
        ev.add("swing", metrics.get("swing"), SCALED, "", "torso")
    else:
        ev.add("swing", None, SCALED, "", "torso")

    # Lockout and hang are shares of the athlete's own reach, and reach is an
    # arm - so they mean something only when the origin is the hands.
    if wrist_origin and _finite(arm) and (arm or 0) > 0:
        peak, depth = _finite(metrics.get("peak_height")), _finite(metrics.get("start_depth"))
        ev.add("lockout_pct", None if peak is None else peak / arm * 100.0,
               SCALED, "", "% of reach")
        ev.add("hang_pct", None if depth is None else depth / arm * 100.0,
               SCALED, "", "% of reach")
    else:
        ev.add("lockout_pct", None, SCALED, "", "% of reach")
        ev.add("hang_pct", None, SCALED, "", "% of reach")

    # Share of the ascent that made no progress - the smoothness component's
    # read-out, recomputed here so the fault and the score cannot disagree.
    ev.add("stalled_frac", _stalled_frac(signal, start, turn,
                                         THRESHOLDS.stall_rate), INVARIANT)

    # How much of the tracked travel this rep actually covered, independent of
    # which end of it the movement starts from (a dip and a pull-up disagree
    # about that, and `rom` only answers for the ascending one).
    ev.add("travel", _travel(signal, start, end), SCALED, "", "torso")
    ev.add("turn_speed", turn_speed(signal, turn, fps), SCALED, "", "torso/s")

    # A rep thrown rather than pulled: its concentric against the set's own
    # median, so it is a comparison within one athlete on one day - no
    # absolute seconds, nothing that depends on the camera.
    conc = _finite(metrics.get("concentric_s"))
    if conc is not None and _finite(median_concentric_s) and median_concentric_s:
        ev.add("fast_ratio", conc / median_concentric_s, INVARIANT)
    else:
        ev.add("fast_ratio", None, INVARIANT)

    if kp is None:
        for key in ("start_elbow_deg", "bottom_elbow_deg", "arms_straight_frac",
                    "legs_straight_frac", "squat_depth", "hip_sag",
                    "torso_lean", "knee_valgus", "heel_rise"):
            spec = PRIMITIVES.get(key, (SCALED, "", ""))
            ev.add(key, None, spec[0], spec[1], spec[2])
        return ev

    torso = robust_torso(kp)
    n = len(kp)
    seg = slice(start, min(end + 1, n))
    half = max(1, int(round(0.10 * max(fps, 1.0))))

    elbow = _both_sides(kp, "elbow")
    knee = _both_sides(kp, "knee")
    ev.add("start_elbow_deg", _med(elbow[_window(n, start, half)]),
           SCALED, "", "deg")
    ev.add("bottom_elbow_deg", _med(elbow[_window(n, turn, half)]),
           SCALED, "", "deg")
    ev.add("arms_straight_frac", _frac_at_least(elbow[seg], THRESHOLDS.straight_arm))
    ev.add("legs_straight_frac", _frac_at_least(knee[seg], THRESHOLDS.straight_leg))

    # Squat depth against this rep's own standing height, measured hip-over-
    # ankle. Vertical, so it does not care where the camera stands.
    hoa = hip_above_ankle(kp, torso)[seg]
    stand = _pct(hoa, 90)
    bottom = _pct(hoa, 5)
    ev.add("squat_depth",
           (stand - bottom) if np.isfinite(stand) and np.isfinite(bottom) else None,
           SCALED, "", "torso")

    sag = hip_line_offset(kp, torso)[seg]
    ev.add("hip_sag", _pct(sag, 90), PLANAR, "sagittal", "torso")
    ev.add("heel_rise", planted_ankle_rise(kp, torso, seg), PLANAR, "sagittal", "torso")

    lean = ((midpoint(kp, "left_hip", "right_hip")[:, 0]
             - midpoint(kp, "left_shoulder", "right_shoulder")[:, 0]) / torso)[seg]
    ev.add("torso_lean", _pct(lean, 90), PLANAR, "sagittal", "torso")
    ev.add("knee_valgus", _knee_valgus(kp, torso, seg), PLANAR, "frontal", "torso")
    return ev


def _frac_at_least(a: np.ndarray, thresh: float) -> float:
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.mean(a >= thresh)) if a.size else float("nan")


def _travel(signal, start: int, end: int) -> float:
    sig = np.asarray(signal, dtype=float)[start:end + 1]
    sig = sig[np.isfinite(sig)]
    return float(sig.max() - sig.min()) if sig.size else float("nan")


def _stalled_frac(signal, start: int, turn: int, stall_rate: float) -> float:
    if signal is None:
        return float("nan")
    seg = np.asarray(signal, dtype=float)[start:turn + 1]
    if seg.size < 6:
        return float("nan")
    step = np.diff(seg)
    total = seg[-1] - seg[0]
    if not np.isfinite(total) or total <= 1e-9:
        return float("nan")
    mean_rate = total / step.size
    return float(np.mean(step < stall_rate * mean_rate))


def _knee_valgus(kp: np.ndarray, torso: float, seg: slice) -> float:
    dev = []
    for side in ("left", "right"):
        kx = kp[:, S.KP_INDEX[f"{side}_knee"], 0]
        hx = kp[:, S.KP_INDEX[f"{side}_hip"], 0]
        ax = kp[:, S.KP_INDEX[f"{side}_ankle"], 0]
        ok = (_ok(kp, f"{side}_knee") & _ok(kp, f"{side}_hip")
              & _ok(kp, f"{side}_ankle"))
        d = (np.abs(kx - (hx + ax) / 2.0) / torso)[seg]
        d = d[ok[seg] & np.isfinite(d)]
        if d.size:
            dev.append(float(np.percentile(d, 90)))
    return max(dev) if dev else float("nan")


# ---------------------------------------------------------------------------
# Viewpoint, from keypoints, for one clip
# ---------------------------------------------------------------------------
def estimate_view(kp: np.ndarray) -> View:
    """The camera's azimuth bin for one clip, and whether to believe it.

    The harness estimator (barra/viewpoint.py) calibrates R_true across every
    clip of a subject, because projection can only ever shrink the apparent
    shoulder width. One clip cannot do that, so this uses the clip's own widest
    view and refuses to be trusted unless that lands inside the anatomical
    prior - which is the same failure the harness reports rather than binning
    wrong. A PLANAR fault gated on an unknowable view is simply not fired.
    """
    from .viewpoint import (ANATOMICAL_PRIOR_RANGE, _bin_of, _theta_deg,
                            apparent_ratios_kp, camera_side_kp)

    ratios = apparent_ratios_kp(kp)
    if ratios.size < 10:
        return View(source="estimated",
                    why="fewer than 10 frames saw both shoulders confidently")
    r_true = float(np.percentile(ratios, 97))
    side, agreement = camera_side_kp(kp)
    theta = float(_theta_deg(float(np.median(ratios)), max(r_true, 1e-6)))
    b = _bin_of(theta)

    lo, hi = ANATOMICAL_PRIOR_RANGE
    if not lo <= r_true <= hi:
        return View(bin=b, knowable=False, side=side, agreement=agreement,
                    ratio=r_true, theta_deg=theta, source="estimated",
                    why=(f"self-calibration {r_true:.2f} is outside the "
                         f"anatomical prior {lo}-{hi}, so the azimuth is biased"))
    if agreement < 0.70:
        return View(bin=b, knowable=False, side=side, agreement=agreement,
                    ratio=r_true, theta_deg=theta, source="estimated",
                    why="which side of the subject the camera is on is unclear")
    if b == "UNKNOWN":
        return View(bin=b, knowable=False, side=side, agreement=agreement,
                    ratio=r_true, theta_deg=theta, source="estimated",
                    why="the azimuth falls outside every bin")
    return View(bin=b, knowable=True, side=side, agreement=agreement,
                ratio=r_true, theta_deg=theta, source="estimated",
                why=f"azimuth {theta:.0f} degrees from the movement plane")
