"""What produced this number.

A measurement without provenance cannot be debugged a week later. "The score
changed" has two very different explanations - the athlete changed, or the build
did - and only one of them is about training. Every artefact and every trace
carries this stamp so the two can be told apart.

The pose model hash matters as much as the code version: mediapipe ships new
weights under the same file name, and a silent model swap moves every number in
the project without a line of code changing.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from . import __version__


@lru_cache(maxsize=1)
def git_commit() -> str:
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        commit = out.stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        # The dirty flag is the important half: a number produced from
        # uncommitted code cannot be reproduced from the repository.
        return f"{commit}{'+dirty' if dirty else ''}" if commit else "unknown"
    except Exception:
        return "unknown"


@lru_cache(maxsize=8)
def file_digest(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return "missing"
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()[:12]


@lru_cache(maxsize=1)
def pose_model() -> dict:
    path = os.environ.get("BARRA_POSE_MODEL", "models/pose_landmarker_heavy.task")
    p = Path(path)
    return {
        "path": str(path),
        "present": p.exists(),
        "bytes": p.stat().st_size if p.exists() else None,
        # mediapipe ships new weights under the same file name; without this a
        # model swap moves every number in the project invisibly.
        "sha256_12": file_digest(str(path)) if p.exists() else "missing",
    }


def backends() -> list[str]:
    try:
        from .pose import available_backends

        return available_backends()
    except Exception:
        return []


def stamp(include_model: bool = True) -> dict:
    """The full provenance record. Cheap enough to attach to everything."""
    out = {
        "barra": __version__,
        "commit": git_commit(),
        "python": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}",
        "poseBackends": backends(),
    }
    if include_model:
        out["poseModel"] = pose_model()
    return out


def line() -> str:
    """One-line form, for a log or a footer."""
    s = stamp(include_model=False)
    m = pose_model()
    return (f"barra {s['barra']} · {s['commit']} · py{s['python']} · "
            f"model {m['sha256_12']}")
