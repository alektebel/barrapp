"""The rule registry: every technique error the geometry can assess, as data.

barra/faults_taxonomy.py used to hold one Python function per movement, each
a list of `_fire(...)` calls. That was testable, but the only way to know which
phase a rule read, which camera it needed, or what it actually measured was to
read the predicate body - and the debug tool kept a hand-typed mirror of it
that had already drifted. So each rule is a record here:

    id           stable, movement-scoped: "muscle_up.incomplete_support_extension".
                 The client and the evaluation harness key on this. It names
                 the OBSERVABLE condition, never the coached cause.
    name         the display label the phone renders today. Preserved through
                 the migration; Cues.kt maps these to over-the-video words and
                 tests/test_cues_parity.py holds the two lists equal.
    phase        where in the rep the primitive is read (barra/phases.py).
    primitive    the Evidence key it reads; robustness, plane and unit come
                 from evidence.PRIMITIVES, not from here.
    comparison   how the value is compared with the threshold, and
    threshold    the one number, a field of config.THRESHOLDS - never a literal.
    observable   what the number is, in words a reviewer can check on the video.
    correction   the cue template.
    note         where the coached label claims more than the measurement
                 shows (bent elbows are not, by themselves, a scapular
                 failure), the note says so. The label is kept for the client;
                 the record does not pretend it is what was measured.
    variants     technique variants the rule applies to; empty = all. A rule
                 with `variant_dependent=True` is still reported when the
                 variant is unspecified, but marked so a consumer knows it was
                 judged against an assumed standard.

`assess()` turns the registry and one Evidence record into the assessment
contract of the implementation plan (section 3): every applicable rule gets a
status - observed, not_observed or unobservable - with the evidence behind it
and, when it could not be judged, the reason. `classify_faults` in
faults_taxonomy.py is the "observed" subset of that, in the shape the client
already parses.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import THRESHOLDS as T
from .evidence import (INSUFFICIENT_EVIDENCE, MEASURED, NOT_APPLICABLE,
                       PRIMITIVES, SCALED, TRACKING_LOSS, UNMEASURED,
                       UNSUITABLE_VIEW, UNSUPPORTED_VARIANT, VIEW_BLOCKED,
                       Evidence)

# Bumped when the meaning of a measurement changes in a way that can move a
# score or a fault on an unchanged clip. Version 1 was the pre-September
# taxonomy; version 2 corrects descending-first phase timing, excludes the
# endpoint deceleration from the stall count, and reads the muscle-up's bent
# arms at the top support rather than across the whole rep. Historical
# payloads carrying a lower version are not comparable without reprocessing.
ASSESSMENT_VERSION = 2
SOURCE_GEOMETRY = "geometry"

OBSERVED = "observed"
NOT_OBSERVED = "not_observed"
UNOBSERVABLE = "unobservable"

VARIANT_UNSPECIFIED = "unspecified"
STRICT, KIPPING = "strict", "kipping"
FULL, TUCK, STRADDLE = "full", "tuck", "straddle"


@dataclass(frozen=True)
class Rule:
    id: str
    movement: str
    name: str
    phase: str
    primitive: str
    comparison: str
    threshold: float
    observable: str
    correction: str
    note: str = ""
    variants: tuple[str, ...] = ()
    variant_dependent: bool = False

    def applies_to(self, variant: str) -> bool:
        """Whether this rule is defined for `variant`. An unspecified variant
        keeps every rule; a declared one drops the rules written for a
        different standard (a kip is not a fault of a kipping muscle-up)."""
        if not self.variants or variant in ("", None, VARIANT_UNSPECIFIED):
            return True
        return variant in self.variants

    def fires(self, value: float) -> bool:
        return {
            "<": value < self.threshold,
            "<=": value <= self.threshold,
            ">": value > self.threshold,
            ">=": value >= self.threshold,
        }[self.comparison]

    def as_dict(self) -> dict:
        spec = PRIMITIVES.get(self.primitive, (SCALED, "", ""))
        return {
            "id": self.id, "movement": self.movement, "name": self.name,
            "phase": self.phase, "primitive": self.primitive,
            "comparison": self.comparison, "threshold": self.threshold,
            "unit": spec[2], "robustness": spec[0], "plane": spec[1],
            "observable": self.observable, "correction": self.correction,
            "note": self.note, "variants": list(self.variants),
            "variantDependent": self.variant_dependent,
        }


def _r(movement: str, error: str, name: str, phase: str, primitive: str,
       comparison: str, threshold: float, observable: str, correction: str,
       note: str = "", variants: tuple[str, ...] = (),
       variant_dependent: bool = False) -> Rule:
    return Rule(f"{movement}.{error}", movement, name, phase, primitive,
                comparison, threshold, observable, correction, note, variants,
                variant_dependent)


# ---------------------------------------------------------------------------
# Shared bar rules - wrist-origin repetition movements
# ---------------------------------------------------------------------------
def _bar(movement: str) -> list[Rule]:
    return [
        _r(movement, "body_swing", "momentum", "rep", "swing", ">", T.swing_torso,
           "the hips travel more than the threshold, in torso-lengths, relative "
           "to the hands across the rep",
           "Stop the swing - pull strict, no momentum",
           note="visible swing. Whether it violates the standard depends on the "
                "variant: a kipping rep is allowed it, a strict one is not.",
           variants=(STRICT,), variant_dependent=True),
        _r(movement, "incomplete_lockout", "lockout", "support", "lockout_pct", "<",
           T.lockout_min * 100,
           "the shoulders' height above the hands at the top, as a share of the "
           "athlete's own arm reach",
           "Lock out fully at the top of every rep"),
        _r(movement, "incomplete_hang", "dead hang", "setup", "hang_pct", "<",
           T.hang_min * 100,
           "the shoulders' depth below the hands at the start, as a share of "
           "the athlete's own arm reach",
           "Start every rep from a full dead hang"),
        _r(movement, "dropped_descent", "control", "rep", "tempo_ratio", "<",
           T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop from the top"),
        _r(movement, "lift_stall", "stall", "lifting", "stalled_frac", ">=",
           T.stalled_frac,
           "the share of the lift, outside its first and last 10% of travel, "
           "spent making no progress",
           "Drive through the sticking point in one arc"),
    ]


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
RULES: dict[str, tuple[Rule, ...]] = {
    "front_lever": (
        _r("front_lever", "body_below_horizontal", "poor range of motion", "hold",
           "body_line_deg", "<", T.strict_horizontal,
           "the median shoulder-hip line angle from vertical across the hold",
           "Take every rep through its full range"),
        _r("front_lever", "bent_arms", "poor scapular retraction", "hold",
           "arms_straight_frac", "<", T.arms_straight_frac,
           "the share of the hold with the elbow angle at or above the "
           "straight-arm threshold",
           "Set the shoulders down and back first",
           note="the label names the coached cause; what is measured is elbow "
                "extension. Bent elbows do not by themselves demonstrate poor "
                "scapular retraction."),
        _r("front_lever", "bent_knees", "bent knees", "hold", "legs_straight_frac",
           "<", T.legs_straight_frac,
           "the share of the hold with the knee angle at or above the "
           "straight-leg threshold",
           "Keep the legs straight through the hold", variants=(FULL,),
           variant_dependent=True),
        _r("front_lever", "piked_hips", "piked hips", "hold", "hip_pike_deg", "<",
           T.pike, "the median shoulder-hip-knee angle across the hold",
           "Hold the body flat - no piking at the hips", variants=(FULL, STRADDLE),
           variant_dependent=True),
        _r("front_lever", "body_swing", "momentum", "hold", "swing", ">",
           T.swing_torso, "hip travel relative to the shoulders across the hold",
           "Stop the swing - pull strict, no momentum"),
    ),
    "planche": (
        _r("planche", "body_below_horizontal", "poor range of motion", "hold",
           "body_line_deg", "<", T.strict_horizontal,
           "the median shoulder-hip line angle from vertical across the hold",
           "Take every rep through its full range"),
        _r("planche", "bent_arms", "poor scapular protraction", "hold",
           "arms_straight_frac", "<", T.arms_straight_frac,
           "the share of the hold with the elbow angle at or above the "
           "straight-arm threshold",
           "Push the shoulders away at the top",
           note="the label names the coached cause; what is measured is elbow "
                "extension. Bent elbows do not by themselves demonstrate poor "
                "scapular protraction."),
        _r("planche", "bent_knees", "bent knees", "hold", "legs_straight_frac", "<",
           T.legs_straight_frac,
           "the share of the hold with the knee angle at or above the "
           "straight-leg threshold",
           "Keep the legs straight through the hold", variants=(FULL,),
           variant_dependent=True),
        _r("planche", "piked_body", "piked body", "hold", "hip_pike_deg", "<",
           T.pike, "the median shoulder-hip-knee angle across the hold",
           "Hold the body flat - no piking at the hips", variants=(FULL, STRADDLE),
           variant_dependent=True),
        _r("planche", "body_swing", "momentum", "hold", "swing", ">", T.swing_torso,
           "hip travel relative to the shoulders across the hold",
           "Stop the swing - pull strict, no momentum"),
    ),
    "muscle_up": tuple(_bar("muscle_up")) + (
        _r("muscle_up", "slow_transition", "poor transition", "transition",
           "transition_s", ">", T.transition_s,
           "seconds the shoulders spend within the bar plane during the lift",
           "Get through the transition in one movement"),
        _r("muscle_up", "incomplete_support_extension", "bent arms", "support",
           "top_elbow_deg", "<", T.straight_arm,
           "the median elbow angle in the support window at the top of the rep",
           "Press out to straight arms at the top of every rep",
           note="elbows bend during the pull and transition by design; only the "
                "support at the top is held to the straight-arm threshold."),
    ),
    "pull_up": tuple(_bar("pull_up")) + (
        _r("pull_up", "no_active_hang", "no active hang", "setup", "start_elbow_deg",
           "<", T.active_hang_deg,
           "the median elbow angle in the setup window at the start of the rep",
           "Straighten the arms between reps - hang, then pull"),
        _r("pull_up", "fast_lift", "too fast", "lifting", "fast_ratio", "<",
           T.fast_rep_frac,
           "this rep's lift duration as a share of the set's own median lift",
           "Slow the pull down - these are being thrown"),
    ),
    "dip": (
        _r("dip", "incomplete_lockout", "lockout", "support", "start_elbow_deg", "<",
           T.straight_arm,
           "the median elbow angle in the support window before lowering",
           "Lock out fully at the top of every rep"),
        _r("dip", "excessive_depth", "too deep", "turnaround", "bottom_elbow_deg",
           "<", T.dip_bottom_deg,
           "the median elbow angle in the turnaround window at the bottom",
           "Stop at ninety degrees - deeper is shoulder, not chest"),
        _r("dip", "bounce", "bounce at bottom", "turnaround", "turn_speed", ">",
           T.bounce_speed,
           "the slowest speed of the tracked point through the turnaround, in "
           "torso-lengths per second",
           "Pause at the bottom instead of bouncing out of it"),
        _r("dip", "dropped_descent", "control", "rep", "tempo_ratio", "<",
           T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop from the top"),
        _r("dip", "lift_stall", "stall", "lifting", "stalled_frac", ">=",
           T.stalled_frac,
           "the share of the lift, outside its first and last 10% of travel, "
           "spent making no progress",
           "Drive through the sticking point in one arc"),
    ),
    "push_up": (
        _r("push_up", "short_travel", "poor range of motion", "rep", "travel", "<",
           T.push_up_depth,
           "the shoulders' travel toward the hands across the rep, in "
           "torso-lengths",
           "Take every rep through its full range"),
        _r("push_up", "incomplete_lockout", "lockout", "support", "start_elbow_deg",
           "<", T.straight_arm,
           "the median elbow angle in the support window before lowering",
           "Lock out fully at the top of every rep"),
        _r("push_up", "hip_sag", "sagging hips", "rep", "hip_sag", ">", T.hip_sag,
           "the 90th percentile of the hips' drop below the shoulder-ankle "
           "line, in torso-lengths",
           "Hold the hips in line - squeeze the glutes"),
        _r("push_up", "dropped_descent", "control", "rep", "tempo_ratio", "<",
           T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop from the top"),
        _r("push_up", "lift_stall", "stall", "lifting", "stalled_frac", ">=",
           T.stalled_frac,
           "the share of the lift, outside its first and last 10% of travel, "
           "spent making no progress",
           "Drive through the sticking point in one arc"),
    ),
    "squat": (
        _r("squat", "shallow_depth", "poor range of motion", "rep", "squat_depth",
           "<", T.squat_depth,
           "the hips' drop from this rep's own standing height, measured over "
           "the ankles, in torso-lengths",
           "Take every rep through its full range"),
        _r("squat", "dropped_descent", "uncontrolled descent", "rep", "tempo_ratio",
           "<", T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop into the hole"),
        _r("squat", "knee_medial_drift", "knee valgus", "rep", "knee_valgus", ">",
           T.pistol_valgus,
           "the 90th percentile of the knee's sideways offset from the hip-ankle "
           "line, in torso-lengths",
           "Drive the knees out over the toes"),
        _r("squat", "planted_ankle_rise", "heel raise", "rep", "heel_rise", ">",
           T.heel_rise,
           "how far the planted ankle landmark rises above its own lowest "
           "position in the rep, in torso-lengths",
           "Keep the heels down through the whole rep",
           note="an ankle-landmark rise, not direct heel tracking: the heel "
                "itself is not a landmark."),
        _r("squat", "lift_stall", "stall", "lifting", "stalled_frac", ">=",
           T.stalled_frac,
           "the share of the lift, outside its first and last 10% of travel, "
           "spent making no progress",
           "Drive through the sticking point in one arc"),
    ),
    "pistol_squat": (
        _r("pistol_squat", "shallow_depth", "poor range of motion", "rep",
           "pistol_depth", "<", T.pistol_depth,
           "the hips' drop below the standing ankle, in torso-lengths",
           "Take every rep through its full range"),
        _r("pistol_squat", "knee_medial_drift", "knee valgus", "rep", "knee_valgus",
           ">", T.pistol_valgus,
           "the 90th percentile of the knee's sideways offset from the hip-ankle "
           "line, in torso-lengths",
           "Drive the knees out over the toes"),
        _r("pistol_squat", "planted_ankle_rise", "heel raise", "rep", "heel_rise",
           ">", T.heel_rise,
           "how far the planted ankle landmark rises above its own lowest "
           "position in the rep, in torso-lengths",
           "Keep the heels down through the whole rep",
           note="an ankle-landmark rise, not direct heel tracking: the heel "
                "itself is not a landmark."),
        _r("pistol_squat", "backward_lean", "leaning back", "rep", "torso_lean", "<",
           T.lean_back,
           "the 90th percentile of the hips' horizontal lead over the shoulders, "
           "in torso-lengths (negative = hips ahead)",
           "Keep the chest up - stop leaning back out of it"),
        _r("pistol_squat", "dropped_descent", "uncontrolled descent", "rep",
           "tempo_ratio", "<", T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop into the hole"),
        _r("pistol_squat", "arm_swing", "arm swing", "rep", "swing", ">",
           T.swing_torso, "hip travel relative to the origin across the rep",
           "Keep the arms still - no swinging for balance"),
    ),
    "split_squat": (
        _r("split_squat", "shallow_depth", "poor range of motion", "rep",
           "split_depth", "<", T.split_depth,
           "the hips' drop below the planted FRONT ankle, in torso-lengths",
           "Take every rep through its full range"),
        _r("split_squat", "knee_medial_drift", "knee valgus", "rep", "knee_valgus",
           ">", T.pistol_valgus,
           "the 90th percentile of the knee's sideways offset from the hip-ankle "
           "line, in torso-lengths",
           "Drive the knees out over the toes"),
        _r("split_squat", "planted_ankle_rise", "heel raise", "rep", "heel_rise",
           ">", T.heel_rise,
           "how far the planted ankle landmark rises above its own lowest "
           "position in the rep, in torso-lengths",
           "Keep the front heel down through the whole rep",
           note="an ankle-landmark rise, not direct heel tracking."),
        _r("split_squat", "backward_lean", "leaning back", "rep", "torso_lean", "<",
           T.lean_back,
           "the 90th percentile of the hips' horizontal lead over the shoulders, "
           "in torso-lengths (negative = hips ahead)",
           "Keep the chest up - stop leaning back out of it"),
        _r("split_squat", "dropped_descent", "uncontrolled descent", "rep",
           "tempo_ratio", "<", T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop into the hole"),
    ),
    "bulgarian_split_squat": (
        _r("bulgarian_split_squat", "shallow_depth", "poor range of motion", "rep",
           "split_depth", "<", T.split_depth,
           "the hips' drop below the planted FRONT ankle, in torso-lengths",
           "Take every rep through its full range"),
        _r("bulgarian_split_squat", "knee_medial_drift", "knee valgus", "rep",
           "knee_valgus", ">", T.pistol_valgus,
           "the 90th percentile of the knee's sideways offset from the hip-ankle "
           "line, in torso-lengths",
           "Drive the knees out over the toes"),
        _r("bulgarian_split_squat", "planted_ankle_rise", "heel raise", "rep",
           "heel_rise", ">", T.heel_rise,
           "how far the planted ankle landmark rises above its own lowest "
           "position in the rep, in torso-lengths",
           "Keep the front heel down through the whole rep",
           note="an ankle-landmark rise, not direct heel tracking."),
        _r("bulgarian_split_squat", "backward_lean", "leaning back", "rep",
           "torso_lean", "<", T.lean_back,
           "the 90th percentile of the hips' horizontal lead over the shoulders, "
           "in torso-lengths (negative = hips ahead)",
           "Keep the chest up - stop leaning back out of it"),
        _r("bulgarian_split_squat", "dropped_descent", "uncontrolled descent", "rep",
           "tempo_ratio", "<", T.controlled_tempo,
           "the lowering phase lasts less than the threshold share of the lift",
           "Lower under control - don't drop into the hole"),
    ),
}

# Variants whose error definitions differ materially. Declared, never
# inferred from one posture: the client may send one, and the payload labels
# it as declared. Anything else is `unspecified`.
KNOWN_VARIANTS: dict[str, tuple[str, ...]] = {
    "pull_up": (STRICT, KIPPING),
    "muscle_up": (STRICT, KIPPING),
    "front_lever": (FULL, TUCK, STRADDLE),
    "planche": (FULL, TUCK, STRADDLE),
}


def rules_for(movement: str) -> tuple[Rule, ...]:
    return RULES.get(movement, ())


def rule_by_id(rule_id: str) -> Rule | None:
    for rules in RULES.values():
        for r in rules:
            if r.id == rule_id:
                return r
    return None


def all_rule_ids() -> tuple[str, ...]:
    return tuple(r.id for rules in RULES.values() for r in rules)


def normalise_variant(movement: str, declared: str | None) -> dict:
    """{name, source} for the variant a job declared, or unspecified.

    A declared variant the movement does not define is not silently accepted:
    it is reported as unspecified with the declaration kept beside it, so the
    fault taxonomy for a different standard cannot be activated by a typo.
    """
    raw = (declared or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw or raw == VARIANT_UNSPECIFIED:
        return {"name": VARIANT_UNSPECIFIED, "source": "none"}
    if raw in KNOWN_VARIANTS.get(movement, ()):
        return {"name": raw, "source": "declared"}
    return {"name": VARIANT_UNSPECIFIED, "source": "none", "declared": raw,
            "why": f"{raw!r} is not a known variant of {movement}"}


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Assessment:
    """One rule applied to one rep or hold: the verdict and its evidence."""
    rule: Rule
    status: str                      # observed | not_observed | unobservable
    value: float | None
    state: str                       # the primitive's knowability state
    reason: str = ""                 # availability reason when unobservable
    phase_window: tuple[int, int] | None = None
    coverage: float | None = None
    variant: str = VARIANT_UNSPECIFIED

    @property
    def fired(self) -> bool:
        return self.status == OBSERVED

    def as_dict(self, rep: str = "", fps: float = 30.0) -> dict:
        spec = PRIMITIVES.get(self.rule.primitive, (SCALED, "", ""))
        fps = max(float(fps), 1.0)
        interval = (None if self.phase_window is None else
                    [round(self.phase_window[0] / fps, 2),
                     round(self.phase_window[1] / fps, 2)])
        out = {
            "rep": rep,
            "exercise": self.rule.movement,
            "variant": self.variant,
            "errorId": self.rule.id,
            "name": self.rule.name,
            "phase": self.rule.phase,
            "scope": "rep" if self.rule.phase in ("rep", "hold") else "phase",
            "status": self.status,
            "intervalS": interval,
            "evidence": {
                "primitive": self.rule.primitive,
                "value": None if self.value is None else round(float(self.value), 4),
                "threshold": round(float(self.rule.threshold), 4),
                "comparison": self.rule.comparison,
                "unit": spec[2],
                "class": spec[0],
                "coverage": None if self.coverage is None else round(float(self.coverage), 3),
            },
            "source": SOURCE_GEOMETRY,
            "version": ASSESSMENT_VERSION,
        }
        if self.status == UNOBSERVABLE:
            out["availability"] = {"reason": _reason_kind(self.reason),
                                   "detail": self.reason}
        if self.rule.variant_dependent and self.variant == VARIANT_UNSPECIFIED:
            out["variantDependent"] = True
        if self.rule.note:
            out["note"] = self.rule.note
        return out


def _reason_kind(detail: str) -> str:
    for kind in (UNSUITABLE_VIEW, INSUFFICIENT_EVIDENCE, UNSUPPORTED_VARIANT,
                 NOT_APPLICABLE, TRACKING_LOSS):
        if detail.startswith(kind):
            return kind
    return TRACKING_LOSS


def assess(movement: str, ev: Evidence, variant: str = VARIANT_UNSPECIFIED,
           blocked: str = "") -> list[Assessment]:
    """Every rule of `movement`, judged on `ev`.

    `blocked`, when given, is a reason the whole rep cannot be assessed (an
    implausible pose, too little tracking): every rule is then unobservable
    with that reason, and nothing fires. An unusable measurement must not
    produce an authoritative fault label, whether or not a score was withheld.

    A rule written for a different declared variant is left out entirely -
    not "not observed", which would read as a pass.
    """
    out: list[Assessment] = []
    for rule in rules_for(movement):
        if not rule.applies_to(variant):
            continue
        m = ev.get(rule.primitive)
        if blocked:
            out.append(Assessment(rule, UNOBSERVABLE, None, UNMEASURED,
                                  f"{TRACKING_LOSS}: {blocked}", m.window,
                                  m.coverage, variant))
            continue
        if m.state == MEASURED and m.value is not None:
            status = OBSERVED if rule.fires(m.value) else NOT_OBSERVED
            out.append(Assessment(rule, status, m.value, m.state, "",
                                  m.window, m.coverage, variant))
        else:
            reason = m.reason or (UNSUITABLE_VIEW if m.state == VIEW_BLOCKED
                                  else TRACKING_LOSS)
            out.append(Assessment(rule, UNOBSERVABLE, None, m.state, reason,
                                  m.window, m.coverage, variant))
    return out


def summarise(assessments: list[list[Assessment]]) -> dict:
    """Clip-level roll-up: per errorId, how many reps observed it, how many
    were checked and clean, how many could not be checked. An empty fault
    list is only a clean result when the checked count says so."""
    table: dict[str, dict] = {}
    for per_rep in assessments:
        for a in per_rep:
            row = table.setdefault(a.rule.id, {
                "errorId": a.rule.id, "name": a.rule.name, "phase": a.rule.phase,
                "observed": 0, "notObserved": 0, "unobservable": 0,
                "reasons": {}})
            if a.status == OBSERVED:
                row["observed"] += 1
            elif a.status == NOT_OBSERVED:
                row["notObserved"] += 1
            else:
                row["unobservable"] += 1
                kind = _reason_kind(a.reason)
                row["reasons"][kind] = row["reasons"].get(kind, 0) + 1
    return {"version": ASSESSMENT_VERSION, "checks": list(table.values())}
