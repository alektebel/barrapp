"""The three things to improve (barra/fault_select.top_fixes) - docs/UX-PLAN.md A1.

Ranked by three keys, in order: importance (the coaching order per movement,
recommend.PRIORITY), prevalence (share of judged reps that showed it), then
exceedance (how far past the threshold the worst rep went), with recurrence as
a key between prevalence and exceedance: a fault seen on at least the gate's
share of reps goes before a one-off. One-rep faults are candidates only when
their worst rep sat more than THRESHOLDS.fault_single_rep_exceedance past the
threshold (audit 16-10-2026, finding 6: recurrence orders, it does not filter).
Fewer than three is an answer, never padded.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from barra import fault_select  # noqa: E402
from barra.recommend import PRIORITY  # noqa: E402
from barra.rules import RULES  # noqa: E402


def row(eid, status="observed", value=0.5, threshold=1.0, comparison="<", name=None):
    return {"errorId": eid, "name": name or eid.split(".", 1)[1], "status": status,
            "evidence": {"value": value, "threshold": threshold, "comparison": comparison}}


def reps(*per_rep):
    return [list(r) for r in per_rep]


PU = "pull_up"


class Ranking(unittest.TestCase):
    def test_importance_comes_first(self):
        # momentum leads the pull-up order; lockout comes after it
        r = reps(*[[row("pull_up.incomplete_lockout", value=0.1, name="lockout"),
                    row("pull_up.body_swing", value=0.9, threshold=1.0, comparison="<", name="momentum")]] * 4)
        top = fault_select.top_fixes(r, PU)
        self.assertEqual([t["name"] for t in top], ["momentum", "lockout"])

    def test_then_prevalence(self):
        # same importance tier is impossible within one track, so use names absent
        # from PRIORITY: they rank after the listed ones, by prevalence then exceedance
        a = row("pull_up.x_a", name="a"); b = row("pull_up.x_b", name="b")
        r = reps([a, b], [a, b], [a, b], [a, row("pull_up.x_b", status="not_observed", name="b")])
        top = fault_select.top_fixes(r, PU)
        self.assertEqual([t["name"] for t in top], ["a", "b"])
        self.assertEqual((top[0]["observedReps"], top[0]["judgedReps"]), (4, 4))
        self.assertEqual((top[1]["observedReps"], top[1]["judgedReps"]), (3, 4))

    def test_then_exceedance(self):
        a = row("pull_up.x_a", value=0.9, name="a")   # 10% past
        b = row("pull_up.x_b", value=0.2, name="b")   # 80% past
        top = fault_select.top_fixes(reps(*[[a, b]] * 3), PU)
        self.assertEqual([t["name"] for t in top], ["b", "a"])

    def test_at_most_three_with_ranks(self):
        names = ["momentum", "lockout", "dead hang", "control"]
        ids = ["body_swing", "incomplete_lockout", "incomplete_hang", "dropped_descent"]
        rowset = [row(f"pull_up.{i}", name=n) for i, n in zip(ids, names)]
        top = fault_select.top_fixes(reps(*[rowset] * 4), PU)
        self.assertEqual([t["rank"] for t in top], [1, 2, 3])
        self.assertEqual([t["name"] for t in top], names[:3])


class Gate(unittest.TestCase):
    def test_weak_one_rep_jitter_is_not_a_fix(self):
        # Barely past the threshold on one rep: the pose jitter the consensus
        # gate was built for. (This test encoded the old absolute rule that a
        # one-rep fault is never a fix; since the audit, a STRONG one-off is
        # kept - test_strong_one_rep_fix_is_kept - so the fixture here is a
        # clearly weak row, 0.1 past, which stays dropped either way.)
        r = reps([row("pull_up.body_swing", value=0.9, name="momentum")], [], [], [])
        self.assertEqual(fault_select.top_fixes(r, PU), [])

    def test_strong_one_rep_fix_is_kept(self):
        # Audit finding 6: a one-off that sat far past the threshold (0.9
        # here, over the 0.5 bar) used to vanish from the summary. Now it is
        # kept, honestly labelled as a single rep.
        r = reps([], [], [row("pull_up.incomplete_lockout", value=0.1, name="lockout")])
        top = fault_select.top_fixes(r, PU)
        self.assertEqual([t["name"] for t in top], ["lockout"])
        self.assertEqual(top[0]["observedReps"], 1)

    def test_recurrent_ranks_before_isolated(self):
        # Same importance tier (names absent from PRIORITY), same prevalence
        # (both fired on every rep they were judged on): the fault seen twice
        # goes before the stronger one-off - exceedance no longer jumps the
        # queue - but the one-off stays in the list.
        a = row("pull_up.x_a", value=0.8, name="a")   # 0.2 past, twice
        b = row("pull_up.x_b", value=0.1, name="b")   # 0.9 past, once
        top = fault_select.top_fixes(reps([a, b], [a], []), PU)
        self.assertEqual([t["name"] for t in top], ["a", "b"])
        self.assertEqual((top[0]["observedReps"], top[1]["observedReps"]), (2, 1))

    def test_prevalence_still_leads_a_rare_fault(self):
        # Recurrence breaks ties only where the existing keys are silent:
        # prevalence, part of the existing ranking, still puts a fault seen
        # on every judged rep ahead of a recurrent one missed on a third.
        a = row("pull_up.x_a", value=0.8, name="a")   # 2 of 3 judged
        b = row("pull_up.x_b", value=0.1, name="b")   # 1 of 1, strong
        clean = row("pull_up.x_a", status="not_observed", name="a")
        top = fault_select.top_fixes(reps([a, b], [a], [clean]), PU)
        self.assertEqual([t["name"] for t in top], ["b", "a"])

    def test_unobservable_reps_are_not_judged(self):
        a = row("pull_up.body_swing", name="momentum")
        u = row("pull_up.body_swing", status="unobservable", name="momentum")
        top = fault_select.top_fixes(reps([a], [a], [u], [u]), PU, min_count=2)
        self.assertEqual((top[0]["observedReps"], top[0]["judgedReps"]), (2, 2))

    def test_nothing_to_fix_is_an_empty_list(self):
        self.assertEqual(fault_select.top_fixes([], PU), [])
        clean = reps(*[[row("pull_up.body_swing", status="not_observed")]] * 4)
        self.assertEqual(fault_select.top_fixes(clean, PU), [])


class Priority(unittest.TestCase):
    def test_every_movement_with_rules_has_a_coaching_order(self):
        for movement, rules in RULES.items():
            self.assertIn(movement, PRIORITY, movement)
            self.assertEqual(sorted(PRIORITY[movement]), sorted({r.name for r in rules}), movement)


class Payload(unittest.TestCase):
    def test_top_fixes_reaches_the_phone_and_agrees_with_the_primary(self):
        src = (ROOT / "server" / "process.py").read_text()
        self.assertIn('"topFixes"', src)
        a = row("pull_up.body_swing", name="momentum", value=0.2)
        b = row("pull_up.incomplete_lockout", name="lockout", value=0.9)
        r = reps(*[[a, b]] * 4)
        top = fault_select.top_fixes(r, PU)
        primary = fault_select.primary_from_assessments(r, movement=PU)
        self.assertEqual(primary["errorId"], top[0]["errorId"])


if __name__ == "__main__":
    unittest.main()
