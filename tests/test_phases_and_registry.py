"""The phase table, the coverage gate and the rule registry: one source of
truth each, and the payload rows that come out of them."""
import dataclasses

import numpy as np
import pytest

from barra import config
from barra.evidence import (INSUFFICIENT_EVIDENCE, MEASURED, PRIMITIVES,
                            UNMEASURED, Evidence, rep_evidence)
from barra.movements import MOVEMENTS
from barra.phases import (HAS_TRANSITION, hold_phases, phases_as_dict,
                          rep_phases, transition_band)
from barra.rules import (ASSESSMENT_VERSION, NOT_OBSERVED, OBSERVED, RULES,
                         UNOBSERVABLE, VARIANT_UNSPECIFIED, all_rule_ids,
                         assess, normalise_variant, rule_by_id, rules_for,
                         summarise)


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------
def test_ascending_rep_lifts_first_and_supports_at_the_turn():
    ph = rep_phases(MOVEMENTS["pull_up"], 0, 60, 90, 30)
    assert (ph["lifting"].start, ph["lifting"].end) == (0, 60)
    assert (ph["lowering"].start, ph["lowering"].end) == (60, 90)
    assert ph["support"].start <= 60 <= ph["support"].end
    assert ph["setup"].start == 0
    assert "turnaround" not in ph
    assert "transition" not in ph


def test_descending_rep_lowers_first_and_supports_at_the_start():
    ph = rep_phases(MOVEMENTS["push_up"], 0, 60, 90, 30)
    assert (ph["lowering"].start, ph["lowering"].end) == (0, 60)
    assert (ph["lifting"].start, ph["lifting"].end) == (60, 90)
    assert ph["support"].start == 0
    assert ph["turnaround"].start <= 60 <= ph["turnaround"].end


def test_transition_is_named_only_for_movements_that_have_one():
    for name, m in MOVEMENTS.items():
        if m.is_hold:
            continue
        ph = rep_phases(m, 0, 30, 60, 30)
        assert ("transition" in ph) == (name in HAS_TRANSITION), name


def test_transition_band_narrows_to_the_frames_in_the_bar_plane():
    ph = rep_phases(MOVEMENTS["muscle_up"], 0, 60, 90, 30)
    sig = np.linspace(-1.0, 1.0, 91)          # crosses the plane mid-lift
    band = transition_band(sig, ph, 0.15)
    assert band is not None
    assert 0 < band.start < band.end < 60
    assert np.all(np.abs(sig[band.start:band.end + 1]) <= 0.15)
    # A lift that never reaches the plane has no transition to report.
    assert transition_band(np.linspace(-1.0, -0.5, 91), ph, 0.15) is None
    # And nothing is invented for a movement that has none.
    assert transition_band(sig, rep_phases(MOVEMENTS["pull_up"], 0, 60, 90, 30), 0.15) is None


def test_hold_phases_split_onset_sustained_exit():
    ph = hold_phases(0, 90, 30)
    assert ph["onset"].start == 0 and ph["exit"].end == 90
    assert ph["onset"].end < ph["sustained"].start <= ph["sustained"].end < ph["exit"].start
    d = phases_as_dict(ph, 30)
    assert d["hold"] == [0.0, 3.0]


def test_metrics_report_the_narrowed_transition_and_payload_uses_it():
    from barra.metrics import rep_metrics
    from tests.test_technique_phases import skeleton
    from barra.schema import KP_INDEX as I
    kp = skeleton(91)
    # Shoulders rise from well below the wrists to well above them.
    rise = np.r_[np.linspace(0, 200, 61), np.linspace(200, 0, 30)]
    for side in ("left", "right"):
        kp[:, I[f"{side}_shoulder"], 1] = 400 - rise
        kp[:, I[f"{side}_wrist"], 1] = 300
    m = rep_metrics(kp, 0, 60, 90, 30, MOVEMENTS["muscle_up"])
    tr = m.phases["transition"]
    assert tr.frames - 1 <= round(m.values["transition_s"] * 30) <= tr.frames
    assert tr.end < 60 and tr.frames < m.phases["lifting"].frames


# ---------------------------------------------------------------------------
# coverage gate
# ---------------------------------------------------------------------------
def test_a_barely_tracked_window_is_unmeasured_with_a_reason():
    ev = Evidence("pull_up")
    ev.add("swing", 0.3, phase="rep", window=(0, 99), coverage=0.2)
    m = ev.get("swing")
    assert m.state == UNMEASURED
    assert m.reason.startswith(INSUFFICIENT_EVIDENCE)
    assert "20%" in m.reason
    ev.add("swing", 0.3, phase="rep", window=(0, 99), coverage=0.9)
    assert ev.get("swing").state == MEASURED


