"""Fusion between the interpretable geometric detector and learned detectors.

The geometric classifier is trustworthy because it states the measurement that
decided each label. A learned model and a vision label are useful second
opinions, but they are not interchangeable evidence: they can be confident on
out-of-taxonomy movements, and labels scraped from the same VLM family can agree
with themselves while both are wrong.

This module therefore makes the vote conservative:
  * it only promotes a learned/vision label when it has repeated independent
    support or, for an unknown geometric call, when the learned label is strong;
  * it never erases the geometric reason; it attaches a status that downstream
    reports can display as review;
  * aliases are resolved before voting, so `pull-up` and `pull_up` count as one.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

# Detector precedence, most reliable first. This is not a preference; it is a
# measurement, and it replaced the opposite arrangement.
#
# The first version of this module preferred geometry and let it veto the other
# detectors whenever its confidence cleared 0.85. That was written when geometry
# was the only detector anyone trusted. Measured out of fold on the 198-clip
# corpus (`scripts/classify_eval.py`, out/classify-eval/report.json):
#
#     vision      0.907        geometry, confidence >= 0.85   0.200
#     model       0.576        geometry, all answers          0.300
#     geometry    0.227
#
# Two things are fatal to the old policy. Geometry is the weakest detector by a
# factor of two, and its confidence is ANTI-correlated with being right - the
# 0.85 gate selected geometry's worst answers and handed them the veto. The
# result was a fusion that scored 0.409 when its own learned input scored 0.576
# and its vision input scored 0.907: it overrode a correct model on 45 clips to
# rescue 12, and abstained on 10 more where the model had the answer.
#
# So the rule is now: agreement first, then the most reliable detector that has
# an answer. Every band of the model's confidence beats geometry's 0.300, so the
# model is not asked to clear a bar to outrank geometry - only to be better than
# a coin flip before it speaks alone.
RELIABILITY = ("vision", "model", "geometry")

# Below this the 17-class softmax is not saying much; with no other detector
# available, "unknown" is a better answer than its guess. Measured: the model's
# lowest confidence band still runs at 0.400, so this is deliberately low.
MODEL_MIN_CONFIDENCE = 0.25

# What agreement is worth. Two independent detectors naming the same movement
# ran at 0.861 on the clips where geometry and the model agreed - well above
# either alone, which is what makes a vote worth counting at all.
AGREEMENT_CONFIDENCE = 0.86


def _label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return str(value.get("exercise") or value.get("label") or "").strip()
    return str(value).strip()


def _known(label: str) -> bool:
    return _canonical(label) is not None


# A detector that abstains says so with one of these, and an abstention is not
# a vote. Everything else it names is a name.
_NOT_A_LABEL = {"", "unknown", "none", "null", "n/a", "other"}


# Classes the learned model can name that have no measurement profile yet.
# Kept as votes so the pipeline can say "deadlift, which I cannot measure"
# instead of replacing them with confident geometry nonsense (3% right on
# exactly those clips). Free-text locate prose is NOT on this list.
_MODEL_ONLY_CLASSES = frozenset({
    "deadlift", "bench_press", "barbell_squat", "handstand",
})


def _canonical(label: str) -> Optional[str]:
    """The label's canonical form, or None if the detector did not name one.

    Resolving through the taxonomy is what makes `pull-up` and `pull_up` one
    vote instead of two detectors disagreeing. But the taxonomy is the set of
    movements the pipeline can MEASURE - it carries the geometry profile each
    one is analysed with - and that is a smaller set than the movements a
    detector can NAME. The learned classifier is trained on 17 classes and a
    few of them (deadlift, bench_press, barbell_squat, handstand) have no
    profile; those stay as votes via `_MODEL_ONLY_CLASSES`.

    Locate free-text (job cc61dc871b9d: "leg raise (lying/hanging…)") used to
    be slugified into an exercise id and win fusion as vision-decides. A name
    that is not a measured movement, a skill id, or a known model class is
    therefore refused here: no vote, not a movement.
    """
    if not label or label.strip().lower() in _NOT_A_LABEL:
        return None
    from .movements import resolve
    try:
        return resolve(label).name
    except SystemExit:
        pass
    slug = (label.strip().lower()
            .replace(" ", "_").replace("-", "_").replace("/", "_"))
    import re
    cleaned = re.sub(r"[^a-z0-9_]", "", slug).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned or cleaned in _NOT_A_LABEL:
        return None
    # "Pull-ups" → pull_ups; try the cleaned slug and a singular form.
    for candidate in (cleaned, cleaned[:-1] if cleaned.endswith("s") else ""):
        if not candidate:
            continue
        try:
            return resolve(candidate).name
        except SystemExit:
            pass
        if candidate in _MODEL_ONLY_CLASSES:
            return candidate
        try:
            from .skills import SKILLS
            if candidate in SKILLS:
                return candidate
        except Exception:  # noqa: BLE001 - skills import must not sink fusion
            pass
    return None


def _same(a: str, b: str) -> bool:
    ca, cb = _canonical(a), _canonical(b)
    return bool(ca and cb and ca == cb)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def fuse_detection(geometry: Mapping[str, Any] | str,
                   model: Optional[Mapping[str, Any]] = None,
                   nan_label: Any = None,
                   pose_reliable: bool = True) -> dict:
    """Return a final suggested exercise and why, without hiding disagreement.

    `geometry` may be a label or a `detected` dict. `model` may be a label or a
    `model_classify()` dict with `confidence` and `marginToRunnerUp`.
    `nan_label` may be a label or dict with `label`/`exercise`.
    `pose_reliable` is False when the caller knows the keypoints are suspect
    (upside-down unresolved, darkness, athlete out of frame).
    """
    g_label = _label(geometry)
    m_label = _label(model)
    n_label = (_label(nan_label.get("label") or nan_label.get("exercise"))
               if isinstance(nan_label, Mapping) else _label(nan_label))

    g_conf = _float(geometry.get("confidence") if isinstance(geometry, Mapping) else 0.0)
    m_conf = _float(model.get("confidence") if isinstance(model, Mapping) else 0.0)
    m_margin = _float(model.get("marginToRunnerUp") if isinstance(model, Mapping) else 0.0)

    said = {"vision": n_label, "model": m_label, "geometry": g_label}

    def answer(exercise: str, confidence: float, status: str, reason: str) -> dict:
        return {
            "exercise": exercise,
            "confidence": round(float(max(0.0, min(1.0, confidence))), 4),
            "status": status,
            "geometry": g_label or None,
            "model": m_label or None,
            "nan": n_label or None,
            "reason": reason,
        }

    # --- 1. agreement, wherever it comes from -----------------------------
    # Two independent detectors naming the same movement is the strongest
    # evidence available, and it does not matter which two: the vote is
    # counted on the canonical label so `pull-up` and `pull_up` are one vote,
    # not two detectors disagreeing.
    votes: dict[str, list[str]] = {}
    for who in RELIABILITY:
        can = _canonical(said[who])
        if can:
            votes.setdefault(can, []).append(who)
    agreed = [c for c, who in votes.items() if len(who) >= 2]
    if agreed:
        best = max(agreed, key=lambda c: len(votes[c]))
        backers = votes[best]
        status = ("geometry-model-agree"
                  if set(backers) == {"geometry", "model"} else "majority")
        return answer(best, max(AGREEMENT_CONFIDENCE, m_conf if
                                "model" in backers else 0.0), status,
                      f"{len(backers)} independent detectors agree on {best} "
                      f"({', '.join(sorted(backers))})")

    # --- 1b. three different names on an untrustworthy pose -----------------
    # Vision alone is usually right when geometry and the classifier split on
    # a clean clip. A sideways / dark clip makes all three misread together
    # (job f31bf9cfc335: dips filmed upside down). Do not claim a movement.
    if (not pose_reliable and _canonical(n_label) and _canonical(g_label)
            and _canonical(m_label) and m_conf >= MODEL_MIN_CONFIDENCE
            and len({_canonical(n_label), _canonical(g_label),
                     _canonical(m_label)}) == 3):
        return answer("unknown", 0.0, "three-way-disagreement-abstain",
                      f"geometry ({g_label}), the learned classifier "
                      f"({m_label}) and the vision read ({n_label}) all name "
                      "different movements on a clip the pose could not read "
                      "reliably, so the exercise is not claimed")

    # Static holds that vision invents for an articulated hang (job
    # 93ebbf6e4894: vision said l_sit for a front-lever pull). A hold label
    # must not outrank a rep-based hang geometry named.
    _HOLD_SKILLS = frozenset({
        "l_sit", "v_sit", "manna", "front_lever", "back_lever", "planche",
        "tuck_front_lever", "adv_tuck_front_lever", "straddle_front_lever",
        "half_front_lever", "tuck_back_lever", "dead_hang",
    })
    _HANG_REPS = frozenset({
        "pull_up", "chin_up", "muscle_up", "knee_raise", "inverted_curl",
        "front_lever_pull_up", "toes_to_bar",
    })

    # --- 2. no agreement: the most reliable detector that has an answer ----
    # Geometry keeps its say only where nothing better spoke. It is never
    # silently discarded - `geometry` is on every payload above, so a consumer
    # can still show the disagreement and the measurement behind it.
    for who in RELIABILITY:
        can = _canonical(said[who])
        if not can:
            continue
        if who == "vision":
            g_can = _canonical(g_label)
            if (can in _HOLD_SKILLS and g_can in _HANG_REPS):
                # Skip vision; let model or geometry speak for the hang.
                continue
            return answer(can, 0.90, "vision-decides",
                          "the vision read of the frames is the most reliable "
                          "single detector and the others did not agree")
        if who == "model":
            if m_conf < MODEL_MIN_CONFIDENCE:
                continue  # near a coin flip; let geometry try
            return answer(can, m_conf, "model-decides",
                          "the learned classifier decided; it is measured well "
                          "above the geometric detector on this corpus")
        return answer(can, g_conf, "geometry-only",
                      "geometry decided the movement; no other detector "
                      "offered a usable label")

    # --- 3. nobody had a usable answer ------------------------------------
    return {
        "exercise": "unknown",
        "confidence": 0.0,
        "status": "abstain",
        "geometry": g_label or None,
        "model": m_label or None,
        "nan": n_label or None,
        "reason": "no detector had enough support to name the movement",
    }
