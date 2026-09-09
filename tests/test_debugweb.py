"""The debug tool describes the pipeline, and describes it honestly.

tools/debugweb/server.py is a hand-maintained surface over code that changes:
fault_spec() maps every fault to the primitive its predicate reads, and
phone_faults() ports Cues.kt's repFaults() so the parity panel has a phone to
compare. Both can drift from what actually runs - these tests hold them to it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from barra.config import THRESHOLDS
from barra.evidence import PRIMITIVES, PLANAR
from barra.faults import rep_faults
from barra.faults_taxonomy import CLASSIFIERS, TRACK_FAILURES

ROOT = Path(__file__).resolve().parents[1]
_SPEC = ROOT / "tools" / "debugweb" / "server.py"


def _load_server():
    spec = importlib.util.spec_from_file_location("debugweb_server", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


server = _load_server()


def test_fault_spec_covers_every_track_and_fault():
    """Every track with a classifier has a spec row per fault it can fire,
    and no row for a fault it cannot - the panel is a window, not an opinion."""
    spec = server.fault_spec()["spec"]
    assert set(spec) == set(CLASSIFIERS), \
        f"spec tracks != classifier tracks: {set(spec) ^ set(CLASSIFIERS)}"
    for track, rows in spec.items():
        names = [r["fault"] for r in rows]
        assert set(names) == set(TRACK_FAILURES[track]), \
            f"{track}: spec faults {sorted(names)} != TRACK_FAILURES " \
            f"{sorted(TRACK_FAILURES[track])}"


def test_fault_spec_thresholds_are_the_config_values():
    """A row's threshold is the THRESHOLDS value its predicate uses - the
    panel imports, never retypes."""
    for rows in server.fault_spec()["spec"].values():
        for r in rows:
            assert r["op"] in ("<", "<=", ">", ">="), r
            if r["key"] == "lockout_pct":
                assert r["threshold"] == THRESHOLDS.lockout_min * 100
            if r["key"] == "hang_pct":
                assert r["threshold"] == THRESHOLDS.hang_min * 100


def test_fault_spec_planes_match_the_primitive_table():
    """A row whose primitive is PLANAR must say which plane, so the panel can
    show why a camera angle blocks it. The plane comes from PRIMITIVES, not
    from this table's opinion."""
    for rows in server.fault_spec()["spec"].values():
        for r in rows:
            spec = PRIMITIVES.get(r["key"])
            if spec and spec[0] == PLANAR:
                assert r.get("plane") == spec[1], \
                    f"{r['fault']}: row plane {r.get('plane')!r} != " \
                    f"PRIMITIVES {spec[1]!r} for {r['key']}"
            else:
                assert not r.get("plane"), \
                    f"{r['fault']}: plane {r['plane']!r} on a plane-free key {r['key']}"


def test_phone_port_agrees_with_the_harness_on_structured_rows():
    """rep_faults() prefers the structured array, and so does the phone port:
    on a payload row shaped the way the server ships, both name the same
    faults (order aside - the phone re-orders by CUE_ORDER for display)."""
    rep = {
        "faults": [
            {"name": "lockout", "primitive": "lockout_pct", "value": 76.0,
             "threshold": 85.0, "comparison": "<"},
            {"name": "momentum", "primitive": "swing", "value": 0.6,
             "threshold": 0.4, "comparison": ">"},
        ],
        "aside": [{"name": "swing", "value": 9.9}],
        "penalties": [{"name": "control", "value": 0.5}],
    }
    assert sorted(server.phone_faults(rep)) == sorted(rep_faults(rep)) \
        == ["lockout", "momentum"]
    assert server.phone_faults(rep) == ["lockout", "momentum"]


def test_phone_port_legacy_path_reads_only_structured_signals():
    """The legacy path is deliberately narrow - swing aside and control penalty.
    The harness's regex fallback still parses the why-strings for old payloads,
    so the phone is a subset of the harness on legacy rows, never the reverse.
    No prose parsing comes back through the port."""
    rep = {"aside": [{"name": "swing", "value": 0.5}],
           "penalties": [{"name": "control", "value": 0.0}],
           "components": [{"name": "range", "why": "lockout 10% of full"}]}
    assert server.phone_faults(rep) == ["momentum"]
    assert set(server.phone_faults(rep)) <= set(rep_faults(rep))


def test_gallery_is_default_not_design_preview():
    """The landing screen must be the real video library, not generated mock metrics."""
    import io
    handler = object.__new__(server.Handler)
    handler.path = '/'
    handler.wfile = io.BytesIO()
    served = []
    handler._static = lambda path: served.append(path)
    handler.do_GET()
    assert served == ['gallery.html']
    handler.path = '/inspect'
    handler.do_GET()
    assert served[-1] == 'index.html'


