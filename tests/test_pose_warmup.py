from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "api"))

from pose_warmup import finish_pose_runtime_warmup, start_pose_runtime_warmup


class PoseRuntimeWarmupTests(unittest.TestCase):
    def test_non_ultralytics_backend_does_not_start_background_work(self):
        with patch("pose_warmup._import_ultralytics") as importer:
            warmup = start_pose_runtime_warmup("mediapipe")
        self.assertIsNone(warmup)
        importer.assert_not_called()
        self.assertEqual(finish_pose_runtime_warmup(warmup)["outcome"], "skipped")

    def test_runtime_warmup_can_be_disabled_for_a_paired_control(self):
        with patch.dict("os.environ", {
                "BARRA_POSE_BACKEND": "ultralytics",
                "BARRA_POSE_RUNTIME_WARMUP": "false"}), \
                patch("pose_warmup._import_ultralytics") as importer:
            warmup = start_pose_runtime_warmup()
        self.assertIsNone(warmup)
        importer.assert_not_called()
        self.assertEqual(finish_pose_runtime_warmup(warmup)["outcome"], "skipped")

    def test_import_runs_asynchronously_and_wait_reports_ready(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_import():
            entered.set()
            self.assertTrue(release.wait(2))

        with patch("pose_warmup._import_ultralytics", side_effect=slow_import):
            warmup = start_pose_runtime_warmup("ultralytics")
            self.assertIsNotNone(warmup)
            self.assertTrue(entered.wait(1))
            self.assertTrue(warmup.thread.is_alive())
            release.set()
            outcome = finish_pose_runtime_warmup(warmup)

        self.assertTrue(outcome["ready"])
        self.assertEqual(outcome["outcome"], "ready")
        self.assertGreaterEqual(outcome["waitMs"], 0)
        self.assertGreaterEqual(outcome["elapsedMs"], outcome["waitMs"])
        self.assertFalse(warmup.thread.is_alive())

    def test_import_failure_is_reported_without_raising(self):
        with patch("pose_warmup._import_ultralytics",
                   side_effect=ImportError("missing optional runtime")):
            warmup = start_pose_runtime_warmup("ultralytics")
            self.assertIsNotNone(warmup)
            outcome = finish_pose_runtime_warmup(warmup)

        self.assertFalse(outcome["ready"])
        self.assertEqual(outcome["outcome"], "import-error")
        self.assertEqual(outcome["errorType"], "ImportError")
        self.assertFalse(warmup.thread.is_alive())
