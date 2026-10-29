"""Fusion must not re-wait for a late locate after fast pose.

When pose took ~128 s, locate finished first. With Full + chunks, pose can
finish in seconds while locate still runs for tens of seconds. The worker
caps the fusion wait so upload→result does not grow again.
"""
from __future__ import annotations

import concurrent.futures
import time
import unittest


def _vote_from_future(future, wait_s: float):
    """Mirrors server/api/handler.py _vision_vote wait behaviour."""
    try:
        located = future.result(timeout=wait_s)
    except Exception:  # noqa: BLE001
        return None
    label = (located or {}).get("exercise") or None
    if label and str(label).lower() in ("none", "unknown", ""):
        return None
    return label


class VisionVoteWait(unittest.TestCase):
    def test_a_ready_locate_is_used(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(lambda: {"exercise": "pull_up"})
            self.assertEqual(_vote_from_future(fut, 2.0), "pull_up")

    def test_a_late_locate_is_skipped_not_waited(self):
        def slow():
            time.sleep(0.4)
            return {"exercise": "pull_up"}

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(slow)
            t0 = time.perf_counter()
            vote = _vote_from_future(fut, 0.05)
            elapsed = time.perf_counter() - t0
        self.assertIsNone(vote)
        self.assertLess(elapsed, 0.25)


if __name__ == "__main__":
    unittest.main()
