"""Knee valgus keeps its direction.

`_knee_valgus` used to take the absolute sideways offset of the knee from the
hip-ankle line, so a knee pushed OUT by 0.4 torso-lengths read the same as a
knee caving IN by 0.4 - and a lateral drift was labelled "knee valgus". The
measure is now signed along each leg's own medial direction (from its hip
toward the opposite hip): positive = medial, negative = lateral.
"""
from __future__ import annotations

import numpy as np
import pytest

from barra import schema as S
from barra.config import THRESHOLDS
from barra.evidence import Evidence, _knee_valgus
from barra.movements import robust_torso
from barra.rules import NOT_OBSERVED, OBSERVED, assess

N = 20


def _frontal(left_dx: float, right_dx: float, mirrored: bool = False,
             hip_gap: float = 0.2):
    """A frontal standing pose. `*_dx` is the knee's offset from the hip-ankle
    line, in torso-lengths, POSITIVE = toward the body's midline (medial).
    `mirrored` swaps which side of the image each leg is on (the person
    facing away from the camera), which must not change the answer."""
    kp = np.zeros((N, len(S.COCO17), 3))
    kp[:, :, 2] = 1.0

    def put(name, x, y):
        kp[:, S.KP_INDEX[name], 0] = x
        kp[:, S.KP_INDEX[name], 1] = y

    cx = 0.5
    sign = -1.0 if mirrored else 1.0
    lx, rx = cx + sign * hip_gap / 2, cx - sign * hip_gap / 2   # image x of each leg
    put("left_shoulder", lx, 0.2); put("right_shoulder", rx, 0.2)
    put("left_hip", lx, 0.5); put("right_hip", rx, 0.5)
    torso = robust_torso(kp)
    # Medial for the left leg is toward the right hip: along (rx - lx).
    for side, x, other, dx in (("left", lx, rx, left_dx), ("right", rx, lx, right_dx)):
        toward_mid = np.sign(other - x)
        put(f"{side}_ankle", x, 0.95)
        put(f"{side}_knee", x + toward_mid * dx * torso, 0.72)
    return kp, torso


def _val(kp, torso):
    return _knee_valgus(kp, torso, slice(0, N))


@pytest.mark.parametrize("mirrored", [False, True])
def test_medial_drift_is_positive_and_reads_the_offset(mirrored):
    kp, torso = _frontal(0.4, 0.4, mirrored)
    assert _val(kp, torso) == pytest.approx(0.4, abs=1e-6)


@pytest.mark.parametrize("mirrored", [False, True])
def test_lateral_drift_is_negative_not_valgus(mirrored):
    kp, torso = _frontal(-0.4, -0.4, mirrored)
    v = _val(kp, torso)
    assert v == pytest.approx(-0.4, abs=1e-6)
    assert v < THRESHOLDS.pistol_valgus


def test_neutral_alignment_is_zero():
    kp, torso = _frontal(0.0, 0.0)
    assert _val(kp, torso) == pytest.approx(0.0, abs=1e-6)


def test_each_leg_is_resolved_against_its_own_side():
    # Left knee caves in, right knee flares out: the caving leg is the answer.
    kp, torso = _frontal(0.4, -0.4)
    assert _val(kp, torso) == pytest.approx(0.4, abs=1e-6)
    kp, torso = _frontal(-0.4, 0.4)
    assert _val(kp, torso) == pytest.approx(0.4, abs=1e-6)


def test_side_on_hips_give_no_direction_so_no_measurement():
    kp, torso = _frontal(0.4, 0.4, hip_gap=0.0)
    assert np.isnan(_val(kp, torso))


def _fires(value: float) -> str:
    ev = Evidence("squat")
    ev.add("knee_valgus", value, phase="rep", window=(0, 90), coverage=1.0)
    a = next(a for a in assess("squat", ev) if a.rule.id == "squat.knee_medial_drift")
    return a.status


def test_only_medial_drift_fires_the_valgus_rule():
    assert _fires(0.4) == OBSERVED
    assert _fires(-0.4) == NOT_OBSERVED
    assert _fires(0.0) == NOT_OBSERVED
