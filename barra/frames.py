"""The technique window, cut out of the raw take, and stills of its key steps.

Measurement runs over the whole clip because rep boundaries are only known
after the fact, but everything that *looks* at the movement - a vision model,
a human replaying the trace - should see the working set, not the walk to the
bar. This module cuts the clip to the measured window and grabs one still per
rep at its turning point.

Both operations are best-effort: a missing decoder or a full disk must never
fail a measurement. Callers treat every failure as "no artifacts".
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MAX_STILLS = 11          # one per rep up to ten, plus the window's first frame
MAX_WIDTH = 512          # stills carry posture, not detail; 512px is enough
JPEG_QUALITY = 80


@dataclass
class TechniqueArtifacts:
    """What could be produced for one job. Paths may be empty on failure."""
    clip: Path | None = None
    stills: list[Path] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)   # one per still, same order

    def as_trace_data(self) -> dict:
        return {
            "clip": self.clip.name if self.clip else None,
            "stills": [p.name for p in self.stills],
            "labels": self.labels,
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


def grab_stills(video_path: Path, moments_s: list[float], out_dir: Path,
                prefix: str = "frame") -> list[Path]:
    """One JPEG per timestamp. cv2 ships with the pose backend, so it is the
    one decoder the pipeline can rely on being there."""
    try:
        import cv2
    except ImportError:
        return []
    paths: list[Path] = []
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
                out = out_dir / f"{prefix}_{i + 1:02d}_{t:.2f}s.jpg"
                if not cv2.imwrite(str(out), frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]):
                    continue
                paths.append(out)
        finally:
            cap.release()
    except Exception:  # noqa: BLE001
        return paths
    return paths


def technique_artifacts(video_path: Path, report: dict, trace_dir: Path,
                        trace_id: str) -> TechniqueArtifacts:
    """Cut the window and still every rep's turning point, from the measured
    report itself - the report is what the phone sees, so the artifacts and
    the numbers can never disagree."""
    trim = report.get("trim") or {}
    start_s = float(trim.get("startS") or 0.0)
    end_s = float(trim.get("endS") or 0.0)
    if end_s <= start_s:
        return TechniqueArtifacts()

    root = trace_dir / trace_id
    art = TechniqueArtifacts(
        clip=cut_technique(video_path, start_s, end_s, root / "technique.mp4"),
    )

    moments: list[float] = []
    labels: list[str] = []
    for rep in report.get("reps") or []:
        turn = float(rep.get("turnS") or 0.0)
        start = float(rep.get("startS") or 0.0)
        end = float(rep.get("endS") or 0.0)
        t = turn if start <= turn <= end and turn > 0 else start
        if t <= 0:
            continue
        moments.append(t)
        labels.append(f"{rep.get('label', 'rep')} turning point")
    if moments:
        moments.insert(0, start_s)
        labels.insert(0, "start of the technique")
    art.stills = grab_stills(video_path, moments, root, prefix="step")
    art.labels = labels[:len(art.stills)]
    return art
