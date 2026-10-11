"""Stage contracts: the invariants each step's output must keep.

Each `check_*` is a pure function, output (+ the context it needs) -> list of
`Violation`. An empty list says the output is well-formed - that the shapes,
ranges and cross-field agreements hold. It does not say the measurement is
right; the labelled corpus answers that.

`fatal` marks a violation the phone cannot survive (a payload without a key
the app reads). Everything else is recorded and the job carries on; see
`barra/sentinel.py` for what happens to each.

The payload key lists live here, once: tests/test_server_payload.py and the
sentinel both read them, so the app, the tests and production agree on one
definition of "a complete answer".
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

# Keys the Kotlin client reads (BarraApi.parseAnalysis).
REQUIRED = [
    "headline", "narrative", "nextSession",
    "exercise", "detected", "trim", "session",
    "sessionScore", "sessionBand",
    "n_reps", "n_candidates", "fps", "duration_s",
    "reps", "sessions", "blockers",
    "topFixes",
]

REP_REQUIRED = [
    "session", "label", "transition_s", "total_s", "class", "metrics",
    "plausible", "problems", "startS", "endS", "turnS",
    "score", "band", "scoreNote", "components", "aside", "trace",
]

BANDS = {"unmeasured", "strong", "solid", "shaky", "broken down"}

# Text that is for a developer, not an athlete. The first is the SystemExit of
# movements.resolve that reached phones in production (2026-09-17).
_DEVELOPER_TEXT = re.compile(r"Known: |Traceback|pip install|\.venv|Exception\b|Error:")

# A duration this far from frames/fps means the container lied about one.
_DURATION_TOLERANCE = 0.05
_MIN_TRACKED = 0.10
_VISIBLE = 0.3
_TIME_SLACK_S = 0.5


@dataclass(frozen=True)
class Violation:
    stage: str
    rule: str
    detail: str
    fatal: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# -- probe -------------------------------------------------------------------
def check_probe(info: dict, **_: Any) -> list[Violation]:
    """probe_video(): {ok, fps, frames, duration_s, ...}."""
    if not info or not info.get("ok"):
        return []  # an unreadable clip is reported as a blocker, not a broken probe
    out: list[Violation] = []
    fps, frames, dur = _num(info.get("fps")), _num(info.get("frames")), _num(info.get("duration_s"))
    if not fps or fps <= 0:
        out.append(Violation("probe", "fps_positive", f"fps={info.get('fps')}"))
    if frames is not None and frames <= 0:
        out.append(Violation("probe", "has_frames", f"frames={frames}"))
    if fps and frames and dur:
        expected = frames / fps
        if abs(dur - expected) > max(_DURATION_TOLERANCE * expected, 1.0 / fps):
            out.append(Violation("probe", "duration_matches_frames",
                                 f"duration {dur:.2f}s vs frames/fps {expected:.2f}s"))
    return out


# -- pose --------------------------------------------------------------------
def check_pose(keypoints: Any, fps: float | None = None, **_: Any) -> list[Violation]:
    """Pose estimate: keypoints (T, K, >=3) with visibility in channel 2."""
    out: list[Violation] = []
    shape = getattr(keypoints, "shape", None)
    if shape is None or len(shape) != 3 or shape[2] < 3:
        return [Violation("pose", "keypoints_shape", f"shape={shape}", fatal=True)]
    if shape[0] == 0:
        return [Violation("pose", "has_frames", "no frames estimated")]
    f = _num(fps)
    if f is None or not (1.0 <= f <= 480.0):
        out.append(Violation("pose", "fps_plausible", f"fps={fps}"))
    import numpy as np
    vis = np.asarray(keypoints[:, :, 2], dtype=float)
    xy = np.asarray(keypoints[:, :, :2], dtype=float)
    tracked = (np.nan_to_num(vis, nan=0.0) > _VISIBLE) & np.isfinite(xy).all(axis=2)
    frac = float(tracked.mean()) if tracked.size else 0.0
    if frac < _MIN_TRACKED:
        out.append(Violation("pose", "tracked_enough",
                             f"{frac:.0%} of joints tracked, needs {_MIN_TRACKED:.0%}"))
    return out


# -- detection / fusion ------------------------------------------------------
def check_detection(detected: dict, **_: Any) -> list[Violation]:
    out: list[Violation] = []
    if not detected or not str(detected.get("exercise") or "").strip():
        out.append(Violation("detection", "exercise_named", f"exercise={detected and detected.get('exercise')!r}"))
    c = _num((detected or {}).get("confidence"))
    if c is None or not (0.0 <= c <= 1.0):
        out.append(Violation("detection", "confidence_in_unit", f"confidence={(detected or {}).get('confidence')}"))
    return out


def check_fusion(fusion: dict | None, **_: Any) -> list[Violation]:
    if fusion is None:
        return []
    if not str(fusion.get("exercise") or "").strip():
        return [Violation("fusion", "exercise_named", f"fusion={fusion}")]
    return []


# -- segmentation ------------------------------------------------------------
def check_segments(found: list, n_frames: int | None = None, **_: Any) -> list[Violation]:
    """segment_reps_verbose(): [(start, turn, end)] frame indices."""
    out: list[Violation] = []
    prev_end = -1
    for i, rep in enumerate(found or []):
        try:
            s, t, e = (int(x) for x in rep)
        except (TypeError, ValueError):
            out.append(Violation("segments", "rep_is_triple", f"rep {i}: {rep!r}"))
            continue
        if not (s < t < e):
            out.append(Violation("segments", "start_turn_end_ordered", f"rep {i}: {s},{t},{e}"))
        if s < 0 or (n_frames is not None and e >= n_frames):
            out.append(Violation("segments", "inside_clip", f"rep {i}: {s}..{e} of {n_frames}"))
        if s < prev_end:
            out.append(Violation("segments", "disjoint_and_sorted", f"rep {i} starts {s} before {prev_end}"))
        prev_end = max(prev_end, e)
    return out


# -- payload -----------------------------------------------------------------
def _band_of(score: float | None) -> str | None:
    try:
        from .quality import band
    except ImportError:  # pragma: no cover
        return None
    return band(None if score is None else int(score))


def _visible_text(payload: dict) -> list[str]:
    texts = [payload.get(k) for k in ("headline", "narrative", "nextSession")]
    texts += list(payload.get("blockers") or [])
    for r in payload.get("reps") or []:
        texts += list(r.get("problems") or [])
        texts.append(r.get("scoreNote"))
    return [t for t in texts if isinstance(t, str) and t]


def check_payload(payload: dict, expected_version: int | None = None, **_: Any) -> list[Violation]:
    """The result the phone renders."""
    out: list[Violation] = []
    missing = [k for k in REQUIRED if k not in payload]
    if missing:
        out.append(Violation("payload", "required_keys", f"missing {missing}", fatal=True))
    if expected_version is None:
        try:
            from .rules import ASSESSMENT_VERSION as expected_version
        except ImportError:
            expected_version = 2
    if payload.get("measurementVersion") != expected_version:
        out.append(Violation("payload", "measurement_version",
                             f"{payload.get('measurementVersion')} != {expected_version}"))

    score = payload.get("sessionScore")
    band = payload.get("sessionBand")
    if score is not None and not (0 <= (_num(score) or -1) <= 100):
        out.append(Violation("payload", "session_score_in_range", f"sessionScore={score}"))
    expected_band = _band_of(_num(score) if score is not None else None)
    if band not in BANDS or (expected_band is not None and band != expected_band):
        out.append(Violation("payload", "session_band_matches_score", f"score={score} band={band!r}"))

    reps = payload.get("reps") or []
    duration = _num(payload.get("duration_s")) or 0.0
    for i, r in enumerate(reps):
        lacking = [k for k in REP_REQUIRED if k not in r]
        if lacking:
            out.append(Violation("payload", "rep_required_keys", f"rep {i} missing {lacking}"))
            continue
        rs = r.get("score")
        if rs is not None and not (0 <= (_num(rs) or -1) <= 100):
            out.append(Violation("payload", "rep_score_in_range", f"rep {i} score={rs}"))
        s, t, e = _num(r.get("startS")), _num(r.get("turnS")), _num(r.get("endS"))
        if None not in (s, t, e):
            if not (s <= t <= e):
                out.append(Violation("payload", "rep_times_ordered", f"rep {i}: {s},{t},{e}"))
            if s < 0 or (duration > 0 and e > duration + _TIME_SLACK_S):
                out.append(Violation("payload", "rep_times_inside_clip",
                                     f"rep {i} ends {e}s of a {duration}s clip"))

    n_reps, n_cand = payload.get("n_reps"), payload.get("n_candidates")
    if isinstance(n_reps, int) and n_reps < 0:
        out.append(Violation("payload", "n_reps_non_negative", f"n_reps={n_reps}"))
    # A count from the vision fallback has no geometric candidates behind it.
    if (isinstance(n_reps, int) and isinstance(n_cand, int) and n_cand > 0
            and n_reps > n_cand):
        out.append(Violation("payload", "n_reps_le_candidates", f"n_reps={n_reps} > n_candidates={n_cand}"))
    if n_reps == 0 and not (payload.get("blockers") or []):
        out.append(Violation("payload", "zero_reps_has_blocker", "nothing counted and no reason given"))

    untranslated = (payload.get("i18n") or {}).get("untranslated") or []
    if untranslated:
        out.append(Violation("payload", "untranslated_text", "; ".join(map(str, untranslated))[:200]))
    for text in _visible_text(payload):
        if _DEVELOPER_TEXT.search(text):
            out.append(Violation("payload", "no_developer_text", text[:120]))
    return out


CONTRACTS: dict[str, Callable[..., list[Violation]]] = {
    "probe": check_probe,
    "pose": check_pose,
    "detection": check_detection,
    "fusion": check_fusion,
    "segments": check_segments,
    "payload": check_payload,
}
