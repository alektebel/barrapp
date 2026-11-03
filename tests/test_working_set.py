from __future__ import annotations

import numpy as np

from barra.working_set import find_working_set


def _pose(T: int = 240, fps: float = 30.0, work=(60, 180)) -> np.ndarray:
    """Synthetic hang with a mid-clip oscillating shoulder (work)."""
    kp = np.zeros((T, 17, 3), dtype=np.float32)
    kp[:, :, 2] = 0.9
    # wrists fixed above
    kp[:, 9, 0] = 80
    kp[:, 10, 0] = 120
    kp[:, 9, 1] = 40
    kp[:, 10, 1] = 40
    # shoulders / elbows / hips / knees / ankles static hang
    kp[:, 5, 0] = 80
    kp[:, 6, 0] = 120
    kp[:, 5, 1] = 120
    kp[:, 6, 1] = 120
    kp[:, 7, 0] = 80
    kp[:, 8, 0] = 120
    kp[:, 7, 1] = 80
    kp[:, 8, 1] = 80
    kp[:, 11, 0] = 85
    kp[:, 12, 0] = 115
    kp[:, 11, 1] = 200
    kp[:, 12, 1] = 200
    kp[:, 13, 0] = 85
    kp[:, 14, 0] = 115
    kp[:, 13, 1] = 260
    kp[:, 14, 1] = 260
    kp[:, 15, 0] = 85
    kp[:, 16, 0] = 115
    kp[:, 15, 1] = 320
    kp[:, 16, 1] = 320
    a, b = work
    t = np.arange(b - a) / fps
    wave = 50.0 * np.sin(2 * np.pi * 0.5 * t)
    kp[a:b, 5, 1] = 120 + wave
    kp[a:b, 6, 1] = 120 + wave
    kp[a:b, 7, 1] = 80 + wave * 0.5
    kp[a:b, 8, 1] = 80 + wave * 0.5
    return kp


def test_working_set_excludes_idle_prefix():
    kp = _pose()
    ws = find_working_set(kp, fps=30.0)
    assert ws.end > ws.start
    # Should start near the work region, not at frame 0 of idle hang.
    assert ws.start >= 20
    assert ws.start <= 90
    assert ws.end >= 150


def test_working_set_dict_has_seconds():
    kp = _pose()
    d = find_working_set(kp, 30.0).as_dict(30.0)
    assert "startS" in d and "endS" in d
    assert d["endS"] > d["startS"]
