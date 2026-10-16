"""The eval layer: measured claims graded, LLM prose judged, regressions gated.

Four kinds of checking live here, each answering a different question:

  * golden      - the measurement core against the reviewed manifest
                  (data/evaluation/sample_manifest.json). Exact counts,
                  exact errorIds: a number is right or it is wrong.
  * judge       - the LLM prose (headline/narrative/nextSession) against a
                  rubric, graded by another model. Structured output, never
                  free-form agreement.
  * reference   - deterministic text metrics (token overlap) between a
                  write-up and the payload facts it must quote. Catches the
                  hallucinated number before any judge is paid for.
  * gate        - the regression gate: run, compare against a saved
                  baseline, exit nonzero when a score drops past its
                  tolerance. This is what CI calls.

The design rules are the project's rules: nothing judged that cannot be
traced to an input; abstention is a result, not a failure; and every metric
reports its denominator, because a 100% over three clips is inconclusive.
"""
from .golden import golden_metrics, GoldenReport
from .gate import compare_to_baseline, GateResult

__all__ = ["golden_metrics", "GoldenReport", "compare_to_baseline", "GateResult"]
