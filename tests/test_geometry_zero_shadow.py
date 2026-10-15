from barra.geometry_zero_shadow import evaluate_zero_candidate


def base_row():
    return {
        "clip": "WA0014",
        "movement": "muscle_up",
        "reported_count_status": "unmeasured",
        "reported_count": 0,
        "accepted_geometry_reps": 0,
        "active_span_coverage": [
            {"at_seconds": [1, 4], "observed_frames": 90, "frames": 100,
             "observed_frac": 0.9},
        ],
        "span_amplitudes": [{"at_seconds": [1, 4], "amplitude": 0.3}],
        "candidate_turnarounds": [2.5],
        "rejections": [{"what": "candidate at 2.5s",
                        "reason": "the rest position is not a hang",
                        "evidence": {"shoulders_above_hands_at_rest": 0.61,
                                     "max_above": 0.3}}],
    }


def test_well_observed_zero_with_explicit_physical_rejection_is_shadow_candidate():
    result = evaluate_zero_candidate(base_row())
    assert result["disposition"] == "candidate_geometry_zero"
    assert result["count"] == 0
    assert result["countStatus"] == "unmeasured"
    assert result["measured"] is False


def test_positive_count_is_never_a_zero_candidate():
    row = base_row() | {"reported_count": 2, "accepted_geometry_reps": 2}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_accepted_reps"


def test_unknown_movement_abstains():
    row = base_row() | {"movement": "auto"}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_unknown_movement"


def test_unsupported_movement_abstains():
    row = base_row() | {"movement": "not_a_movement"}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_unknown_movement"


def test_inadequate_coverage_abstains_at_threshold():
    row = base_row()
    row["active_span_coverage"][0]["observed_frames"] = 89
    row["active_span_coverage"][0]["observed_frac"] = 0.89
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_inadequate_coverage"


def test_missing_active_span_abstains():
    row = base_row() | {"active_span_coverage": []}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_no_active_spans"


def test_turnaround_without_physical_rejection_abstains():
    row = base_row() | {"rejections": []}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_unaccounted_turnaround"


def test_no_turnarounds_abstains():
    row = base_row() | {"candidate_turnarounds": []}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_no_turnarounds"


def test_each_turnaround_needs_its_own_physical_rejection():
    row = base_row() | {"candidate_turnarounds": [2.5, 3.1]}
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_unaccounted_turnaround"


def test_invalid_coverage_values_fail_closed():
    row = base_row()
    row["active_span_coverage"][0]["observed_frac"] = float("nan")
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_invalid_evidence"


def test_span_amplitude_must_refer_to_same_interval():
    row = base_row()
    row["span_amplitudes"][0]["at_seconds"] = [5, 8]
    assert evaluate_zero_candidate(row)["disposition"] == "abstain_invalid_evidence"


def test_invalid_threshold_is_rejected():
    try:
        evaluate_zero_candidate(base_row(), min_observed_frac=1.1)
    except ValueError as exc:
        assert "min_observed_frac" in str(exc)
    else:
        raise AssertionError("invalid observed-fraction threshold was accepted")
