from __future__ import annotations

import numpy as np

from barra.pose.ultralytics_backend import UltralyticsBackend


def test_select_subject_prefers_current_track():
    areas = np.array([10.0, 20.0])
    idx, selected, missed = UltralyticsBackend._select_subject(areas, [7, 8], 7, 0)
    assert (idx, selected, missed) == (0, 7, 0)


def test_select_subject_survives_short_gap():
    areas = np.array([20.0, 10.0])
    idx, selected, missed = UltralyticsBackend._select_subject(areas, [8], 7, 2)
    assert (idx, selected, missed) == (0, 7, 3)


def test_select_subject_switches_after_long_gap():
    areas = np.array([10.0, 20.0])
    idx, selected, missed = UltralyticsBackend._select_subject(areas, [8], 7, 99)
    assert (idx, selected, missed) == (1, 8, 0)


def test_select_subject_without_ids_falls_back_to_largest_box():
    areas = np.array([10.0, 20.0])
    idx, selected, missed = UltralyticsBackend._select_subject(areas, None, 7, 0)
    assert (idx, selected, missed) == (1, 7, 0)


def test_resolve_weights_honours_env_override(monkeypatch, tmp_path):
    p = tmp_path / "custom-pose.pt"
    p.write_bytes(b"")
    monkeypatch.setenv("BARRA_YOLO_POSE_WEIGHTS", str(p))
    assert UltralyticsBackend().weights == str(p)


def test_resolve_weights_prefers_local_stronger_weights(monkeypatch, tmp_path):
    import barra.pose.ultralytics_backend as ub
    monkeypatch.delenv("BARRA_YOLO_POSE_WEIGHTS", raising=False)
    monkeypatch.setattr(ub, "_ROOT", tmp_path)
    (tmp_path / "yolo11m-pose.pt").write_bytes(b"")
    (tmp_path / "yolo11s-pose.pt").write_bytes(b"")
    assert UltralyticsBackend().weights == str(tmp_path / "yolo11m-pose.pt")
