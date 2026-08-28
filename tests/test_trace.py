"""The trace has to be trustworthy, because it is what gets believed when
something is wrong.

Three properties matter and each is tested here: it survives serialisation
without losing values, it records the threshold next to the evidence, and
turning it off costs nothing.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from barra.trace import NullTrace, Trace, _plain, new_id


class TestSerialisation(unittest.TestCase):
    def test_numpy_values_survive(self):
        """numpy scalars subclass the Python numeric types, so an isinstance
        check passes them through and they render as 'np.float64(8.43)'."""
        out = _plain({"a": np.float64(8.43), "b": np.int64(3),
                      "c": np.array([1.5, 2.5]), "d": np.bool_(True)})
        self.assertEqual(out, {"a": 8.43, "b": 3, "c": [1.5, 2.5], "d": True})
        json.dumps(out)

    def test_nan_becomes_null_not_a_crash(self):
        """A metric that could not be measured is a real outcome. A trace that
        died serialising one would be lost exactly when it mattered."""
        out = _plain({"x": float("nan"), "y": float("inf"), "z": np.float32("nan")})
        self.assertEqual(out, {"x": None, "y": None, "z": None})
        json.dumps(out)

    def test_unknown_objects_do_not_raise(self):
        class Odd:
            def __repr__(self):
                return "<odd>"

        self.assertEqual(_plain({"o": Odd()}), {"o": "<odd>"})

    def test_round_trip_through_disk(self):
        t = Trace(new_id(), "clip.mp4", fps=30.0)
        t.stage("segment")
        t.reject("candidate at 12.4s", "hands not on a fixed bar",
                 travel=np.float64(2.63), max=0.80)
        with tempfile.TemporaryDirectory() as d:
            p = t.write(Path(d) / "t.json")
            data = json.loads(p.read_text())
        self.assertEqual(data["traceId"], t.id)
        self.assertEqual(data["counts"]["reject"], 1)
        entry = [e for e in data["entries"] if e["kind"] == "reject"][0]
        self.assertEqual(entry["data"]["travel"], 2.63)
        self.assertEqual(entry["data"]["max"], 0.80)


class TestRecording(unittest.TestCase):
    def test_a_rejection_carries_its_threshold(self):
        """'rejected: travel 2.63 > 0.80' is debuggable. 'rejected' is not."""
        t = Trace("x", "clip")
        t.stage("segment")
        t.reject("candidate", "hands not on a fixed bar", travel=2.63, max_travel=0.80)
        e = t.rejections[0]
        self.assertIn("travel", e.data)
        self.assertIn("max_travel", e.data)
        self.assertIn("hands", e.message)

    def test_stage_groups_entries(self):
        t = Trace("x", "clip")
        t.stage("classify"); t.step("a")
        t.stage("segment"); t.step("b"); t.step("c")
        self.assertEqual(len(t.of_stage("segment")), 3)   # the stage marker plus two
        self.assertEqual([e.stage for e in t.of_stage("classify")], ["classify"] * 2)

    def test_errors_are_separable(self):
        t = Trace("x", "clip")
        t.stage("pose"); t.error("no backend"); t.note("fyi"); t.reject("rep", "too short")
        self.assertEqual(len(t.errors), 1)
        self.assertEqual(len(t.rejections), 1)

    def test_render_modes_narrow_the_output(self):
        t = Trace("x", "clip")
        t.stage("segment"); t.step("bookkeeping")
        t.decision("rep 1", "accepted"); t.reject("rep 2", "too short")
        self.assertIn("bookkeeping", t.render(show="all"))
        self.assertNotIn("bookkeeping", t.render(show="decisions"))
        self.assertNotIn("accepted", t.render(show="problems"))
        self.assertIn("too short", t.render(show="problems"))

    def test_ids_are_unique_and_time_ordered(self):
        ids = [new_id(str(i)) for i in range(50)]
        self.assertEqual(len(set(ids)), 50)
        self.assertEqual(ids, sorted(ids, key=lambda s: (s[:13], ids.index(s))) or ids)


class TestNullTrace(unittest.TestCase):
    def test_records_nothing_but_answers_everything(self):
        """Call sites take a trace unconditionally. Guarding each call with
        `if trace is not None` is where tracing quietly stops happening."""
        n = NullTrace()
        n.stage("x"); n.step("y"); n.decision("a", "b", v=1)
        n.reject("c", "d"); n.note("e"); n.error("f")
        self.assertEqual(n.entries, [])
        self.assertEqual(n.rejections, [])
        self.assertEqual(n.as_dict()["counts"]["step"], 0)

    def test_the_pipeline_runs_without_a_trace(self):
        """Every traced function must work when handed nothing."""
        import sys

        sys.path.insert(0, "tests")
        from test_classify_quality import bar_clip

        from barra.classify import classify
        from barra.ingest import segment_reps_verbose
        from barra.movements import MUSCLE_UP

        kp = bar_clip(n_reps=2)
        self.assertEqual(classify(kp).exercise, "muscle_up")
        self.assertEqual(len(segment_reps_verbose(kp, 30.0, MUSCLE_UP)[0]), 2)


class TestPipelineTracing(unittest.TestCase):
    def test_a_rejected_rep_says_why_with_numbers(self):
        import sys

        sys.path.insert(0, "tests")
        from test_classify_quality import bar_clip

        from barra.ingest import segment_reps_verbose
        from barra.movements import MAX_BAR_TRAVEL, MUSCLE_UP

        t = Trace("x", "drifting bar")
        segment_reps_verbose(bar_clip(n_reps=3, drift=3.5), 30.0, MUSCLE_UP, trace=t)
        self.assertTrue(t.rejections, "a drifting anchor must be recorded, not silent")
        got = t.rejections[0].data
        self.assertGreater(got["wrist_travel"], MAX_BAR_TRAVEL)
        self.assertEqual(got["max_travel"], MAX_BAR_TRAVEL)

    def test_the_classifier_records_the_evidence_for_its_choice(self):
        import sys

        sys.path.insert(0, "tests")
        from test_classify_quality import bar_clip

        from barra.classify import OVER_BAR, classify

        t = Trace("x", "clip")
        classify(bar_clip(clearance=0.5), t)
        decisions = [e for e in t.entries if e.kind == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].data["outcome"], "muscle_up")
        self.assertEqual(decisions[0].data["over_bar_threshold"], OVER_BAR)
        self.assertGreater(decisions[0].data["peak_above_hands"], OVER_BAR)


if __name__ == "__main__":
    unittest.main()
