"""The cold-container prewarm reads files and changes nothing else."""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server" / "api")]

import prewarm  # noqa: E402


class Prewarm(unittest.TestCase):
    def setUp(self):
        prewarm._done = False
        self.addCleanup(setattr, prewarm, "_done", False)

    def test_it_reads_every_file_it_is_given_from_several_threads(self):
        import tempfile
        seen, threads = [], set()
        with tempfile.TemporaryDirectory() as d:
            files = []
            for i in range(6):
                p = Path(d) / f"f{i}.bin"
                p.write_bytes(b"x" * (prewarm.BLOCK + 5))
                files.append(p)
            real = prewarm._read

            def read(p):
                threads.add(threading.get_ident())
                time.sleep(0.05)
                seen.append(p)
                return real(p)
            with mock.patch.object(prewarm, "_read", side_effect=read):
                prewarm._run(files, 3)
        self.assertEqual(sorted(seen), sorted(files))
        self.assertGreater(len(threads), 1)

    def test_it_starts_once_per_container(self):
        with mock.patch.object(prewarm, "cold_files", return_value=[]):
            self.assertTrue(prewarm.start())
            self.assertFalse(prewarm.start())

    def test_it_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"BARRA_PREWARM": "0"}):
            self.assertFalse(prewarm.start())

    def test_a_missing_file_or_a_failing_listing_is_silent(self):
        self.assertEqual(prewarm._read(Path("/nonexistent/file.so")), 0)
        with mock.patch.object(prewarm, "cold_files", side_effect=RuntimeError("boom")):
            self.assertTrue(prewarm.start())  # the background thread swallows it
            time.sleep(0.1)

    def test_the_file_list_has_the_pose_model_first_among_equals(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            model = Path(d) / "pose.task"
            model.write_bytes(b"m" * 100)
            with mock.patch.dict(os.environ, {"BARRA_POSE_MODEL": str(model),
                                              "BARRA_ROOT": d}):
                self.assertIn(model, prewarm.cold_files())


if __name__ == "__main__":
    unittest.main()
