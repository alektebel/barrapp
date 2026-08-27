"""Artefact IO. Every stage reads its inputs from disk and writes its outputs
to disk; nothing is passed in memory between CLI commands."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PATHS


class MissingArtefact(RuntimeError):
    """Raised when a stage's input has not been produced yet."""


def require(path: Path, produced_by: str) -> Path:
    if not path.exists():
        raise MissingArtefact(
            f"missing {path} - run `barra {produced_by}` first"
        )
    return path


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_parquet(path: Path, produced_by: str) -> pd.DataFrame:
    return pd.read_parquet(require(path, produced_by))


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def read_csv(path: Path, produced_by: str) -> pd.DataFrame:
    return pd.read_csv(require(path, produced_by))


def write_json(obj: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))
    return path


def read_json(path: Path, produced_by: str) -> Any:
    return json.loads(require(path, produced_by).read_text())


def config_fingerprint() -> str:
    """Git hash of config.py, so the report can show whether the decision
    thresholds were edited after labels were seen."""
    try:
        out = subprocess.run(
            ["git", "hash-object", str(Path(__file__).with_name("config.py"))],
            capture_output=True, text=True, cwd=PATHS.root, timeout=10,
        )
        return out.stdout.strip()[:12] or "unknown"
    except Exception:
        return "unknown"


def video_stem(path: str | Path) -> str:
    return Path(path).stem
