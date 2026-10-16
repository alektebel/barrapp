"""The eval layer: golden grading, regression gate, reference check.

These test the graders against payloads built to exercise each registry
(forbidden, phaseScoped, notReps, unobservable, movement, repCount), the
gate's tolerance semantics (drop blocks, improve never blocks, denominator
drift is informational, no-baseline is advisory), and the deterministic
hallucination check on the prose. The LLM judge's network path is not
tested here: without a key it must degrade to the reference check, and
that degradation is what is asserted.
"""
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.eval.golden import grade_payload, grade_run, golden_metrics  # noqa: E402
from barra.eval.gate import compare_to_baseline  # noqa: E402
from barra.eval.perf import timing_summary  # noqa: E402
from barra.eval.judge import reference_check, judge_writeup  # noqa: E402

MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"


def _payload(exercise, n_reps, faults=(), assessments=(), starts=None):
    reps = []
    for i in range(n_reps):
        reps.append({"label": f"r{i + 1}", "startS": (starts or [1.0, 5.0])[i % 2],
                     "endS": (starts or [1.0, 5.0])[i % 2] + 3,
                     "faults": list(faults), "assessments": list(assessments)})
    return {"exercise": exercise, "detected": {"exercise": exercise},
            "n_reps": n_reps, "reps": reps}


# The manifest labels VID-20260827-WA0010.mp4 as muscle_up, 2 reps.
GOLDEN_FILE = "VID-20260827-WA0010"


def _manifest():
    return json.loads(MANIFEST.read_text())


def test_manifest_is_loadable_and_reports_denominators():
    m = golden_metrics(MANIFEST)
    assert m["clips"] == 8 and m["reviewedClips"] >= 1


def test_correct_payload_passes_every_check():
    g = grade_payload(GOLDEN_FILE, _payload("muscle_up", 2), _manifest())
    assert g.graded
    assert g.failed() == []


def test_wrong_movement_and_count_fail_with_both_numbers_in_the_row():
    g = grade_payload(GOLDEN_FILE, _payload("dip", 5), _manifest())
    kinds = {c["check"]: c for c in g.checks}
    assert kinds["movement"]["ok"] is False
    assert kinds["movement"]["detected"] == "dip"
    assert kinds["movement"]["reviewed"] == "muscle_up"
    assert kinds["repCount"]["ok"] is False


def test_forbidden_fault_firing_is_a_failure():
    manifest = {"clips": [{"file": "synth.mp4", "movement": "pull_up", "reps": 2,
                           "forbidden": [{"errorId": "pull_up.incomplete_lockout",
                                          "why": "test"}]}]}
    g = grade_payload("synth", _payload(
        "pull_up", 2,
        faults=[{"errorId": "pull_up.incomplete_lockout"}]), manifest)
    forb = [c for c in g.checks if c["check"] == "forbidden"]
    assert forb and not forb[0]["ok"] and forb[0]["firedOn"] == ["r1", "r2"]
    # and passes when it does not fire
    g2 = grade_payload("synth", _payload("pull_up", 2), manifest)
    assert next(c for c in g2.checks if c["check"] == "forbidden")["ok"] is True


def test_phase_scoped_check_outside_phase_or_window_fails():
    m = _manifest()
    label = next(c for c in m["clips"] if c["file"] == f"{GOLDEN_FILE}.mp4")
    ps = label["phaseScoped"][0]           # support phase, maxWindowS 0.5
    outside = [{"errorId": ps["errorId"], "status": "observed",
                "phase": "hang", "intervalS": [1.0, 1.1]}]
    g = grade_payload(GOLDEN_FILE, _payload("muscle_up", 2, assessments=outside), m)
    assert any(c["check"] == "phaseScoped" and not c["ok"] for c in g.checks)
    # same check inside the phase and window passes
    inside = [{"errorId": ps["errorId"], "status": "observed",
               "phase": ps["phase"], "intervalS": [1.0, 1.3]}]
    g2 = grade_payload(GOLDEN_FILE, _payload("muscle_up", 2, assessments=inside), m)
    row = next(c for c in g2.checks if c["check"] == "phaseScoped")
    assert row["ok"] is True


def test_error_payload_on_reviewed_clip_fails_closed():
    g = grade_payload(GOLDEN_FILE, {"error": "boom"}, _manifest())
    assert not g.graded and g.why.startswith("payload errored")


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
def _grade(rollup, all_passed=True, graded=8):
    return {"rollup": rollup, "allPassed": all_passed, "gradedClips": graded}


def test_gate_blocks_on_drop_past_tolerance_and_on_any_zero_tol_drop():
    baseline = _grade({"movement": {"pass": 8, "fail": 0, "total": 8, "rate": 1.0},
                       "forbidden": {"pass": 4, "fail": 0, "total": 4, "rate": 1.0}})
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "grade.json"
        p.write_text(json.dumps(baseline))
        # movement drops 0.125 > 0.05 tolerance
        r = compare_to_baseline(
            _grade({"movement": {"pass": 7, "fail": 1, "total": 8, "rate": 0.875},
                    "forbidden": {"pass": 4, "fail": 0, "total": 4, "rate": 1.0}}), p)
        assert r.blocked and any("movement" in s for s in r.reasons)
        # zero-tolerance metric drops at all
        r2 = compare_to_baseline(
            _grade({"movement": {"pass": 8, "fail": 0, "total": 8, "rate": 1.0},
                    "forbidden": {"pass": 3, "fail": 1, "total": 4, "rate": 0.75}}), p)
        assert r2.blocked and any("forbidden" in s for s in r2.reasons)