def test_upload_preserves_existing_files_and_confines_filename(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    responses = []
    def upload(name, body):
        handler = object.__new__(server.Handler)
        handler.path = '/api/clips?name=' + name
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler._json = lambda code, data: responses.append((code, data))
        handler.do_POST()
    upload('../../clip.mp4', b'first')
    upload('../../clip.mp4', b'second')
    assert all(code == 201 for code, _ in responses)
    assert responses[0][1]['name'] != responses[1][1]['name']
    files = list((tmp_path/'data/videos').glob('*.mp4'))
    assert sorted(f.read_bytes() for f in files) == [b'first', b'second']
    upload('script.html', b'bad')
    assert responses[-1][0] == 400


def test_upload_truncation_removes_partial_file(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(server, 'ROOT', tmp_path)
    handler = object.__new__(server.Handler)
    handler.path = '/api/clips?name=clip.mp4'
    handler.headers = {'Content-Length': '20'}
    handler.rfile = io.BytesIO(b'short')
    result = []
    handler._json = lambda code, data: result.append(code)
    handler.do_POST()
    assert result == [400]
    assert not list((tmp_path/'data/videos').iterdir())


def test_cancel_stops_only_the_requested_run(monkeypatch):
    class Process:
        stopped = False
        def poll(self): return None
        def terminate(self): self.stopped = True
    first, second = Process(), Process()
    monkeypatch.setattr(server, 'RUNS', {'first': {'proc': first}, 'second': {'proc': second}})
    h = object.__new__(server.Handler)
    h.path = '/api/runs/first/cancel'
    result = []
    h._json = lambda code, body: result.append((code, body))
    h.do_POST()
    assert first.stopped and not second.stopped
    assert result == [(200, {'cancelled': True})]


def test_gallery_includes_unanalyzed_clips_once_and_latest_summary(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(server, 'TRACES', tmp_path)
    monkeypatch.setattr(server, 'list_clips', lambda: [
        {'name': 'a.mp4', 'mtime': 2}, {'name': 'b.mp4', 'mtime': 1}])
    monkeypatch.setattr(server, 'list_traces', lambda limit: [
        {'subject': 'a.mp4', 'traceId': 'new', 'hasPayload': True},
        {'subject': 'a.mp4', 'traceId': 'old', 'hasPayload': True}])
    (tmp_path / 'new.payload.json').write_text(json.dumps({'exercise': 'push_up', 'n_reps': 0, 'sessionScore': None}))
    cards = server.gallery_clips()
    assert len(cards) == 2
    assert cards[0]['summary']['reps'] == 0
    assert cards[0]['summary']['score'] is None
    assert cards[0]['trace']['traceId'] == 'new'
    assert cards[1]['trace'] is None and cards[1]['summary'] is None


def test_model_card_exposes_live_thresholds_with_source_notes():
    """The model card is the prediction model: every THRESHOLDS field is a row,
    and a field documented by a block comment above it carries that gloss —
    not the section banner that sits above the paragraph."""
    card = server.model_card()
    assert card["counts"]["stages"] == 12
    assert card["counts"]["constants"] >= 90
    names = {r["name"]: r for rows in card["modules"].values() for r in rows}
    assert "THRESHOLDS.swing_torso" in names
    assert names["THRESHOLDS.swing_torso"]["value"] == THRESHOLDS.swing_torso
    assert "momentum" in names["THRESHOLDS.swing_torso"]["note"]
    band = names["THRESHOLDS.bar_plane_band"]["note"]
    assert "torso-lengths" in band
    assert not band.lstrip().startswith("-")
    # Segment stage must name the amplitude threshold it rejects against.
    segment = next(s for s in card["pipeline"] if s["key"] == "segment")
    assert any(c["name"] == "THRESHOLDS.min_span_amplitude" for c in segment["constants"])

    stage_keys = [s["key"] for s in card["pipeline"]]
    assert stage_keys == ["probe", "pose", "classify", "model", "fusion", "signal",
                          "segment", "metrics", "score", "faults", "vision", "payload"]
    model = next(s for s in card["pipeline"] if s["key"] == "model")
    fusion = next(s for s in card["pipeline"] if s["key"] == "fusion")
    assert any(c["name"] == "FEATURE_NAMES" for c in model["constants"])
    assert any(c["name"] == "MODEL_ACCEPT_CONFIDENCE" for c in fusion["constants"])


def test_debug_runner_uses_the_production_process_job_path():
    """The debug tool must not grow its own mini-pipeline. It estimates or loads
    pose first, then delegates to process_job just like the server worker."""
    source = (ROOT / "tools" / "debugweb" / "runner.py").read_text()
    assert "from process import process_job" in source
    assert "process_job(" in source
    assert "analyze_clip(" not in source
