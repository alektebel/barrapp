"""The decision tree must keep naming exactly the graph it claims to name.

The failure this guards against is silent. A skill added to `barra.skills`
without a branch here is simply never classifiable, and nothing complains: the
classifier keeps returning plausible answers from the branches that do exist,
and the new skill is quietly unreachable forever. So the binding between the
two is asserted rather than trusted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.movement_tree import (  # noqa: E402
    NODES, ROOT as TREE_ROOT, UNCLEAR, Option, leaves, prompt_for, validate, walk,
)
from barra.skills import SKILLS  # noqa: E402


class TestTreeIsSound(unittest.TestCase):
    def test_the_tree_agrees_with_the_skill_graph(self):
        problems = validate()
        self.assertEqual(problems, [], "\n".join(problems))

    def test_every_skill_is_reachable(self):
        missing = sorted(set(SKILLS) - set(leaves()))
        self.assertEqual(missing, [], f"unreachable skills: {missing}")

    def test_no_skill_is_named_by_two_different_branches(self):
        """Two paths to one skill means the tree has an ambiguous question, and
        a classifier that can arrive by either has learned nothing from the
        difference."""
        seen = {}
        for node in NODES.values():
            for opt in node.options:
                if not opt.skill:
                    continue
                if opt.skill in seen:
                    self.fail(f"{opt.skill!r} is named by both {seen[opt.skill]!r} "
                              f"and {node.id!r}")
                seen[opt.skill] = node.id


class TestWalking(unittest.TestCase):
    def _answers(self, mapping):
        return lambda node: mapping.get(node.id, UNCLEAR)

    def test_a_full_walk_names_a_skill(self):
        got = walk(self._answers({
            "support": "hanging",
            "hang_what": "arms_pull",
            "pull_how": "palms_away",
        }))
        self.assertEqual(got.skill, "pull_up")
        self.assertTrue(got.ok)
        self.assertEqual([n for n, _ in got.path],
                         ["support", "hang_what", "pull_how"])

    def test_the_path_is_kept_so_a_wrong_answer_can_be_attributed(self):
        got = walk(self._answers({
            "support": "hanging",
            "hang_what": "over_the_bar",
            "muscle_up_how": "no_kick",
        }))
        self.assertEqual(got.skill, "strict_muscle_up")
        self.assertEqual(got.as_trace()["path"][1],
                         {"node": "hang_what", "answer": "over_the_bar"})

    def test_unclear_stops_the_walk_without_inventing_a_skill(self):
        got = walk(self._answers({"support": "hanging", "hang_what": UNCLEAR}))
        self.assertEqual(got.skill, "")
        self.assertFalse(got.ok)
        self.assertEqual(got.stopped_at, "hang_what")
        # The partial path still says what WAS established.
        self.assertEqual(got.path[0], ("support", "hanging"))

    def test_an_answer_that_is_not_an_option_is_refused_not_guessed(self):
        """A model that replies with a skill name instead of an option key must
        not be silently resolved to something nearby."""
        got = walk(self._answers({"support": "muscle_up"}))
        self.assertEqual(got.skill, "")
        self.assertIn("not an option", got.reason)

    def test_no_answer_at_all_is_unclear_rather_than_a_crash(self):
        got = walk(lambda node: None)
        self.assertEqual(got.skill, "")
        self.assertEqual(got.stopped_at, TREE_ROOT)

    def test_every_skill_can_actually_be_walked_to(self):
        """Reachability in `validate` is structural. This walks each branch for
        real, which also proves no path exceeds the depth limit."""
        by_skill = {}
        def collect(node_id, answers, seen):
            if node_id in seen:
                return
            for opt in NODES[node_id].options:
                if opt.skill:
                    by_skill[opt.skill] = {**answers, node_id: opt.key}
                elif opt.then:
                    collect(opt.then, {**answers, node_id: opt.key}, seen | {node_id})
        collect(TREE_ROOT, {}, set())

        self.assertEqual(len(by_skill), len(SKILLS))
        for skill, answers in by_skill.items():
            got = walk(self._answers(answers))
            self.assertEqual(got.skill, skill,
                             f"walking to {skill} landed on {got.skill!r}")


class TestPrompts(unittest.TestCase):
    def test_every_prompt_stays_small(self):
        """The entire argument for a tree is that each question is smaller than
        one 88-way question. If a node grows past that, the tree has stopped
        paying for itself and wants splitting."""
        flat = sum(len(f'- "{k}": {s.name}\n') for k, s in SKILLS.items())
        for node in NODES.values():
            size = len(prompt_for(node))
            self.assertLess(size, flat,
                            f"node {node.id!r} prompt ({size}) is no smaller "
                            f"than naming all {len(SKILLS)} skills ({flat})")

    def test_a_prompt_offers_every_key_and_asks_for_json(self):
        text = prompt_for(NODES["support"])
        for opt in NODES["support"].options:
            self.assertIn(f'"{opt.key}"', text)
        self.assertIn('"choice"', text)

    def test_descriptions_say_what_is_seen_not_what_it_is_called(self):
        """An option whose description is just the skill's name teaches the
        model nothing it did not already have from the key."""
        for node in NODES.values():
            for opt in node.options:
                if opt.key == UNCLEAR:
                    continue
                self.assertGreater(
                    len(opt.seen), 25,
                    f"{node.id}/{opt.key} has no real description")
                if opt.skill:
                    name = SKILLS[opt.skill].name.lower()
                    self.assertNotEqual(opt.seen.lower().rstrip("."), name,
                                        f"{node.id}/{opt.key} just restates the name")


class TestOptionInvariants(unittest.TestCase):
    def test_an_option_cannot_both_continue_and_conclude(self):
        with self.assertRaises(ValueError):
            Option("x", "a description long enough to pass", then="a", skill="b")

    def test_an_option_must_go_somewhere(self):
        with self.assertRaises(ValueError):
            Option("x", "a description long enough to pass")

    def test_unclear_must_not_lead_anywhere(self):
        with self.assertRaises(ValueError):
            Option(UNCLEAR, "a description", skill="pull_up")


if __name__ == "__main__":
    unittest.main()
