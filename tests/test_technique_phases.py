"""Regressions for phase confusion found while replaying the sample videos."""
import numpy as np
import pytest

from barra.evidence import _stalled_frac, rep_evidence
from barra.faults_taxonomy import classify_failures
from barra.metrics import rep_metrics
from barra.movements import MOVEMENTS


def skeleton(n=91):
    from barra.schema import KP_INDEX as I
    kp = np.zeros((n, 17, 3))
    kp[..., 2] = .95
    for side, x in [('left', 100), ('right', 180)]:
        for part, y in [('shoulder', 200), ('elbow', 250), ('wrist', 300),
                        ('hip', 320), ('knee', 420), ('ankle', 520)]:
            kp[:, I[f'{side}_{part}'], :2] = (x, y)
    return kp


@pytest.mark.parametrize('name', ['push_up', 'dip', 'squat', 'pistol_squat'])
def test_lowering_first_is_eccentric(name):
    m = rep_metrics(skeleton(), 0, 60, 90, 30, MOVEMENTS[name]).values
    assert m['eccentric_s'] == 2
    assert m['concentric_s'] == 1
    assert m['tempo_ratio'] == 2


def test_smooth_turnarounds_are_not_stalls_but_mid_rep_pauses_are():
    smooth = .5 - .5 * np.cos(np.linspace(0, np.pi, 61))
    assert _stalled_frac(smooth, 0, 60, .2) == 0
    paused = np.r_[np.linspace(0, .5, 21), np.full(20, .5), np.linspace(.5, 1, 21)]
    assert _stalled_frac(paused, 0, len(paused)-1, .2) > .2


def test_muscle_up_bent_arms_is_a_top_phase_check():
    from barra.schema import KP_INDEX as I
    kp = skeleton()
    # Bent during the pull, straight at top: expected movement, not a fault.
    for side in ('left', 'right'):
        kp[:, I[f'{side}_elbow'], 0] += 55
        kp[42:49, I[f'{side}_elbow'], 0] -= 55
    ev = rep_evidence({}, 1, np.sin(np.linspace(0,np.pi,91)), 0,45,90,30,
                      MOVEMENTS['muscle_up'], kp=kp)
    assert ev.value('arms_straight_frac') < .5
    assert 'bent arms' not in classify_failures('muscle_up', ev)
    for side in ('left', 'right'):
        kp[42:49, I[f'{side}_elbow'], 0] += 55
    bent = rep_evidence({}, 1, np.sin(np.linspace(0,np.pi,91)), 0,45,90,30,
                        MOVEMENTS['muscle_up'], kp=kp)
    assert 'bent arms' in classify_failures('muscle_up', bent)


def test_descending_stall_uses_the_return_ascent():
    sig = np.r_[np.linspace(0,1,31), np.linspace(1,.5,15),
                np.full(20,.5),np.linspace(.5,0,25)]
    ev = rep_evidence({}, 1, sig, 0,30,90,30,MOVEMENTS['push_up'])
    assert ev.value('stalled_frac') > .2


def test_rescue_cannot_bypass_the_fixed_hand_requirement():
    from barra.ingest import rescue_reps
    from barra.schema import KP_INDEX as I
    kp = skeleton(300)
    # A hang: the hands overhead. The default skeleton has the wrists below
    # the shoulders (a support), and a pull-up that rests with the shoulders
    # above the hands is rejected for that reason alone - see
    # test_a_rep_of_a_hanging_movement_must_rest_in_a_hang.
    for side in ('left', 'right'):
        kp[:, I[f'{side}_wrist'], 1] = 100
        kp[:, I[f'{side}_elbow'], 1] = 150
    t = np.arange(300)/30
    pulse = np.zeros(300)
    for at in (1,4,7):
        m=(t>=at)&(t<=at+1.5)
        pulse[m]=100*np.sin(np.pi*(t[m]-at)/1.5)
    for side in ('left','right'):
        for part in ('shoulder','elbow','hip','knee','ankle'):
            kp[:,I[f'{side}_{part}'],1]-=pulse
    assert rescue_reps(kp,30,MOVEMENTS['pull_up'])[0]
    moving=kp.copy()
    moving[:,:,:2] += np.stack([120*t,np.zeros(300)],axis=1)[:,None,:]
    assert rescue_reps(moving,30,MOVEMENTS['pull_up'])[0] == []
