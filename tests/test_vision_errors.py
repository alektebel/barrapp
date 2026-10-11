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


class Base(unittest.TestCase):
    def setUp(self):
        vision.reset_state()
        self.addCleanup(vision.reset_state)
        sleep = mock.patch.object(vision.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)
        # Model check passes unless a test says otherwise.
        self.models = mock.patch.object(vision, "_model_listed", return_value=True)
        self.models.start()
        self.addCleanup(self.models.stop)

    def call(self, side_effect):
        with mock.patch.object(vision.urllib.request, "urlopen", side_effect=side_effect) as m, \
                redirect_stdout(io.StringIO()) as out:
            result = vision._chat_result(BASE, KEY, "mimo-v2.6-flash", "sys", [])
        return result, m, out.getvalue()


class ChatResult(Base):
    def test_success_carries_text_and_no_error(self):
        r, m, _ = self.call([reply('{"ok": true}')])
        self.assertEqual(r.text, '{"ok": true}')
        self.assertIsNone(r.error)
        self.assertEqual(r.model, "mimo-v2.6-flash")

    def test_a_401_keeps_its_cause_and_is_not_retried(self):
        r, m, _ = self.call([http_error(401, "This API key does not have access to the requested model.")])
        self.assertIsNone(r.text)
        self.assertEqual(r.status, 401)
        self.assertIn("401", r.error)
        self.assertIn("does not have access", r.error)
        self.assertEqual(m.call_count, 1)

    def test_a_server_error_is_retried(self):
        r, m, _ = self.call([http_error(503, "busy") for _ in range(vision.CHAT_ATTEMPTS)])
        self.assertEqual(m.call_count, vision.CHAT_ATTEMPTS)
        self.assertIn("503", r.error)

    def test_an_empty_reply_is_retried_then_named(self):
        r, m, _ = self.call([reply("") for _ in range(vision.CHAT_ATTEMPTS)])
        self.assertEqual(m.call_count, vision.CHAT_ATTEMPTS)
        self.assertEqual(r.error, "empty reply")

    def test_a_retry_that_succeeds_is_a_success(self):
        r, _, _ = self.call([reply(""), reply("hola")])
        self.assertEqual(r.text, "hola")
        self.assertIsNone(r.error)

    def test_a_timeout_is_named(self):
        r, _, _ = self.call([TimeoutError("timed out")] * vision.CHAT_ATTEMPTS)
        self.assertIn("timeout", r.error.lower())

    def test_each_failure_logs_one_parseable_line(self):
        _, _, out = self.call([http_error(401, "no access")])
        self.assertRegex(out, r"\[barra\] vision call failed model=mimo-v2\.6-flash status=401 ")

    def test_legacy_chat_still_returns_text_or_none(self):
        with mock.patch.object(vision.urllib.request, "urlopen",
                               side_effect=[http_error(401, "x")]), redirect_stdout(io.StringIO()):
            self.assertIsNone(vision._chat(BASE, KEY, "m", "s", []))


class LastError(Base):
    def test_the_last_failure_is_remembered_for_the_trace(self):
        self.call([http_error(401, "no access")])
        self.assertIn("401", vision.last_error())

    def test_a_success_clears_it(self):
        self.call([http_error(401, "no access")])
        self.call([reply("ok")])
        self.assertIsNone(vision.last_error())


class SkipReason(Base):
    def test_no_key_means_not_configured(self):
        with mock.patch.object(vision, "_config", return_value=None):
            self.assertEqual(vision.skip_reason(), "not_configured")

    def test_a_failed_call_is_not_called_unconfigured(self):
        self.call([http_error(401, "no access")])
        with mock.patch.object(vision, "_config", return_value=(BASE, KEY, "m")):
            self.assertTrue(vision.skip_reason().startswith("call_failed: 401"))

    def test_configured_and_no_failure_means_no_usable_reply(self):
        with mock.patch.object(vision, "_config", return_value=(BASE, KEY, "m")):
            self.assertEqual(vision.skip_reason(), "no_usable_reply")


class ModelCheck(unittest.TestCase):
    def setUp(self):
        vision.reset_state()
        self.addCleanup(vision.reset_state)

    def listed(self, *ids):
        with mock.patch.object(vision.urllib.request, "urlopen", return_value=models(*ids)) as m:
            return vision._model_listed(BASE, KEY, "mimo-v2.6-flash"), m

    def test_a_listed_model_passes(self):
        self.assertTrue(self.listed("qwen3.8-flash", "mimo-v2.6-flash")[0])

    def test_a_retired_model_is_caught_before_the_call(self):
        self.assertFalse(self.listed("qwen3.8-flash")[0])

    def test_the_listing_is_fetched_once_per_container(self):
        with mock.patch.object(vision.urllib.request, "urlopen",
                               side_effect=lambda *a, **k: models("mimo-v2.6-flash")) as m:
            vision._model_listed(BASE, KEY, "mimo-v2.6-flash")
            vision._model_listed(BASE, KEY, "qwen3.8-flash")
        self.assertEqual(m.call_count, 1)

    def test_an_unreachable_listing_does_not_block_the_call(self):
        # The check is a guard, not a gate: if /models itself fails, try anyway.
        with mock.patch.object(vision.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertTrue(vision._model_listed(BASE, KEY, "mimo-v2.6-flash"))

    def test_a_missing_model_fails_with_its_name(self):
        with mock.patch.object(vision, "_model_listed", return_value=False), \
                mock.patch.object(vision.urllib.request, "urlopen") as chat, \
                redirect_stdout(io.StringIO()):
            r = vision._chat_result(BASE, KEY, "mimo-v2.5", "s", [])
        chat.assert_not_called()
        self.assertEqual(r.error, "model_missing: mimo-v2.5")


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
                for p in (ROOT / folder).rglob("*.py")
                if '"mimo-v2.5"' in p.read_text(errors="ignore")]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