def test_too_few_samples_is_unmeasured_unless_the_caller_vouches_for_them():
    ev = Evidence("muscle_up")
    # A 2-frame window: too few samples for a median...
    ev.add("top_elbow_deg", 170.0, phase="support", window=(10, 11), coverage=1.0)
    assert ev.get("top_elbow_deg").state == UNMEASURED
    # ...but a 2-frame transition IS the measurement, backed by the lift.
    ev.add("transition_s", 0.07, phase="transition", window=(10, 11),
           coverage=1.0, seen=60)
    assert ev.get("transition_s").state == MEASURED


def test_missing_primitive_reads_as_tracking_loss_not_as_a_value():
    ev = Evidence("pull_up")
    m = ev.get("nothing_here")
    assert m.state == UNMEASURED and m.value is None and m.reason


def test_rep_evidence_windows_carry_phase_and_coverage():
    sig = np.sin(np.linspace(0, np.pi, 91))
    valid = np.ones(91, dtype=bool)
    valid[:45] = False                          # the lift was barely seen
    ev = rep_evidence({"concentric_s": 1.5, "eccentric_s": 1.0}, 1.0, sig,
                      0, 45, 90, 30, MOVEMENTS["pull_up"], valid=valid)
    w = ev.windows(30)
    assert w["concentric_s"]["phase"] == "lifting"
    assert w["concentric_s"]["coverage"] < 0.1
    assert w["concentric_s"]["state"] == UNMEASURED
    assert w["eccentric_s"]["phase"] == "lowering"
    assert w["eccentric_s"]["state"] == MEASURED


def test_transition_window_is_the_band_not_the_lift():
    sig = np.linspace(-1.0, 1.0, 91)
    ev = rep_evidence({"transition_s": 0.3}, 1.0, sig, 0, 60, 90, 30,
                      MOVEMENTS["muscle_up"], valid=np.ones(91, bool))
    w = ev.windows(30)["transition_s"]
    lo, hi = w["intervalS"]
    assert 0 < lo < hi < 2.0
    assert w["state"] == MEASURED


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def test_rule_ids_are_unique_and_movement_scoped():
    ids = all_rule_ids()
    assert len(ids) == len(set(ids))
    for movement, rules in RULES.items():
        for r in rules:
            assert r.id.startswith(movement + "."), r.id
            assert r.movement == movement
            assert rule_by_id(r.id) is r


def test_every_rule_reads_a_known_primitive_and_a_config_threshold():
    raw = [float(v) for v in dataclasses.asdict(config.THRESHOLDS).values()
           if isinstance(v, (int, float))]
    # Percent-scaled primitives compare with a fraction threshold times 100.
    cfg = {round(v, 6) for v in raw} | {round(v * 100, 6) for v in raw}
    for r in (x for rules in RULES.values() for x in rules):
        assert r.primitive in PRIMITIVES, r.id
        assert round(float(r.threshold), 6) in cfg, (r.id, r.threshold)
        assert r.phase in {"rep", "setup", "lowering", "lifting", "transition",
                           "support", "turnaround", "hold", "onset", "sustained", "exit"}
        assert r.observable and r.correction


def test_registry_and_taxonomy_agree():
    from barra.faults_taxonomy import TRACK_FAILURES, all_tracks
    assert set(all_tracks()) == set(RULES)
    for movement, rules in RULES.items():
        assert set(TRACK_FAILURES[movement]) == {r.name for r in rules}


def test_assess_yields_three_statuses_and_only_observed_fires():
    ev = Evidence("pull_up")
    ev.add("swing", 0.9, phase="rep", window=(0, 90), coverage=1.0)        # fires
    ev.add("lockout_pct", 95.0, phase="support", window=(40, 50), coverage=1.0)  # clean
    ev.add("hang_pct", 50.0, phase="setup", window=(0, 5), coverage=0.1)    # too little
    by_id = {a.rule.id: a for a in assess("pull_up", ev)}
    assert by_id["pull_up.body_swing"].status == OBSERVED
    assert by_id["pull_up.incomplete_lockout"].status == NOT_OBSERVED
    hang = by_id["pull_up.incomplete_hang"]
    assert hang.status == UNOBSERVABLE
    assert hang.reason.startswith(INSUFFICIENT_EVIDENCE)
    assert hang.as_dict("r1", 30)["availability"]["reason"] == INSUFFICIENT_EVIDENCE
    fired = {a.rule.id for a in by_id.values() if a.fired}
    assert fired == {"pull_up.body_swing"}


