from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def _analyze_with_count(vision_count, segments=()):
    import importlib
    import sys

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "server"))
    from barra.classify import Classification
    from barra.trace import NullTrace
    # Other test modules import `process` before adding the server path, so a
    # plain `from process import ...` can reuse a cached module from a
    # different test setup. Reload after the path is established to exercise
    # the current worker implementation consistently in combined runs.
    process = sys.modules.get("process")
    if process is None:
        process = importlib.import_module("process")
    else:
        process = importlib.reload(process)
    analyze_clip = process.analyze_clip

    keypoints = np.zeros((30, 17, 3), dtype=float)
    body = {
        0: (100, 60), 5: (90, 100), 6: (110, 100),
        7: (80, 130), 8: (120, 130), 9: (70, 160), 10: (130, 160),
        11: (95, 180), 12: (105, 180), 13: (95, 220), 14: (105, 220),
        15: (95, 260), 16: (105, 260),
    }
    for index, point in body.items():
        keypoints[:, index, :2] = point
        keypoints[:, index, 2] = 1.0
    pose = SimpleNamespace(keypoints=keypoints, fps=30.0,
                           source="count-rescue-test")
    with (
        mock.patch("barra.classify.classify", return_value=Classification(
            exercise="push_up", confidence=1.0, reason="test fixture")),
        mock.patch("barra.ingest.segment_reps_verbose",
                   return_value=(list(segments), ["test segmentation"])),
        mock.patch("barra.ingest.rescue_reps", return_value=([], "no reps")),
        mock.patch("barra.model.load_default", return_value=None),
        mock.patch("barra.metrics.rep_metrics", return_value=SimpleNamespace(
            values={}, phases=None, plausible=False,
            quality={"rep": 0.9}, problems=["candidate rejected as impossible"])),
    ):
        payload = analyze_clip(
            ROOT / "VID-20260827-WA0020.mp4",
            exercise="push_up",
            session="2026-10-13",
            trace=NullTrace(),
            visual_count=lambda: vision_count,
            pose=pose,
        )

    return payload


def test_accepted_visual_count_is_used_in_session_summary():
    payload = _analyze_with_count({
        "usable": True,
        "reps": 5,
        "models": ["primary", "secondary"],
        "agreement": "exact",
        "range": [5, 5],
    })
    assert payload["countedBy"] == "vision"
    assert payload["countStatus"] == "vision"
    assert payload["n_reps"] == 5
    assert payload["sessions"][0]["reps"] == 5


def test_failed_count_rescue_is_explicitly_unmeasured():
    payload = _analyze_with_count(None)
    assert payload["countedBy"] is None
    assert payload["countStatus"] == "unmeasured"
    assert payload["n_reps"] == 0


def test_rejected_geometric_candidates_do_not_claim_a_measured_zero():
    payload = _analyze_with_count(None, segments=[(0, 15, 29)])
    assert payload["n_candidates"] == 1
    assert payload["n_reps"] == 0
    assert payload["countStatus"] == "unmeasured"
