from __future__ import annotations

from barra.load import apply_declared_load, asks_load, refine_asks_load


def test_plain_dip_does_not_ask():
    out = asks_load(exercise="dip")
    assert out["asksLoad"] is False
    assert out["weightedExercise"] == "weighted_dip"


def test_declared_weighted_asks():
    out = asks_load(exercise="dip", declared="weighted_dip")
    assert out["asksLoad"] is True
    assert "declared:weighted_dip" in out["reasons"]


def test_vision_weighted_asks():
    out = asks_load(exercise="dip", vision_label="weighted_dip")
    assert out["asksLoad"] is True


def test_locate_prose_asks():
    out = asks_load(
        exercise="dip",
        locate={"exercise": "weighted dips with a belt",
                "description": "athlete dipping with a weight belt"},
    )
    assert out["asksLoad"] is True
    assert any("text" in r or "locate" in r for r in out["reasons"])


def test_recent_weighted_history_asks():
    out = asks_load(exercise="pull_up", recent={"weighted_pull_up": 3, "dip": 2})
    assert out["asksLoad"] is True
    assert out["weightedExercise"] == "weighted_pull_up"


def test_push_up_never_asks():
    out = asks_load(exercise="push_up", vision_label="weighted_dip",
                    locate={"description": "weighted"})
    assert out["asksLoad"] is False
    assert out["weightedExercise"] is None


def test_refine_upgrades_after_locate():
    result = {"exercise": "dip", "asksLoad": False, "loadKg": None}
    refined = refine_asks_load(
        result, {"exercise": "weighted parallel bar dips", "description": "belt"})
    assert refined["asksLoad"] is True
    assert refined["weightedExercise"] == "weighted_dip"


def test_apply_declared_load_stamps_kg():
    result = {
        "exercise": "dip",
        "asksLoad": True,
        "weightedExercise": "weighted_dip",
        "baseExercise": "dip",
        "detected": {"exercise": "dip", "label": "Dip"},
    }
    out = apply_declared_load(result, 20)
    assert out["loadKg"] == 20.0
    assert out["asksLoad"] is False
    assert out["declaredLoad"] is True
    assert out["skillClaim"] == "weighted_dip"
    assert "20" in out["clientLabel"]
