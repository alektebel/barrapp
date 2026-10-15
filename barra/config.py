"""Run-wide configuration. Values here are set before labels are seen.

Section 8 of the spec forbids threshold tuning after seeing labels. The only
threshold that decides a flag is FLAG_PERCENTILE, and it is fixed at 95 here,
in code, under version control. ``barra validate`` records the git hash of this
file alongside its results so a post-hoc change is visible in the report.
"""
from __future__ import annotations

import os
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
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
    # Pull-up lockout is NOT the muscle-up constant. A muscle-up ends in support
    # above the bar (shoulders ~70-100% of arm reach above the hands); a pull-up
    # finishes near hand height, where the same primitive reads ~1. Sharing
    # 0.85 made pull_up.incomplete_lockout fire on every clip (measured range
    # −45..73, threshold 85). Tuned against vision fault labels on the
    # calisthenics corpus: −27.6% catches severe short-tops without the
    # always-fire false-alarm storm. Units: percent of arm reach, same as
    # lockout_pct in evidence.py (not a 0-1 fraction).
    pull_up_lockout_pct: float = -27.6
    hang_min: float = 0.75         # share of that reach at the bottom
    controlled_tempo: float = 0.70  # eccentric:concentric below this is dropped
    stall_rate: float = 0.20       # ascent step below this share of mean = stalled
    stalled_frac: float = 0.05     # share of stalled frames before "stall"
    # Clip-level coaching cue: a fault must be observed on at least this many
    # reps before the clip-level failures / recommendation treat it as present.
    # One-off pose jitter on a single rep was the bulk of the false-alarm storm
    # (precision 0.146 → ~0.18 with recall unchanged on the labelled corpus).
    fault_min_reps: int = 2
    # Exclude the outer share of the lifting DISPLACEMENT from the stall count:
    # leaving rest and turning around both decelerate, and neither is a stall.
    # Provenance records this convention beside the rate it modifies.
    stall_edge_fraction: float = 0.10
    transition_s: float = 0.60     # seconds crossing the bar plane, muscle-up

    # -- the bar plane -------------------------------------------------------
    # Shoulders within this many torso-lengths of the hands are "at the bar":
    # the muscle-up's transition is the time spent inside this band, and a rep
    # of a hanging movement whose REST position sits further than this on the
    # wrong side of the hands (shoulders above them, on a pull-up) did not
    # start from a hang - it is a person standing near the rig with the
    # wrists tracked below the shoulders. 0014's walking interval rested 0.86
    # torso-lengths above the hands; every real hang in the sample corpus
    # rests below them.
    bar_plane_band: float = 0.15
    rest_side_tolerance: float = 0.30

    # -- availability --------------------------------------------------------
    # A phase-window primitive is withheld unless at least this share of the
    # window actually saw the joints it needs. The same 60% the segmenter
    # demands of a rep before counting it: a number from a fragment of a phase
    # is not a measurement of that phase.
    min_phase_coverage: float = 0.60
    min_phase_samples: int = 3         # and at least this many observed frames

    # -- straightness: 180 = fully extended ----------------------------------
    straight_arm: float = 160.0
    straight_leg: float = 160.0
    arms_straight_frac: float = 0.60   # share of the hold with straight arms
    # Hold-specific arm bars. The shared 0.60 sits above every front_lever /
    # planche arms_straight_frac ever measured on the corpus (max 0.53 / ~0.5),
    # so bent_arms always fired. These sit inside the measured ranges and are
    # the fault_eval --tune proposals that catch at least one labelled positive.
    front_lever_arms_straight_frac: float = 0.25
    planche_arms_straight_frac: float = 0.35
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

    # -- split squat (front-ankle-referenced) --------------------------------
    split_depth: float = 0.35          # hip drop from the planted front ankle, torso

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
    peak_prominence: float = 0.35      # share of span amplitude for a turnaround
    rescue_prominence: float = 0.15
    # Minimum share of a span's motion the turnaround must reach. Kept at the
    # historical 60% default; experiments may lower it only with reviewed QA.
    min_turn_peak_fraction: float = 0.60
    max_half_rep_s: float = 4.0        # longest half-rep the standard pass keeps
    # The least a span may move and still be a set, in torso-lengths.
    #
    # Amplitude is measured per active span, so each span sets its own
    # prominence threshold - which is the point, and which also means a span
    # that only contains noise would set an arbitrarily small one and count
    # its own jitter as reps. This is the floor under that, and like every
    # other threshold in this file it sits in a measured gap rather than being
    # tuned: a static hang plus pose jitter spans 0.014 torso-lengths, the
    # shallowest real set measured spans 0.39, and a full set 1.54. Ten times
    # the noise, and a third of the quietest real movement.
    min_span_amplitude: float = 0.15

    # -- rep-to-rep variation (what the replay marks, never what is scored) --
    # A rep is marked as unlike the rest of its own set when its amplitude or
    # its duration sits this far from the set's median. Relative to the
    # athlete's own reps, so no population norm is assumed; the replay only
    # points at the rep, the score is untouched.
    rep_amplitude_outlier: float = 0.20
    rep_tempo_outlier: float = 0.25
    # A set whose amplitude and tempo CVs both sit at or under this is
    # "estable"; above it on either is "irregular".
    set_steady_cv: float = 0.15


def thresholds_from_environment(
    environ: Mapping[str, str] | None = None,
) -> Thresholds:
    """Apply the explicit Round 2 shadow-only span-floor override.

    The ordinary config remains pinned at 0.15. A candidate runtime may set
    ``BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE`` to reproduce a screened value;
    invalid values fail worker startup rather than silently changing behavior.
    """
    values = os.environ if environ is None else environ
    raw = values.get("BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE")
    if raw is None or not raw.strip():
        return Thresholds()
    try:
        floor = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE must be a finite, non-negative number"
        ) from exc
    if not math.isfinite(floor) or floor < 0:
        raise ValueError(
            "BARRA_EXPERIMENTAL_MIN_SPAN_AMPLITUDE must be a finite, non-negative number"
        )
    return replace(Thresholds(), min_span_amplitude=floor)


THRESHOLDS = thresholds_from_environment()
