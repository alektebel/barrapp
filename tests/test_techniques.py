"""The technique ledger: matching, mining, provenance, and the committed file."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scrape_techniques as st  # noqa: E402

from barra import techniques  # noqa: E402
from barra.skills import MEASURED, SKILLS  # noqa: E402


class TestMatching(unittest.TestCase):
    def test_names_land_on_the_right_skill(self):
        for name, sid in (
            ("Pullups", "pull_up"), ("Chin-Up", "chin_up"),
            ("Kipping Muscle Up", "kipping_muscle_up"), ("Muscle Up", "muscle_up"),
            ("Parallel Bar Dip", "dip"), ("Dips - Triceps Version", "dip"),
            ("Pushups", "push_up"), ("Push-Ups - Close Triceps Position", "diamond_push_up"),
            ("Bodyweight Squat", "squat"), ("Hanging Pike", "toes_to_bar"),
            ("Hanging Leg Raise", "leg_raise"), ("Handstand Push-Ups", "wall_hspu"),
            ("Front lever", "front_lever"), ("Natural Glute Ham Raise", "nordic_curl"),
        ):
            self.assertEqual(st.match_skill(name), sid, name)

    def test_longest_alias_wins(self):
        self.assertEqual(st.match_skill("tuck front lever"), "tuck_front_lever")
        self.assertEqual(st.match_skill("ring muscle up"), "ring_muscle_up")

    def test_equipment_is_not_a_bodyweight_skill(self):
        for name in ("Smith Machine Pistol Squat", "Kettlebell Pistol Squat",
                     "Barbell Squat", "Dip Machine", "Band Assisted Pull-Up",
                     "Weighted Pull-Up", "Leverage High Row"):
            self.assertIsNone(st.match_skill(name), name)

    def test_a_step_up_is_not_a_hanging_knee_raise(self):
        self.assertIsNone(st.match_skill("Step-up with Knee Raise"))

    def test_every_alias_points_at_a_real_skill(self):
        for sid in st.ALIASES:
            self.assertIn(sid, SKILLS, sid)
        for sid in st.WIKI_PAGES:
            self.assertIn(sid, SKILLS, sid)


class TestMining(unittest.TestCase):
    def test_cues_and_faults_are_read_by_sentence_shape(self):
        text = ("Grab the bar with an overhand grip. Keep your elbows close to "
                "your body throughout the movement. Avoid swinging your legs to "
                "gain momentum. Tip: squeeze the back at the top. This exercise "
                "works the lats.")
        cues, faults = st.mine(text)
        self.assertIn("Keep your elbows close to your body throughout the movement.", cues)
        self.assertIn("squeeze the back at the top.", cues)
        self.assertEqual(faults, ["Avoid swinging your legs to gain momentum."])
        self.assertNotIn("This exercise works the lats.", cues)

    def test_a_lead_in_does_not_hide_a_cue(self):
        cues, _ = st.mine("As you squat, keep your head and chest up and push your knees out.")
        self.assertEqual(len(cues), 1)

    def test_html_is_stripped(self):
        cues, _ = st.mine("<p>Keep the <b>core</b> braced throughout the hold.</p>")
        self.assertEqual(cues, ["Keep the core braced throughout the hold."])

    def test_duplicates_collapse(self):
        cues, _ = st.mine("Keep your chest up. Keep your chest up. keep your chest up.")
        self.assertEqual(len(cues), 1)


class TestParsers(unittest.TestCase):
    def test_free_exercise_db_record_keeps_its_provenance(self):
        recs = st.parse_free_exercise_db([{
            "id": "Pullups", "name": "Pullups", "equipment": "body only",
            "level": "beginner", "primaryMuscles": ["lats"], "secondaryMuscles": ["biceps"],
            "instructions": ["Grab the bar.", "Pull your torso up until the bar touches your chest."],
        }, {
            "id": "Barbell_Squat", "name": "Barbell Squat", "equipment": "barbell",
            "instructions": ["Nope."],
        }])
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["skill"], "pull_up")
        self.assertEqual(r["source"], "free_exercise_db")
        self.assertIn("Unlicense", r["license"])
        self.assertIn("yuhonas/free-exercise-db", r["url"])
        self.assertEqual(r["muscles"], ["lats", "biceps"])

    def test_wger_reads_translations_or_flat_names(self):
        page = {"results": [
            {"id": 1, "translations": [{"language": 2, "name": "Muscle up",
                                        "description": "<p>Pull to the bar. Keep the core tight.</p>"}],
             "equipment": [{"name": "Pull-up bar"}], "muscles": [{"name_en": "Lats"}],
             "license": {"short_name": "CC-BY-SA 4"}, "license_author": "someone"},
            {"id": 2, "name": "Front lever", "description": "Hold the body level.",
             "equipment": [], "muscles": []},
            {"id": 3, "name": "Barbell row", "description": "x", "equipment": [{"name": "Barbell"}]},
        ]}
        recs = st.parse_wger([page])
        self.assertEqual([r["skill"] for r in recs], ["muscle_up", "front_lever"])
        self.assertEqual(recs[0]["attribution"], "someone")
        self.assertIn("wger.de/en/exercise/1", recs[0]["url"])

    def test_wikipedia_extract_is_split_into_summary_and_steps(self):
        data = {"query": {"pages": {"1": {"title": "Muscle-up", "extract":
            "A muscle-up is a strength training exercise.\nKeep the bar close "
            "during the transition. Avoid kipping if training strictly."}}}}
        recs = st.parse_wikipedia("muscle_up", "Muscle-up", data)
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["summary"].startswith("A muscle-up"))
        self.assertIn("CC BY-SA", recs[0]["license"])
        self.assertTrue(recs[0]["url"].endswith("Muscle-up"))

    def test_missing_wikipedia_page_yields_nothing(self):
        self.assertEqual(st.parse_wikipedia("x", "X", {"query": {"pages": {"-1": {"missing": ""}}}}), [])

    def test_vtt_is_flattened_without_the_rolling_duplicates(self):
        vtt = ("WEBVTT\nKind: captions\n\n00:00:00.000 --> 00:00:02.000\nkeep your elbows in\n\n"
               "00:00:02.000 --> 00:00:04.000\nkeep your elbows in\nand don't swing\n")
        self.assertEqual(st.vtt_to_text(vtt), "keep your elbows in and don't swing")


class TestMerge(unittest.TestCase):
    def test_records_fold_into_one_entry_per_skill_with_every_source_listed(self):
        recs = [
            {"skill": "pull_up", "source": "a", "title": "A", "url": "u1", "license": "L",
             "attribution": "x", "summary": "", "instructions": ["Keep the chest up throughout the pull."],
             "muscles": ["lats"], "equipment": [], "level": "beginner"},
            {"skill": "pull_up", "source": "b", "title": "B", "url": "u2", "license": "L",
             "attribution": "y", "summary": "S", "instructions": ["Avoid swinging the legs for momentum."],
             "muscles": ["biceps"], "equipment": [], "level": ""},
        ]
        merged = st.merge(recs)
        e = merged["pull_up"]
        self.assertEqual(e["name"], "Pull-up")
        self.assertTrue(e["measurable"])
        self.assertEqual(e["cues"], ["Keep the chest up throughout the pull."])
        self.assertEqual(e["faults"], ["Avoid swinging the legs for momentum."])
        self.assertEqual(e["muscles"], ["lats", "biceps"])
        self.assertEqual([s["source"] for s in e["sources"]], ["a", "b"])
        self.assertEqual(e["summary"], "S")


class TestCommittedLedger(unittest.TestCase):
    """The file in the repo is what the app and the CLI read."""

    def setUp(self):
        self.path = ROOT / "data" / "techniques" / "techniques.json"
        self.assertTrue(self.path.exists(), "run scripts/scrape_techniques.py")
        self.doc = json.loads(self.path.read_text())

    def test_the_measured_skills_are_documented(self):
        """Five of the six. The hanging knee raise has no entry in
        free-exercise-db; it is the first thing the wger and Wikipedia sources
        add when they are reachable, and this test grows with the ledger."""
        for sid in MEASURED:
            if sid == "knee_raise":
                continue
            self.assertIn(sid, self.doc["skills"], sid)

    def test_every_entry_carries_a_licence_and_a_url(self):
        for sid, e in self.doc["skills"].items():
            self.assertTrue(e["sources"], sid)
            for s in e["sources"]:
                self.assertTrue(s["license"], f"{sid}: {s}")
                self.assertTrue(s["url"].startswith("http"), f"{sid}: {s}")

    def test_the_loader_reads_it(self):
        t = techniques.technique("pull_up")
        self.assertIsNotNone(t)
        self.assertTrue(t.cues)
        self.assertIn("free_exercise_db", t.attribution)
        self.assertEqual(techniques.cues("pull_up", 2), list(t.cues[:2]))
        self.assertIsNone(techniques.technique("no_such_skill"))

    def test_holds_reach_their_skill(self):
        # plank is in the ledger; the mapping goes through the skill graph
        self.assertEqual(techniques.for_hold("plank").id, "plank")
        self.assertIsNone(techniques.for_hold("handstand"),
                          "a handstand is deliberately not mapped to one graph entry")

    def test_the_card_says_it_is_quoted(self):
        text = techniques.render(techniques.technique("dip"))
        self.assertIn("Quoted, not measured", text)
        self.assertIn("Sources:", text)


if __name__ == "__main__":
    unittest.main()
