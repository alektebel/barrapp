"""Canonical keypoint schema and on-disk table contracts.

Every stage reads and writes plain columnar files (parquet/csv) under ``out/``.
There is no hidden state: a stage's entire input is the files named here.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Keypoints
# ---------------------------------------------------------------------------
# COCO-17 ordering. Pose backends that emit a different topology (e.g. BlazePose
# 33) are remapped to this list by their adapter in barra/pose/, so that
# everything downstream sees one schema.
COCO17 = [
    "nose",
    "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]
KP_INDEX = {name: i for i, name in enumerate(COCO17)}

# Joints actually scored. Face keypoints are excluded: they carry no barbell
# technique information and their jitter would inflate the null distribution
# for no gain.
ANALYSIS_JOINTS = [
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
]
ANALYSIS_IDX = [KP_INDEX[j] for j in ANALYSIS_JOINTS]

# Bones used for segment-length estimation (stage 1).
SEGMENTS = {
    "torso_left": ("left_shoulder", "left_hip"),
    "torso_right": ("right_shoulder", "right_hip"),
    "shoulder_width": ("left_shoulder", "right_shoulder"),
    "hip_width": ("left_hip", "right_hip"),
    "femur_left": ("left_hip", "left_knee"),
    "femur_right": ("right_hip", "right_knee"),
    "tibia_left": ("left_knee", "left_ankle"),
    "tibia_right": ("right_knee", "right_ankle"),
    "humerus_left": ("left_shoulder", "left_elbow"),
    "humerus_right": ("right_shoulder", "right_elbow"),
    "forearm_left": ("left_elbow", "left_wrist"),
    "forearm_right": ("right_elbow", "right_wrist"),
}

# Skeleton edges for the QC overlay renderer.
SKELETON_EDGES = [
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]

# ---------------------------------------------------------------------------
# Viewpoint bins (stage 2)
# ---------------------------------------------------------------------------
# Azimuth is measured as the angle between the camera axis and the movement
# plane (the sagittal plane of the lift). 0 deg = filmed from the side.
VIEWPOINT_BINS = ["SAGITTAL", "OBLIQUE", "FRONTAL", "UNKNOWN"]
BIN_EDGES_DEG = {"SAGITTAL": (0.0, 20.0), "OBLIQUE": (20.0, 65.0), "FRONTAL": (65.0, 90.0)}

# A bin with fewer than this many reps is reported as underpowered and excluded
# from every comparison.
MIN_REPS_PER_BIN = 6
# A template may not be built from fewer reference reps than this.
MIN_REFERENCE_REPS = 8
# Fraction of clean reps held out of the reference set for the FPR estimate.
MIN_CLEAN_HOLDOUT_FRAC = 0.30

# ---------------------------------------------------------------------------
# Phases (stage 4)
# ---------------------------------------------------------------------------
# A rep is split into eccentric and concentric halves at the depth extremum,
# and each half into PHASES_PER_HALF equal fractions of aligned path.
PHASES_PER_HALF = 3
PHASE_NAMES = (
    [f"ecc_{i+1}" for i in range(PHASES_PER_HALF)]
    + [f"con_{i+1}" for i in range(PHASES_PER_HALF)]
)

# ---------------------------------------------------------------------------
# Artefact paths (relative to the out/ directory)
# ---------------------------------------------------------------------------
P_KEYPOINTS = "keypoints"              # out/keypoints/<video>.parquet
P_REPS = "reps.csv"                    # rep segmentation, one row per rep
P_INGEST_LOG = "ingest_log.csv"        # one row per video, including those with 0 reps
P_ANATOMY = "subject_anatomy.json"
P_NORMALISED = "normalised"            # out/normalised/<video>.parquet
P_VIEWPOINTS = "viewpoints.csv"
P_REFERENCE = "reference_reps.csv"     # hand-marked reference rep ids
P_TEMPLATE = "template_{bin}.parquet"
P_NULL = "null_{bin}.parquet"
P_SCORES = "scores.csv"
P_VALIDATION = "validation.json"
P_LABELS = "labels.csv"                # user-supplied ground truth for stage 6
P_REPORT = "report.html"
P_QC = "qc"                            # out/qc/<rep>.mp4

# Column contracts -----------------------------------------------------------
# keypoints/<video>.parquet : frame, kp_<joint>_x, kp_<joint>_y, kp_<joint>_c
# reps.csv                  : rep_id, video, session_id, rep_index,
#                             start_frame, turn_frame, end_frame, fps
# normalised/<video>.parquet: frame, n_<joint>_x, n_<joint>_y, c_<joint>
# viewpoints.csv            : video, session_id, azimuth_deg, azimuth_lo,
#                             azimuth_hi, bin, n_frames_used
# labels.csv                : rep_id, label, note
#                             label == "clean" or an error name the user chose
