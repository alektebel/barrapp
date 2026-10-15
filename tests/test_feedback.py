"""The feedback contract: a message always reaches the server, and the
optional clip rides the same presigned PUT an upload speaks - on AWS and on
the LAN.

The LAN path was the one that was broken: `POST /v1/feedback` handed back
`/v1/feedback/<id>/video`, but `local_server.py` had no PUT handler for it, so
attaching a clip to feedback worked in production and 404'd against the local
API. These tests pin both halves so the two stop drifting apart.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "api"))

# handler.py reads its table names at import time, like a Lambda does. Set
# before the first import so a bare `pytest` is the whole contract.
os.environ.setdefault("JOBS_TABLE", "test-jobs")
os.environ.setdefault("FEEDBACK_TABLE", "test-feedback")
os.environ.setdefault("REFERRALS_TABLE", "test-referrals")
os.environ.setdefault("UPLOADS_TABLE", "test-uploads")
os.environ.setdefault("VIDEO_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")


class FakeTable:
    """Just enough of DynamoDB to hold a feedback row."""

    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_item(self, Item):  # noqa: N803 - boto3's spelling
        self.items[Item["id"]] = dict(Item)
        return {}


class TestFeedbackEndpoint(unittest.TestCase):
    """The AWS handler's answer to the phone."""

    def setUp(self):
        import handler
        self.handler = handler
        self.table = FakeTable()
        self.s3 = mock.Mock()
        self.s3.generate_presigned_url.return_value = "https://s3.test/put"
        self.patch = mock.patch.multiple(handler, feedback_table=self.table,
                                         s3=self.s3)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_a_message_is_required(self):
        code, _ = self.handler._feedback("dev1", {"message": "   "})
        self.assertEqual(code, 400)
        self.assertEqual(self.table.items, {})

    def test_a_message_is_stored_against_its_owner(self):
        code, body = self.handler._feedback(
            "dev1", {"message": "the score is nonsense", "appVersion": "1.2"})
        self.assertEqual(code, 201)
        row = self.table.items[body["id"]]
        self.assertEqual(row["owner"], "dev1")
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["appVersion"], "1.2")

    def test_the_owner_is_not_echoed_back(self):
        """The row is the server's; the owner column is not the phone's."""
        _, body = self.handler._feedback("dev1", {"message": "x"})
        self.assertNotIn("owner", body)

    def test_a_clip_gets_a_presigned_put_and_a_key(self):
        code, body = self.handler._feedback(
            "dev1", {"message": "x", "video": True})
        self.assertEqual(code, 201)
        self.assertEqual(body["uploadMethod"], "PUT")
        self.assertEqual(body["uploadUrl"], "https://s3.test/put")
        self.assertEqual(self.table.items[body["id"]]["videoKey"],
                         f"feedback/dev1/{body['id']}.mp4")

    def test_no_clip_means_no_upload_url(self):
        _, body = self.handler._feedback("dev1", {"message": "x"})
        self.assertNotIn("uploadUrl", body)

    def test_a_long_message_is_refused(self):
        code, _ = self.handler._feedback("dev1", {"message": "x" * 5001})
        self.assertEqual(code, 400)


class TestLocalFeedbackClip(unittest.TestCase):
    """End-to-end against the real sockets the phone talks to on the LAN."""

    def setUp(self):
        import local_server
        self.mod = local_server
        self.server = local_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), local_server.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        quiet = mock.patch.object(local_server.Handler, "log_message",
                                  lambda *a, **k: None)
        quiet.start()
        self.addCleanup(quiet.stop)

    def _req(self, method, path, body=None, device="dev-feedback"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"X-Device-Id": device}
        if body is not None and isinstance(body, dict):
            body = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_a_feedback_clip_reaches_disk(self):
        status, data = self._req(
            "POST", "/v1/feedback", {"message": "a clip", "video": True})
        self.assertEqual(status, 201)
        created = json.loads(data)
        self.assertEqual(created["uploadMethod"], "PUT")
        clip = b"x" * 20000
        status, _ = self._req("PUT", created["uploadUrl"], clip)
        self.assertEqual(status, 200)
        stored = self.mod.DATA / f"feedback-{created['id']}.mp4"
        try:
            self.assertTrue(stored.exists())
            self.assertEqual(stored.stat().st_size, len(clip))
        finally:
            stored.unlink(missing_ok=True)

    def test_another_device_cannot_write_the_clip(self):
        status, data = self._req(
            "POST", "/v1/feedback", {"message": "mine", "video": True})
        created = json.loads(data)
        status, _ = self._req("PUT", created["uploadUrl"], b"x" * 100,
                              device="someone-else")
        self.assertEqual(status, 404)

    def test_a_message_without_a_clip_still_lands(self):
        status, data = self._req(
            "POST", "/v1/feedback", {"message": "no clip"})
        self.assertEqual(status, 201)
        self.assertNotIn("uploadUrl", json.loads(data))

    def test_small_job_upload_can_refresh_url_and_submit_only_after_full_put(self):
        status, data = self._req("POST", "/v1/jobs", {"exercise": "auto"})
        self.assertEqual(status, 201)
        job = json.loads(data)
        path = f"/v1/jobs/{job['id']}/upload-url"
        status, refreshed = self._req("POST", path, {})
        self.assertEqual(status, 200)
        upload = json.loads(refreshed)
        self.assertEqual(upload["uploadMethod"], "PUT")

        status, _ = self._req("POST", f"/v1/jobs/{job['id']}/submit", {})
        self.assertEqual(status, 409)
        status, _ = self._req("PUT", upload["uploadUrl"], b"x" * 20000)
        self.assertEqual(status, 200)
        status, _ = self._req("POST", f"/v1/jobs/{job['id']}/submit", {})
        self.assertEqual(status, 202)

    def test_another_device_cannot_refresh_a_job_upload_url(self):
        status, data = self._req("POST", "/v1/jobs", {"exercise": "auto"})
        self.assertEqual(status, 201)
        job = json.loads(data)
        status, _ = self._req("POST", f"/v1/jobs/{job['id']}/upload-url", {},
                              device="another-device")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
