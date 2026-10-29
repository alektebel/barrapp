"""Read the worker's cold files in parallel, while the clip downloads.

A cold worker container reads its files from the image lazily, a block at a
time, the first time each is touched. Job 44268cdeec26 (2026-10-29, the first
after an idle spell) spent 9.8 s hashing the 30 MB pose model for the
provenance stamp and 20.2 s importing cv2/mediapipe/numpy/scipy before the pose
began - 30 s that a warm container (0.3 s + 1.0 s) does not pay, on a
sequential walk through the files that one thread at a time cannot hide.

`start()` reads the same files from a few threads so their first touches
overlap, beginning the moment the handler runs. It changes no value anywhere:
it only reads bytes the worker is about to read anyway, ignores every error,
runs once per container, and leaves a warm container alone (nothing is cold).
Whether it shortens a real cold start is measured with `scripts/job_timing.py`
(`probe@` and `imports` in the trace); the measurement itself cannot change.

`BARRA_PREWARM=0` turns it off.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

BLOCK = 1 << 20
THREADS = 4
PACKAGES = ("mediapipe", "cv2", "numpy", "scipy", "sklearn")
_started = threading.Lock()
_done = False


def enabled() -> bool:
    return os.environ.get("BARRA_PREWARM", "1").strip().lower() not in ("0", "false", "off", "no")


def cold_files() -> list[Path]:
    """The worker's model files and the native libraries of its heavy
    imports, biggest first (the long reads start earliest)."""
    files: list[Path] = []
    for name in ("BARRA_POSE_MODEL",):
        value = os.environ.get(name)
        if value:
            files.append(Path(value))
    root = Path(os.environ.get("BARRA_ROOT", "/opt/barra"))
    files += sorted((root / "models").glob("*")) if (root / "models").is_dir() else []
    for entry in sys.path:
        base = Path(entry or ".")
        for pkg in PACKAGES:
            d = base / pkg
            if d.is_dir():
                files += [p for p in d.rglob("*.so*") if p.is_file()]
        # wheels keep their bundled libraries beside the package
        files += [p for p in base.glob("*.libs/*") if p.is_file()] if base.is_dir() else []
    seen, out = set(), []
    for p in files:
        try:
            key = p.resolve()
        except OSError:
            continue
        if key not in seen:
            seen.add(key)
            out.append(p)
    def size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0
    return sorted(out, key=size, reverse=True)


def _read(path: Path) -> int:
    n = 0
    try:
        with open(path, "rb") as f:
            while block := f.read(BLOCK):
                n += len(block)
    except OSError:
        pass
    return n


def _run(files: list[Path], threads: int) -> None:
    it = iter(files)
    take = threading.Lock()

    def worker() -> None:
        while True:
            with take:
                path = next(it, None)
            if path is None:
                return
            _read(path)

    pool = [threading.Thread(target=worker, name="prewarm", daemon=True)
            for _ in range(max(1, threads))]
    for t in pool:
        t.start()
    for t in pool:
        t.join()


def start(threads: int = THREADS) -> bool:
    """Begin reading in the background. True when this call started it."""
    global _done
    if not enabled():
        return False
    with _started:
        if _done:
            return False
        _done = True

    def go() -> None:
        try:
            _run(cold_files(), threads)
        except Exception:  # noqa: BLE001 - a warm-up is never worth a job
            pass

    threading.Thread(target=go, name="prewarm-main", daemon=True).start()
    return True
