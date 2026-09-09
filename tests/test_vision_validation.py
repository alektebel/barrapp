"""The vision pass cannot outrank a measurement: its replies are parsed by
schema, validated against the request, and dropped when they are not."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import vision  # noqa: E402
from barra.frames import Still, TechniqueArtifacts  # noqa: E402


def _art(tmp_path):
    frames = [
        Still(tmp_path / "f0.jpg", None, "rep", "window start", 0.0),
        Still(tmp_path / "f1.jpg", "r1", "setup", "start", 1.0),
        Still(tmp_path / "f2.jpg", "r1", "lifting", "mid-lift", 1.5),
        Still(tmp_path / "f3.jpg", "r1", "support", "top", 2.0),
        Still(tmp_path / "f4.jpg", "r3", "support", "top", 6.0),
    ]
    for s in frames:
        s.path.write_bytes(b"\xff\xd8jpeg")
    return TechniqueArtifacts(clip=None, frames=frames, selected_reps=["r1", "r3"])


def _report():
    return {
        "exercise": "pull_up",
        "detected": {"exercise": "pull_up", "reason": "shoulders never rise above the hands"},
        "variant": {"name": "unspecified", "source": "none"},
        "view": {"bin": "UNKNOWN", "knowable": False, "why": "torso too narrow"},
        "reps": [
            {"label": "r1", "startS": 1.0, "endS": 3.0,
             "phases": {"rep": [1.0, 3.0], "setup": [1.0, 1.1], "lifting": [1.0, 2.0],
                        "support": [1.9, 2.1], "lowering": [2.0, 3.0]},
             "assessments": [
                 {"errorId": "pull_up.incomplete_lockout", "status": "observed",
                  "evidence": {"primitive": "lockout_pct", "value": 70.0,
                               "threshold": 85.0, "comparison": "<", "unit": "%"}},
                 {"errorId": "pull_up.body_swing", "status": "unobservable",
                  "evidence": {}, "availability": {"reason": "tracking loss"}}]},
            {"label": "r2", "startS": 3.5, "endS": 5.0, "phases": {}, "assessments": []},
            {"label": "r3", "startS": 5.5, "endS": 7.0, "phases": {}, "assessments": []},
        ],
    }


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def test_json_object_is_found_under_a_fence_or_prose():
    assert vision.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert vision.parse_json_object('Sure. {"a": {"b": 2}} Hope that helps') == {"a": {"b": 2}}
    assert vision.parse_json_object("[1, 2]") is None
    assert vision.parse_json_object("no json here") is None
    assert vision.parse_json_object(None) is None


def test_count_is_read_by_schema_not_by_substring():
    assert vision.parse_count('{"reps": 7, "note": "sparse"}') == 7
    assert vision.parse_count('{"reps": 7.0}') == 7
    assert vision.parse_count("I count 3 or 4 reps") is None
    assert vision.parse_count('{"reps": "3"}') is None
    assert vision.parse_count('{"reps": true}') is None
    assert vision.parse_count('{"reps": 2.5}') is None
    assert vision.parse_count('{"reps": -1}') is None


def test_count_reconciliation_is_explicit_about_disagreement():
    agree = vision.reconcile_counts({"a": 5, "b": 5})
    assert agree["reps"] == 5 and agree["usable"]
    close = vision.reconcile_counts({"a": 5, "b": 6})
    assert close["reps"] == 5 and close["range"] == [5, 6] and close["usable"]
    apart = vision.reconcile_counts({"a": 3, "b": 8})
    assert apart["reps"] is None and not apart["usable"] and "disagree" in apart["agreement"]
    single = vision.reconcile_counts({"a": 4})
    assert single["reps"] == 4 and "single" in single["agreement"]
    assert vision.reconcile_counts({}) is None


def test_verdict_needs_one_unambiguous_word():
    assert vision.parse_verdict('{"verdict": "minor"}') == "minor"
    assert vision.parse_verdict("Overall: major.") == "major"
    assert vision.parse_verdict("not clean, minor issues") is None
    assert vision.parse_verdict('{"verdict": "great"}') is None
    assert vision.parse_verdict("") is None


# ---------------------------------------------------------------------------
# the request
# ---------------------------------------------------------------------------
def test_request_text_carries_the_evidence_and_the_stills(tmp_path):
    text = vision._user_text(_art(tmp_path), _report())
    assert "pull_up" in text and "unspecified" in text
    assert "r1: 1.0-3.0s" in text
    assert "pull_up.incomplete_lockout (lockout_pct=70.0 %, < 85.0)" in text
    assert "could not check: pull_up.body_swing (tracking loss)" in text
    assert "f3.jpg: r1, support, top, 2.00s" in text
    # Only the sampled reps are described; r2 was not shown.
    assert "r2:" not in text
    # The rule list is the registry's, by id.
    assert "- pull_up.incomplete_lockout [support]" in text


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def test_observations_must_reference_the_request(tmp_path):
    art, report = _art(tmp_path), _report()
    raw = [
        {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "phase": "support",
         "status": "observed", "frames": ["f3.jpg"], "description": "elbows stay bent"},
        {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "status": "Not observed",
         "frames": "f3.jpg"},                                    # normalised status
        {"errorId": "muscle_up.slow_transition", "rep": "r1", "status": "observed"},
        {"errorId": "pull_up.incomplete_lockout", "rep": "r9", "status": "observed"},
        {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "status": "likely"},
        {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "status": "observed",
         "frames": ["made_up.jpg"]},
        {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "status": "observed",
         "phase": "descent"},
        "not an object",
    ]
    kept, dropped = vision.validate_observations(raw, report, art)
    assert [o["status"] for o in kept] == ["observed", "not_observed"]
    assert kept[0]["source"] == vision.SOURCE_VISION
    assert kept[0]["name"] == "lockout" and kept[0]["frames"] == ["f3.jpg"]
    assert kept[1]["phase"] == "support"           # defaulted from the rule
    assert dropped == {"notAList": 0, "notAnObject": 1, "unknownError": 1,
                       "unknownRep": 1, "badStatus": 1, "unknownFrame": 1,
                       "unknownPhase": 1}


def test_observations_that_are_not_a_list_are_dropped_wholesale(tmp_path):
    kept, dropped = vision.validate_observations({"errorId": "x"}, _report(), _art(tmp_path))
    assert kept == [] and dropped["notAList"] == 1


def test_no_endpoint_means_no_note_and_no_call(monkeypatch, tmp_path):
    for k in ("BARRA_VISION_BASE_URL", "BARRA_VISION_API_KEY", "NAN_BASE_URL", "NAN_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    calls = []
    monkeypatch.setattr(vision, "_chat", lambda *a, **k: calls.append(a) or None)
    assert vision.technique_note(_art(tmp_path), _report()) is None
    assert vision.technique_second_opinion(_art(tmp_path)) is None
    assert calls == []


def test_note_keeps_only_validated_observations_and_flags_disagreement(monkeypatch, tmp_path):
    monkeypatch.setenv("BARRA_VISION_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("BARRA_VISION_API_KEY", "k")
    reply = json.dumps({
        "headline": "Bent at the top",
        "narrative": "You stop short of lockout.",
        "nextSession": "Film from the side.",
        "movement": {"label": "chin-up", "agreesWithGeometry": False},
        "observations": [
            {"errorId": "pull_up.incomplete_lockout", "rep": "r1", "status": "observed",
             "frames": ["f3.jpg"], "description": "elbows bent at the top"},
            {"errorId": "pull_up.incomplete_lockout", "rep": "r7", "status": "observed"},
        ],
    })
    monkeypatch.setattr(vision, "_chat", lambda *a, **k: reply)
    note = vision.technique_note(_art(tmp_path), _report())
    assert note["headline"] == "Bent at the top"
    assert len(note["visionObservations"]) == 1
    assert note["visionValidation"]["kept"] == 1
    assert note["visionValidation"]["invalid"] == 1
    assert note["visionMovement"]["review"] is True
    assert note["visionMovement"]["geometry"] == "pull_up"


def test_malformed_reply_degrades_to_no_note(monkeypatch, tmp_path):
    monkeypatch.setenv("BARRA_VISION_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("BARRA_VISION_API_KEY", "k")
    monkeypatch.setattr(vision, "_chat", lambda *a, **k: "I think it looks fine overall.")
    assert vision.technique_note(_art(tmp_path), _report()) is None
    monkeypatch.setattr(vision, "_chat", lambda *a, **k: '{"headline": "x", "narrative": ""}')
    assert vision.technique_note(_art(tmp_path), _report()) is None
