from __future__ import annotations

from barra.channels import Estimate, FAMILY_POSE, FAMILY_VISION
from barra.consensus import agree_identity, agree_reps, resolve


def test_agree_identity_canonical():
    assert agree_identity("pull_up", "pull-up") == "agree"
    assert agree_identity("dip", "squat") == "disagree"
    assert agree_identity("unknown", "dip") == "abstain"
    assert agree_identity("diamond_push_up", "push_up") == "partial"
    assert agree_identity("front_lever_raise", "pull_up") == "partial"


def test_agree_reps_tolerance():
    assert agree_reps(5, 6) == "agree"
    assert agree_reps(5, 9) == "disagree"


def test_resolve_needs_two_families():
    only_pose = [
        Estimate("dip", 0.8, "ok", {}, channel="I1", quantity="identity",
                 family=FAMILY_POSE),
    ]
    out = resolve(only_pose, "identity")
    assert out["status"] == "abstain"
    assert out["reason"] == "single_family"

    both = only_pose + [
        Estimate("dip", 0.7, "ok", {}, channel="I3", quantity="identity",
                 family=FAMILY_VISION),
    ]
    out2 = resolve(both, "identity")
    assert out2["status"] == "ok"
    assert out2["value"] == "dip"
