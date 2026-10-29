"""Is the clip upside down? And what the camera framed badly.

A phone left in a locked orientation, or propped upside down on the floor, records
a clip whose container says "rotate 90" exactly like a correct one - there is no
metadata to fix. Everything downstream then reads an inverted athlete: on the
dips clip that started this (job f31bf9cfc335) geometry said muscle-up, the
learned model said back lever and vision said hanging leg raise, and the pipeline
scored six reps of a movement nobody did.

Pose alone cannot settle it. An inverted body - nose more than half a torso BELOW
the hips for most of the frames - is also what a real handstand, a skin-the-cat or
a back lever pulled from an inverted hang looks like (the corpus has all three).
So the check has two parts, and only the second one turns anything:

  * `suspect_inverted` reads the keypoints the pipeline already has, so it costs
    nothing on a normal clip, and decides whether a second look is worth paying
    for. Horizontal bodies (levers, planche, human flag) and anything with the
    head above the hips never reach it.
  * The second look poses the clip turned 180 degrees and asks the movement
    detectors again. The clip is turned only when geometry and the learned
    classifier AGREE on a movement in the turned picture and did not in the
    original (`decide`). An upright back lever is recognised as a back lever the
    way it was filmed, so it is never turned; a dips clip filmed upside down is
    recognised as dips only once it is turned.

Pure functions over numpy arrays and labels; the one function that touches
pixels (`frame_samples`) is isolated so the rules are testable without a video.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

# COCO-17 indices.
NOSE = 0
L_SHOULDER, R_SHOULDER = 5, 6
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_ANKLE, R_ANKLE = 15, 16

# A joint below this confidence is not an observation.
MIN_CONF = 0.5
# Frames with a usable head, shoulders and hips needed before anything is said.
MIN_FRAMES = 4
# The nose is "below the hips" when it is this many torso lengths lower in the
# picture (y grows downward). A hanging leg raise at its top still has the nose
# ABOVE the hips; a lever has them level (|d| < 0.5).
BELOW_HIPS = 0.5
# Share of usable frames that must read inverted.
INVERTED_SHARE = 0.7


@dataclass
class Verdict:
    """What the orientation check concluded, and why - for the trace and the
    payload. `rotate` is the one field behaviour hangs on."""
    rotate: bool = False
    rotated_by: int = 0                 # degrees applied to the clip
    status: str = "upright"             # upright | rotated | ambiguous | uncertain
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"rotatedBy": self.rotated_by, "status": self.status,
                "reason": self.reason, "evidence": self.evidence}


def _torso(kp: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    sh = (kp[L_SHOULDER, :2] + kp[R_SHOULDER, :2]) / 2.0
    hp = (kp[L_HIP, :2] + kp[R_HIP, :2]) / 2.0
    return sh, hp, float(np.linalg.norm(hp - sh))


def frame_stats(kp: np.ndarray) -> Optional[dict]:
    """One frame's orientation evidence, or None when the person is not
    readable in it (head, both shoulders or both hips under MIN_CONF).

    `head_below_hips` and `hands_below_shoulders` are in torso lengths, so they
    do not depend on how large the athlete is in the picture."""
    need = (NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)
    if kp.shape[0] < 17 or any(kp[i, 2] < MIN_CONF for i in need):
        return None
    sh, hp, length = _torso(kp)
    if length < 1e-6:
        return None
    wrist_ok = [kp[i, 2] >= MIN_CONF for i in (L_WRIST, R_WRIST)]
    hands = None
    if any(wrist_ok):
        ys = [kp[i, 1] for i, ok in zip((L_WRIST, R_WRIST), wrist_ok) if ok]
        hands = float((np.mean(ys) - sh[1]) / length)
    return {"head_below_hips": float((kp[NOSE, 1] - hp[1]) / length),
            "hands_below_shoulders": hands}


def _summarise(frames: Sequence[Optional[dict]]) -> Optional[dict]:
    usable = [f for f in frames if f is not None]
    if len(usable) < MIN_FRAMES:
        return None
    head = np.array([f["head_below_hips"] for f in usable])
    hands = [f["hands_below_shoulders"] for f in usable
             if f["hands_below_shoulders"] is not None]
    return {
        "frames": len(usable),
        "inverted_share": float(np.mean(head > BELOW_HIPS)),
        "head_below_hips_median": float(np.median(head)),
        "hands_below_shoulders_median": (float(np.median(hands)) if hands else None),
    }


def suspect_inverted(keypoints: np.ndarray, max_frames: int = 400) -> tuple[bool, dict]:
    """Cheap first look at the pose the pipeline already estimated.

    Returns (suspect, evidence). `suspect` means "worth the confirmation pass",
    not "rotate": a handstand is suspect too, and is cleared (or not) by what
    comes after. Subsamples long clips; this runs on every job."""
    kp = np.asarray(keypoints)
    if kp.ndim != 3 or len(kp) == 0:
        return False, {"frames": 0}
    step = max(1, len(kp) // max_frames)
    stats = _summarise([frame_stats(f) for f in kp[::step]])
    if stats is None:
        return False, {"frames": 0, "why": "too few frames with a readable person"}
    return stats["inverted_share"] >= INVERTED_SHARE, stats


@dataclass(frozen=True)
class Votes:
    """What the two pose-based detectors said about one orientation."""
    geometry: str = ""
    model: str = ""
    model_conf: float = 0.0


def agreement(votes: Optional[Votes]) -> Optional[str]:
    """The movement both detectors name, or None when they split or abstain."""
    if votes is None:
        return None
    from .fusion import _canonical
    g, m = _canonical(votes.geometry), _canonical(votes.model)
    return g if (g and m and g == m) else None


# Movements the classifier names for a body that is upside down by design.
# When it says one of these about a clip that reads inverted, the inversion may
# be real (a handstand, a back lever pulled from an inverted hang) - or the
# classifier's best name for a person filmed upside down, which is what the
# corpus shows: turned 180 degrees, a pull-up clip read "handstand" at 0.45.
INVERTED_BY_DESIGN = frozenset({"handstand", "back_lever"})
# The second path needs the classifier to be unsure as filmed, clearly sure of
# an ordinary movement once turned, and the vision model to name that movement.
SOFT_MAX_AS_FILMED = 0.7
SOFT_MIN_TURNED = 0.5
SOFT_MIN_GAIN = 0.1


def soft_candidate(original: Votes, rotated: Optional[Votes]) -> bool:
    """Everything the second path asks except the vision witness - cheap, so
    the caller only waits for vision when it could change the answer."""
    from .fusion import _canonical
    if rotated is None:
        return False
    mo, mr = _canonical(original.model), _canonical(rotated.model)
    if not mo or not mr or mo not in INVERTED_BY_DESIGN or mr in INVERTED_BY_DESIGN:
        return False
    if original.model_conf >= SOFT_MAX_AS_FILMED:
        return False
    if rotated.model_conf < SOFT_MIN_TURNED or \
            rotated.model_conf - original.model_conf < SOFT_MIN_GAIN:
        return False
    g = _canonical(rotated.geometry)
    return not g or g == mr


def decide(original: Votes, rotated: Optional[Votes],
           vision_label: Optional[str] = None) -> Verdict:
    """Turn the clip, or leave it.

    `original` / `rotated` are the detectors' votes on the clip as filmed and
    on the clip turned 180 degrees (None when it could not be turned or posed).
    `vision_label` is the vision model's name for the movement, when it had one.
    Turning a legitimate inverted movement is the worse error, so every path
    that turns needs the turned picture to be recognised AND something
    independent to back it.
    """
    from .fusion import _canonical
    if rotated is None:
        return Verdict(status="uncertain",
                       reason="the clip reads inverted but could not be turned to check",
                       evidence={"original": original.__dict__})
    as_filmed, turned = agreement(original), agreement(rotated)
    ev = {"original": original.__dict__, "rotated": rotated.__dict__,
          "agreedAsFilmed": as_filmed, "agreedTurned": turned}
    if turned and not as_filmed:
        return Verdict(True, 180, "rotated",
                       f"geometry and the classifier agree on {turned} only once "
                       "the clip is turned 180 degrees", ev)
    if turned and as_filmed and turned != as_filmed:
        # Both orientations are recognised as different movements: only an
        # independent witness can break it, and with none the clip stays as it
        # was filmed.
        if vision_label and _canonical(vision_label) == turned:
            return Verdict(True, 180, "rotated",
                           f"both orientations are recognised; vision names {turned}, "
                           "the turned one", ev)
        return Verdict(status="ambiguous",
                       reason=f"{as_filmed} as filmed and {turned} turned: not enough to turn it",
                       evidence=ev)
    if as_filmed:
        return Verdict(status="upright",
                       reason=f"the detectors agree on {as_filmed} as filmed", evidence=ev)
    if soft_candidate(original, rotated):
        mr = _canonical(rotated.model)
        if vision_label and _canonical(vision_label) == mr:
            return Verdict(True, 180, "rotated",
                           f"the classifier is unsure as filmed ({original.model}), "
                           f"reads {mr} at {rotated.model_conf:.2f} once turned, and "
                           "vision names the same movement", ev)
        return Verdict(status="uncertain",
                       reason=f"the turned clip reads {mr}, but nothing independent backs it",
                       evidence=ev)
    return Verdict(status="uncertain",
                   reason="inverted on the pose, and the detectors agree on nothing in "
                          "either orientation", evidence=ev)


# -- the part that touches pixels ------------------------------------------

def frame_samples(video: Path, n: int = 10, width: int = 640) -> list[np.ndarray]:
    """`n` BGR frames spread over the middle 80% of the clip, resized to `width`.
    Seeking is inexact in H.264, which is fine for a sample."""
    import cv2

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out: list[np.ndarray] = []
    try:
        if total <= 0:
            return out
        for idx in np.linspace(total * 0.1, total * 0.9, n).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, max(1, int(h * width / w))),
                                   interpolation=cv2.INTER_AREA)
            out.append(frame)
    finally:
        cap.release()
    return out


def brightness(frames: Sequence[np.ndarray]) -> Optional[float]:
    """Mean luma of the sampled frames, 0 (black) to 255. None with no frames."""
    if not len(frames):
        return None
    return float(np.mean([f.mean(axis=2).mean() if f.ndim == 3 else f.mean()
                          for f in frames]))


# -- framing and light ------------------------------------------------------

# Mean luma (0-255) under which the pose model is working in the dark. The two
# night clips that failed (2026-10-28) measure 15; over 94 corpus clips the
# median is 104 and 4% fall under 30.
DARK_LUMA = 30.0
# Share of frames in which wrists / shoulders were tracked, under which the
# upper body is out of the picture.
UPPER_BODY_SEEN = 0.25
LEGS_SEEN = 0.25


def framing_issues(keypoints: np.ndarray, luma: Optional[float]) -> list[str]:
    """Catalog codes for what is wrong with how the clip was filmed. The codes
    are rendered in Spanish by barra/i18n.py, each saying what to do."""
    issues: list[str] = []
    if luma is not None and luma < DARK_LUMA:
        issues.append("framing_dark")
    kp = np.asarray(keypoints)
    if kp.ndim == 3 and len(kp):
        conf = kp[:, :, 2]
        upper = float(np.mean(conf[:, [L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST]] >= MIN_CONF))
        legs = float(np.mean(conf[:, [L_ANKLE, R_ANKLE]] >= MIN_CONF))
        if upper < UPPER_BODY_SEEN and legs >= LEGS_SEEN:
            issues.append("framing_legs_only")
        elif upper < UPPER_BODY_SEEN and legs < LEGS_SEEN and "framing_dark" not in issues:
            # In the dark the pose model loses everyone, legs included; telling
            # the athlete they are out of frame would be wrong. The light is
            # the cause, and its message already says so.
            issues.append("framing_no_athlete")
    return issues
