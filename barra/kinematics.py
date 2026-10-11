"""The kinematic feature set the learned classifier reads.

`barra.classify.features` was written for the geometric rules: every value in
it exists because some hand-written branch compares it against a threshold, and
it covers the eleven movements those branches decide between. That made it a
poor vector for a *learned* model asked about seventeen classes, because the
things which separate a deadlift from a back squat, a bench press from a dip,
or a back lever from a front lever were never measured - nothing in the rules
needed them.

So this module is the second, wider view of the same keypoints. Three ideas
from the skeleton-action-recognition literature shape it, and each is here
because it is what that work found to matter more than model capacity:

  * **Anatomical priors beat raw coordinates.** Angles taken along the
    kinematic chains (hip-knee-ankle, shoulder-elbow-wrist, shoulder-hip-knee)
    and their ranges of motion are what a coach actually reads, and they are
    invariant to where in frame the athlete stands and how far away the camera
    is. A biomechanically-constrained model beat a plain ST-GCN on error
    detection by 7.5 F1 while running faster, and the reason given was exactly
    this: spend the representation on joint couplings that mean something.
  * **The support matters as much as the pose.** What the hands are on, where
    the feet are, and which way the body faces separate most of the classes
    that the rules confuse. A human flag is a horizontal body on *vertically
    stacked* hands; a front lever is the same body on hands side by side. A
    barbell back squat holds the wrists a fixed distance from the shoulders all
    set; a bodyweight squat does not.
  * **Time is a feature, not an axis to average away.** Clip-level percentiles
    cannot tell a hold from a set. Motion energy, the strongest periodicity in
    the main signal, and how much of the clip is actually moving, can.

Every value is scale-free (divided by a robust torso length) or already a
fraction/angle, so the same number means the same thing at any camera distance.
Every value is NaN when it was not measured, never zero: the model's normaliser
carries a sentinel for "unknown", and a missing ankle must not read as an ankle
on the floor.

The vector is a superset - `classify.features()` is embedded whole - so a model
trained here can still be compared against the geometric path feature by
feature.
"""
from __future__ import annotations

import numpy as np

from . import schema as S
from .classify import MIN_CONF, features as geometric_features
from .movements import midpoint, pair_confidence, robust_torso

# A joint seen less often than this in a clip is not measured well enough there
# for its angles to mean anything.
MIN_JOINT_SEEN = 0.15

# COCO-17 left/right pairs, for the mirrored view of a clip.
_MIRROR = [
    (S.KP_INDEX["left_eye"], S.KP_INDEX["right_eye"]),
    (S.KP_INDEX["left_ear"], S.KP_INDEX["right_ear"]),
    (S.KP_INDEX["left_shoulder"], S.KP_INDEX["right_shoulder"]),
    (S.KP_INDEX["left_elbow"], S.KP_INDEX["right_elbow"]),
    (S.KP_INDEX["left_wrist"], S.KP_INDEX["right_wrist"]),
    (S.KP_INDEX["left_hip"], S.KP_INDEX["right_hip"]),
    (S.KP_INDEX["left_knee"], S.KP_INDEX["right_knee"]),
    (S.KP_INDEX["left_ankle"], S.KP_INDEX["right_ankle"]),
]


def mirror(kp: np.ndarray) -> np.ndarray:
    """The same clip filmed from the other side.

    A left-facing pull-up and a right-facing pull-up are the same movement, and
    nothing in this feature set should say otherwise - so the mirrored clip is
    a free, label-preserving training example. x is reflected about the frame's
    own midline (its own x range, since the frame width is not carried with the
    keypoints) and the left/right landmarks are swapped, or every left-right
    contrast in the vector would be mirrored geometry with unmirrored names.
    """
    out = kp.copy()
    seen = out[:, :, 2] >= MIN_CONF
    if seen.any():
        lo = float(out[:, :, 0][seen].min())
        hi = float(out[:, :, 0][seen].max())
        out[:, :, 0] = (lo + hi) - out[:, :, 0]
    for a, b in _MIRROR:
        out[:, [a, b], :] = out[:, [b, a], :]
    return out


def jitter(kp: np.ndarray, sigma_torso: float = 0.02, seed: int = 0) -> np.ndarray:
    """Keypoints nudged by pose-estimator-sized noise.

    Sigma is in torso-lengths because that is the unit every feature is in: a
    2% wobble is what a good detector actually does frame to frame, and a label
    that flips under it was never carried by the geometry.
    """
    rng = np.random.default_rng(seed)
    out = kp.copy()
    torso = robust_torso(out)
    seen = out[:, :, 2] >= MIN_CONF
    noise = rng.normal(0.0, sigma_torso * torso, size=out[:, :, :2].shape)
    out[:, :, :2] = np.where(seen[:, :, None], out[:, :, :2] + noise, out[:, :, :2])
    return out


