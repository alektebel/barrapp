"""The upload log, and the sweep that closes an abandoned upload out.

These are the regressions this suite exists for, each one a thing that was
actually found in the live stack on 2026-09-13:

  * nine jobs read "the clip was never finished uploading" with no record of
    what the phone was doing when it stopped;
  * six multipart uploads had been accruing storage since the day they were
    started, invisible to ListObjects and untouched by the expiry rule;
  * eight rows sat in `created`/`queued` forever because reaping only ever
    happened on a read, and nothing read them;
  * a 17-byte .mp4 came out of a "successful" upload.

Everything here runs against fakes. The point is the decisions - what gets
recorded, what gets reaped, what gets refused - not boto3.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

# handler.py, sweeper.py and uploads.py read their table names at import time,
# the way a Lambda does. Set before the first import rather than asked of
# whoever runs pytest, so `pytest` with no arguments is the whole contract.
os.environ.setdefault("JOBS_TABLE", "test-jobs")
os.environ.setdefault("FEEDBACK_TABLE", "test-feedback")
os.environ.setdefault("REFERRALS_TABLE", "test-referrals")
os.environ.setdefault("UPLOADS_TABLE", "test-uploads")
os.environ.setdefault("VIDEO_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")


def _stamp(minutes_ago: float) -> str:
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeTable:
    """Enough DynamoDB to hold rows and refuse a conditional write."""

    def __init__(self, items=None, key="id"):
        self.key = key
        self.items = {i[key]: dict(i) for i in (items or [])}
        self.updates = []

    def get_item(self, Key):  # noqa: N803 - boto3's spelling
        item = self.items.get(Key[self.key])
        return {"Item": dict(item)} if item else {}

    def scan(self, **kwargs):
        return {"Items": [dict(i) for i in self.items.values()]}

    def update_item(self, Key, **kwargs):  # noqa: N803
        ident = Key[self.key]
        self.updates.append({"key": ident, **kwargs})
        row = self.items.setdefault(ident, {self.key: ident})
        values = kwargs.get("ExpressionAttributeValues") or {}
        expected = kwargs.get("_expect_status")
        if expected is not None and row.get("status") != expected:
            raise RuntimeError("ConditionalCheckFailedException")
        if ":failed" in values:
            row["status"] = values[":failed"]
            row["error"] = values.get(":err")
        return {}


class TestRecorder(unittest.TestCase):
    """uploads.record must never be the reason an upload fails."""

    def test_record_keeps_subsecond_time_for_the_fifteen_second_budget(self):
        table = FakeTable(key="jobId")
        patch, uploads = self._module(table)
        instant = datetime(2026, 10, 12, 10, 0, 15, 960000, tzinfo=timezone.utc)
        with patch, mock.patch.object(uploads, "datetime") as clock:
            clock.now.return_value = instant
            self.assertTrue(uploads.record("job1", "dev1", "done"))
        recorded = table.updates[0]["ExpressionAttributeValues"][":one"][0]["at"]
        self.assertEqual(datetime.fromisoformat(recorded), instant)
        self.assertTrue(recorded.endswith("Z"))

    def _module(self, table):
        import uploads
        return mock.patch.object(uploads, "_table", table), uploads

    def test_an_event_is_appended_to_the_job_s_row(self):
        table = FakeTable(key="jobId")
        patch, uploads = self._module(table)
        with patch:
            self.assertTrue(uploads.record("job1", "dev1", "upload-started", "x"))
        self.assertEqual(table.updates[0]["key"], "job1")
        events = table.updates[0]["ExpressionAttributeValues"][":one"]
        self.assertEqual(events[0]["event"], "upload-started")
        self.assertEqual(events[0]["level"], "info")

    def test_a_store_that_is_down_does_not_raise(self):
        table = FakeTable(key="jobId")
        table.update_item = mock.Mock(side_effect=RuntimeError("throttled"))
        patch, uploads = self._module(table)
        with patch:
            self.assertFalse(uploads.record("job1", "dev1", "part-presigned"))

    def test_no_table_configured_is_not_an_error(self):
        import uploads
        with mock.patch.object(uploads, "_table", None):
            self.assertFalse(uploads.record("job1", "dev1", "anything"))

    def test_floats_and_empty_strings_are_made_storable(self):
        """DynamoDB rejects both. Neither is worth a lost event."""
        import uploads
        from decimal import Decimal
        cleaned = uploads._clean({"event": "x", "detail": "", "secs": 1.5})
        self.assertNotIn("detail", cleaned)
        self.assertEqual(cleaned["secs"], Decimal("1.5"))

    def test_a_long_detail_is_truncated_rather_than_refused(self):
        table = FakeTable(key="jobId")
        patch, uploads = self._module(table)
        with patch:
            uploads.record("job1", "dev1", "retry", "x" * 5000)
        stored = table.updates[0]["ExpressionAttributeValues"][":one"][0]["detail"]
        self.assertEqual(len(stored), uploads.MAX_DETAIL_CHARS)


class TestSweeper(unittest.TestCase):
    """The clock that reaches the jobs a read never will."""

    def _sweeper(self, table, s3):
        import sweeper
        return mock.patch.multiple(sweeper, table=table, s3=s3), sweeper

    def test_a_job_stuck_past_the_window_is_failed_with_a_reason(self):
        table = FakeTable([
            {"id": "old", "owner": "dev", "status": "created",
             "createdAt": _stamp(120)},
        ])
        patch, sweeper = self._sweeper(table, mock.Mock())
        with patch, mock.patch("uploads.record") as rec:
            reaped = sweeper.reap_jobs()
        self.assertEqual([r["id"] for r in reaped], ["old"])
        self.assertEqual(table.items["old"]["status"], "failed")
        self.assertIn("la subida del vídeo no llegó a terminar", table.items["old"]["error"])
        rec.assert_called_once()
        self.assertEqual(rec.call_args[0][2], "reaped")

    def test_a_job_inside_the_window_is_left_alone(self):
        """A clip still uploading is not a stuck clip."""
        table = FakeTable([
            {"id": "fresh", "owner": "dev", "status": "created",
             "createdAt": _stamp(5)},
        ])
        patch, sweeper = self._sweeper(table, mock.Mock())
        with patch, mock.patch("uploads.record"):
            self.assertEqual(sweeper.reap_jobs(), [])
        self.assertEqual(table.items["fresh"]["status"], "created")

    def test_a_finished_job_is_never_touched(self):
        table = FakeTable([
            {"id": "good", "owner": "dev", "status": "done",
             "createdAt": _stamp(9999), "result": {"n_reps": 4}},
        ])
        patch, sweeper = self._sweeper(table, mock.Mock())
        with patch, mock.patch("uploads.record"):
            self.assertEqual(sweeper.reap_jobs(), [])
        self.assertEqual(table.items["good"]["status"], "done")

    def test_each_stuck_status_gets_its_own_sentence(self):
        """"never picked up" and "died while measuring" are different
        problems, and a user reading the message should be able to tell."""
        import sweeper
        # Spanish: the phone shows these as they are (the API zip has no
        # barra, so no catalog to translate them on the way out).
        self.assertIn("la subida del vídeo no llegó a terminar", sweeper._reason("created", 60))
        self.assertIn("el análisis no llegó a empezar", sweeper._reason("queued", 60))
        self.assertIn("el análisis se interrumpió mientras medía", sweeper._reason("processing", 60))
        self.assertIn("(atascado 60 min)", sweeper._reason("queued", 60))

    def test_an_abandoned_multipart_upload_is_aborted(self):
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = [{
            "Uploads": [{
                "Key": "dev1/job9.mp4", "UploadId": "u1",
                "Initiated": datetime.now(timezone.utc) - timedelta(days=3),
            }],
        }]
        patch, sweeper = self._sweeper(FakeTable(), s3)
        with patch, mock.patch("uploads.record") as rec:
            aborted = sweeper.abort_stale_uploads()
        self.assertEqual(len(aborted), 1)
        s3.abort_multipart_upload.assert_called_once()
        # The job id has to survive: it is the only link back to the row.
        self.assertEqual(rec.call_args[0][0], "job9")
        self.assertEqual(rec.call_args[0][1], "dev1")

    def test_an_upload_still_in_its_window_is_not_aborted(self):
        """A phone on a slow connection is still uploading. Cutting it off
        would turn a slow upload into the failure this is meant to record."""
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = [{
            "Uploads": [{
                "Key": "dev1/fresh.mp4", "UploadId": "u2",
                "Initiated": datetime.now(timezone.utc) - timedelta(minutes=10),
            }],
        }]
        patch, sweeper = self._sweeper(FakeTable(), s3)
        with patch, mock.patch("uploads.record"):
            self.assertEqual(sweeper.abort_stale_uploads(), [])
        s3.abort_multipart_upload.assert_not_called()


class TestSweepIsolation(unittest.TestCase):
    """One half of the sweep failing must not discard the other's work.

    The first live invocation died on a missing s3:ListBucketMultipartUploads
    and returned nothing, even though the reap before it had already failed
    eight stuck rows correctly. The result has to survive the other half.
    """

    def test_a_failing_abort_does_not_lose_the_reap(self):
        import sweeper
        with mock.patch.object(sweeper, "reap_jobs", return_value=[{"id": "a", "was": "created", "ageMin": 90}]), \
             mock.patch.object(sweeper, "abort_stale_uploads",
                               side_effect=RuntimeError("AccessDenied")):
            out = sweeper.sweep()
        self.assertEqual(out["reaped"], 1)
        self.assertEqual(out["aborted"], 0)
        self.assertIn("abort failed", out["errors"][0])

    def test_a_failing_reap_does_not_lose_the_aborts(self):
        import sweeper
        with mock.patch.object(sweeper, "reap_jobs", side_effect=RuntimeError("throttled")), \
             mock.patch.object(sweeper, "abort_stale_uploads",
                               return_value=[{"key": "d/j.mp4", "initiated": "x"}]):
            out = sweeper.sweep()
        self.assertEqual(out["aborted"], 1)
        self.assertIn("reap failed", out["errors"][0])

    def test_a_clean_sweep_reports_no_errors_key(self):
        """A quiet success must not look like a suppressed failure."""
        import sweeper
        with mock.patch.object(sweeper, "reap_jobs", return_value=[]), \
             mock.patch.object(sweeper, "abort_stale_uploads", return_value=[]):
            out = sweeper.sweep()
        self.assertNotIn("errors", out)


class TestClipFloor(unittest.TestCase):
    def test_the_floor_is_below_any_real_capture_and_above_a_dead_stream(self):
        """A 17-byte object came out of a 'successful' upload once. The floor
        has to refuse that without ever refusing a short real clip."""
        import handler
        self.assertGreater(handler.MIN_CLIP_BYTES, 17)
        self.assertLess(handler.MIN_CLIP_BYTES, 200 * 1024)

    def test_the_local_server_applies_the_same_floor(self):
        """Parity matters: a truncated clip must fail at the same seam on LAN
        as it does on AWS, or local testing stops predicting production."""
        import handler
        import local_server
        self.assertEqual(local_server.MIN_CLIP_BYTES, handler.MIN_CLIP_BYTES)


if __name__ == "__main__":
    unittest.main()
