"""The technique window, cut out of the raw take, and stills of its phases.

Measurement runs over the whole clip because rep boundaries are only known
after the fact, but everything that *looks* at the movement - a vision model,
a human replaying the trace - should see the working set, not the walk to the
bar. This module cuts the clip to the measured window and grabs stills that
walk through the phases of representative reps.

Why phase sequences and not one still per turning point: a turning point shows
where the rep ended up, not how it got there. A stall is invisible at the top;
a dropped descent is invisible at the bottom; a kip is visible only mid-lift.
So for a fixed frame budget, a few reps are sampled at five moments each -
start, mid-first-phase, turn, mid-second-phase, end - and a hold at its onset,
sustained middle and exit. Every still is labelled with its rep, its phase and
its timestamp in the SOURCE video, and the label travels with the file: a
still that failed to decode drops out of both lists together, so label N is
always image N.

Both operations are best-effort: a missing decoder or a full disk must never
fail a measurement. Callers treat every failure as "no artifacts".
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MAX_STILLS = 16          # the frame budget: 3 reps x 5 phases, plus the window start
REPS_SAMPLED = 3         # early, middle, late
MAX_WIDTH = 512          # stills carry posture, not detail; 512px is enough
JPEG_QUALITY = 80

# Phase names on a still, in the order they are sampled.
REP_MOMENTS = ("start", "mid-first", "turn", "mid-second", "end")
HOLD_MOMENTS = ("onset", "sustained", "exit")


@dataclass(frozen=True)
class Still:
    """One frame and what it shows: rep, phase, source-video timestamp."""
    path: Path
    rep: str          # "r2", "h1", or "" for the window's first frame
    phase: str        # the phase name the moment falls in
    moment: str       # start | mid-first | turn | mid-second | end | onset | ...
    t_s: float        # timestamp in the source video

    @property
    def label(self) -> str:
        who = self.rep or "window"
        return f"{who} {self.phase} ({self.moment}) at {self.t_s:.2f}s"

    def as_dict(self) -> dict:
        return {"file": self.path.name, "rep": self.rep, "phase": self.phase,
                "moment": self.moment, "tS": round(float(self.t_s), 2)}


@dataclass
class TechniqueArtifacts:
    """What could be produced for one job. Paths may be empty on failure.

    `stills` and `labels` are kept as parallel lists for callers that predate
    `frames`; the two are built from the same records, so they cannot drift.
    """
    clip: Path | None = None
    frames: list[Still] = field(default_factory=list)
    selected_reps: list[str] = field(default_factory=list)

    @property
    def stills(self) -> list[Path]:
        return [s.path for s in self.frames]

    @property
    def labels(self) -> list[str]:
        return [s.label for s in self.frames]

    def as_trace_data(self) -> dict:
        return {
            "clip": self.clip.name if self.clip else None,
            "stills": [p.name for p in self.stills],
            "labels": self.labels,
            "frames": [s.as_dict() for s in self.frames],
            "selectedReps": list(self.selected_reps),
            "budget": MAX_STILLS,
        }


def cut_technique(video_path: Path, start_s: float, end_s: float,
                  out_path: Path) -> Path | None:
    """The raw take trimmed to the working set, with a little air either side.

    Stream-copy keeps it cheap and lossless enough for review; the cut lands
    on keyframes, which is fine for a study artifact, not for measurement.
    """
    if end_s <= start_s:
        return None
    try:
        if shutil.which("ffmpeg") is None:
            return None
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y",
             "-ss", f"{max(0.0, start_s):.2f}", "-i", str(video_path),
             "-t", f"{max(0.1, end_s - start_s):.2f}", "-c", "copy",
             str(out_path)],
            check=True, capture_output=True, timeout=60,
        )
    except Exception:  # noqa: BLE001 - an artifact is never worth a job
        return None
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else None


def grab_frames(video_path: Path, moments_s: list[float], out_dir: Path,
                prefix: str = "frame") -> list[tuple[int, Path]]:
    """One JPEG per timestamp, returned as (index into moments_s, path) so the
    caller knows WHICH moments succeeded. cv2 ships with the pose backend, so
    it is the one decoder the pipeline can rely on being there."""
    try:
        import cv2
    except ImportError:
        return []
    out: list[tuple[int, Path]] = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(video_path))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            for i, t in enumerate(moments_s[:MAX_STILLS]):
                idx = min(max(int(t * fps), 0), max(n_frames - 1, 0))
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if not ok:
                    continue
                h, w = frame.shape[:2]
                if w > MAX_WIDTH:
                    frame = cv2.resize(frame, (MAX_WIDTH, int(h * MAX_WIDTH / w)))
                path = out_dir / f"{prefix}_{i + 1:02d}_{t:.2f}s.jpg"
                if not cv2.imwrite(str(path), frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]):
                    continue
                out.append((i, path))
        finally:
            cap.release()
    except Exception:  # noqa: BLE001
        return out
    return out


def grab_stills(video_path: Path, moments_s: list[float], out_dir: Path,
                prefix: str = "frame") -> list[Path]:
    """The paths only. Callers that need to know which moment each still is
    should use `grab_frames`; this shape cannot tell them."""
    return [p for _, p in grab_frames(video_path, moments_s, out_dir, prefix)]


# ---------------------------------------------------------------------------
# Which reps, and which moments of each
# ---------------------------------------------------------------------------
def select_reps(reps: list[dict], k: int = REPS_SAMPLED) -> list[dict]:
    """Early, middle and late reps - the set's arc under a fixed budget. All
    of them when there are no more than `k`."""
    n = len(reps)
    if n <= k:
        return list(reps)
    if k == 1:
        return [reps[n // 2]]
    idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return [reps[i] for i in idx]


def _phase_at(rep: dict, t: float, default: str) -> str:
    """The name of the phase `t` falls in, from the rep's own phase table
    (payloads since the registry carry one); `default` when it does not."""
    phases = rep.get("phases") or {}
    best = default
    best_len = float("inf")
    for name, span in phases.items():
        if name in ("rep", "hold") or not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        a, b = float(span[0]), float(span[1])
        if a <= t <= b and (b - a) < best_len:
            best, best_len = name, b - a
    return best


def rep_moments(rep: dict) -> list[tuple[str, str, float]]:
    """(moment, phase, t_s) for one rep: start, mid-first, turn, mid-second,
    end. Phase names come from the rep's phase table, so a push-up's first
    half is `lowering` and a pull-up's is `lifting` without this module
    knowing either movement."""
    start = float(rep.get("startS") or 0.0)
    end = float(rep.get("endS") or 0.0)
    turn = float(rep.get("turnS") or 0.0)
    if end <= start:
        return []
    if not start <= turn <= end:
        turn = 0.5 * (start + end)
    ts = [start, 0.5 * (start + turn), turn, 0.5 * (turn + end), end]
    out = []
    for moment, t in zip(REP_MOMENTS, ts):
        if moment == "start":
            phase = _phase_at(rep, t + 1e-3, "setup")
        elif moment == "end":
            phase = _phase_at(rep, t - 1e-3, "end")
        elif moment == "turn":
            phase = _phase_at(rep, t, "turn")
        else:
            phase = _phase_at(rep, t, moment)
        out.append((moment, phase, t))
    return out


def hold_moments(rep: dict) -> list[tuple[str, str, float]]:
    start = float(rep.get("startS") or 0.0)
    end = float(rep.get("endS") or 0.0)
    if end <= start:
        return []
    ts = [start, 0.5 * (start + end), end]
    return [(m, m, t) for m, t in zip(HOLD_MOMENTS, ts)]


def technique_artifacts(video_path: Path, report: dict, trace_dir: Path,
                        trace_id: str) -> TechniqueArtifacts:
    """Cut the window and still the phases of representative reps, from the
    measured report itself - the report is what the phone sees, so the
    artifacts and the numbers can never disagree."""
    trim = report.get("trim") or {}
    start_s = float(trim.get("startS") or 0.0)
    end_s = float(trim.get("endS") or 0.0)
    if end_s <= start_s:
        return TechniqueArtifacts()

    root = trace_dir / trace_id
    art = TechniqueArtifacts(
        clip=cut_technique(video_path, start_s, end_s, root / "technique.mp4"),
    )

    reps = [r for r in (report.get("reps") or []) if isinstance(r, dict)]
    is_hold = any(str(r.get("label", "")).startswith("h") for r in reps)
    chosen = select_reps(reps)
    art.selected_reps = [str(r.get("label", "")) for r in chosen]

    plan: list[Still] = []   # paths filled in after the grab
    moments: list[tuple[str, str, str, float]] = [("", "window", "start", start_s)]
    for rep in chosen:
        label = str(rep.get("label", "rep"))
        for moment, phase, t in (hold_moments(rep) if is_hold else rep_moments(rep)):
            moments.append((label, phase, moment, t))
    moments = moments[:MAX_STILLS]
    if len(moments) <= 1:
        return art

    grabbed = grab_frames(video_path, [t for *_, t in moments], root, prefix="step")
    for i, path in grabbed:
        rep, phase, moment, t = moments[i]
        plan.append(Still(path, rep, phase, moment, t))
    art.frames = plan
    return art
