"""Rep-to-rep variation: which rep broke its own set's pattern.

The replay marks these reps. They are relative to the athlete's own median,
so the tests pin the median behaviour, the short-set refusal and the band.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra.variation import (  # noqa: E402
    consistency_band, rep_variation, spans_as_seconds,
)


class RepVariation(unittest.TestCase):
    def test_an_even_set_has_no_outlier(self):
        out = rep_variation([1.0, 1.02, 0.98, 1.0], [2.0, 2.1, 1.95, 2.0])
        self.assertEqual([r["outlier"] for r in out], [False] * 4)

    def test_a_short_rep_in_an_even_set_is_marked(self):
        out = rep_variation([1.0, 1.0, 0.6, 1.0], [2.0, 2.0, 2.0, 2.0])
        self.assertEqual([r["outlier"] for r in out], [False, False, True, False])
        self.assertAlmostEqual(out[2]["amplitude"], -0.4)

    def test_a_rushed_rep_is_marked_by_tempo_alone(self):
        out = rep_variation([1.0] * 4, [2.0, 2.0, 1.2, 2.0])
        self.assertTrue(out[2]["outlier"])
        self.assertEqual(out[2]["amplitude"], 0.0)

    def test_two_reps_have_no_median_to_compare_with(self):
        out = rep_variation([1.0, 0.3], [2.0, 4.0])
        self.assertEqual(out, [{"amplitude": None, "tempo": None, "outlier": False}] * 2)

    def test_a_missing_amplitude_stays_missing_and_does_not_shift_the_rest(self):
        out = rep_variation([1.0, None, 1.0, 0.5], [2.0] * 4)
        self.assertIsNone(out[1]["amplitude"])
        self.assertTrue(out[3]["outlier"])

    def test_lists_of_different_lengths_are_refused(self):
        with self.assertRaises(ValueError):
            rep_variation([1.0], [1.0, 2.0])


class Band(unittest.TestCase):
    def test_band(self):
        self.assertIsNone(consistency_band(None))
        self.assertIsNone(consistency_band({}))
        self.assertEqual(consistency_band({"amplitudeCV": 0.05, "tempoCV": 0.1}), "estable")
        self.assertEqual(consistency_band({"amplitudeCV": 0.05, "tempoCV": 0.3}), "irregular")


class Spans(unittest.TestCase):
    def test_spans_are_ordered_and_disjoint_seconds(self):
        out = spans_as_seconds([(60, 89), (0, 29)], 30.0)
        self.assertEqual(out, [{"startS": 0.0, "endS": 1.0}, {"startS": 2.0, "endS": 3.0}])
        for a, b in zip(out, out[1:]):
            self.assertLessEqual(a["endS"], b["startS"])

    def test_no_fps_no_spans(self):
        self.assertEqual(spans_as_seconds([(0, 10)], 0), [])


class PayloadCarriesIt(unittest.TestCase):
    def test_empty_payload_has_the_new_keys(self):
        from process import _empty
        payload = _empty("auto", ["x"])
        self.assertEqual(payload["activeSpans"], [])
        self.assertIsNone(payload["consistencyBand"])


if __name__ == "__main__":
    unittest.main()
