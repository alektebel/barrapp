import pytest

from barra.fusion import fuse_detection
from barra.movements import resolve, resolve_family

IN = {
    "barbell_back_squat": "squat",
    "front_squat": "squat",
    "ring_muscle_up": "muscle_up",
    "superman_dip_(straight_bar_dip_with_legs_extended)": "dip",
    "decline_push_up": "push_up",
    "pistol_squat_(assisted_with_resistance_band,_on_bench)": "pistol_squat",
    "lunge": "split_squat",
    "split_squat": "split_squat",
    "bulgarian_split_squat": "bulgarian_split_squat",
    "narrow_grip_push_up": "push_up",
    "weighted_chin_up": "pull_up",
    "hanging_leg_raise": "knee_raise",
    "toes_to_bar": "knee_raise",
    "straddle_planche": "planche",
}
OUT = ["lateral_lunge", "front_splits_stretch", "dumbbell_front_raise",
       "dumbbell_step_up", "barbell_deadlift", "handstand_kick_up",
       "back_lever", "deadlift", "bench_press", "human_flag", "handstand",
       "", None]


@pytest.mark.parametrize("label,family", IN.items())
def test_family_in(label, family):
    assert resolve_family(label).name == family


@pytest.mark.parametrize("label", OUT)
def test_family_out(label):
    assert resolve_family(label) is None


def test_separators_are_alike():
    for a in ("front_squat", "front-squat", "front squat", "Front-Squat"):
        assert resolve(a).name == "squat"
    assert resolve("pull-up").name == resolve("pull_up").name == "pull_up"
    assert resolve("muscle up").name == "muscle_up"


def test_resolve_stays_strict():
    with pytest.raises(SystemExit):
        resolve("ring_muscle_up")


def test_fusion_vision_family_agrees_with_geometry():
    out = fuse_detection({"exercise": "muscle_up"}, None, nan_label="ring_muscle_up")
    assert out["exercise"] == "muscle_up"
