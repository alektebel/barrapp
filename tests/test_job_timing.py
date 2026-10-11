"""scripts/job_timing.py: where a production job's time went.

The fixture is job 31103ccedfc3 (2026-10-11), recorded from production with
the owner stripped. Its numbers are the "after deploy 4" row of
docs/SPEED-PLAN.md, and they exposed a stage nobody had named: ~44 s between
the payload being ready and `done` being written (cutting and re-uploading the
stored clip).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import job_timing  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "job_timing_31103ccedfc3.json").read_text())


class Durations(unittest.TestCase):
    def setUp(self):
        self.d = job_timing.durations(FIXTURE["uploads"], FIXTURE["trace"])

    def test_upload_and_queue(self):
        self.assertEqual(self.d["upload"], 69)
        self.assertEqual(self.d["queue"], 2)

    def test_pose(self):
        self.assertAlmostEqual(self.d["pose"], 134, delta=1)

    def test_measure_and_report(self):
        self.assertAlmostEqual(self.d["measure+report"], 21, delta=2)

    def test_the_gap_before_done_is_named(self):
        self.assertAlmostEqual(self.d["after payload, before done"], 44, delta=3)

    def test_what_the_athlete_waits(self):
        # upload-complete 16:17:15 -> done 16:20:37
        self.assertEqual(self.d["upload end -> result"], 202)

    def test_vision_after_the_result(self):
        self.assertEqual(self.d["vision (after result)"], 68)
        self.assertEqual(self.d["total"], 339)

    def test_a_job_without_vision_or_trace_still_reports(self):
        ups = [e for e in FIXTURE["uploads"] if e["event"] != "vision"]
        d = job_timing.durations(ups, None)
        self.assertNotIn("vision (after result)", d)
        self.assertNotIn("pose", d)
        self.assertEqual(d["upload end -> result"], 202)

    def test_table_prints_every_stage(self):
        text = job_timing.table(self.d)
        for k in ("upload", "pose", "upload end -> result", "total"):
            self.assertIn(k, text)


if __name__ == "__main__":
    unittest.main()
