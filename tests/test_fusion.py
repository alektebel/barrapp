from __future__ import annotations

from barra.fusion import fuse_detection


def test_strong_geometry_wins_without_other_evidence():
    fused = fuse_detection({"exercise": "muscle_up", "confidence": 0.95})
    assert fused["exercise"] == "muscle_up"
    assert fused["status"] == "geometry-strong"


def test_model_and_nan_alias_agree_with_geometry():
    fused = fuse_detection(
        {"exercise": "pull_up", "confidence": 0.70},
        {"exercise": "pull-up", "confidence": 0.90, "marginToRunnerUp": 0.70},
        {"exercise": "chin_up"},
    )
    assert fused["exercise"] == "pull_up"
    assert fused["status"] == "geometry-model-agree"


def test_model_and_nan_majority_can_override_weak_geometry():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.70},
        {"exercise": "squat", "confidence": 0.90, "marginToRunnerUp": 0.70},
        {"exercise": "back-squat"},
    )
    assert fused["exercise"] == "squat"
    assert fused["status"] == "majority"


def test_model_cannot_override_strong_geometry_alone():
    fused = fuse_detection(
        {"exercise": "muscle_up", "confidence": 0.95},
        {"exercise": "pull_up", "confidence": 0.99, "marginToRunnerUp": 0.99},
    )
    assert fused["exercise"] == "muscle_up"
    assert fused["status"] == "geometry-reviewed"


def test_strong_model_can_override_weak_geometry():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.78},
        {"exercise": "squat", "confidence": 0.94, "marginToRunnerUp": 0.70},
    )
    assert fused["exercise"] == "squat"
    assert fused["status"] == "model-overrides-weak-geometry"


def test_unknown_geometry_accepts_strong_model():
    fused = fuse_detection(
        {"exercise": "unknown", "confidence": 0.0},
        {"exercise": "squat", "confidence": 0.94, "marginToRunnerUp": 0.80},
    )
    assert fused["exercise"] == "squat"
    assert fused["status"] == "unknown-model-accept"


def test_unknown_geometry_abstains_on_weak_model():
    fused = fuse_detection(
        {"exercise": "unknown", "confidence": 0.0},
        {"exercise": "squat", "confidence": 0.62, "marginToRunnerUp": 0.10},
    )
    assert fused["exercise"] == "unknown"
    assert fused["status"] == "abstain"
