"""Reliability gate for an exact speed-up: the whole measured payload, before
and after, on the corpus.

    python scripts/corpus_gate.py CLIP [CLIP...]

Runs the production measurement (process.measure_job, remote models off - no
network) on each clip twice, with the pose prefetch thread off and on
(BARRA_POSE_PREFETCH), and compares EVERY number the phone shows (the payload
minus run-metadata keys, as scripts/pose_parallel_check.py defines them).
Prints exercise, reps, countStatus, session score and the wall time of each
side. Exit status 1 if any payload differs. docs/SPEED-ROUND3.md has the table.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server"), str(ROOT / "scripts")]
for k in ("NAN_API_KEY", "NAN_SECRET_ID", "BARRA_VISION_API_KEY"):
    os.environ.pop(k, None)
os.environ["NAN_BASE_URL"] = ""
os.environ["BARRA_SENTINEL"] = "record"
os.environ["BARRA_TRACE_DIR"] = str(ROOT / "out" / "corpus-gate-traces")

from pose_parallel_check import deep_diff, payload_for, strip  # noqa: E402


def run(clip: Path, prefetch: bool) -> tuple[dict, float]:
    os.environ["BARRA_POSE_PREFETCH"] = "1" if prefetch else "0"
    t0 = time.perf_counter()
    payload = payload_for(clip, "on" if prefetch else "off", None)
    return payload, time.perf_counter() - t0


def main() -> int:
    bad = 0
    for clip in map(Path, sys.argv[1:]):
        before, t_before = run(clip, False)
        after, t_after = run(clip, True)
        diffs = deep_diff(strip(before), strip(after))
        bad += bool(diffs)
        d = after.get("detected") or {}
        print(f"{clip.name}: exercise={after.get('exercise')} reps={after.get('n_reps')} "
              f"countStatus={after.get('countStatus')} score={after.get('sessionScore')} "
              f"| before {t_before:.1f} s, after {t_after:.1f} s "
              f"| payload {'IDENTICAL' if not diffs else f'{len(diffs)} DIFFERENCES'}",
              flush=True)
        for line in diffs[:10]:
            print("    ", line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
