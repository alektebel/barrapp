"""The referral program: codes, one redemption per owner, and credits.

The decisions worth pinning are the ones that fail silently when wrong - who
may cash a code, whether the same code can be cashed twice, and whether a
balance moves by one or by two when two redemptions race. The core is tested
directly, and the LAN stack is exercised over real sockets because it shares
the same module with the Lambda.
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

os.environ.setdefault("JOBS_TABLE", "test-jobs")
os.environ.setdefault("FEEDBACK_TABLE", "test-feedback")
os.environ.setdefault("REFERRALS_TABLE", "test-referrals")
os.environ.setdefault("UPLOADS_TABLE", "test-uploads")
os.environ.setdefault("VIDEO_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")


class TestReferralCore(unittest.TestCase):
    def setUp(self):
        import referral
        self.r = referral
        self.store = referral.MemoryStore()

    def test_a_new_owner_gets_a_code_and_a_starting_balance(self):
        with mock.patch.dict(os.environ, {"STARTING_CREDITS": "3"}):
            row = self.r.ensure(self.store, "u:ana")
        self.assertEqual(row["credits"], 3)
        self.assertEqual(len(row["code"]), self.r.CODE_LEN)
        self.assertTrue(set(row["code"]) <= set(self.r.ALPHABET))

    def test_a_code_is_stable_across_calls(self):
        self.assertEqual(self.r.ensure(self.store, "dev1")["code"],
                         self.r.ensure(self.store, "dev1")["code"])

    def test_redeeming_rewards_both_sides_once(self):
        env = {"STARTING_CREDITS": "0", "REFERRAL_REWARD": "3",
               "WELCOME_CREDITS": "1"}
        with mock.patch.dict(os.environ, env):
            ana = self.r.ensure(self.store, "u:ana")
            code, body = self.r.redeem(self.store, "u:bo", ana["code"])
            self.assertEqual(code, 200)
            self.assertTrue(body["redeemed"])
            self.assertEqual(self.r.status(self.store, "u:ana")["credits"], 3)
            self.assertEqual(self.r.status(self.store, "u:bo")["credits"], 1)
            ana_now = self.r.status(self.store, "u:ana")
            self.assertEqual(ana_now["referrals"], 1)
            self.assertEqual(ana_now["earned"], 3)

    def test_a_second_redemption_by_the_same_owner_is_refused(self):
        """One phone, one code. Not because a loophole is likely, but because
        a check-then-write loses the race two taps on a flaky line create."""
        ana = self.r.ensure(self.store, "u:ana")
        cat = self.r.ensure(self.store, "u:cat")
        self.r.redeem(self.store, "u:bo", ana["code"])
        code, _ = self.r.redeem(self.store, "u:bo", cat["code"])
        self.assertEqual(code, 409)

    def test_you_cannot_redeem_your_own_code(self):
        ana = self.r.ensure(self.store, "u:ana")
        code, _ = self.r.redeem(self.store, "u:ana", ana["code"])
        self.assertEqual(code, 400)

    def test_an_unknown_code_is_a_404(self):
        self.r.ensure(self.store, "u:ana")
        code, _ = self.r.redeem(self.store, "u:ana", "ZZZZZZZZ")
        self.assertEqual(code, 404)

    def test_a_code_is_read_the_way_a_person_types_it(self):
        ana = self.r.ensure(self.store, "u:ana")
        code, _ = self.r.redeem(self.store, "u:bo",
                                " " + ana["code"].lower() + "-")
        self.assertEqual(code, 200)

    def test_a_code_with_no_letters_or_digits_is_refused(self):
        code, _ = self.r.redeem(self.store, "u:bo", "  --  ")
        self.assertEqual(code, 400)

    def test_charging_is_off_unless_the_deployment_turns_it_on(self):
        with mock.patch.dict(os.environ,
                             {"STARTING_CREDITS": "1", "REQUIRE_CREDITS": "0"}):
            for _ in range(5):
                allowed, balance = self.r.charge(self.store, "u:ana")
                self.assertTrue(allowed)
            self.assertEqual(balance, 1, "a free deployment spent a credit")

    def test_charging_consumes_and_then_refuses(self):
        with mock.patch.dict(os.environ,
                             {"STARTING_CREDITS": "2", "REQUIRE_CREDITS": "1"}):
            self.assertEqual(self.r.charge(self.store, "u:ana"), (True, 1))
            self.assertEqual(self.r.charge(self.store, "u:ana"), (True, 0))
            allowed, balance = self.r.charge(self.store, "u:ana")
            self.assertFalse(allowed)
            self.assertEqual(balance, 0)

    def test_a_referral_refills_a_spent_balance(self):
        env = {"STARTING_CREDITS": "0", "REQUIRE_CREDITS": "1",
               "REFERRAL_REWARD": "2"}
        with mock.patch.dict(os.environ, env):
            ana = self.r.ensure(self.store, "u:ana")
            self.assertFalse(self.r.charge(self.store, "u:ana")[0])
            self.r.redeem(self.store, "u:bo", ana["code"])
            self.assertTrue(self.r.charge(self.store, "u:ana")[0])


class TestBumpExpression(unittest.TestCase):
    """The DynamoDB update must be well-formed; a bad one fails on a redeem."""

    def test_add_and_default_produce_a_set_and_an_add(self):
        import handler
        expr, names, values = handler._bump_expression(
            {"credits": 3}, {"referrals": 0, "earned": 0})
        self.assertIn("ADD", expr)
        self.assertIn("SET", expr)
        self.assertIn("if_not_exists", expr)
        self.assertEqual(names["#credits"], "credits")
        self.assertEqual(values[":a_credits"], 3)
        self.assertEqual(values[":d_referrals"], 0)

    def test_a_pure_spend_needs_no_set_clause(self):
        import handler
        expr, names, values = handler._bump_expression({"credits": -1}, {})
        self.assertTrue(expr.startswith("ADD"))
        self.assertNotIn("SET", expr)
        self.assertEqual(values[":a_credits"], -1)


class TestHandlerRoutes(unittest.TestCase):
    """The Lambda's dispatch, so a mistyped path fails here and not in prod."""

    def setUp(self):
        import handler
        self.handler = handler
        self.table = mock.Mock()
        self.table.get_item.return_value = {}
        self.table.put_item.return_value = {}
        self.table.update_item.return_value = {"Attributes": {"credits": 3}}
        patch = mock.patch.object(handler, "referrals_table", self.table)
        patch.start()
        self.addCleanup(patch.stop)

    def _route(self, method, path, body=None):
        event = {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
            "headers": {"x-device-id": "dev-route"},
        }
        if body is not None:
            event["body"] = json.dumps(body)
        return self.handler._route(event)

    def test_get_referral_answers_with_a_code(self):
        resp = self._route("GET", "/v1/referral")
        self.assertEqual(resp["statusCode"], 200)
        self.assertTrue(json.loads(resp["body"])["code"])

    def test_redeeming_an_unknown_code_is_a_404(self):
        resp = self._route("POST", "/v1/referral/redeem", {"code": "ZZZZZZZZ"})
        self.assertEqual(resp["statusCode"], 404)


