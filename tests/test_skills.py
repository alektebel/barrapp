"""The calisthenics skill graph.

Most of these test the graph's honesty rather than its content: that a
self-report can never become evidence, that the measured core stays small and
explicit, and that the graph and the progression card cannot disagree about the
same athlete.
"""
import unittest

from barra.skills import (AVAILABLE, CLAIMED, LOCKED, MEASURED, SKILLS,
                          VERIFIED, ancestors, families, next_up, state, tiers,
                          unlocks, validate)


class TestTheGraphIsSound(unittest.TestCase):
    def test_it_validates(self):
        self.assertEqual(validate(), [])

    def test_every_prerequisite_exists(self):
        for skill in SKILLS.values():
            for req in skill.requires:
                self.assertIn(req, SKILLS, f"{skill.id} -> {req}")

    def test_no_skill_precedes_its_own_prerequisite(self):
        t = tiers()
        for skill in SKILLS.values():
            for req in skill.requires:
                self.assertGreater(t[skill.id], t[req],
                                   f"{skill.id} is not deeper than {req}")

    def test_it_is_a_graph_not_a_tree(self):
        """A muscle-up is a pull-up and a dip joined by a transition. Forcing a
        single parent would mean choosing which prerequisite to pretend away."""
        multi = [s.id for s in SKILLS.values() if len(s.requires) > 1]
        self.assertGreater(len(multi), 5, multi)

    def test_the_families_are_all_populated(self):
        for family, ids in families().items():
            self.assertGreater(len(ids), 3, family)

    def test_unlocks_is_the_reverse_of_requires(self):
        rev = unlocks()
        for skill in SKILLS.values():
            for req in skill.requires:
                self.assertIn(skill.id, rev[req])


class TestMeasuredStaysSmallAndExplicit(unittest.TestCase):
    def test_only_the_six_barra_can_verify_are_marked_measurable(self):
        """If this ever grows silently, the graph has started claiming the app
        can see things it cannot."""
        self.assertEqual(set(MEASURED),
                         {"push_up", "dip", "pull_up", "muscle_up",
                          "knee_raise", "squat"})

    def test_most_of_the_graph_is_not_measurable(self):
        self.assertLess(len(MEASURED) / len(SKILLS), 0.15)

    def test_a_standard_exists_exactly_where_it_can_be_judged(self):
        for skill in SKILLS.values():
            self.assertEqual(skill.measurable, skill.standard is not None,
                             skill.id)


class TestStates(unittest.TestCase):
    def test_nothing_done_leaves_only_the_roots_available(self):
        st = state(set(), set())
        for sid, v in st.items():
            expected = AVAILABLE if not SKILLS[sid].requires else LOCKED
            self.assertEqual(v, expected, sid)

    def test_verified_beats_claimed(self):
        st = state({"pull_up"}, {"pull_up"})
        self.assertEqual(st["pull_up"], VERIFIED)

    def test_a_claim_never_becomes_verification(self):
        """The one rule the whole app rests on. A self-report unlocks what
        comes next and is never itself evidence."""
        st = state(set(), {"muscle_up", "front_lever", "human_flag"})
        for sid in ("muscle_up", "front_lever", "human_flag"):
            self.assertEqual(st[sid], CLAIMED)
        self.assertNotIn(VERIFIED, st.values())

    def test_doing_a_skill_implies_its_prerequisites(self):
        """Without this the graph tells a verified pull-up owner to go and work
        on a dead hang."""
        st = state({"pull_up"}, set())
        self.assertEqual(st["dead_hang"], CLAIMED)
        self.assertEqual(st["scapular_pull"], CLAIMED)

    def test_an_implied_prerequisite_is_claimed_not_verified(self):
        """It was inferred, not measured, and the two words mean different
        things everywhere else in this project."""
        st = state({"muscle_up"}, set())
        self.assertEqual(st["muscle_up"], VERIFIED)
        self.assertEqual(st["pull_up"], CLAIMED)
        self.assertEqual(st["dip"], CLAIMED)

    def test_a_claim_unlocks_what_it_should(self):
        locked = state(set(), set())
        self.assertEqual(locked["tuck_planche"], LOCKED)
        opened = state(set(), {"frog_stand"})
        self.assertEqual(opened["tuck_planche"], AVAILABLE)

    def test_ancestors_are_transitive(self):
        anc = ancestors("muscle_up")
        self.assertIn("pull_up", anc)
        self.assertIn("dead_hang", anc)      # two levels further up
        self.assertNotIn("muscle_up", anc)


class TestWhatToWorkOn(unittest.TestCase):
    def test_measurable_skills_lead(self):
        """They are the ones where the app can tell you something you did not
        already know."""
        first = next_up(set(), set())[0]
        self.assertTrue(first.measurable, first.id)

    def test_it_never_suggests_something_already_done(self):
        done = {"push_up", "pull_up", "dip"}
        suggested = {s.id for s in next_up(done, set())}
        self.assertFalse(suggested & done, suggested & done)

    def test_it_never_suggests_something_locked(self):
        st = state(set(), set())
        for s in next_up(set(), set()):
            self.assertEqual(st[s.id], AVAILABLE, s.id)


class TestTheGraphAndTheLadderAgree(unittest.TestCase):
    """Two structures describing one athlete. If they disagree, the skill tree
    and the progression card give different answers about the same person."""

    def test_the_ladder_covers_exactly_the_measured_skills(self):
        from barra.progression import LADDER
        self.assertEqual(set(LADDER), set(MEASURED))

    def test_every_ladder_target_is_a_real_skill(self):
        from barra.progression import LADDER
        for movement, step in LADDER.items():
            self.assertIn(step.towards, SKILLS, movement)

    def test_the_standards_come_from_the_graph(self):
        from barra.progression import LADDER
        for movement, step in LADDER.items():
            std = SKILLS[movement].standard
            self.assertEqual((step.reps, step.quality, step.days),
                             (std.reps, std.quality, std.days), movement)

    def test_a_ladder_target_is_reachable_from_its_movement(self):
        """Pointing someone at a milestone that is not downstream of what they
        are doing would be a map that does not join up."""
        from barra.progression import LADDER
        for movement, step in LADDER.items():
            self.assertIn(movement, ancestors(step.towards) | {movement},
                          f"{step.towards} is not downstream of {movement}")

    def test_an_unmeasurable_target_is_marked_as_such_on_both_sides(self):
        from barra.progression import LADDER
        for movement, step in LADDER.items():
            self.assertEqual(step.target_measurable,
                             SKILLS[step.towards].measurable, movement)


if __name__ == "__main__":
    unittest.main()
