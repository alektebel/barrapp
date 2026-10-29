"""The one client every model call goes through (server/api/llm.py).

Vision, the objectives chat and the written report each had their own HTTP
code - three User-Agents, three retry policies, three ways to lose a 401. This
pins the shared behaviour once: the cause of a failure is kept, a client error
is not retried, a retired model is caught before the call, the key comes from
the one secret, and every failure logs one parseable line.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "server" / "api")]

import llm  # noqa: E402

BASE, KEY = "https://nan.test/v1", "k"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def reply(content):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def http_error(code, message):
    body = json.dumps({"error": {"message": message}}).encode()
    return urllib.error.HTTPError(f"{BASE}/chat/completions", code, "x", {}, io.BytesIO(body))


class Base(unittest.TestCase):
    def setUp(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        for target, kw in ((llm.time, {"attribute": "sleep"}),):
            p = mock.patch.object(target, kw["attribute"])
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(llm, "model_listed", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def call(self, effects, **kw):
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=effects) as m, \
                redirect_stdout(io.StringIO()) as out:
            r = llm.complete("deepseek-v4-flash", [{"role": "user", "content": "hola"}],
                             base=BASE, key=KEY, **kw)
        return r, m, out.getvalue()


class Complete(Base):
    def test_success(self):
        r, m, _ = self.call([reply("hola")])
        self.assertEqual((r.text, r.error, r.model), ("hola", None, "deepseek-v4-flash"))
        sent = json.loads(m.call_args[0][0].data)
        self.assertEqual(sent["messages"], [{"role": "user", "content": "hola"}])

    def test_system_prompt_is_prepended(self):
        _, m, _ = self.call([reply("x")], system="eres el coach")
        sent = json.loads(m.call_args[0][0].data)
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "eres el coach"})

    def test_json_mode_is_requested_when_asked(self):
        _, m, _ = self.call([reply("{}")], json_mode=True)
        self.assertEqual(json.loads(m.call_args[0][0].data)["response_format"], {"type": "json_object"})

    def test_a_401_keeps_its_cause_and_is_not_retried(self):
        r, m, out = self.call([http_error(401, "no access to the requested model")])
        self.assertEqual(m.call_count, 1)
        self.assertEqual(r.status, 401)
        self.assertIn("no access", r.error)
        self.assertRegex(out, r"\[barra\] llm call failed model=deepseek-v4-flash status=401 ")

    def test_429_and_5xx_are_retried(self):
        r, m, _ = self.call([http_error(429, "slow down"), http_error(503, "busy"), reply("ok")])
        self.assertEqual(m.call_count, 3)
        self.assertEqual(r.text, "ok")

    def test_empty_reply_is_retried_then_named(self):
        r, m, _ = self.call([reply("") for _ in range(llm.ATTEMPTS)])
        self.assertEqual(m.call_count, llm.ATTEMPTS)
        self.assertEqual(r.error, "empty reply")

    def test_budget_caps_the_whole_call_not_each_attempt(self):
        # Three timeouts of 60 s used to hold a failing call for ~183 s.
        clock = iter([0.0, 0.0, 61.0, 99.0, 99.0, 99.0])
        timeouts = []

        def slow(req, timeout):
            timeouts.append(timeout)
            raise TimeoutError("timed out")

        with mock.patch.object(llm.time, "monotonic", side_effect=lambda: next(clock)):
            r, m, _ = self.call(slow, budget=100)
        self.assertEqual(timeouts[0], 60)            # first attempt: the usual timeout
        self.assertLessEqual(timeouts[1], 39)        # second: only what is left
        self.assertEqual(m.call_count, 2)            # third never starts: <8 s left
        self.assertTrue(r.error.startswith("timeout"))

    def test_budget_does_not_cost_quick_failures_their_attempts(self):
        r, m, _ = self.call([reply(""), http_error(503, "busy"), reply("ok")], budget=100)
        self.assertEqual(m.call_count, 3)
        self.assertEqual(r.text, "ok")

    def test_a_retired_model_is_caught_before_the_call(self):
        with mock.patch.object(llm, "model_listed", return_value=False), \
                mock.patch.object(llm.urllib.request, "urlopen") as chat, \
                redirect_stdout(io.StringIO()):
            r = llm.complete("mimo-v2.5", [], base=BASE, key=KEY)
        chat.assert_not_called()
        self.assertEqual(r.error, "model_missing: mimo-v2.5")

    def test_latency_sensitive_call_can_skip_the_redundant_model_listing(self):
        with mock.patch.object(llm, "model_listed", side_effect=AssertionError("preflight called")), \
                mock.patch.object(llm.urllib.request, "urlopen", return_value=reply("ok")):
            r = llm.complete("mimo-v2.6-flash", [], base=BASE, key=KEY,
                             check_model=False)
        self.assertEqual(r.text, "ok")

    def test_last_error_tracks_the_latest_call(self):
        self.call([http_error(401, "x")])
        self.assertIn("401", llm.last_error())
        self.call([reply("ok")])
        self.assertIsNone(llm.last_error())

    def test_unconfigured_is_an_error_not_a_crash(self):
        with mock.patch.object(llm, "config", return_value=None), redirect_stdout(io.StringIO()):
            r = llm.complete("m", [])
        self.assertEqual(r.error, "not_configured")


class Config(unittest.TestCase):
    def setUp(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)

    def test_key_from_the_secret_and_default_base(self):
        with mock.patch.object(llm, "get_nan_key", return_value="sk"), \
                mock.patch.dict(os.environ, {"NAN_BASE_URL": ""}):
            self.assertEqual(llm.config(), ("https://api.nan.builders/v1", "sk"))

    def test_no_key_means_unconfigured(self):
        with mock.patch.object(llm, "get_nan_key", return_value=""):
            self.assertIsNone(llm.config())


class ModelListing(unittest.TestCase):
    def setUp(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)

    def test_fetched_once_and_answers_membership(self):
        listing = lambda *a, **k: FakeResponse(json.dumps({"data": [{"id": "qwen3.8-flash"}]}).encode())
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=listing) as m:
            self.assertTrue(llm.model_listed(BASE, KEY, "qwen3.8-flash"))
            self.assertFalse(llm.model_listed(BASE, KEY, "mimo-v2.5"))
        self.assertEqual(m.call_count, 1)

    def test_an_unreadable_listing_does_not_block(self):
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertTrue(llm.model_listed(BASE, KEY, "anything"))


class OneClient(unittest.TestCase):
    def test_no_module_opens_its_own_connection_to_a_model(self):
        """Only llm.py may POST to /chat/completions."""
        offenders = []
        for p in list((ROOT / "server").glob("*.py")) + list((ROOT / "server" / "api").glob("*.py")):
            if p.name == "llm.py":
                continue
            if "/chat/completions" in p.read_text():
                offenders.append(p.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
