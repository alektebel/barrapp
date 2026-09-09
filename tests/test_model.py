"""The first classification model trains, predicts, and is honest about load.

The model has no labelled-load corpus (the scraped set is bodyweight), so the
load head must admit that rather than invent a number. These tests check the
mechanics on fast synthetic data - no videos, no pose - and the honesty of the
load baseline, without pretending any real accuracy.
"""
from __future__ import annotations

import numpy as np

from barra.model import (FEATURE_NAMES, ExerciseModel, model_classify,
                         model_load, train_classifier, train_load,
                         vector_from_dict)


def _synthetic(n_per: int = 60, seed: int = 7) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    # Three separable classes distinguished by a few features.
    X, y = [], []
    centers = {
        "squat": {"hip_travel": 0.6, "split_ankle_heights": 0.0,
                  "hands_overhead_frac": 0.0, "body_line_deg": 5.0},
        "pull_up": {"hip_travel": 0.0, "split_ankle_heights": 0.0,
                    "hands_overhead_frac": 0.9, "body_line_deg": 5.0},
        "split_squat": {"hip_travel": 0.6, "split_ankle_heights": 0.4,
                        "hands_overhead_frac": 0.0, "body_line_deg": 5.0},
    }
    for cls, centre in centers.items():
        for _ in range(n_per):
            row = {name: 0.0 for name in FEATURE_NAMES}
            for name, val in centre.items():
                row[name] = val + rng.normal(0, 0.02)
            X.append([row[n] for n in FEATURE_NAMES])
            y.append(cls)
    return np.asarray(X), y


def test_train_and_predict():
    X, y = _synthetic()
    m = train_classifier(X, y, epochs=300)
    preds, _, _ = m.predict(X)
    acc = sum(a == b for a, b in zip(preds, y)) / len(y)
    assert acc >= 0.95, f"model should separate synthetic classes, got {acc:.2f}"


def test_probabilities_sum_to_one():
    X, _ = _synthetic()
    m = train_classifier(X, list(_synthetic()[1]))
    p = m.predict_proba(X[:5])
    np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-4)
    assert p.shape == (5, len(m.classes))


def test_deterministic():
    X, y = _synthetic()
    a = train_classifier(X, y, seed=42)
    b = train_classifier(X, y, seed=42)
    np.testing.assert_array_equal(a.w1, b.w1)
    np.testing.assert_array_equal(a.w2, b.w2)


def test_save_and_load_roundtrip(tmp_path):
    X, y = _synthetic()
    m = train_classifier(X, y)
    p = tmp_path / "model.npz"
    m.save(p)
    loaded = ExerciseModel.load(p)
    preds_l, _, _ = loaded.predict(X[:4])
    preds_m, _, _ = m.predict(X[:4])
    assert preds_l == preds_m
    assert loaded.classes == m.classes
    assert tuple(loaded.feature_names) == tuple(m.feature_names)


def test_vector_from_dict_fills_nan():
    f = {name: float("nan") for name in FEATURE_NAMES}
    v = vector_from_dict(f)
    assert v.shape == (len(FEATURE_NAMES),)
    assert np.all(np.isfinite(v))


def test_load_head_baseline_is_zero_and_honest():
    X, y = _synthetic()
    w, b, note = train_load(X, None)
    assert b == 0.0 and np.allclose(w, 0.0)
    assert "baseline" in note.lower()


def test_load_head_fits_when_labelled():
    X, y = _synthetic()
    ykg = [0.0] * len(y)
    ykg[:20] = [20.0] * 20
    w, b, note = train_load(X, ykg)
    assert "labelled" in note.lower()
    assert not np.allclose(w, 0.0)
    assert b != 0.0
