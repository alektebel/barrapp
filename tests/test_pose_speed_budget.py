"""Pose time for X minutes of video must drop under the new defaults."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.pose.speed_budget import (  # noqa: E402
    PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S,
    PROJECTED_FULL_PARALLEL_S_PER_S,
    pose_seconds_for_minutes,
    speedup,
)

SERVER = ROOT / "server"


class SpeedBudget(unittest.TestCase):
    def test_production_baseline_for_x_minutes(self):
        # 3.6 s pose / 1 s video → 1 min of footage ≈ 3.6 min of pose.
        self.assertEqual(PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S, 3.6)
        self.assertAlmostEqual(pose_seconds_for_minutes(1, 3.6), 216.0)
        self.assertAlmostEqual(pose_seconds_for_minutes(0.5, 3.6), 108.0)

    def test_projection_is_materially_faster(self):
        self.assertLess(PROJECTED_FULL_PARALLEL_S_PER_S, 1.2)
        self.assertGreaterEqual(
            speedup(PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S, PROJECTED_FULL_PARALLEL_S_PER_S), 3.0)
        # 1 min of video: was ~216 s pose, projected ~31 s.
        self.assertLess(pose_seconds_for_minutes(1, PROJECTED_FULL_PARALLEL_S_PER_S), 80.0)

    def test_worker_template_ships_the_fast_defaults(self):
        t = (SERVER / "template.yaml").read_text()
        self.assertRegex(t, r"BARRA_POSE_MODEL:\s*/opt/barra/models/pose_landmarker_full\.task")
        self.assertRegex(t, r'BARRA_POSE_WORKERS:\s*"6"')

    def test_fixture_records_baseline_and_projection(self):
        path = ROOT / "tests" / "fixtures" / "pose_speed_bench.json"
        if not path.exists():
            self.skipTest("run scripts/pose_speed_bench.py to refresh the fixture")
        report = json.loads(path.read_text())
        self.assertEqual(
            report["productionBaseline"]["posePerVideoSecond"],
            PRODUCTION_HEAVY_SEQUENTIAL_S_PER_S)
        self.assertEqual(report["productionBaseline"]["minutes1"], 216.0)
        self.assertEqual(
            report["productionProjectionAfter"]["posePerVideoSecond"],
            PROJECTED_FULL_PARALLEL_S_PER_S)
        self.assertLess(report["productionProjectionAfter"]["minutes1"], 80.0)
        self.assertGreaterEqual(report["productionProjectionAfter"]["speedupVsBaseline"], 3.0)
        before = report["localMeasured"]["before"]
        after = report["localMeasured"]["after"]
        self.assertIn("heavy", before["model"])
        self.assertIn("full", after["model"])
        self.assertGreaterEqual(after["workers"], 2)
        # Real-clip fixture (WA0020): Full+chunks must beat Heavy sequential.
        self.assertLess(after["posePerVideoSecond"], before["posePerVideoSecond"])
        self.assertGreaterEqual(report["localMeasured"]["speedup"], 3.0)
        self.assertLess(after["minutes1"], before["minutes1"] / 2)


if __name__ == "__main__":
    unittest.main()
