"""A check measured in torso units cannot be called clean when the torso ruler
itself was declared unusable on the clip."""
from barra.evidence import RULER_UNUSABLE, Evidence
from barra.i18n import translate
from barra.rules import NOT_OBSERVED, UNOBSERVABLE, assess, rules_for, summarise
from barra.rules import _needs_ruler


def _ev():
    ev = Evidence(track="push_up")
    # A deep, clean push-up: travel well past every threshold, angles fine.
    for r in rules_for("push_up"):
        ev.add(r.primitive, 2.24 if r.primitive == "travel" else 0.0,
               phase="rep", window=(0, 30))
    return ev


def _by_id(assessments):
    return {a.rule.id: a for a in assessments}


def test_scaled_torso_checks_abstain_when_ruler_unusable():
    out = _by_id(assess("push_up", _ev(), ruler_usable=False))
    a = out["push_up.short_travel"]
    assert a.status == UNOBSERVABLE and a.value is None
    d = a.as_dict("r1")
    assert d["availability"]["reason"] == RULER_UNUSABLE
    assert d["evidence"]["class"] == "SCALED" and d["evidence"]["unit"] == "torso"
    for rule in rules_for("push_up"):
        if _needs_ruler(rule):
            assert out[rule.id].status == UNOBSERVABLE


def test_ruler_independent_checks_unchanged():
    ev = _ev()
    off = _by_id(assess("push_up", ev, ruler_usable=False))
    on = _by_id(assess("push_up", ev))
    for rule in rules_for("push_up"):
        if not _needs_ruler(rule):
            assert off[rule.id].status == on[rule.id].status
            assert off[rule.id].value == on[rule.id].value


def test_usable_ruler_is_the_default_and_changes_nothing():
    ev = _ev()
    assert ([a.as_dict("r") for a in assess("push_up", ev)]
            == [a.as_dict("r") for a in assess("push_up", ev, ruler_usable=True)])
    assert _by_id(assess("push_up", ev))["push_up.short_travel"].status == NOT_OBSERVED


def test_summary_counts_the_ruler_reason():
    row = next(c for c in summarise([assess("push_up", _ev(), ruler_usable=False)])["checks"]
               if c["errorId"] == "push_up.short_travel")
    assert row["unobservable"] == 1 and row["reasons"] == {RULER_UNUSABLE: 1}


def test_reason_detail_has_spanish():
    detail = next(a.reason for a in assess("push_up", _ev(), ruler_usable=False)
                  if a.rule.id == "push_up.short_travel")
    missing: list = []
    es = translate(detail.split(": ", 1)[1], missing)
    assert es and not missing
