"""The two MiMo passes: locate the exercise, then judge the errors.

Offline tests pin the parsing, the window validation and the rubric/biometric
prompt. The labelled-case evals only run with `BARRA_MIMO_EVAL=1`, so the normal
suite never makes a paid call.

Localization cases live in `data/evaluation/localization_labels.csv`:

    clip,exercise,start_s,end_s,tolerance_s,notes
    data/calisthenics/videos/muscle_up/youtube_X.mp4,muscle_up,2.9,6.8,2.0,intro then one rep
    data/videos/talking_head.mp4,none,,,,"no exercise performed"

Error cases reuse the human fault labels the repo already has,
`out/fault-labels-human/<movement>/<stem>.json`:

    {"file": "...", "movement": "pull_up",
     "faults": {"body_swing": "present", "incomplete_lockout": "absent"}}

Keys are the rule ids in `barra/rules.py` with the movement prefix stripped,
and the verdicts are present / absent / unclear.

Run the evals:
    BARRA_MIMO_EVAL=1 .venv/bin/python -m pytest tests/test_mimo.py -s
"""
import csv
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

import nan_secret  # noqa: E402
import vision  # noqa: E402
from barra.frames import Still, TechniqueArtifacts, trim_clip  # noqa: E402

LABELS = ROOT / "data" / "evaluation" / "localization_labels.csv"
HUMAN_ERRORS = ROOT / "out" / "fault-labels-human"
KEYPOINTS = ROOT / "out" / "keypoints"
LIVE = os.environ.get("BARRA_MIMO_EVAL") == "1"


# ---------------------------------------------------------------------------
# offline
# ---------------------------------------------------------------------------
def test_window_requires_a_real_short_stretch():
    good = vision.window_from_verdict(
        {"technique_start": 10, "technique_end": 30, "detected_exercise": "pull_up"},
        60.0, "mimo-v2.5")
    assert good["usable"] and good["startS"] == 10.0 and good["endS"] == 30.0
    assert good["exercise"] == "pull_up"

    # Covers the whole clip: not a localization, so no trim.
    assert not vision.window_from_verdict(
        {"technique_start": 0, "technique_end": 60}, 60.0)["usable"]
    # Too short to be a set.
    assert not vision.window_from_verdict(
        {"technique_start": 10, "technique_end": 12}, 60.0)["usable"]
    # Explicit "no exercise".
    none = vision.window_from_verdict(
        {"technique_start": 0, "technique_end": 0, "detected_exercise": "none"}, 60.0)
    assert not none["usable"] and none["exercise"] == "none"
    # Garbage is not a window.
    assert not vision.window_from_verdict({"technique_start": "x"}, 60.0)["usable"]


def test_locate_exercise_with_a_stubbed_model(tmp_path, monkeypatch):
    frames = []
    for i in range(6):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"\xff\xd8jpeg")
        frames.append((i, p))

    monkeypatch.setenv("BARRA_VISION_BASE_URL", "http://x/v1")
    monkeypatch.delenv("BARRA_LOCALIZE", raising=False)
    monkeypatch.setattr(vision, "_config", lambda: ("http://x/v1", "k", "mimo-v2.5"))
    monkeypatch.setattr("barra.ingest.probe_video",
                        lambda p: {"ok": True, "duration_s": 60.0})
    monkeypatch.setattr("barra.frames.grab_frames",
                        lambda v, moments, out, prefix="locate": frames)
    monkeypatch.setattr(vision, "_chat", lambda *a, **k: json.dumps({
        "detected_exercise": "pull_up", "agrees": True,
        "technique_start": 12.0, "technique_end": 31.0,
        "reps_estimate": 5, "description": "side view on a bar"}))

    got = vision.locate_exercise(tmp_path / "clip.mp4", tmp_path / "out", "auto")
    assert got["usable"] and got["exercise"] == "pull_up"
    assert (got["startS"], got["endS"]) == (12.0, 31.0)
    assert got["repsEstimate"] == 5 and got["model"] == "mimo-v2.5"


def test_locate_exercise_is_off_without_a_key_or_a_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "_config", lambda: None)
    assert vision.locate_exercise(tmp_path / "c.mp4", tmp_path) is None

    monkeypatch.setattr(vision, "_config", lambda: ("http://x", "k", "m"))
    monkeypatch.setenv("BARRA_LOCALIZE", "0")
    assert vision.locate_exercise(tmp_path / "c.mp4", tmp_path) is None


def test_rubric_carries_corrections_and_biometrics(tmp_path):
    rules = vision._known_rules({"exercise": "pull_up"})
    assert rules and all(r["correction"] for r in rules)

    frame = Still(tmp_path / "f1.jpg", "r1", "lifting", "mid-lift", 1.5)
    frame.path.write_bytes(b"\xff\xd8jpeg")
    art = TechniqueArtifacts(clip=None, frames=[frame], selected_reps=["r1"])
    report = {
        "exercise": "pull_up",
        "detected": {"reason": "shoulders never rise above the hands"},
        "variant": {"name": "unspecified", "source": "none"},
        "view": {"bin": "UNKNOWN", "knowable": False, "why": "narrow"},
        "sessionScore": 72, "sessionBand": "solid",
        "consistency": {"amplitudeCV": 0.11},
        "reps": [{"label": "r1", "startS": 1.0, "endS": 3.0,
                  "metrics": ["rom: 0.83", "tempo_ratio: 1.10"],
                  "score": 72, "band": "solid",
                  "phases": {"rep": [1.0, 3.0]}, "assessments": []}],
    }
    text = vision._user_text(art, report)
    assert "measured: rom: 0.83" in text
    assert "Session score: 72" in text
    assert "Fix:" in text


