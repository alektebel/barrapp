"""QC overlay renderer.

Produces out/qc/<rep>.mp4: the source frames with the detected skeleton on the
left, and the same rep aligned onto the template on the right, drawn in the
normalised frame with the reference interquartile band behind it.

This exists so that a flagged rep can be checked by eye before it is believed.
A deviation score that the overlay does not visibly corroborate is a pose
estimation failure, not a technique finding, and this is how you tell.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from . import schema as S
from .config import PATHS, RESAMPLE_LENGTH
from .ingest import discover

PANEL = 480
COL_TEST = (80, 200, 255)     # BGR - amber
COL_TEMPLATE = (140, 255, 140)  # BGR - green
COL_BAND = (70, 90, 70)


def _find_source(video: str) -> Path | None:
    for p in discover():
        if p.stem == video:
            return p
    return None


def _draw_skeleton(canvas, pts, colour, thickness=2, radius=3):
    for a, b in S.SKELETON_EDGES:
        if a in S.ANALYSIS_JOINTS and b in S.ANALYSIS_JOINTS:
            ia, ib = S.ANALYSIS_JOINTS.index(a), S.ANALYSIS_JOINTS.index(b)
            pa, pb = pts[ia], pts[ib]
            if np.isfinite(pa).all() and np.isfinite(pb).all():
                cv2.line(canvas, tuple(pa), tuple(pb), colour, thickness, cv2.LINE_AA)
    for p in pts:
        if np.isfinite(p).all():
            cv2.circle(canvas, tuple(p), radius, colour, -1, cv2.LINE_AA)


def _to_panel(xy: np.ndarray, scale: float, cx: float, cy: float) -> np.ndarray:
    """Normalised coords (hip at origin, torso = 1, image-y down) -> pixels."""
    out = np.empty(xy.shape[:-1] + (2,), dtype=np.int32)
    out[..., 0] = np.round(xy[..., 0] * scale + cx)
    out[..., 1] = np.round(xy[..., 1] * scale + cy)
    return out


def _fit(*clouds: np.ndarray, margin: float = 0.10) -> tuple[float, float, float]:
    """Scale and centre that fit every point of every cloud in the panel.

    Computed once over the whole rep rather than per frame, so the skeleton
    does not swim around inside the panel as the rep progresses - a moving
    frame of reference would make the two skeletons hard to compare by eye,
    which is the only thing this render is for.
    """
    pts = np.concatenate([c.reshape(-1, 2) for c in clouds], axis=0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    scale = float(PANEL * (1.0 - 2 * margin) / span.max())
    mid = 0.5 * (lo + hi)
    return scale, PANEL / 2 - mid[0] * scale, PANEL / 2 - mid[1] * scale


def render_overlay(rep_row: pd.Series, sc, T: np.ndarray, q1: np.ndarray,
                   q3: np.ndarray, fps: float | None = None) -> Path | None:
    video = str(rep_row["video"])
    src = _find_source(video)
    out_path = PATHS.o(S.P_QC, f"{rep_row['rep_id'].replace('#', '_')}.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    L = T.shape[0]
    start, end = int(rep_row["start_frame"]), int(rep_row["end_frame"])
    fps = float(fps or rep_row.get("fps", 30.0) or 30.0)

    # template index -> source frame, via the warping path
    tmpl_to_i: dict[int, list[int]] = {}
    for i, j in sc.path:
        tmpl_to_i.setdefault(j, []).append(i)
    src_frame = {
        j: start + int(round(np.median(v) / max(RESAMPLE_LENGTH - 1, 1) * (end - start)))
        for j, v in tmpl_to_i.items()
    }

    frames: dict[int, np.ndarray] = {}
    if src is not None:
        cap = cv2.VideoCapture(str(src))
        if cap.isOpened():
            wanted = set(src_frame.values())
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            f = start
            while f <= end:
                ok, img = cap.read()
                if not ok:
                    break
                if f in wanted:
                    frames[f] = img
                f += 1
            cap.release()

    writer = cv2.VideoWriter(
        str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), max(fps, 1.0), (PANEL * 2, PANEL)
    )
    if not writer.isOpened():
        return None

    scale, cx, cy = _fit(T, sc.aligned, q1, q3)

    for j in range(L):
        left = np.zeros((PANEL, PANEL, 3), dtype=np.uint8)
        img = frames.get(src_frame.get(j, -1))
        if img is not None:
            h, w = img.shape[:2]
            s = PANEL / max(h, w)
            r = cv2.resize(img, (int(w * s), int(h * s)))
            y0, x0 = (PANEL - r.shape[0]) // 2, (PANEL - r.shape[1]) // 2
            left[y0:y0 + r.shape[0], x0:x0 + r.shape[1]] = r
        else:
            cv2.putText(left, "source frame unavailable", (20, PANEL // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1, cv2.LINE_AA)

        right = np.full((PANEL, PANEL, 3), 18, dtype=np.uint8)
        lo = _to_panel(q1[j], scale, cx, cy)
        hi = _to_panel(q3[j], scale, cx, cy)
        for k in range(lo.shape[0]):
            cv2.rectangle(right, tuple(np.minimum(lo[k], hi[k]) - 2),
                          tuple(np.maximum(lo[k], hi[k]) + 2), COL_BAND, -1)
        _draw_skeleton(right, _to_panel(T[j], scale, cx, cy), COL_TEMPLATE, 2, 3)
        _draw_skeleton(right, _to_panel(sc.aligned[j], scale, cx, cy), COL_TEST, 2, 4)

        cv2.putText(right, "template", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    COL_TEMPLATE, 1, cv2.LINE_AA)
        cv2.putText(right, "this rep (aligned)", (12, 46), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, COL_TEST, 1, cv2.LINE_AA)
        cv2.putText(right, f"t {j+1}/{L}", (12, PANEL - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)
        cv2.putText(left, str(rep_row["rep_id"]), (12, 24), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (230, 230, 230), 1, cv2.LINE_AA)

        writer.write(np.hstack([left, right]))
    writer.release()
    return out_path
