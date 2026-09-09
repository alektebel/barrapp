"""The fault layer, and the three ways it used to lie.

1. A squat routed into the bar classifier fired "dead hang" on every rep,
   because on a hip-origin track the shoulders are measured against the hips.
2. A measurement that did not exist counted as a healthy one, so "bent arms"
   could not fire at all.
3. Planar faults - knee valgus is frontal, a sagging hip line sagittal - fired
   from any camera angle, though docs/FINDINGS.md measured a 10-degree azimuth
   change outweighing a deliberately induced error.

Everything here is synthetic: no labels, no footage, only invariants that must
hold whatever the numbers turn out to be on real clips.
"""
from __future__ import annotations

import numpy as np
import pytest

from barra import schema as S
from barra.config import THRESHOLDS
from barra.evidence import (MEASURED, UNMEASURED, VIEW_BLOCKED, Evidence, View,
                            declared_view, rep_evidence)
from barra.faults_taxonomy import (all_fault_names, classify_faults,
                                   classify_failures)
from barra.movements import MOVEMENTS

FRONTAL = View(bin="FRONTAL", knowable=True, side="anterior", agreement=1.0,
               source="declared", why="test")
SAGITTAL = View(bin="SAGITTAL", knowable=True, side="anterior", agreement=1.0,
                source="declared", why="test")


# ---------------------------------------------------------------------------
# 2. A missing measurement is not a healthy one
# ---------------------------------------------------------------------------
def test_absent_measurement_does_not_fire_and_is_not_clean():
    ev = Evidence.from_values({"tempo_ratio": 1.0}, track="muscle_up")
    assert classify_faults("muscle_up", ev) == []
    assert "arms_straight_frac" not in ev.keys()          # never claimed
    assert ev.value("arms_straight_frac") is None


def test_nan_is_unmeasured_not_zero():
    ev = Evidence().add("swing", float("nan"))
    assert ev.get("swing").state == UNMEASURED
    assert ev.value("swing") is None
    assert ev.unmeasured() == ["swing"]


def test_bent_arms_can_actually_fire_now():
    """It could not before: the key was defaulted to 1.0 and never produced."""
    clean = Evidence.from_values({"top_elbow_deg": 175}, track="muscle_up")
    bent = Evidence.from_values({"top_elbow_deg": 120}, track="muscle_up")
    assert "bent arms" not in classify_failures("muscle_up", clean)
    assert "bent arms" in classify_failures("muscle_up", bent)


# ---------------------------------------------------------------------------
# 1. Bar faults belong to bar movements
# ---------------------------------------------------------------------------
def test_squat_does_not_inherit_the_bar_faults():
    """The hip-origin geometry that made these fire is still what it was."""
    hip_origin_reading = {"peak_height": 1.0, "start_depth": -1.0, "swing": 0.0,
                          "lockout_pct": 100.0, "hang_pct": -100.0}
    assert classify_failures("squat", hip_origin_reading) == []


def test_every_track_only_offers_faults_it_declares():
    from barra.faults_taxonomy import TRACK_FAILURES
    loud = {k: 999.0 for k in
            ("swing", "lockout_pct", "hang_pct", "tempo_ratio", "stalled_frac",
             "transition_s", "arms_straight_frac", "legs_straight_frac",
             "body_line_deg", "hip_pike_deg", "pistol_depth", "squat_depth",
             "travel", "knee_valgus", "heel_rise", "torso_lean", "turn_speed",
             "start_elbow_deg", "bottom_elbow_deg", "fast_ratio")}
    quiet = {k: -999.0 for k in loud}
    for track, declared in TRACK_FAILURES.items():
        for values in (loud, quiet):
            ev = Evidence.from_values(values, track=track, view=FRONTAL)
            fired = {f.name for f in classify_faults(track, ev)}
            assert fired <= set(declared), f"{track} fired {fired - set(declared)}"


def test_an_unknown_track_borrows_nothing():
    assert classify_failures("bench_press", {"hang_pct": -100.0}) == []


# ---------------------------------------------------------------------------
# 3. Planar faults need a plane
# ---------------------------------------------------------------------------
def test_planar_fault_is_blocked_when_the_view_is_unknown():
    values = {"knee_valgus": 0.9, "pistol_depth": 0.9}
    ev = Evidence.from_values(values, track="pistol_squat")
    assert ev.get("knee_valgus").state == VIEW_BLOCKED
    assert "knee valgus" not in classify_failures("pistol_squat", ev)
    assert ev.view_blocked() == ["knee_valgus"]
    # blocked is not the same as clean, and the record says which it is
    assert ev.unmeasured() == []


def test_planar_fault_fires_from_the_plane_it_lives_in():
    values = {"knee_valgus": 0.9, "pistol_depth": 0.9}
    ev = Evidence.from_values(values, track="pistol_squat", view=FRONTAL)
    assert ev.get("knee_valgus").state == MEASURED
    assert "knee valgus" in classify_failures("pistol_squat", ev)


def test_a_frontal_camera_cannot_see_a_sagittal_quantity():
    ev = Evidence.from_values({"hip_sag": 0.9}, track="push_up", view=FRONTAL)
    assert ev.get("hip_sag").state == VIEW_BLOCKED
    ev = Evidence.from_values({"hip_sag": 0.9}, track="push_up", view=SAGITTAL)
    assert "sagging hips" in classify_failures("push_up", ev)


