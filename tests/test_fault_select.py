"""Clip-level fault selection: consensus gate and primary cue."""
from __future__ import annotations

from barra.config import THRESHOLDS
from barra.fault_select import clip_fault_counts, primary_from_assessments
from barra.rules import OBSERVED, NOT_OBSERVED, RULES, Assessment


def _assessment(error_id: str, status: str, value: float) -> Assessment:
    rule = next(r for r in RULES["pull_up"] if r.id == error_id)
    return Assessment(rule, status, value, "", None, None, None, "unspecified")


def test_clip_fault_counts_requires_consensus():
    reps = [
        {"failures": ["lockout", "control"]},
        {"failures": ["lockout"]},
        {"failures": ["stall"]},
    ]
    # Default gate is 2: lockout clears, control and stall do not.
    assert clip_fault_counts(reps) == {"lockout": 2}
    assert clip_fault_counts(reps, min_count=1) == {
        "lockout": 2, "control": 1, "stall": 1,
    }


def test_clip_fault_counts_relaxes_on_short_sets():
    reps = [{"failures": ["lockout"]}]
    # One-rep set: gate collapses to 1 so the only evidence is not deleted.
    assert clip_fault_counts(reps) == {"lockout": 1}
    assert THRESHOLDS.fault_min_reps >= 2


def _lockout_row(value: float) -> dict:
    """An assessment row for pull_up.incomplete_lockout, as a payload rep carries."""
    return _assessment("pull_up.incomplete_lockout", OBSERVED, value).as_dict()


def test_single_strong_lockout_is_kept():
    # The audit's reproduction (docs/AUDITORIA-TECNICA.md, finding 6): three
    # reps with `lockout` in only one produced an empty summary. A one-off now
    # survives the gate when its rep sat unmistakably past the threshold -
    # here (-27.6 - (-80)) / 27.6 ≈ 1.9 normalised thresholds past it.
    assert 0 < THRESHOLDS.fault_single_rep_exceedance
    strong = {"failures": ["lockout"], "assessments": [_lockout_row(-80.0)]}
    clean = {"failures": []}
    assert clip_fault_counts([clean, strong, clean]) == {"lockout": 1}


def test_weak_or_unmeasured_single_rep_lockout_is_dropped():
    # Barely over the line is pose-jitter territory, where the two-rep
    # consensus came from: (-27.6 - (-30)) / 27.6 ≈ 0.09, under the bar.
    # Without valid evidence on the rep there is nothing to weigh, so the
    # gate stays shut too.
    weak = {"failures": ["lockout"], "assessments": [_lockout_row(-30.0)]}
    unmeasured = {"failures": ["lockout"]}
    clean = {"failures": []}
    assert clip_fault_counts([clean, weak, clean]) == {}
    assert clip_fault_counts([clean, unmeasured, clean]) == {}


def test_primary_from_assessments_picks_largest_exceedance():
    # incomplete_lockout threshold is pull_up_lockout_pct (~-27.6), comparison <.
    # value -80 is further past than -40.
    mild = [
        _assessment("pull_up.incomplete_lockout", OBSERVED, -40.0),
        _assessment("pull_up.incomplete_hang", NOT_OBSERVED, 90.0),
    ]
    severe = [
        _assessment("pull_up.incomplete_lockout", OBSERVED, -80.0),
        _assessment("pull_up.incomplete_hang", OBSERVED, 10.0),
    ]
    primary = primary_from_assessments([mild, severe], min_count=2)
    assert primary is not None
    assert primary["errorId"] == "pull_up.incomplete_lockout"
    assert primary["observedReps"] == 2
    assert primary["exceedance"] > 0


def test_pull_up_lockout_is_not_the_muscle_up_bar():
    pu = next(r for r in RULES["pull_up"] if r.id == "pull_up.incomplete_lockout")
    mu = next(r for r in RULES["muscle_up"] if r.id == "muscle_up.incomplete_lockout")
    assert pu.threshold == THRESHOLDS.pull_up_lockout_pct
    assert mu.threshold == THRESHOLDS.lockout_min * 100
    assert pu.threshold != mu.threshold
