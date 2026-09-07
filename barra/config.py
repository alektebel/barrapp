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


# --- fault-layer thresholds (one source, mirrored nowhere) -------------------
# Before this block the same numbers lived in barra/faults.py, in
# barra/faults_taxonomy.py and again in the phone's Cues.kt, so "change them
# together" was a comment rather than a property of the code. They are pinned
# here for the same reason as everything else in this file: `validate`
# fingerprints config.py, so a threshold that moves after labels were seen is
# visible in the report.
#
# The phone no longer holds copies at all - the server ships each fired fault
# with the value and the threshold that fired it, and Cues.kt renders names.
@dataclass(frozen=True)
class Thresholds:
    # -- shared bar faults ---------------------------------------------------
    swing_torso: float = 0.40      # body travel, torso-lengths, before "momentum"
    lockout_min: float = 0.85      # share of the athlete's own reach at the top
    hang_min: float = 0.75         # share of that reach at the bottom
    controlled_tempo: float = 0.70  # eccentric:concentric below this is dropped
    stall_rate: float = 0.20       # ascent step below this share of mean = stalled
    stalled_frac: float = 0.05     # share of stalled frames before "stall"
    transition_s: float = 0.60     # seconds crossing the bar plane, muscle-up

    # -- straightness: 180 = fully extended ----------------------------------
    straight_arm: float = 160.0
    straight_leg: float = 160.0
    arms_straight_frac: float = 0.60   # share of the hold with straight arms
    legs_straight_frac: float = 0.60
    bent_arms_frac: float = 0.50       # the looser bar-rep version

    # -- body line: 0 = vertical, 90 = horizontal ----------------------------
    horizontal: float = 70.0
    strict_horizontal: float = 75.0
    pike: float = 150.0                # hip angle below this is a piked body

    # -- pistol squat --------------------------------------------------------
    pistol_depth: float = 0.55         # hip drop below the standing ankle, torso
    pistol_valgus: float = 0.12        # sideways knee travel, torso-lengths
    heel_rise: float = 0.06            # planted-ankle rise, torso-lengths
    lean_back: float = -0.30           # hips ahead of shoulders, torso-lengths

    # -- squat (hip-origin, ankle-referenced) --------------------------------
    squat_depth: float = 0.35          # hip drop from this rep's own stand, torso

    # -- push-up -------------------------------------------------------------
    push_up_depth: float = 0.35        # shoulder travel toward the hands, torso
    hip_sag: float = 0.12              # hip off the shoulder-ankle line, torso

    # -- dip -----------------------------------------------------------------
    dip_bottom_deg: float = 90.0       # elbow angle at the bottom, below = too deep
    bounce_speed: float = 0.15         # torso/s at the turnaround, above = bounced

    # -- pull-up -------------------------------------------------------------
    active_hang_deg: float = 150.0     # elbow angle at rep start, below = no hang
    fast_rep_frac: float = 0.50        # concentric below this share of the set's
                                       # own median is a rep thrown, not pulled

    # -- segmentation (mirrored from the literals ingest.py used inline) -----
    peak_prominence: float = 0.35      # share of clip amplitude for a turnaround
    rescue_prominence: float = 0.15
    max_half_rep_s: float = 4.0        # longest half-rep the standard pass keeps


THRESHOLDS = Thresholds()
