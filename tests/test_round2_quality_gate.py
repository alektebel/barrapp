import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "round2_quality_gate", ROOT / "scripts/round2_quality_gate.py")
gate = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(gate)


def _references():
    return {
        "WA0010": {
            "reviewMethod": "contact-sheet", "movement": "muscle_up", "reps": 2,
            "forbidden": [], "notReps": [],
        },
        "WA0017": {
            "reviewMethod": "contact-sheet", "movement": "unknown", "reps": 0,
            "forbidden": [], "notReps": [],
        },
        "WA0020": {
            "reviewMethod": "contact-sheet", "movement": "push_up", "reps": 19,
            "forbidden": [{"errorId": "push_up.lift_stall"}], "notReps": [],
        },
    }


def test_quality_gate_accepts_reviewed_output_and_ignores_unreviewed_details():
    result = gate.evaluate({
        "clip": "WA0020",
        "measurements": {"auto": {"exercise": "push_up", "n_reps": 19,
                                     "countStatus": "geometry",
                                     "failures": {}, "phases": []}},
    }, _references())
    assert result["status"] == "pass"


def test_quality_gate_rejects_wrong_auto_label_count_and_forbidden_fault():
    result = gate.evaluate({
        "clip": "WA0020",
        "measurements": {"auto": {"exercise": "deadlift", "n_reps": 0,
                                     "countStatus": "geometry",
                                     "failures": {"stall": 1}, "phases": []}},
    }, _references())
    assert result["status"] == "fail"
    assert len(result["failures"]) == 3


def test_quality_gate_marks_review_unavailable_as_a_gap_not_a_passed_label():
    refs = _references()
    refs["WA0014"] = {"reviewMethod": "contact-sheet", "movement": "muscle_up",
                      "reps": None, "forbidden": [], "notReps": []}
    result = gate.evaluate({"clip": "WA0014-30s", "measurements": {}}, refs)
    assert result["status"] == "incomplete"
    assert result["coverageGaps"]


def test_quality_gate_reads_server_payload_assessments():
    refs = _references()
    refs["WA0020"]["forbidden"] = [{"errorId": "push_up.lift_stall"}]
    result = gate.evaluate({
        "clip": "WA0020", "exercise": "push_up", "n_reps": 19,
        "countStatus": "geometry",
        "reps": [{"startS": 1.0, "endS": 2.0, "assessments": [
            {"errorId": "push_up.lift_stall", "status": "present"},
        ]}],
    }, refs)
    assert result["status"] == "fail"
    assert any("lift_stall" in failure for failure in result["failures"])


def test_quality_gate_uses_auto_fusion_abstention_as_unknown():
    result = gate.evaluate({
        "clip": "WA0017", "exercise": "auto", "n_reps": 0,
        "countStatus": "unmeasured",
        "detected": {"exercise": "split_squat", "fusion": {
            "exercise": "unknown", "status": "ultralytics-abstain-screen",
        }},
        "reps": [],
    }, _references())
    assert result["status"] == "pass"


def test_quality_gate_uses_report_filename_when_payload_has_no_clip(tmp_path):
    report = tmp_path / "WA0017-rtx-report.json"
    report.write_text('{"exercise":"unknown","n_reps":0,"reps":[]}')
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"clips":[{"file":"VID-WA0017.mp4",'
                        '"movement":"unknown","reps":0,'
                        '"reviewMethod":"contact-sheet"}]}')
    result = gate.run([report], manifest)
    assert result["passed"] is True
    assert result["results"][0]["clip"] == "WA0017"


def test_quality_gate_translates_cropped_intervals_to_source_timestamps():
    refs = _references()
    refs["WA0014"] = {
        "reviewMethod": "contact-sheet", "movement": "muscle_up", "reps": None,
        "forbidden": [], "notReps": [{"intervalS": [22.61, 25.16]}],
    }
    result = gate.evaluate({
        "clip": "WA0014-window-10.4-30s", "sourceOffsetS": 10.4,
        "exercise": "muscle_up", "n_reps": 1,
        "reps": [{"startS": 12.4, "endS": 14.7}],
    }, refs)
    assert result["status"] == "fail"
    assert any("[22.61, 25.16]" in failure for failure in result["failures"])


def test_quality_gate_rejects_invalid_source_offset():
    result = gate.evaluate({"clip": "WA0014", "sourceOffsetS": float("nan")},
                           _references())
    assert result["status"] == "fail"
    assert result["failures"] == ["invalid sourceOffsetS"]


def test_quality_gate_uses_reviewed_source_window_count():
    refs = _references()
    refs["WA0014"] = {
        "reviewMethod": "unreviewed", "movement": "muscle_up", "reps": None,
        "forbidden": [], "notReps": [{"intervalS": [0.0, 30.0]}],
        "windows": [{"intervalS": [0.0, 30.0], "movement": "muscle_up",
                     "reps": 0, "reviewMethod": "contact-sheet"}],
    }
    result = gate.evaluate({
        "clip": "WA0014-first30s", "sourceOffsetS": 0.0,
        "sourceWindowS": [0.0, 29.9667],
        "exercise": "muscle_up", "n_reps": 0, "countStatus": "geometry", "reps": [],
    }, refs)
    assert result["status"] == "pass"


def test_quality_gate_rejects_false_or_unmeasured_reviewed_window_count():
    refs = _references()
    refs["WA0014"] = {
        "reviewMethod": "unreviewed", "movement": "muscle_up", "reps": None,
        "forbidden": [], "notReps": [{"intervalS": [0.0, 30.0]}],
        "windows": [{"intervalS": [0.0, 30.0], "movement": "muscle_up",
                     "reps": 0, "reviewMethod": "contact-sheet"}],
    }
    for count in (1, None):
        result = gate.evaluate({
            "clip": "WA0014-first30s", "sourceOffsetS": 0.0,
            "sourceWindowS": [0.0, 29.9667],
            "exercise": "muscle_up", "n_reps": count,
            "countStatus": "unmeasured" if count is None else "geometry",
            "reps": [],
        }, refs)
    assert result["status"] == "fail"
    assert any(failure.startswith("reps ") for failure in result["failures"])
    if count is None:
        assert any(failure.startswith("count status ") for failure in result["failures"])


def test_quality_gate_rejects_inconsistent_source_window_offset():
    result = gate.evaluate({
        "clip": "WA0014-window", "sourceOffsetS": 10.4,
        "sourceWindowS": [0.0, 30.0],
    }, _references())
    assert result["status"] == "fail"
    assert result["failures"] == ["invalid sourceWindowS"]