def test_trim_clip_is_best_effort(monkeypatch, tmp_path):
    monkeypatch.setattr("barra.frames._ffmpeg_bin", lambda: None)
    assert trim_clip(tmp_path / "a.mp4", 0, 10, tmp_path / "o.mp4") is None
    assert trim_clip(tmp_path / "a.mp4", 10, 10, tmp_path / "o.mp4") is None


def test_nan_key_reads_the_environment_without_the_network(monkeypatch):
    nan_secret.reset_cache()
    monkeypatch.delenv("NAN_SECRET_ID", raising=False)
    monkeypatch.setenv("NAN_API_KEY", "test-key-123")
    assert nan_secret.get_nan_key() == "test-key-123"
    nan_secret.reset_cache()


def _reply(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def test_chat_retries_an_empty_reply(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return self._p

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _Resp(_reply("" if calls["n"] == 1 else '{"ok": true}'))

    monkeypatch.setattr(vision.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(vision.time, "sleep", lambda *_: None)
    assert vision._chat("http://x", "k", "m", "s",
                        [{"type": "text", "text": "hi"}]) == '{"ok": true}'
    assert calls["n"] == 2


def test_chat_gives_up_after_persistent_empty_replies(monkeypatch):
    monkeypatch.setattr(vision.urllib.request, "urlopen",
                        lambda req, timeout=None: type("R", (), {
                            "read": lambda self: _reply(""),
                            "__enter__": lambda self: self,
                            "__exit__": lambda self, *a: False})())
    monkeypatch.setattr(vision.time, "sleep", lambda *_: None)
    assert vision._chat("http://x", "k", "m", "s",
                        [{"type": "text", "text": "hi"}]) is None


# ---------------------------------------------------------------------------
# the labelled cases (live)
# ---------------------------------------------------------------------------
def _rows():
    if not LABELS.exists():
        return []
    with open(LABELS, newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("clip") or "").strip()]


@pytest.mark.skipif(not LIVE, reason="live MiMo eval; set BARRA_MIMO_EVAL=1")
def test_localization_against_labelled_cases(tmp_path):
    rows = _rows()
    if not rows:
        pytest.skip(f"no labelled cases yet in {LABELS}")
    if vision._config() is None:
        pytest.skip("no vision endpoint configured")

    failures = []
    for row in rows:
        clip = ROOT / row["clip"]
        if not clip.exists():
            failures.append(f"{row['clip']}: missing file")
            continue
        got = vision.locate_exercise(clip, tmp_path / clip.stem, row.get("exercise"))
        if (row.get("exercise") or "").strip().lower() == "none":
            if got and got.get("usable"):
                failures.append(f"{row['clip']}: expected no window, got "
                                f"{got['startS']}-{got['endS']}")
            continue
        if not got or not got.get("usable"):
            failures.append(f"{row['clip']}: no usable window (got {got})")
            continue
        tol = float(row.get("tolerance_s") or 2.0)
        ds = abs(float(got["startS"]) - float(row["start_s"]))
        de = abs(float(got["endS"]) - float(row["end_s"]))
        if ds > tol or de > tol:
            failures.append(f"{row['clip']}: off start {ds:.1f}s / end {de:.1f}s "
                            f"(tol {tol})")
    assert not failures, "localization mismatches:\n" + "\n".join(failures)


# The vision status -> the human label vocabulary, so the two sides are asked
# the same question.
_STATUS = {"observed": "present", "not_observed": "absent",
           "unobservable": "unclear", "uncertain": "unclear"}


@pytest.mark.skipif(not LIVE, reason="live MiMo eval; set BARRA_MIMO_EVAL=1")
def test_error_rubric_against_human_labels(tmp_path):
    if vision._config() is None:
        pytest.skip("no vision endpoint configured")
    if not HUMAN_ERRORS.exists():
        pytest.skip("no human fault labels (out/fault-labels-human)")

    from barra.frames import technique_artifacts
    from barra.posecache import load, load_or_estimate
    from process import analyze_clip

    misses, compared = [], 0
    for sidecar in sorted(HUMAN_ERRORS.rglob("*.json")):
        try:
            label = json.loads(sidecar.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        movement, file = label.get("movement"), label.get("file")
        if not movement or not file:
            continue
        clip = ROOT / "data" / "calisthenics" / "videos" / movement / Path(file).name
        if not clip.exists() or load(clip) is None:
            continue  # only clips that have already paid for pose

        pose = load_or_estimate(clip, fresh=False, write_cache=False)
        payload = analyze_clip(clip, exercise=movement, pose=pose)
        art = technique_artifacts(clip, payload, tmp_path, clip.stem)
        note = vision.technique_note(art, payload)
        if not note:
            misses.append(f"{clip.name}: no MiMo note")
            continue

        seen = {}
        for obs in note.get("visionObservations") or []:
            status = _STATUS.get(str(obs.get("status")), "unclear")
            if status == "present" or obs.get("errorId") not in seen:
                seen[obs["errorId"]] = status
        for key, want in (label.get("faults") or {}).items():
            want = str(want).lower()
            if want == "unclear":
                continue
            error_id = f"{movement}.{key}"
            got = seen.get(error_id, "unclear")
            if got == "unclear":
                continue
            compared += 1
            if got != want:
                misses.append(f"{clip.name} {error_id}: said {got}, label {want}")

    if compared == 0:
        pytest.skip("no judgeable error labels with cached keypoints")
    agreement = 1 - len(misses) / compared
    print(f"\nMiMo error rubric: {compared} judged, agreement {agreement:.2f}")
    assert agreement >= 0.5, "error rubric agreement below chance:\n" + "\n".join(misses)