class TestLocalReferral(unittest.TestCase):
    """The whole program over the sockets the phone actually talks to."""

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

    def _req(self, method, path, body=None, device="dev-referral"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"X-Device-Id": device}
        if body is not None:
            body = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, json.loads(data or b"{}")

    def test_a_device_gets_a_code_and_a_balance(self):
        status, body = self._req("GET", "/v1/referral", device="dev-a")
        self.assertEqual(status, 200)
        self.assertTrue(body["code"])
        self.assertEqual(body["credits"], 3)
        self.assertEqual(body["referrals"], 0)

    def test_redeeming_on_the_lan_moves_the_balance(self):
        _, ana = self._req("GET", "/v1/referral", device="dev-ana")
        status, body = self._req("POST", "/v1/referral/redeem",
                                 {"code": ana["code"]}, device="dev-bo")
        self.assertEqual(status, 200)
        self.assertTrue(body["redeemed"])
        _, ana_after = self._req("GET", "/v1/referral", device="dev-ana")
        status, bo = self._req("GET", "/v1/referral", device="dev-bo")
        self.assertEqual(ana_after["referrals"], 1)
        self.assertGreater(ana_after["credits"], ana["credits"])
        self.assertGreater(bo["credits"], 3)

    def test_jobs_are_charged_only_when_required(self):
        with mock.patch.dict(os.environ, {"REQUIRE_CREDITS": "1",
                                          "STARTING_CREDITS": "2"}):
            device = "dev-charge"
            self.assertEqual(
                self._req("POST", "/v1/jobs", {"exercise": "auto"},
                          device=device)[0], 201)
            self.assertEqual(
                self._req("POST", "/v1/jobs", {"exercise": "auto"},
                          device=device)[0], 201)
            status, body = self._req("POST", "/v1/jobs", {"exercise": "auto"},
                                     device=device)
            self.assertEqual(status, 402)
            self.assertEqual(body["credits"], 0)

    def test_jobs_are_free_when_not_required(self):
        device = "dev-free"
        for _ in range(5):
            status, _ = self._req("POST", "/v1/jobs", {"exercise": "auto"},
                                  device=device)
            self.assertEqual(status, 201)


if __name__ == "__main__":
    unittest.main()
