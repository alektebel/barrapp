"""The evaluation runner and the reviewed manifest it scores against."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_technique_pipeline as run  # noqa: E402
from barra.movements import MOVEMENTS  # noqa: E402
from barra.rules import all_rule_ids  # noqa: E402

MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"


def _payload(exercise, reps, faults=(), assessments=()):
    rows = []
    for i, (a, t, b) in enumerate(reps):
        rows.append({"label": f"r{i + 1}", "startS": a, "turnS": t, "endS": b,
                     "failures": [f["name"] for f in faults],
                     "faults": list(faults), "assessments": list(assessments)})
    return {"exercise": exercise, "detected": {"exercise": exercise},
            "n_reps": len(rows), "reps": rows, "sessionScore": 50,
            "variant": {"name": "unspecified"}, "measurementVersion": 2}


def test_manifest_is_reviewed_and_speaks_the_registry_language():
    m = json.loads(MANIFEST.read_text())
    assert m["schema"] == 1 and m["version"]
    ids = set(all_rule_ids())
    files = [c["file"] for c in m["clips"]]
    assert len(files) == len(set(files)) == 8
    for c in m["clips"]:
        assert (ROOT / c["file"]).exists(), c["file"]
        assert c["movement"] in (None, "unknown") or c["movement"] in MOVEMENTS
        assert c["reviewMethod"] in ("contact-sheet", "frame-by-frame", "unreviewed")
        assert c["reviewerConfidence"] in ("high", "medium", "low")
        if c["reviewMethod"] == "unreviewed":
            assert c["reps"] is None or c["role"] == "abstention"
        for key in ("errors", "forbidden", "phaseScoped", "unobservable"):
            for e in c.get(key) or []:
                assert e["errorId"] in ids, (c["file"], e["errorId"])


def test_summary_counts_faults_by_error_id_and_unobservable_checks():
    p = _payload("pull_up", [(1, 2, 3)],
                 faults=[{"name": "lockout", "errorId": "pull_up.incomplete_lockout"}],
                 assessments=[{"errorId": "pull_up.body_swing", "status": "unobservable"}])
    s = run.summarise_payload(p)
    assert s["faults"] == {"pull_up.incomplete_lockout": 1}
    assert s["unobservable"] == {"pull_up.body_swing": 1}
    assert s["repWindows"] == [[1, 2, 3]]


def test_diff_reports_removed_reps_and_fault_name_deltas(tmp_path):
    before = _payload("pull_up", [(1, 2, 3), (4, 5, 6)],
                      faults=[{"name": "stall", "errorId": "pull_up.lift_stall"}])
    (tmp_path / "clip-before.json").write_text(json.dumps(before))
    after = _payload("pull_up", [(1, 2, 3)])
    d = run.diff_against_baseline("clip", after, tmp_path)
    assert d["changed"]
    assert d["repsRemoved"] == [(4.0, 5.0, 6.0)] and d["repsAdded"] == []
    assert d["faultNameDelta"] == {"stall": {"before": 2, "after": 0}}
    assert run.diff_against_baseline("missing", after, tmp_path) is None


def test_metrics_score_forbidden_phase_scoped_and_false_retained():
    manifest = {"clips": [
        {"file": "a.mp4", "movement": "muscle_up", "reps": 2,
         "phaseScoped": [{"errorId": "muscle_up.incomplete_support_extension",
                          "phase": "support", "maxWindowS": 0.5}],
         "notReps": [{"intervalS": [22.61, 25.16]}]},
        {"file": "b.mp4", "movement": "push_up", "reps": 3,
         "forbidden": [{"errorId": "push_up.lift_stall"}],
         "unobservable": [{"errorId": "push_up.hip_sag"}]},
        {"file": "c.mp4", "movement": "unknown", "reps": 0},
        {"file": "d.mp4", "movement": None, "reps": None},
    ]}
    good = {"errorId": "muscle_up.incomplete_support_extension", "status": "observed",
            "phase": "support", "intervalS": [5.8, 6.0]}
    wide = dict(good, intervalS=[2.0, 6.0])
    results = {
        "a": _payload("muscle_up", [(2, 5, 7), (22.61, 23, 25.16)],
                      assessments=[good, wide]),
        "b": _payload("push_up", [(1, 2, 3), (3, 4, 5), (5, 6, 7)],
                      faults=[{"name": "stall", "errorId": "push_up.lift_stall"}],
                      assessments=[{"errorId": "push_up.hip_sag", "status": "unobservable"}]),
        "c": _payload("pull_up", []),
        "d": _payload("pull_up", [(1, 2, 3)]),
    }
    m = run.metrics_against_manifest(results, manifest)
    mv = m["movement"]
    assert mv["reviewedClips"] == 3                     # d has no label
    assert mv["accuracy"] == pytest.approx(2 / 3)
    assert mv["perClass"]["unknown"]["predicted"] == {"pull_up": 1}
    seg = m["segmentation"]
    assert {c["clip"]: c["error"] for c in seg["countErrors"]} == {"a": 0, "b": 0, "c": 0}
    assert seg["falseRetained"] == [{"clip": "a", "intervalS": [22.61, 25.16], "retained": True}]
    err = m["errors"]
    assert err["forbidden"] == [{"clip": "b", "errorId": "push_up.lift_stall",
                                 "repsFired": 3, "repsTotal": 3}]
    (ps,) = err["phaseScoped"]
    assert ps["fired"] == 4 and ps["outsidePhaseOrTooWide"] == 2 and ps["ok"] is False
    assert err["unobservableExpected"][0]["statuses"] == {"unobservable": 3}


def test_vision_mode_refuses_to_run_without_an_endpoint(monkeypatch, tmp_path):
    for k in ("BARRA_VISION_BASE_URL", "BARRA_VISION_API_KEY", "NAN_BASE_URL", "NAN_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"")
    assert run.main(["--mode", "vision", "--out", str(tmp_path / "out"), str(clip)]) == 3
    assert not (tmp_path / "out").exists()


def test_cached_run_writes_every_artifact_and_never_overwrites(monkeypatch, tmp_path):
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"")

    def fake_cached(path, exercise, trace_dir):
        (trace_dir / "t.json").write_text("{}")
        p = _payload("pull_up", [(1, 2, 3)])
        p["traceId"] = "t"
        return p, {}

    monkeypatch.setattr(run, "run_cached", fake_cached)
    monkeypatch.setattr(run.time, "strftime", lambda fmt: "fixed")
    out = tmp_path / "out"
    assert run.main(["--mode", "cached", "--out", str(out), "--baseline",
                     str(tmp_path / "nobase"), str(clip)]) == 0
    run_dir = out / "fixed-cached"
    for name in ("summary.json", "summary.csv", "diff-vs-baseline.json", "metrics.json",
                 "manifest-audit.json", "provenance.json", "failures.json"):
        assert (run_dir / name).exists(), name
    assert (run_dir / "payloads" / "x.json").exists()
    assert (run_dir / "traces" / "t.json").exists()
    assert json.loads((run_dir / "failures.json").read_text()) == {}
    prov = json.loads((run_dir / "provenance.json").read_text())
    assert "thresholds" in prov and "rules" in prov
    # Same timestamp again: refuse rather than clobber a reviewed run.
    assert run.main(["--mode", "cached", "--out", str(out), str(clip)]) == 4


def test_a_failing_clip_is_recorded_not_fatal(monkeypatch, tmp_path):
    clip = tmp_path / "x.mp4"
    clip.write_bytes(b"")

    def boom(path, exercise, trace_dir):
        raise RuntimeError("pose backend fell over")

    monkeypatch.setattr(run, "run_cached", boom)
    out = tmp_path / "out"
    assert run.main(["--mode", "cached", "--out", str(out), str(clip)]) == 1
    (run_dir,) = out.iterdir()
    failures = json.loads((run_dir / "failures.json").read_text())
    assert "pose backend fell over" in failures["x"]["error"]
