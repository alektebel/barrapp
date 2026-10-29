"""The exercise the athlete declares when uploading.

The pipeline resolves a requested movement with a function that raises
SystemExit on a name it does not know, so the API has to reject anything that
is not in the catalog before it reaches the worker."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

os.environ.setdefault("JOBS_TABLE", "test-jobs")
os.environ.setdefault("FEEDBACK_TABLE", "test-feedback")
os.environ.setdefault("REFERRALS_TABLE", "test-referrals")
os.environ.setdefault("UPLOADS_TABLE", "test-uploads")
os.environ.setdefault("VIDEO_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")


class FakeTable:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, Item):  # noqa: N803 - boto3's spelling
        self.items[Item["id"]] = dict(Item)
        return {}


class TestDeclaredExercise(unittest.TestCase):
    def setUp(self):
        import handler
        self.handler = handler
        self.table = FakeTable()
        s3 = mock.Mock()
        s3.generate_presigned_url.return_value = "https://s3.test/put"
        patch = mock.patch.multiple(handler, table=self.table, s3=s3)
        patch.start()
        self.addCleanup(patch.stop)
        charge = mock.patch.object(handler.referral, "charge",
                                   return_value=(True, 0))
        charge.start()
        self.addCleanup(charge.stop)
        uploads = mock.patch.object(handler.uploads, "record")
        uploads.start()
        self.addCleanup(uploads.stop)

    def _create(self, body: dict):
        event = {"requestContext": {"http": {"method": "POST"}},
                 "rawPath": "/v1/jobs",
                 "headers": {"x-device-id": "dev1"},
                 "body": json.dumps(body)}
        resp = self.handler._route(event)
        return resp["statusCode"], json.loads(resp["body"])

    def test_nothing_declared_is_auto(self):
        code, _ = self._create({"exercise": "auto"})
        self.assertEqual(201, code)
        self.assertEqual(["auto"], [i["exercise"] for i in self.table.items.values()])
        self.assertEqual("auto", self.handler.declared_exercise(None))
        self.assertEqual("auto", self.handler.declared_exercise(""))

    def test_a_catalog_movement_is_stored_as_declared(self):
        code, _ = self._create({"exercise": "dip"})
        self.assertEqual(201, code)
        self.assertEqual("dip", next(iter(self.table.items.values()))["exercise"])

    def test_separators_are_forgiving(self):
        for raw in ("pull-up", "Pull Up", " pull_up "):
            self.assertEqual("pull_up", self.handler.declared_exercise(raw), raw)

    def test_an_unknown_movement_is_rejected_before_anything_is_stored(self):
        for raw in ("deadlift_but_wrong", "hanging leg raise", 7, ["dip"]):
            self.table.items.clear()
            code, body = self._create({"exercise": raw})
            self.assertEqual(400, code, raw)
            self.assertIn("unknown exercise", body["error"])
            self.assertEqual({}, self.table.items)

    def test_the_literal_matches_the_catalog(self):
        try:
            from barra.movements import MOVEMENTS
        except ImportError:
            self.skipTest("barra needs numpy to import")
        self.assertEqual(set(MOVEMENTS), set(self.handler.DECLARABLE_EXERCISES))


if __name__ == "__main__":
    unittest.main()
