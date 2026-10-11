"""The sentinel: runs a stage's contract and records what came in, what went
out, and the verdict, in the trace.

Two modes, because the same check has two jobs:
  * strict (tests, the corpus, the canary clips): a violation raises, so a
    broken invariant fails the run that produced it;
  * record (production, the default): a violation is written to the trace and
    logged as one parseable line for a metric, and the job carries on - unless
    the violation is fatal, in which case the caller is told.
A sentinel that crashes must never take a job down with it.
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra import sentinel  # noqa: E402
from barra.contracts import Violation  # noqa: E402
from barra.trace import Trace  # noqa: E402


def passing(_out, **_ctx):
    return []


def failing(_out, **_ctx):
    return [Violation("probe", "fps_positive", "fps=0")]


def fatal(_out, **_ctx):
    return [Violation("payload", "required_keys", "missing reps", fatal=True)]


def crashing(_out, **_ctx):
    raise ZeroDivisionError("bug in the check")


class Recording(unittest.TestCase):
    def setUp(self):
        self.tr = Trace("t1")
        patcher = mock.patch.dict(os.environ, {"BARRA_SENTINEL": "record"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def entry(self):
        return [e for e in self.tr.entries if e.kind == "sentinel"][-1]

    def test_a_pass_is_recorded_with_its_input_and_output(self):
        verdict = sentinel.watch(self.tr, "probe", {"fps": 30}, check=passing,
                                 inputs={"path": "a.mp4"})
        self.assertTrue(verdict.ok)
        e = self.entry()
        self.assertEqual(e.data["stage"], "probe")
        self.assertTrue(e.data["ok"])
        self.assertEqual(e.data["inputs"], {"path": "a.mp4"})
        self.assertEqual(e.data["outputs"], {"fps": 30})

    def test_a_violation_is_recorded_and_logged_not_raised(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            verdict = sentinel.watch(self.tr, "probe", {"fps": 0}, check=failing)
        self.assertFalse(verdict.ok)
        self.assertFalse(verdict.fatal)
        self.assertEqual(self.entry().data["violations"][0]["rule"], "fps_positive")
        self.assertIn("[barra] sentinel stage=probe ok=false rules=fps_positive", buf.getvalue())

    def test_fatal_is_reported_to_the_caller(self):
        with redirect_stdout(io.StringIO()):
            self.assertTrue(sentinel.watch(self.tr, "payload", {}, check=fatal).fatal)

    def test_a_crashing_check_never_fails_the_job(self):
        with redirect_stdout(io.StringIO()):
            verdict = sentinel.watch(self.tr, "probe", {}, check=crashing)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.violations[0].rule, "check_crashed")

    def test_large_outputs_are_summarised_not_copied(self):
        import numpy as np
        sentinel.watch(self.tr, "pose", {"keypoints": np.zeros((900, 33, 3))}, check=passing)
        self.assertEqual(self.entry().data["outputs"]["keypoints"],
                         {"type": "ndarray", "shape": [900, 33, 3]})

    def test_trace_counts_sentinels(self):
        sentinel.watch(self.tr, "probe", {}, check=passing)
        self.assertEqual(self.tr.as_dict()["counts"]["sentinel"], 1)


class Strict(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"BARRA_SENTINEL": "strict"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_violation_raises(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(sentinel.SentinelError) as cm:
            sentinel.watch(Trace("t"), "probe", {"fps": 0}, check=failing)
        self.assertIn("fps_positive", str(cm.exception))

    def test_a_crashing_check_raises_too(self):
        # In strict mode a broken check is a broken test, not a pass.
        with redirect_stdout(io.StringIO()), self.assertRaises(sentinel.SentinelError):
            sentinel.watch(Trace("t"), "probe", {}, check=crashing)

    def test_passing_is_silent(self):
        self.assertTrue(sentinel.watch(Trace("t"), "probe", {}, check=passing).ok)

    def test_default_check_comes_from_the_registry(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(sentinel.SentinelError):
            sentinel.watch(Trace("t"), "probe", {"ok": True, "fps": 0, "frames": 10,
                                                 "duration_s": 1.0})


class Mode(unittest.TestCase):
    def test_production_default_is_record(self):
        env = {k: v for k, v in os.environ.items() if k != "BARRA_SENTINEL"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(sentinel.mode(), "record")


if __name__ == "__main__":
    unittest.main()
