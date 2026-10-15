"""Overlap optional pose-runtime imports with clip transfer."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class PoseRuntimeWarmup:
    thread: threading.Thread
    done: threading.Event
    started_ns: int
    outcome: dict[str, Any]


def _import_ultralytics() -> None:
    # Load the package only; model construction remains in the measured pose
    # path and is intentionally not duplicated here.
    from ultralytics import YOLO  # noqa: F401


def start_pose_runtime_warmup(backend: str | None = None) -> PoseRuntimeWarmup | None:
    """Start the optional Ultralytics import in a short-lived daemon thread.

    The caller can overlap this with an incoming upload or object download,
    then call ``finish_pose_runtime_warmup`` before pose inference. Non-YOLO
    backends do no work. Import failures are recorded and left for the normal
    backend path to report, so this optimization cannot change job semantics.
    """
    enabled = os.environ.get("BARRA_POSE_RUNTIME_WARMUP", "true").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return None

    configured = backend
    if configured is None:
        configured = os.environ.get("BARRA_POSE_BACKEND", "")
    if configured.strip().lower() != "ultralytics":
        return None

    done = threading.Event()
    outcome: dict[str, Any] = {}
    started_ns = time.perf_counter_ns()

    def run() -> None:
        try:
            _import_ultralytics()
            outcome["ready"] = True
        except Exception as exc:  # noqa: BLE001 - preserve the normal failure path
            outcome["ready"] = False
            outcome["errorType"] = type(exc).__name__
        finally:
            done.set()

    thread = threading.Thread(target=run, name="barra-pose-runtime-warmup", daemon=True)
    try:
        thread.start()
    except RuntimeError:
        return None
    return PoseRuntimeWarmup(thread=thread, done=done, started_ns=started_ns,
                             outcome=outcome)


def finish_pose_runtime_warmup(
    warmup: PoseRuntimeWarmup | None,
) -> dict[str, int | bool | str]:
    """Join a started import and return overlap/wait diagnostics."""
    if warmup is None:
        return {"ready": False, "outcome": "skipped", "elapsedMs": 0, "waitMs": 0}

    wait_started_ns = time.perf_counter_ns()
    warmup.done.wait()
    warmup.thread.join()
    wait_ms = round((time.perf_counter_ns() - wait_started_ns) / 1_000_000)
    elapsed_ms = round((time.perf_counter_ns() - warmup.started_ns) / 1_000_000)
    ready = bool(warmup.outcome.get("ready"))
    result: dict[str, int | bool | str] = {
        "ready": ready,
        "outcome": "ready" if ready else "import-error",
        "elapsedMs": elapsed_ms,
        "waitMs": wait_ms,
    }
    if not ready:
        result["errorType"] = str(warmup.outcome.get("errorType", "UnknownError"))
    return result
