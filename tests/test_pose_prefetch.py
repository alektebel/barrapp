"""Decoding ahead of the landmarker must hand it the same frames, in order."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from barra.pose import mediapipe_backend as mb  # noqa: E402


class FakeCap:
    """n frames whose pixel value is their index; counts grab/read calls."""

    def __init__(self, n, w=1280, h=720):
        self.n, self.w, self.h, self.i = n, w, h, 0
        self.grabs = self.reads = 0

    def grab(self):
        if self.i >= self.n:
            return False
        self.i += 1
        self.grabs += 1
        return True

    def read(self):
        if self.i >= self.n:
            return False, None
        f = np.full((self.h, self.w, 3), self.i, dtype=np.uint8)
        self.i += 1
        self.reads += 1
        return True, f


def collect(it):
    return [(i, int(f[0, 0, 0]), f.shape) for i, f in it]


class Decode(unittest.TestCase):
    def test_frames_before_warm_are_advanced_not_converted(self):
        cap = FakeCap(10)
        got = collect(mb._decode(cap, 4, 8, cap.w, cap.h))
        self.assertEqual([g[0] for g in got], [4, 5, 6, 7])
        self.assertEqual([g[1] for g in got], [4, 5, 6, 7])
        self.assertEqual((cap.grabs, cap.reads), (4, 4))

    def test_wide_frames_are_resized_to_the_process_width(self):
        cap = FakeCap(2, w=1280, h=720)
        (_, _, shape), _ = collect(mb._decode(cap, 0, -1, 1280, 720))
        self.assertEqual(shape, (360, mb.PROCESS_WIDTH, 3))

    def test_end_minus_one_reads_to_the_end_of_the_file(self):
        cap = FakeCap(7)
        self.assertEqual(len(collect(mb._decode(cap, 0, -1, cap.w, cap.h))), 7)


class Prefetch(unittest.TestCase):
    def test_same_frames_same_order_as_the_serial_loop(self):
        for n in (0, 1, 3, 50):
            serial = collect(mb._decode(FakeCap(n), 2, -1, 1280, 720))
            with mock.patch.dict(os.environ, {"BARRA_POSE_PREFETCH": "1"}):
                ahead = mb._prepared_frames(FakeCap(n), 2, -1, 1280, 720)
                got = collect(ahead)
                ahead.close()
            self.assertEqual(got, serial, n)

    def test_the_flag_turns_it_off_and_the_loop_still_works(self):
        with mock.patch.dict(os.environ, {"BARRA_POSE_PREFETCH": "0"}):
            prepared = mb._prepared_frames(FakeCap(5), 0, -1, 1280, 720)
            self.assertNotIsInstance(prepared, mb._Prefetch)
            self.assertEqual(len(collect(prepared)), 5)
            prepared.close()

    def test_a_decode_error_surfaces_in_the_consumer(self):
        def boom():
            yield 0, np.zeros((2, 2, 3), np.uint8)
            raise RuntimeError("bad packet")
        p = mb._Prefetch(boom())
        self.assertEqual(next(p)[0], 0)
        with self.assertRaisesRegex(RuntimeError, "bad packet"):
            next(p)
        p.close()

    def test_it_reads_ahead_but_only_by_the_queue_depth(self):
        pulled = []

        def source():
            for i in range(100):
                pulled.append(i)
                yield i, np.zeros((1, 1, 3), np.uint8)
        p = mb._Prefetch(source(), depth=4)
        next(p)
        threading.Event().wait(0.3)
        self.assertLessEqual(len(pulled), 4 + 3)  # queue + the one in hand + consumed
        self.assertGreater(len(pulled), 1)         # it did run ahead
        p.close()

    def test_close_stops_the_thread_mid_stream(self):
        def source():
            for i in range(10_000):
                yield i, np.zeros((1, 1, 3), np.uint8)
        p = mb._Prefetch(source(), depth=2)
        next(p)
        p.close()
        self.assertFalse(p._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
