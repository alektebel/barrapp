"""The plan walks the graph, and the graph is the only source.

barra/planner.py answers "what do I do this week on the way to X". It may
not hold its own copy of the chain, the standards, or the names: if the
graph changes, the plan follows, or the plan is lying about what earns the
skill. These tests hold the derivations and the two tracks' shapes.
"""
from __future__ import annotations

import pytest

from barra.planner import TRACKS, build_plan
from barra.skills import SKILLS, ancestors


def test_unknown_track_is_rejected():
    with pytest.raises(ValueError):
        build_plan("mobility", "muscle_up")


def test_skill_plan_walks_the_graph():
    plan = build_plan("skill", "muscle_up")
    assert plan.track == "skill"
    assert plan.target == "muscle_up"
    assert plan.total_weeks == len(plan.weeks) > 0
    # Every week is a rung on the target's own prerequisite path.
    path = set(ancestors("muscle_up")) | {"muscle_up"}
    assert {w.skill_id for w in plan.weeks} <= path
    # The final week is the skill itself, and it is measurable.
    last = plan.weeks[-1]
    assert last.skill_id == "muscle_up"
    assert last.measurable is True
    # Its target quotes the graph's published standard, not an invented one.
    std = SKILLS["muscle_up"].standard
    assert std is not None
    assert str(std.reps) in last.target and str(std.quality) in last.target


def test_done_rungs_are_skipped():
    """Verified or claimed work is done, and so is everything behind it: the
    plan starts at the first rung that is not, and never re-asks for one."""
    full = build_plan("skill", "muscle_up")
    first = full.weeks[0].skill_id
    partial = build_plan("skill", "muscle_up", verified={first})
    assert partial.weeks[0].skill_id != first
    assert first not in {w.skill_id for w in partial.weeks}
    assert partial.weeks[-1].skill_id == "muscle_up"


def test_a_finished_target_plans_nothing():
    """Verifying the target itself retires the whole walk behind it - a plan
    that asks for the rungs below a measured muscle-up ignores its evidence."""
    plan = build_plan("skill", "muscle_up", verified={"muscle_up"})
    assert plan.weeks == ()
    assert plan.total_weeks == 0
    assert "already" in plan.note


def test_strength_plan_is_a_volume_build():
    plan = build_plan("strength", "push_up")
    assert plan.track == "strength"
    assert plan.weeks[-1].skill_id == "push_up"
    # Strength targets quote a rep standard too - but the walk is the
    # prerequisite path, not a chain of positions.
    assert plan.weeks[-1].measurable is True


def test_max_weeks_caps_the_walk():
    plan = build_plan("strength", "push_up", max_weeks=2)
    assert plan.total_weeks == len(plan.weeks) == 2
