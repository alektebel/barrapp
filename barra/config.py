"""Run-wide configuration. Values here are set before labels are seen.

Section 8 of the spec forbids threshold tuning after seeing labels. The only
threshold that decides a flag is FLAG_PERCENTILE, and it is fixed at 95 here,
in code, under version control. ``barra validate`` records the git hash of this
file alongside its results so a post-hoc change is visible in the report.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# --- fixed decision rule (spec section 7) ----------------------------------
FLAG_PERCENTILE = 95.0

# --- verdict rule (spec section 8) -----------------------------------------
MAX_ACCEPTABLE_FPR = 0.20
MIN_ACCEPTABLE_DETECTION = 0.60

# --- stage 1 ---------------------------------------------------------------
MIN_MEAN_CONFIDENCE = 0.60   # frames below this are not used for anatomy
CONF_FLOOR = 0.10            # weight floor so one dead joint cannot vanish

# --- stage 3 ---------------------------------------------------------------
RESAMPLE_LENGTH = 100        # frames per time-normalised rep
DBA_ITERATIONS = 12
DTW_WINDOW_FRAC = 0.15       # Sakoe-Chiba band as a fraction of rep length


@dataclass(frozen=True)
class Paths:
    root: Path = field(default_factory=lambda: Path(os.environ.get("BARRA_ROOT", ".")))

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def videos(self) -> Path:
        return self.root / "data" / "videos"

    def o(self, *parts: str) -> Path:
        return self.out.joinpath(*parts)

    def ensure(self) -> "Paths":
        for d in ("keypoints", "normalised", "qc", "figures"):
            (self.out / d).mkdir(parents=True, exist_ok=True)
        return self


PATHS = Paths()
