"""Barrass' Astra DB store, tested without a live database.

The store must be optional and lazy (no astrapy import / client / network when
Astra is not configured), degrade honestly (a failed write returns
{"ok": False, ...}, never a raise), and be idempotent (deterministic _id, so a
re-run cannot duplicate a row). A fake client that keeps documents in a dict
stands in for the network.
"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

from barra import tracestore
from barra.astra_store import AstraStore, configured


class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def replace_one(self, flt, replacement, upsert=False):
        self.docs[flt["_id"]] = dict(replacement)
        return mock.Mock(upserted_id=flt["_id"])

    def insert_one(self, document):
        self.docs[document["_id"]] = dict(document)

    def find_one(self, flt=None):
        if not flt:
            return None
        return dict(self.docs[flt["_id"]]) if flt.get("_id") in self.docs else None

    def find(self, flt=None, limit=None):
        items = [dict(d) for d in self.docs.values()]
        if flt:
            items = [d for d in items if all(d.get(k) == v for k, v in flt.items())]
        return items[:limit] if limit else items

    def count_documents(self, flt=None):
        return len([d for d in self.docs.values()
                    if not flt or all(d.get(k) == v for k, v in flt.items())])


class FakeClient:
    def __init__(self):
        self.collections = {
            "pipeline_eval": FakeCollection(),
            "pipeline_eval_traces": FakeCollection(),
            "pipeline_eval_failures": FakeCollection(),
        }


def _store(**kw):
    return AstraStore(token="tok", endpoint="https://example", client=FakeClient(), **kw)


class AstraStoreTests(unittest.TestCase):
    def test_import_does_not_touch_astrapy_when_unconfigured(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertFalse(configured())
        self.assertNotIn("astrapy", sys.modules)

    def test_unconfigured_writes_are_honest_failures(self):
        store = AstraStore()
        self.assertFalse(store.configured())
        res = store.put_evaluation({"trick": "squat", "detected": "dip"})
        self.assertEqual(res.get("ok"), False)
        self.assertIn("not configured", res.get("reason", ""))
        self.assertEqual(store.get(trick="squat"), [])

    def test_evaluation_row_uses_eval_id_and_roundtrips(self):
        fake = FakeClient()
        store = AstraStore(token="t", endpoint="https://x", client=fake)
        res = store.put_evaluation({"evaluationId": "e1", "trick": "squat",
                                    "detected": "dip", "correct": False})
        self.assertTrue(res["ok"])
        self.assertTrue(res["_id"].startswith("eval:"))
        docs = store.get(trick="squat")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["detected"], "dip")

    def test_trace_row_lives_in_a_separate_collection_and_namespace(self):
        fake = FakeClient()
        store = AstraStore(token="t", endpoint="https://x", client=fake)
        store.put_trace({"traceId": "tr1", "payload": "{}"})
        self.assertIn("trace:tr1", fake.collections["pipeline_eval_traces"].docs)
        self.assertNotIn("trace:tr1", fake.collections["pipeline_eval"].docs)

    def test_client_failure_never_raises(self):
        class Boom:
            def replace_one(self, *_a, **_k):
                raise RuntimeError("boom")

        fake = FakeClient()
        fake.collections["pipeline_eval"] = Boom()
        store = AstraStore(token="t", endpoint="https://x", client=fake)
        res = store.put_evaluation({"evaluationId": "x", "trick": "squat"})
        self.assertFalse(res["ok"])
        self.assertIn("boom", res["reason"])
        self.assertEqual(res["store"], "local")

    def test_writes_are_idempotent_for_a_rerun(self):
        fake = FakeClient()
        store = AstraStore(token="t", endpoint="https://x", client=fake)
        doc = {"evaluationId": "e1", "trick": "squat", "detected": "dip"}
        store.put_evaluation(dict(doc))
        store.put_evaluation({**doc, "detected": "unknown"})
        self.assertEqual(len(store.get(trick="squat")), 1)
        self.assertEqual(store.get(trick="squat")[0]["detected"], "unknown")


class TracestoreAstraTests(unittest.TestCase):
    def test_put_trace_returns_astra_when_configured_and_no_dynamodb_table(self):
        class FakeAstraStore:
            def put_trace(self, doc):
                return {"ok": True, "store": "astra"}

        env = {"ASTRA_DB_APPLICATION_TOKEN": "t", "ASTRA_DB_API_ENDPOINT": "https://x"}
        with mock.patch.dict("os.environ", env, clear=False):
            with mock.patch("barra.astra_store.AstraStore", FakeAstraStore):
                self.assertEqual(tracestore.put_trace({"s": 1}, "tr1"), "astra")

    def test_put_trace_keeps_dynamodb_when_only_traces_table_set(self):
        with mock.patch.dict("os.environ", {"TRACES_TABLE": "my-table"}, clear=False):
            with mock.patch("boto3.client") as boto:
                boto.return_value.put_item.return_value = None
                self.assertEqual(tracestore.put_trace({"s": 1}, "tr1"), "dynamodb")


if __name__ == "__main__":
    unittest.main()
