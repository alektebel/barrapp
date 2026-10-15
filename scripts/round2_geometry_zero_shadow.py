#!/usr/bin/env python3
"""Evaluate explicit zero-count evidence without changing production counts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from barra.geometry_zero_shadow import evaluate_zero_candidate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / (
    "out/round2-latency/fusion-v2-final/"
    "docker-reviewed-cohort-amplitude025/zero-coverage-shadow-screen.json"
)
DEFAULT_OUTPUT = ROOT / "out/round2-latency/fusion-v2-final/geometry-zero-shadow-evaluation.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-observed-frac", type=float, default=0.90)
    args = parser.parse_args()

    source = json.loads(args.input.read_text())
    rows = source.get("rows")
    if not isinstance(rows, list):
        parser.error("input must contain a rows array")
    results = [evaluate_zero_candidate(row,
                                      min_observed_frac=args.min_observed_frac)
               for row in rows]
    payload = {
        "title": "Fail-closed geometric zero shadow evaluation",
        "source": str(args.input.relative_to(ROOT)
                      if args.input.is_relative_to(ROOT) else args.input),
        "minObservedFrac": args.min_observed_frac,
        "productionStatusChanged": False,
        "measuredZeros": 0,
        "results": results,
        "warning": "candidate_geometry_zero is not a measured count and must not be rendered as one",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for result in results:
        key = result["disposition"]
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"output": str(args.output), "counts": counts,
                      "productionStatusChanged": False, "measuredZeros": 0},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
