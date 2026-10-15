"""The shadow amplitude floor must be configurable and stamped in provenance."""
from __future__ import annotations

import unittest

from barra.config import thresholds_from_environment
from barra.provenance import measurement_semantics


class Round2ThresholdConfig(unittest.TestCase):
    def test_default_keeps_production_floor(self):
        thresholds = thresholds_from_environment({})
        self.assertEqual(thresholds.min_span_amplitude, 0.15)

    def test_shadow_floor_override_changes_only_that_threshold(self):
        thresholds = thresholds_from_environment(
            {"BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE": "0.25"})
        self.assertEqual(thresholds.min_span_amplitude, 0.25)
        self.assertEqual(thresholds.min_turn_peak_fraction, 0.60)
        self.assertEqual(thresholds.peak_prominence, 0.35)

    def test_shadow_floor_rejects_invalid_values(self):
        for value in ("not-a-number", "nan", "inf", "-0.01"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                thresholds_from_environment(
                    {"BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE": value})

    def test_measurement_provenance_names_the_floor(self):
        self.assertEqual(measurement_semantics()["minSpanAmplitude"], 0.15)


if __name__ == "__main__":
    unittest.main()