def test_gate_never_blocks_on_improvement_or_denominator_drift():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "grade.json"
        p.write_text(json.dumps(_grade(
            {"movement": {"pass": 7, "fail": 1, "total": 8, "rate": 0.875}})))
        r = compare_to_baseline(
            _grade({"movement": {"pass": 8, "fail": 0, "total": 8, "rate": 1.0}},
                   graded=6), p)
        assert not r.blocked
        assert any(m.get("metric") == "gradedClips"
                   and m.get("note") == "informational" for m in r.metrics)


def test_gate_flags_allPassed_regression():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "grade.json"
        p.write_text(json.dumps(_grade({}, all_passed=True)))
        r = compare_to_baseline(_grade({}, all_passed=False), p)
        assert r.blocked and any("allPassed" in s for s in r.reasons)


def test_gate_without_baseline_is_advisory_not_block(tmp_path):
    r = compare_to_baseline(_grade({}), tmp_path / "missing.json")
    assert not r.blocked
    assert any("baseline" in s for s in r.reasons)


# ---------------------------------------------------------------------------
# reference check (hallucinated numbers)
# ---------------------------------------------------------------------------
def _prose_payload():
    return {"n_reps": 2, "sessionScore": 63, "duration_s": 15.29,
            "reps": [{"label": "r1", "score": 61, "startS": 1.0, "endS": 4.0,
                      "transition_s": 0.4, "concentric_s": 1.2},
                     {"label": "r2", "score": 65, "startS": 5.0, "endS": 8.4,
                      "transition_s": 0.5, "concentric_s": 1.4}]}


def test_reference_check_catches_invented_numbers():
    prose = {"headline": "2 reps, session score 63",
             "narrative": "Your first rep scored 61.",
             "nextSession": "Try for 7 reps next set."}   # 7 invented
    ref = reference_check(_prose_payload(), prose)
    assert not ref["ok"]
    assert ref["invented"] == [{"number": "7", "where": "nextSession"}]


def test_reference_check_passes_faithful_prose():
    prose = {"headline": "2 clean-ish reps",
             "narrative": "Rep scores 61 and 65; transitions 0.4s and 0.5s.",
             "nextSession": "Film the same angle."}
    ref = reference_check(_prose_payload(), prose)
    assert ref["ok"], ref["invented"]
    assert ref["quoted"] >= 4


def test_judge_degrades_to_reference_check_without_endpoint():
    prose = {"headline": "2 reps", "narrative": "", "nextSession": ""}
    out = judge_writeup(_prose_payload(), prose)
    assert out["judged"] is False or out.get("verdict") in (None, "pass", "borderline", "fail")
    assert "reference" in out
    # and the deterministic fail path fires even with no endpoint
    bad = {"headline": "you did 11 reps", "narrative": "", "nextSession": ""}
    out2 = judge_writeup(_prose_payload(), bad)
    assert out2["verdict"] == "fail"
    assert not out2["reference"]["ok"]


def test_grade_run_reports_ungraded_and_denominators():
    results = {GOLDEN_FILE: _payload("muscle_up", 2),
               "no_such_clip": {"error": "not real"}}
    g = grade_run(results, MANIFEST)
    assert g["gradedClips"] == 1
    assert g["ungraded"][0]["clip"] == "no_such_clip"
    assert g["allPassed"] is True
    assert g["rollup"]["movement"]["total"] == 1


def test_timing_summary_reports_distribution_and_slowest():
    records = [
        {"clip": "a.mp4", "wallS": 1.0, "analyzeS": 0.8, "poseSource": "cache"},
        {"clip": "b.mp4", "wallS": 2.0, "analyzeS": 1.5, "poseSource": "cache"},
        {"clip": "c.mp4", "wallS": 10.0, "analyzeS": 9.0, "poseSource": "mediapipe"},
        {"clip": "d.mp4", "wallS": 0.0, "error": "boom"},
    ]
    p = timing_summary(records)
    assert p["okClips"] == 3 and p["failedClips"] == [{"clip": "d.mp4", "error": "boom"}]
    assert p["wallS"]["total"] == 13.0
    assert p["wallS"]["median"] == 2.0
    assert p["wallS"]["max"] == 10.0
    assert p["slowest"][0]["clip"] == "c.mp4"
    assert p["byPoseSource"]["cache"]["clips"] == 2
    assert abs(p["poseS"]["mean"] - 0.567) < 0.001


def test_timing_summary_empty_and_all_failed():
    p = timing_summary([])
    assert p["okClips"] == 0 and p["wallS"]["mean"] is None
    p2 = timing_summary([{"clip": "x", "wallS": 0.0, "error": "dead"}])
    assert p2["okClips"] == 0 and p2["failedClips"][0]["clip"] == "x"