def test_blocked_rep_is_unobservable_everywhere_and_fires_nothing():
    from barra.faults_taxonomy import classify_faults
    ev = Evidence("pull_up")
    ev.add("swing", 0.9, phase="rep", window=(0, 90), coverage=1.0)
    rows = assess("pull_up", ev, blocked="the pose estimate is not physically possible")
    assert rows and all(a.status == UNOBSERVABLE for a in rows)
    assert all("not physically possible" in a.reason for a in rows)
    # The compatibility path fires when unblocked, so the two must be told apart.
    assert any(f.id == "pull_up.body_swing" for f in classify_faults("pull_up", ev))


def test_assessment_row_is_the_client_contract():
    ev = Evidence("muscle_up")
    ev.add("top_elbow_deg", 120.0, phase="support", window=(58, 62), coverage=1.0)
    row = next(a for a in assess("muscle_up", ev)
               if a.rule.id == "muscle_up.incomplete_support_extension").as_dict("r2", 30)
    assert row["status"] == OBSERVED and row["phase"] == "support"
    assert row["scope"] == "phase" and row["intervalS"] == [1.93, 2.07]
    assert row["evidence"]["value"] == 120.0 and row["evidence"]["threshold"] == config.THRESHOLDS.straight_arm
    assert row["source"] == "geometry" and row["version"] == ASSESSMENT_VERSION
    assert row["name"] == "bent arms"


def test_fault_rows_carry_error_id_phase_and_interval():
    from barra.faults_taxonomy import classify_faults
    ev = Evidence("muscle_up")
    ev.add("top_elbow_deg", 120.0, phase="support", window=(58, 62), coverage=1.0)
    (f,) = [f for f in classify_faults("muscle_up", ev, fps=30) if f.name == "bent arms"]
    d = f.as_dict()
    assert d["errorId"] == "muscle_up.incomplete_support_extension"
    assert d["phase"] == "support" and d["intervalS"] == [1.93, 2.07]


def test_variant_rules_are_left_out_for_another_variant_and_flagged_when_unspecified():
    strict_only = [r for r in rules_for("pull_up") if r.variants == ("strict",)]
    assert strict_only, "the kip rule is the reason variants exist"
    ev = Evidence("pull_up")
    ev.add("swing", 0.9, phase="rep", window=(0, 90), coverage=1.0)
    # Declared kipping: the strict-only rule is not assessed at all - absent,
    # not "not observed", which would read as a pass.
    kipping = {a.rule.id for a in assess("pull_up", ev, "kipping")}
    strict = {a.rule.id for a in assess("pull_up", ev, "strict")}
    for r in strict_only:
        assert r.id not in kipping and r.id in strict
    # Unspecified: assessed, but the row says the verdict depends on a
    # standard nobody declared.
    rows = {a.rule.id: a.as_dict("r1", 30) for a in assess("pull_up", ev, VARIANT_UNSPECIFIED)}
    for r in strict_only:
        assert rows[r.id]["variantDependent"] is True
        assert rows[r.id]["status"] == OBSERVED


def test_unknown_variant_is_reported_not_applied():
    assert normalise_variant("pull_up", "strict") == {"name": "strict", "source": "declared"}
    assert normalise_variant("pull_up", "Kipping") == {"name": "kipping", "source": "declared"}
    out = normalise_variant("pull_up", "sticky")
    assert out["name"] == VARIANT_UNSPECIFIED and out["declared"] == "sticky"
    assert normalise_variant("squat", "strict")["name"] == VARIANT_UNSPECIFIED
    assert normalise_variant("pull_up", None) == {"name": VARIANT_UNSPECIFIED, "source": "none"}


def test_summary_counts_checked_clean_and_unobservable_separately():
    ev_fire = Evidence("pull_up")
    ev_fire.add("swing", 0.9, phase="rep", window=(0, 90), coverage=1.0)
    ev_clean = Evidence("pull_up")
    ev_clean.add("swing", 0.1, phase="rep", window=(0, 90), coverage=1.0)
    ev_blind = Evidence("pull_up")
    s = summarise([assess("pull_up", ev_fire), assess("pull_up", ev_clean),
                   assess("pull_up", ev_blind)])
    row = next(c for c in s["checks"] if c["errorId"] == "pull_up.body_swing")
    assert (row["observed"], row["notObserved"], row["unobservable"]) == (1, 1, 1)
    assert sum(row["reasons"].values()) == 1
    assert s["version"] == ASSESSMENT_VERSION
