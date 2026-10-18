"""Reps wholly outside the window where the vision model located the exercise
are setup, not set (picking the kettlebells up before a Bulgarian split squat
was counted as rep 1)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import process  # noqa: E402
from barra.ingest import Reps  # noqa: E402
from barra.trace import NullTrace  # noqa: E402

FPS = 30.0
# The real clip's reps (frames), and vision's window 9.73-35.67 s.
FOUND = [(131, 167, 179), (368, 428, 465), (491, 537, 569), (569, 653, 656),
         (719, 766, 796), (828, 893, 924)]


def reps(cut=()):
    r = Reps(FOUND)
    r.cut = set(cut)
    return r


def test_the_pick_up_before_the_set_is_dropped():
    out = process._inside_vision_window(reps(cut={653}), (9.73, 35.67), FPS, NullTrace())
    assert list(out) == FOUND[1:]
    assert out.cut == {653}


def test_no_window_or_a_failing_one_changes_nothing():
    for window in (None, lambda: None, lambda: 1 / 0):
        assert list(process._inside_vision_window(reps(), window, FPS, NullTrace())) == FOUND


def test_a_window_never_erases_the_whole_set():
    out = process._inside_vision_window(reps(), (100.0, 120.0), FPS, NullTrace())
    assert list(out) == FOUND


def test_a_rep_overlapping_the_margin_stays():
    # Rep 1 ends at 5.97 s; a window starting at 7.0 s (margin 1.5) reaches it.
    out = process._inside_vision_window(reps(), (7.0, 35.0), FPS, NullTrace())
    assert list(out) == FOUND
