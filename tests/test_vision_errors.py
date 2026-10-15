"""A failed vision call must say why, not look like an empty reply.

From 2026-09-17 every vision call in production got
  401 "This API key does not have access to the requested model."
because nan.builders retired mimo-v2.5. `_chat` swallowed that as None, the
localizer logged "no JSON in the reply (0 chars)", and the trace wrote
"no vision endpoint configured" - three lies about one 401, for four weeks.

These tests pin: the cause is kept, a client error is not retried, a missing
model is caught before the call, one log line per failure feeds the metric,
and the one default model matches what the stack deploys.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

import vision  # noqa: E402

BASE, KEY = "https://nan.test/v1", "k"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def reply(content):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def http_error(code, message):
    body = json.dumps({"error": {"message": message, "code": str(code)}}).encode()
    return urllib.error.HTTPError(f"{BASE}/chat/completions", code, "x", {}, io.BytesIO(body))


def models(*ids):
    return FakeResponse(json.dumps({"data": [{"id": i} for i in ids]}).encode())


class Delegation(unittest.TestCase):
    """The HTTP behaviour itself is tests/test_llm.py; vision only has to hand
    its stills to the one client and read the cause back."""

    def setUp(self):
        vision.reset_state()
        self.addCleanup(vision.reset_state)

    def test_chat_hands_system_and_stills_to_the_client(self):
        content = [{"type": "text", "text": "frames"}]
        with mock.patch.object(vision.llm, "complete",
                               return_value=vision.llm.ChatResult("mimo-v2.6-flash", text="ok")) as c:
            self.assertEqual(vision._chat(BASE, KEY, "mimo-v2.6-flash", "sys", content), "ok")
        args, kw = c.call_args
        self.assertEqual(args, ("mimo-v2.6-flash", [{"role": "user", "content": content}]))
        self.assertEqual((kw["system"], kw["base"], kw["key"]), ("sys", BASE, KEY))
        self.assertTrue(kw["check_model"])

    def test_latency_critical_locator_skips_separate_models_preflight(self):
        with mock.patch.object(vision, "_config", return_value=(BASE, KEY, "m")), \
                mock.patch("barra.ingest.probe_video", return_value={"ok": True, "duration_s": 10}), \
                mock.patch("barra.frames.grab_frames", return_value=[(0, Path("/tmp/frame.jpg"))]), \
                mock.patch.object(vision, "_images", return_value=[{"type": "image_url"}]), \
                mock.patch.object(vision, "_chat", return_value=None) as chat:
            self.assertIsNone(vision.locate_exercise("clip.mp4", "/tmp/locate"))
        self.assertFalse(chat.call_args.kwargs["check_model"])

    def test_a_401_reaches_the_trace_reason(self):
        with mock.patch.object(vision.llm, "model_listed", return_value=True), \
                mock.patch.object(vision.llm.urllib.request, "urlopen",
                                  side_effect=[http_error(401, "no access")]), \
                redirect_stdout(io.StringIO()):
            self.assertIsNone(vision._chat(BASE, KEY, "mimo-v2.6-flash", "s", []))
        with mock.patch.object(vision, "_config", return_value=(BASE, KEY, "m")):
            self.assertTrue(vision.skip_reason().startswith("call_failed: 401"))


class SkipReason(unittest.TestCase):
    def setUp(self):
        vision.reset_state()
        self.addCleanup(vision.reset_state)

    def test_no_key_means_not_configured(self):
        with mock.patch.object(vision, "_config", return_value=None):
            self.assertEqual(vision.skip_reason(), "not_configured")

    def test_configured_and_no_failure_means_no_usable_reply(self):
        with mock.patch.object(vision, "_config", return_value=(BASE, KEY, "m")):
            self.assertEqual(vision.skip_reason(), "no_usable_reply")


class Spanish(unittest.TestCase):
    def test_the_technique_prompt_asks_for_spanish_prose_and_keeps_codes(self):
        self.assertIn("in Spanish from Spain", vision.SYSTEM)
        self.assertIn("they are codes, not prose", vision.SYSTEM)


class OneDefault(unittest.TestCase):
    def test_the_default_model_is_one_nan_still_serves(self):
        self.assertEqual(vision.VISION_MODEL_DEFAULT, "mimo-v2.6-flash")
        self.assertEqual(vision.LOCALIZE_MODEL_DEFAULT, vision.VISION_MODEL_DEFAULT)

    def test_the_stack_deploys_the_same_model(self):
        template = (ROOT / "server" / "template.yaml").read_text()
        for var in ("BARRA_VISION_MODEL", "BARRA_LOCALIZE_MODEL"):
            m = re.search(rf"{var}:\s*(\S+)", template)
            self.assertIsNotNone(m, var)
            self.assertEqual(m.group(1), vision.VISION_MODEL_DEFAULT, var)

    def test_no_code_still_names_the_retired_model(self):
        hits = [p.relative_to(ROOT).as_posix()
                for folder in ("server", "barra", "scripts")
                for p in (ROOT / folder).rglob("*.py") if "vendor" not in p.parts
                if '"mimo-v2.5"' in p.read_text(errors="ignore")]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