def crop(kp: np.ndarray, start: float, end: float) -> np.ndarray:
    """A contiguous slice of a clip, as fractions of its length.

    Temporal crop-resize is the single most productive augmentation reported
    for small skeleton corpora, and it is honest here for a second reason: the
    scraped clips are tutorials, so a random window of one is a *different*
    real view of the same movement, not a synthetic one.
    """
    n = len(kp)
    a = max(0, min(n - 1, int(round(start * n))))
    b = max(a + 1, min(n, int(round(end * n))))
    return kp[a:b]


# ---------------------------------------------------------------------------
# small helpers - every one returns NaN rather than a number it cannot justify
# ---------------------------------------------------------------------------
def _finite(a: np.ndarray) -> np.ndarray:
    return a[np.isfinite(a)]


def _pct(a: np.ndarray, q: float) -> float:
    a = _finite(a)
    return float(np.percentile(a, q)) if a.size else float("nan")


def _mean(a: np.ndarray) -> float:
    a = _finite(a)
    return float(a.mean()) if a.size else float("nan")


def _std(a: np.ndarray) -> float:
    a = _finite(a)
    return float(a.std()) if a.size >= 2 else float("nan")


def _range(a: np.ndarray) -> float:
    a = _finite(a)
    return float(np.percentile(a, 95) - np.percentile(a, 5)) if a.size else float("nan")


def _frac(a: np.ndarray, thresh: float) -> float:
    """Share of the MEASURED frames past a threshold. NaN when none were."""
    a = _finite(a)
    return float((a >= thresh).mean()) if a.size else float("nan")


