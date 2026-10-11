from __future__ import annotations

from barra.fusion import fuse_detection

# These tests encode a policy that MEASUREMENT changed. The earlier version of
# this file asserted that strong geometry outranks everything - written when
# geometry was the only detector in the pipeline. On the 198-clip corpus,
# scored out of fold, geometry runs at 0.227 against the learned model's 0.576
# and the vision read's 0.907, and geometry's confidence is anti-correlated
# with being right (0.200 above the old 0.85 "strong" gate). So the assertions
# below are the opposite of the ones they replaced, on purpose.


def test_lone_geometry_still_answers_when_nothing_else_did():
    fused = fuse_detection({"exercise": "muscle_up", "confidence": 0.95})
    assert fused["exercise"] == "muscle_up"
    assert fused["status"] == "geometry-only"


def test_all_three_agreeing_is_a_majority():
    fused = fuse_detection(
        {"exercise": "pull_up", "confidence": 0.70},
        {"exercise": "pull-up", "confidence": 0.90, "marginToRunnerUp": 0.70},
        {"exercise": "chin_up"},
    )
    assert fused["exercise"] == "pull_up"
    assert fused["status"] == "majority"
    assert fused["confidence"] >= 0.86


def test_geometry_and_model_agreeing_is_named_as_such():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.55},
        {"exercise": "dip", "confidence": 0.60, "marginToRunnerUp": 0.20},
    )
    assert fused["exercise"] == "dip"
    assert fused["status"] == "geometry-model-agree"


def test_model_and_vision_outvote_geometry():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.70},
        {"exercise": "squat", "confidence": 0.90, "marginToRunnerUp": 0.70},
        {"exercise": "back-squat"},
    )
    assert fused["exercise"] == "squat"
    assert fused["status"] == "majority"


def test_model_outranks_geometry_however_confident_geometry_is():
    """The case that cost 45 clips: geometry's veto is gone."""
    fused = fuse_detection(
        {"exercise": "muscle_up", "confidence": 0.95},
        {"exercise": "pull_up", "confidence": 0.99, "marginToRunnerUp": 0.99},
    )
    assert fused["exercise"] == "pull_up"
    assert fused["status"] == "model-decides"


def test_vision_outranks_both_when_they_disagree_with_it_and_each_other():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.90},
        {"exercise": "squat", "confidence": 0.88, "marginToRunnerUp": 0.40},
        {"exercise": "muscle_up"},
    )
    assert fused["exercise"] == "muscle_up"
    assert fused["status"] == "vision-decides"


def test_unknown_geometry_accepts_a_middling_model():
    """A model at 0.62 is far better evidence than the abstention it used to
    produce: every band of its confidence beats geometry on this corpus."""
    fused = fuse_detection(
        {"exercise": "unknown", "confidence": 0.0},
        {"exercise": "squat", "confidence": 0.62, "marginToRunnerUp": 0.10},
    )
    assert fused["exercise"] == "squat"
    assert fused["status"] == "model-decides"


def test_geometry_answers_when_the_model_is_a_coin_flip():
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.40},
        {"exercise": "squat", "confidence": 0.12, "marginToRunnerUp": 0.01},
    )
    assert fused["exercise"] == "dip"
    assert fused["status"] == "geometry-only"


def test_abstains_when_nothing_usable_was_offered():
    fused = fuse_detection(
        {"exercise": "unknown", "confidence": 0.0},
        {"exercise": "squat", "confidence": 0.12, "marginToRunnerUp": 0.01},
    )
    assert fused["exercise"] == "unknown"
    assert fused["status"] == "abstain"


def test_a_label_outside_the_taxonomy_never_recurses():
    """`resolve` refusing a label used to bounce between `_known` and
    `_canonical` until the stack gave out - and the one caller wraps fusion in
    `except Exception`, so it read as "fusion unavailable" and the vote
    silently stopped happening."""
    fused = fuse_detection(
        {"exercise": "dip", "confidence": 0.40},
        {"exercise": "not_a_movement", "confidence": 0.99,
         "marginToRunnerUp": 0.9},
    )
    assert fused["exercise"] == "not_a_movement"
    assert fused["status"] == "model-decides"


def test_a_movement_with_no_profile_still_gets_named():
    """Six of the corpus's seventeen classes have no measurement profile.
    Dropping their votes left geometry to answer, at 3% accuracy on exactly
    those clips; naming them lets the pipeline say what it cannot measure."""
    fused = fuse_detection(
        {"exercise": "squat", "confidence": 0.90},
        {"exercise": "deadlift", "confidence": 0.80, "marginToRunnerUp": 0.30},
        {"exercise": "deadlift"},
    )
    assert fused["exercise"] == "deadlift"
    assert fused["status"] == "majority"


def test_an_abstention_is_not_a_vote():
    fused = fuse_detection(
        {"exercise": "unknown", "confidence": 0.0},
        {"exercise": "none", "confidence": 0.99, "marginToRunnerUp": 0.9},
        {"exercise": "n/a"},
    )
    assert fused["exercise"] == "unknown"
    assert fused["status"] == "abstain"
