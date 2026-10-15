"""scripts/job_timing.py: where a production job's time went.

The fixture is job 31103ccedfc3 (2026-10-11), recorded from production with
the owner stripped. Its numbers are the "after deploy 4" row of
docs/SPEED-PLAN.md, and they exposed a stage nobody had named: ~44 s between
the payload being ready and `done` being written (cutting and re-uploading the
stored clip).
"""
from __future__ import annotations

import json
import subprocess
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

    def test_round_two_includes_upload_in_the_server_total(self):
        self.assertEqual(self.d["upload start -> server result"], 271)

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


class RoundTwoTiming(unittest.TestCase):
    def test_dispatch_queue_and_worker_import_are_separate_intervals(self):
        events = [
            {"event": "dispatch-started", "at": "2026-10-12T10:00:00.000Z"},
            {"event": "dispatch-accepted", "at": "2026-10-12T10:00:00.040Z"},
            {"event": "worker-entry", "at": "2026-10-12T10:00:00.190Z"},
            {"event": "worker-ready", "at": "2026-10-12T10:00:00.490Z"},
        ]
        result = job_timing.durations(events, None)
        self.assertAlmostEqual(result["worker dispatch request"], 0.040)
        self.assertAlmostEqual(result["accepted -> worker entry"], 0.150)
        self.assertAlmostEqual(result["worker handler -> imports ready"], 0.300)

    def test_clock_inversion_does_not_report_negative_dispatch(self):
        events = [
            {"event": "dispatch-accepted", "at": "2026-10-12T10:00:00.100Z"},
            {"event": "worker-entry", "at": "2026-10-12T10:00:00.000Z"},
        ]
        self.assertNotIn("accepted -> worker entry", job_timing.durations(events, None))

    def test_fractional_seconds_cannot_turn_a_slow_result_into_a_pass(self):
        events = [
            {"event": "upload-started", "at": "2026-10-12T10:00:00.950Z"},
            {"event": "upload-complete", "at": "2026-10-12T10:00:03.125Z"},
            {"event": "submitted", "at": "2026-10-12T10:00:03.225Z"},
            {"event": "stage", "detail": "receiving the clip",
             "at": "2026-10-12T10:00:03.475Z"},
            {"event": "stage", "detail": "opening the clip",
             "at": "2026-10-12T10:00:03.800Z"},
            {"event": "done", "at": "2026-10-12T10:00:15.960Z"},
        ]
        result = job_timing.durations(events, None)
        self.assertAlmostEqual(result["upload"], 2.175)
        self.assertAlmostEqual(result["submit"], 0.100)
        self.assertAlmostEqual(result["queue"], 0.250)
        self.assertAlmostEqual(result["download+dispatch"], 0.325)
        self.assertAlmostEqual(result["upload start -> server result"], 15.010)
        self.assertIn("15.010", job_timing.table(result))

    def test_offsets_and_append_order_do_not_change_the_first_result(self):
        events = [
            {"event": "done", "at": "2026-10-12T12:00:20.000+02:00"},
            {"event": "upload-started", "at": "2026-10-12T10:00:00.100Z"},
            {"event": "done", "at": "2026-10-12T10:00:14.999Z"},
        ]
        result = job_timing.durations(events, None)
        self.assertAlmostEqual(result["upload start -> server result"], 14.899)

    def test_missing_start_cannot_be_substituted_with_upload_completion(self):
        events = [
            {"event": "upload-complete", "at": "2026-10-12T10:00:10Z"},
            {"event": "done", "at": "2026-10-12T10:00:20Z"},
        ]
        self.assertNotIn("upload start -> server result", job_timing.durations(events, None))

    def test_deferred_prose_does_not_move_the_first_result(self):
        events = [
            {"event": "job-created", "at": "2026-10-12T10:00:00Z"},
            {"event": "upload-started", "at": "2026-10-12T10:00:00Z"},
            {"event": "done", "at": "2026-10-12T10:00:14Z"},
            {"event": "vision", "at": "2026-10-12T10:00:17Z"},
            {"event": "prose", "at": "2026-10-12T10:00:25.100Z"},
        ]
        result = job_timing.durations(events, None)
        self.assertEqual(result["upload start -> server result"], 14.0)
        self.assertAlmostEqual(result["prose (after result)"], 11.1)
        self.assertAlmostEqual(result["total"], 25.1)

    def test_fusion_wait_is_visible_inside_measurement(self):
        trace = {"entries": [
            {"message": "entered probe", "atMs": 50},
            {"message": "pose backend", "atMs": 8050},
            {"message": "entered fusion", "stage": "fusion", "atMs": 8100},
            {"message": "fusion", "stage": "fusion", "atMs": 20000},
            {"message": "entered payload", "atMs": 20125},
            # The deferred passes append another payload; first result wins.
            {"message": "entered payload", "atMs": 30000},
        ]}
        result = job_timing.durations([], trace)
        self.assertAlmostEqual(result["fusion (includes vision wait)"], 11.9)
        self.assertAlmostEqual(result["measure+report"], 12.075)
        self.assertAlmostEqual(result["pose"], 8.0)

    def test_visual_count_rescue_duration_is_reported_from_trace(self):
        trace = {"entries": [{
            "message": "visual count rescue",
            "data": {"durationMs": 2350, "outcome": "accepted"},
        }]}

        result = job_timing.durations([], trace)

        self.assertAlmostEqual(result["visual count rescue"], 2.35)

    def test_locator_and_fusion_vote_wait_are_reported_separately(self):
        events = [
            {"event": "worker-timing", "at": "2026-10-13T10:00:08.300Z",
             "fusionWaitMs": 6300, "fusionOutcome": "ready",
             "locatorMsAtResult": 7200, "locatorCompleteAtResult": True,
             "stageWriteCount": 2, "stageTableUs": 21000,
             "stageUploadLogUs": 41000, "stageTotalUs": 62000,
             "stageSlowestName": "locating", "stageSlowestUs": 32000,
             "clipDownloadUs": 250000, "processingStateWriteUs": 5000,
             "resultWriteUs": 15000},
            {"event": "locator-finished", "at": "2026-10-13T10:00:08.310Z",
             "durationMs": 7200, "resultPersisted": True,
             "postResultWaitMs": 0, "usable": True},
        ]
        result = job_timing.durations(events, None)
        self.assertAlmostEqual(result["fusion vision wait"], 6.3)
        self.assertAlmostEqual(result["locator before result"], 7.2)
        self.assertAlmostEqual(result["locator after result wait"], 0.0)
        self.assertAlmostEqual(result["stage table writes"], 0.021)
        self.assertAlmostEqual(result["stage upload-log writes"], 0.041)
        self.assertAlmostEqual(result["stage telemetry writes"], 0.062)
        self.assertAlmostEqual(result["slowest stage telemetry write"], 0.032)
        self.assertAlmostEqual(result["clip download"], 0.25)
        self.assertAlmostEqual(result["processing status write"], 0.005)
        self.assertAlmostEqual(result["first result write"], 0.015)

    def test_late_locator_is_separated_from_first_result(self):
        events = [
            {"event": "worker-timing", "at": "2026-10-13T10:00:12Z",
             "fusionWaitMs": 5000, "fusionOutcome": "timeout",
             "locatorMsAtResult": None, "locatorCompleteAtResult": False},
            {"event": "locator-finished", "at": "2026-10-13T10:00:16Z",
             "durationMs": 9000, "resultPersisted": True,
             "postResultWaitMs": 4000, "usable": True},
        ]
        result = job_timing.durations(events, None)
        self.assertAlmostEqual(result["fusion vision wait"], 5.0)
        self.assertNotIn("locator before result", result)
        self.assertAlmostEqual(result["locator"], 9.0)
        self.assertAlmostEqual(result["locator after result wait"], 4.0)

    def test_fixture_cli_needs_no_aws_and_does_not_claim_phone_latency(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "job_timing.py"),
             "--fixture", str(ROOT / "tests" / "fixtures" / "job_timing_31103ccedfc3.json")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("upload start -> server result", completed.stdout)
        self.assertIn("phone rendering is not measured", completed.stdout)


if __name__ == "__main__":
    unittest.main()