def _angle(kp: np.ndarray, a: str, b: str, c: str) -> np.ndarray:
    """The angle at joint b, in degrees, on frames where all three were seen."""
    ia, ib, ic = S.KP_INDEX[a], S.KP_INDEX[b], S.KP_INDEX[c]
    ok = ((kp[:, ia, 2] >= MIN_CONF) & (kp[:, ib, 2] >= MIN_CONF)
          & (kp[:, ic, 2] >= MIN_CONF))
    u = kp[:, ia, :2] - kp[:, ib, :2]
    v = kp[:, ic, :2] - kp[:, ib, :2]
    nu = np.linalg.norm(u, axis=1)
    nv = np.linalg.norm(v, axis=1)
    good = ok & (nu > 1e-6) & (nv > 1e-6)
    cos = np.full(len(kp), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos[good] = np.clip((u[good] * v[good]).sum(axis=1) / (nu[good] * nv[good]),
                            -1.0, 1.0)
    return np.degrees(np.arccos(cos))


def _bilateral(kp: np.ndarray, a: str, b: str, c: str) -> np.ndarray:
    """One angle series from both sides, so a side-on clip still measures."""
    left = _angle(kp, f"left_{a}", f"left_{b}", f"left_{c}")
    right = _angle(kp, f"right_{a}", f"right_{b}", f"right_{c}")
    return np.nanmean(np.stack([left, right]), axis=0)


def _periodicity(signal: np.ndarray, fps: float) -> tuple[float, float]:
    """How repetitive the main signal is, and at what rate (reps per second).

    A set repeats; a hold does not, and neither does a talking head. The
    autocorrelation peak outside the trivial lag says which - and its lag says
    how fast, which separates a slow strict set from a fast kipping one.
    """
    a = _finite(signal)
    if a.size < 16:
        return float("nan"), float("nan")
    a = a - a.mean()
    denom = float((a * a).sum())
    if denom <= 1e-9:
        return 0.0, float("nan")
    ac = np.correlate(a, a, mode="full")[a.size - 1:] / denom
    lo = max(2, int(0.25 * fps))                 # faster than 4 reps/s is noise
    hi = min(a.size - 1, int(8.0 * fps))         # slower than one rep / 8 s
    if hi <= lo:
        return float("nan"), float("nan")
    window = ac[lo:hi]
    k = int(np.argmax(window))
    peak = float(window[k])
    lag = (lo + k) / (fps or 30.0)
    return peak, (1.0 / lag if lag > 0 else float("nan"))


# ---------------------------------------------------------------------------
# the feature vector
# ---------------------------------------------------------------------------
def kinematics(kp: np.ndarray, fps: float = 30.0) -> dict:
    """The wider feature view: joint angles, support, orientation, tempo."""
    fps = float(fps or 30.0) or 30.0
    torso = robust_torso(kp)
    out: dict[str, float] = {}

    shoulder = midpoint(kp, "left_shoulder", "right_shoulder")
    hip = midpoint(kp, "left_hip", "right_hip")
    wrist = midpoint(kp, "left_wrist", "right_wrist")
    knee = midpoint(kp, "left_knee", "right_knee")
    ankle = midpoint(kp, "left_ankle", "right_ankle")

    s_ok = pair_confidence(kp, "left_shoulder", "right_shoulder") >= MIN_CONF
    h_ok = pair_confidence(kp, "left_hip", "right_hip") >= MIN_CONF
    w_ok = pair_confidence(kp, "left_wrist", "right_wrist") >= MIN_CONF
    k_ok = pair_confidence(kp, "left_knee", "right_knee") >= MIN_CONF
    a_ok = pair_confidence(kp, "left_ankle", "right_ankle") >= MIN_CONF
    nose = kp[:, S.KP_INDEX["nose"], :]
    n_ok = nose[:, 2] >= MIN_CONF

    # --- 1. joint angles along the kinematic chains ------------------------
    # The four a coach names. Each contributes where it sits, how far it
    # travels, and how much of the clip it spent extended - the last is what
    # separates a straight-arm skill from a bent-arm one.
    chains = {
        "elbow": _bilateral(kp, "shoulder", "elbow", "wrist"),
        "knee": _bilateral(kp, "hip", "knee", "ankle"),
        "hip": _bilateral(kp, "shoulder", "hip", "knee"),
        "shoulder": _bilateral(kp, "hip", "shoulder", "elbow"),
    }
    for name, series in chains.items():
        seen = float(np.isfinite(series).mean())
        out[f"{name}_seen"] = seen
        measured = series if seen >= MIN_JOINT_SEEN else np.full(len(series), np.nan)
        out[f"{name}_min"] = _pct(measured, 5)
        out[f"{name}_max"] = _pct(measured, 95)
        out[f"{name}_median"] = _pct(measured, 50)
        out[f"{name}_rom"] = _range(measured)
        out[f"{name}_extended_frac"] = _frac(measured, 160.0)
        out[f"{name}_flexed_frac"] = _frac(-measured, -90.0)

    # --- 2. what the body is doing in space --------------------------------
    # Inversion. A handstand puts the hips above the shoulders and the head
    # below both; nothing else in the catalogue does, and the rules never
    # measured it because no branch decided a handstand.
    hips_above_shoulders = np.where(s_ok & h_ok, (hip[:, 1] - shoulder[:, 1]) / torso,
                                    np.nan)
    out["hips_above_shoulders_median"] = _pct(-hips_above_shoulders, 50)
    out["inverted_frac"] = _frac(-hips_above_shoulders, 0.30)
    head_below_hips = np.where(n_ok & h_ok, (nose[:, 1] - hip[:, 1]) / torso, np.nan)
    out["head_below_hips_frac"] = _frac(head_below_hips, 0.10)
    ankles_above_head = np.where(a_ok & n_ok, (nose[:, 1] - ankle[:, 1]) / torso,
                                 np.nan)
    out["ankles_above_head_frac"] = _frac(ankles_above_head, 0.20)

    # Where the feet are relative to the hands: on the floor below them
    # (push-up, squat), hanging under them (bar work), or carried above them
    # (handstand, back lever off rings).
    ankle_below_wrist = np.where(a_ok & w_ok, (ankle[:, 1] - wrist[:, 1]) / torso,
                                 np.nan)
    out["ankle_below_wrist_median"] = _pct(ankle_below_wrist, 50)
    out["feet_above_hands_frac"] = _frac(-ankle_below_wrist, 0.10)

    # --- 3. the support: what the hands are on -----------------------------
    # Vertically stacked hands are the human flag's signature and belong to
    # nothing else here: a flag grips a pole with one hand high and one low,
    # while every bar and floor movement puts the hands side by side.
    lw = kp[:, S.KP_INDEX["left_wrist"], :]
    rw = kp[:, S.KP_INDEX["right_wrist"], :]
    both_w = (lw[:, 2] >= MIN_CONF) & (rw[:, 2] >= MIN_CONF)
    hand_dy = np.where(both_w, np.abs(lw[:, 1] - rw[:, 1]) / torso, np.nan)
    hand_dx = np.where(both_w, np.abs(lw[:, 0] - rw[:, 0]) / torso, np.nan)
    out["hand_separation_vertical"] = _pct(hand_dy, 50)
    out["hand_separation_horizontal"] = _pct(hand_dx, 50)
    with np.errstate(invalid="ignore", divide="ignore"):
        stacked = hand_dy / np.maximum(hand_dx, 0.05)
    out["hands_stacked_ratio"] = _pct(stacked, 50)
    out["hands_stacked_frac"] = _frac(stacked, 1.5)

    # A loaded bar rides at a fixed offset from the body: on the back in a
    # squat, in the hands at arm's length in a deadlift. So the distance from
    # wrist to shoulder is nearly CONSTANT through a back squat and swings
    # through a deadlift - which is the difference the rules could never see,
    # because neither movement was one of theirs.
    wrist_to_shoulder = np.where(w_ok & s_ok,
                                 np.linalg.norm(wrist - shoulder, axis=1) / torso,
                                 np.nan)
    out["wrist_shoulder_dist_median"] = _pct(wrist_to_shoulder, 50)
    out["wrist_shoulder_dist_std"] = _std(wrist_to_shoulder)
    out["wrist_shoulder_dist_rom"] = _range(wrist_to_shoulder)
    wrist_to_hip = np.where(w_ok & h_ok,
                            np.linalg.norm(wrist - hip, axis=1) / torso, np.nan)
    out["wrist_hip_dist_median"] = _pct(wrist_to_hip, 50)
    out["wrist_hip_dist_rom"] = _range(wrist_to_hip)
    wrist_to_ankle = np.where(w_ok & a_ok, (ankle[:, 1] - wrist[:, 1]) / torso,
                              np.nan)
    out["wrist_above_ankle_min"] = _pct(wrist_to_ankle, 5)

    # --- 4. which way the body faces ---------------------------------------
    # A front lever and a back lever are the same horizontal body on the same
    # bar; the difference is which way it faces, and in 2D the only reliable
    # tell is the KNEE breaking towards the same side as the face or away from
    # it. The signed perpendicular offset of the nose from the shoulder-hip
    # line, and of the knee from it, give exactly that - and their product's
    # sign is the answer, so it survives the athlete being filmed from either
    # side (which the mirror augmentation then holds us to).
    body = hip[:, :2] - shoulder[:, :2]
    blen = np.linalg.norm(body, axis=1)
    good = (blen > 1e-6) & s_ok & h_ok
    perp = np.stack([-body[:, 1], body[:, 0]], axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        perp = perp / np.where(good, blen, np.nan)[:, None]
    nose_side = np.where(good & n_ok,
                         ((nose[:, :2] - shoulder[:, :2]) * perp).sum(axis=1) / torso,
                         np.nan)
    knee_side = np.where(good & k_ok,
                         ((knee[:, :2] - hip[:, :2]) * perp).sum(axis=1) / torso,
                         np.nan)
    out["nose_offset_signed"] = _pct(np.abs(nose_side), 50)
    out["knee_offset_signed"] = _pct(np.abs(knee_side), 50)
    same_side = np.where(np.isfinite(nose_side) & np.isfinite(knee_side),
                         np.sign(nose_side) * np.sign(knee_side), np.nan)
    out["face_knee_same_side_frac"] = _frac(same_side, 0.5)

    # --- 5. extent and posture --------------------------------------------
    # How the whole body sits in frame. A held horizontal skill is a wide, flat
    # silhouette; a squat or a press is a tall one. Taken over confident
    # landmarks only, so an occluded leg does not shrink the body.
    conf = kp[:, :, 2] >= MIN_CONF
    xs = np.where(conf, kp[:, :, 0], np.nan)
    ys = np.where(conf, kp[:, :, 1], np.nan)
    with np.errstate(invalid="ignore"):
        width = (np.nanmax(xs, axis=1) - np.nanmin(xs, axis=1)) / torso
        height = (np.nanmax(ys, axis=1) - np.nanmin(ys, axis=1)) / torso
        aspect = width / np.maximum(height, 1e-6)
    out["body_width"] = _pct(width, 50)
    out["body_height"] = _pct(height, 50)
    out["body_aspect_median"] = _pct(aspect, 50)
    out["body_aspect_max"] = _pct(aspect, 95)
    out["wide_silhouette_frac"] = _frac(aspect, 1.2)

    # Hip hinge vs knee bend. Both a squat and a deadlift lower the hips; the
    # squat does it mostly at the knee and the deadlift mostly at the hip, so
    # the RATIO of the two ranges of motion is the discriminator, and it is
    # scale-free in a second sense - it does not care how deep either went.
    knee_rom = out.get("knee_rom", float("nan"))
    hip_rom = out.get("hip_rom", float("nan"))
    if np.isfinite(knee_rom) and np.isfinite(hip_rom):
        out["hinge_ratio"] = float(hip_rom / max(knee_rom, 1.0))
    else:
        out["hinge_ratio"] = float("nan")

    # --- 6. tempo and repetition -------------------------------------------
    # The signal a set actually repeats in: the hips against the ankles when
    # the feet are on the floor, the shoulders against the hands when they are
    # not. Both are already scale-free.
    hip_signal = np.where(a_ok & h_ok, (ankle[:, 1] - hip[:, 1]) / torso, np.nan)
    bar_signal = np.where(w_ok & s_ok, (wrist[:, 1] - shoulder[:, 1]) / torso, np.nan)
    primary = hip_signal if np.isfinite(hip_signal).sum() >= np.isfinite(bar_signal).sum() \
        else bar_signal
    peak, rate = _periodicity(primary, fps)
    out["periodicity"] = peak
    out["rep_rate_hz"] = rate
    out["primary_rom"] = _range(primary)

    # Motion energy: how far the measured body moves frame to frame, in torso-
    # lengths per second. A hold is near zero however long it is held; a set is
    # not; a talking head sits between the two, and the fraction of the clip
    # spent moving is what separates that from a slow rep.
    d = np.diff(kp[:, :, :2], axis=0)
    both_seen = conf[1:] & conf[:-1]
    speed = np.where(both_seen, np.linalg.norm(d, axis=2) / torso, np.nan)
    with np.errstate(invalid="ignore"):
        per_frame = np.nanmean(speed, axis=1) * fps
    out["motion_energy_median"] = _pct(per_frame, 50)
    out["motion_energy_p95"] = _pct(per_frame, 95)
    out["moving_frac"] = _frac(per_frame, 0.25)

    # --- 7. how much was seen at all ---------------------------------------
    # Visibility is a feature, not only a caveat: which landmarks a camera
    # could see is a strong proxy for the viewpoint, and the viewpoint is part
    # of what a movement looks like from the one angle people film it from.
    for name in ("nose", "left_wrist", "left_elbow", "left_hip", "left_knee",
                 "left_ankle"):
        out[f"seen_{name}"] = float((kp[:, S.KP_INDEX[name], 2] >= MIN_CONF).mean())
    out["duration_s"] = float(len(kp) / fps)
    return out


# The full vector the learned model reads: the geometric features the rules
# decide on, plus the kinematic view above. Names are unique across the two by
# construction (the rules' names are all descriptive of their own thresholds),
# and a collision would be a bug worth failing on rather than silently letting
# one side win, so it is checked.
def full_features(kp: np.ndarray, fps: float = 30.0) -> dict:
    """Every feature the learned classifier sees, from one clip's keypoints."""
    base = geometric_features(kp, fps)
    base = {k: v for k, v in base.items() if not isinstance(v, (list, tuple))}
    extra = kinematics(kp, fps)
    clash = set(base) & set(extra)
    if clash:
        raise AssertionError(f"feature name collision: {sorted(clash)}")
    base.update(extra)
    return base


def phased_features(kp: np.ndarray, fps: float = 30.0, bins: int = 3) -> dict:
    """`full_features` for the whole clip, plus the same view of each segment.

    Every feature above is a whole-clip aggregate - a percentile, a mean, a
    fraction of frames. That makes the vector invariant to time: reverse a clip
    and it produces exactly the same numbers. But a muscle-up is a pull THEN a
    press, a squat descends THEN stands, and the descent and the ascent of a
    rep differ in ways the median of both cannot express. Whether that costs
    anything is a question the corpus can answer, so this exists to be measured
    against the flat vector rather than assumed better.

    The clip is cut into `bins` equal segments and each is featurised the same
    way, prefixed `p1_`, `p2_`, ... A segment too short to featurise
    contributes NaN, which the model's normaliser already carries as a
    sentinel - a missing segment is not a zero.
    """
    out = dict(full_features(kp, fps))
    n = len(kp)
    for i in range(bins):
        a, b = (n * i) // bins, (n * (i + 1)) // bins
        seg = kp[a:b]
        prefix = f"p{i + 1}_"
        if len(seg) >= 8:
            for k, v in full_features(seg, fps).items():
                out[prefix + k] = v
        else:
            for k in full_features(kp, fps):
                out[prefix + k] = float("nan")
    return out


def feature_names(kp_frames: int = 32) -> tuple[str, ...]:
    """The vector's names, in a fixed order, derived from a synthetic clip."""
    kp = np.zeros((kp_frames, 17, 3), dtype=np.float32)
    kp[:, :, 2] = 1.0
    kp[:, :, 0] = np.arange(17)[None, :]
    kp[:, :, 1] = np.arange(17)[None, :] * 2.0
    return tuple(sorted(full_features(kp, 30.0).keys()))
