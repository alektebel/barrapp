"""The exercise catalogue is sound, and honest about what it measures.

A catalogue row is data, but it is data the app teaches from, so the same
discipline that guards the measurement core guards it: a row that claims to be
measurable must name a real movement with real, owned fault rules, a row that
is not must carry no ruleId, and a weighted variant must name a real base.
"""
from __future__ import annotations

from barra.exercises import (all_exercises, get, measurable, validate,
                             weighted_variants)


def test_catalogue_is_sound():
    assert validate() == []


def test_reaches_20_gym_exercises():
    core = [e for e in all_exercises() if not e.weighted]
    # 20 gym exercises in the catalogue (plus weighted variants).
    assert len(core) >= 20


def test_every_row_has_five_errors():
    for e in all_exercises():
        assert len(e.errors) == 5, e.id


def test_bulgarian_split_squat_present_and_measurable():
    b = get("bulgarian_split_squat")
    assert b is not None
    assert b.measurable
    assert len(b.rule_ids()) == 5
    # every rule is owned by the movement itself
    for rid in b.rule_ids():
        assert rid.startswith("bulgarian_split_squat.")


def test_weighted_calisthenics_are_catalogged_and_honest():
    w = weighted_variants()
    assert w, "weighted calisthenics should be present"
    for e in w:
        assert e.weighted
        assert e.base_of
        assert not e.measurable, "barra cannot see added load, so weighted must be catalog-only"
        assert e.rule_ids() == [], "a weighted row must not claim a measured rule"


def test_measurable_rows_are_known_movements():
    for e in measurable():
        from barra.movements import MOVEMENTS
        assert e.id in MOVEMENTS, e.id


def test_lookup_by_language_name():
    assert get("Sentadilla b\u00falgara") is not None
    assert get("sentadilla_bulgara") is not None
