"""Pose backend registry."""
from __future__ import annotations

from .base import PoseBackend, PoseResult
from .mediapipe_backend import MediapipeBackend
from .ultralytics_backend import UltralyticsBackend

BACKENDS: dict[str, PoseBackend] = {
    "mediapipe": MediapipeBackend(),
    "ultralytics": UltralyticsBackend(),
}


def get_backend(name: str) -> PoseBackend:
    if name not in BACKENDS:
        raise SystemExit(
            f"unknown pose backend {name!r}; choices: {', '.join(BACKENDS)}"
        )
    be = BACKENDS[name]
    if not be.available():
        raise SystemExit(
            f"pose backend {name!r} is not installed.\n"
            f"  uv pip install -e \".[{name}]\"\n"
            "No pose estimator ships by default - the core dependency list is "
            "pinned by the spec, so the backend is an explicit opt-in."
        )
    return be


def available_backends() -> list[str]:
    return [n for n, b in BACKENDS.items() if b.available()]


__all__ = ["BACKENDS", "get_backend", "available_backends", "PoseBackend", "PoseResult"]