def test_an_oblique_camera_supports_no_planar_fault_at_all():
    oblique = declared_view("OBLIQUE")
    assert oblique.knowable
    ev = Evidence.from_values({"knee_valgus": 0.9, "hip_sag": 0.9},
                              view=oblique)
    assert ev.view_blocked() == ["hip_sag", "knee_valgus"]


def test_a_declared_view_that_is_not_a_bin_is_not_believed():
    assert not declared_view("from the left a bit").knowable
    assert not declared_view(None).knowable


# ---------------------------------------------------------------------------
# A fired fault carries its own evidence
# ---------------------------------------------------------------------------
def test_a_fault_states_the_number_that_fired_it():
    ev = Evidence.from_values({"swing": 0.55}, track="muscle_up")
    fault, = classify_faults("muscle_up", ev)
    assert fault.name == "momentum"
    assert fault.primitive == "swing"
    assert fault.value == pytest.approx(0.55)
    assert fault.threshold == pytest.approx(THRESHOLDS.swing_torso)
    assert fault.comparison == ">"
    assert fault.as_dict()["unit"] == "torso"


def test_boundary_does_not_fire():
    """Comparisons are strict where the docstring says they are strict."""
    ev = Evidence.from_values({"swing": THRESHOLDS.swing_torso})
    assert classify_failures("muscle_up", ev) == []
    ev = Evidence.from_values({"lockout_pct": THRESHOLDS.lockout_min * 100})
    assert classify_failures("muscle_up", ev) == []


def test_fault_names_are_unique_across_tracks():
    names = all_fault_names()
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# The squat's own geometry
# ---------------------------------------------------------------------------
def _skeleton(frames: int = 60) -> np.ndarray:
    kp = np.zeros((frames, 17, 3))
    kp[..., 2] = 0.95
    return kp


def _squat_clip(depth: float, frames: int = 60) -> np.ndarray:
    """A standing figure that squats `depth` torso-lengths and stands back up.

    Image y grows downward. Torso is 100 px; the ankles never move.
    """
    kp = _skeleton(frames)
    t = np.linspace(0, np.pi, frames)
    drop = depth * 100.0 * np.sin(t)          # 0 at the ends, `depth` at the turn
    for side, x in (("left", -20.0), ("right", 20.0)):
        kp[:, S.KP_INDEX[f"{side}_ankle"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_ankle"], 1] = 400.0
        kp[:, S.KP_INDEX[f"{side}_knee"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_knee"], 1] = 300.0 + drop / 2
        kp[:, S.KP_INDEX[f"{side}_hip"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_hip"], 1] = 200.0 + drop
        kp[:, S.KP_INDEX[f"{side}_shoulder"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_shoulder"], 1] = 100.0 + drop
        kp[:, S.KP_INDEX[f"{side}_elbow"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_elbow"], 1] = 160.0 + drop
        kp[:, S.KP_INDEX[f"{side}_wrist"], 0] = x
        kp[:, S.KP_INDEX[f"{side}_wrist"], 1] = 220.0 + drop
    return kp


def _squat_evidence(kp: np.ndarray, view: View = SAGITTAL) -> Evidence:
    hip_y = kp[:, S.KP_INDEX["left_hip"], 1]
    signal = -hip_y / 100.0
    turn = int(np.argmin(signal))
    metrics = {"concentric_s": 1.0, "eccentric_s": 1.0, "tempo_ratio": 1.0,
               "total_s": 2.0}
    return rep_evidence(metrics, float("nan"), signal, 0, turn, len(kp) - 1,
                        30.0, MOVEMENTS["squat"], kp=kp, view=view)


def test_squat_depth_is_measured_over_the_ankles():
    deep = _squat_evidence(_squat_clip(0.9))
    shallow = _squat_evidence(_squat_clip(0.1))
    assert deep.value("squat_depth") > THRESHOLDS.squat_depth
    assert shallow.value("squat_depth") < THRESHOLDS.squat_depth
    assert "poor range of motion" not in classify_failures("squat", deep)
    assert "poor range of motion" in classify_failures("squat", shallow)


def test_squat_depth_survives_the_camera_moving_around_the_athlete():
    """Azimuth foreshortens x. Depth is vertical, so it must not move."""
    kp = _squat_clip(0.9)
    turned = kp.copy()
    turned[:, :, 0] *= 0.3                     # a much more frontal camera
    a = _squat_evidence(kp).value("squat_depth")
    b = _squat_evidence(turned).value("squat_depth")
    assert a == pytest.approx(b, rel=0.02)


def test_swing_is_not_measured_on_a_hip_origin_track():
    """It would be the hips' distance from the hips - a self-referential zero."""
    ev = _squat_evidence(_squat_clip(0.9))
    assert ev.get("swing").state == UNMEASURED
    assert "momentum" not in classify_failures("squat", ev)


def test_lockout_and_hang_need_hands_to_be_the_origin():
    ev = _squat_evidence(_squat_clip(0.9))
    assert ev.get("lockout_pct").state == UNMEASURED
    assert ev.get("hang_pct").state == UNMEASURED


def test_evidence_without_keypoints_measures_nothing_it_cannot_see():
    metrics = {"tempo_ratio": 1.0, "concentric_s": 1.0}
    ev = rep_evidence(metrics, 1.2, np.linspace(0, 1, 40), 0, 20, 39, 30.0,
                      MOVEMENTS["pull_up"], kp=None)
    for key in ("start_elbow_deg", "arms_straight_frac", "squat_depth",
                "knee_valgus", "hip_sag"):
        assert not ev.measured(key)
    assert "no active hang" not in classify_failures("pull_up", ev)
