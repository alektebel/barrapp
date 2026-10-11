"""The skill graph the app ships (app/src/main/assets/skills.json) - UX-PLAN B1.

The graph lives in barra/skills.py; the phone reads a JSON export of it. The
committed JSON must equal a fresh export, so a skill added on the server side
and not exported fails here, not on a phone that silently shows an old graph.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import export_skills  # noqa: E402
from barra import skills as S  # noqa: E402
from barra.i18n import english_words  # noqa: E402
from barra.skills_es import FAMILY_ES, NAME_ES, UNTRANSLATED  # noqa: E402

ASSET = ROOT / "app" / "src" / "main" / "assets" / "skills.json"


class Spanish(unittest.TestCase):
    def test_every_skill_and_family_has_a_spanish_name(self):
        self.assertEqual(sorted(set(S.SKILLS) - set(NAME_ES)), [])
        self.assertEqual(sorted(set(NAME_ES) - set(S.SKILLS)), [])
        self.assertEqual(sorted({s.family for s in S.SKILLS.values()} - set(FAMILY_ES)), [])

    def test_names_read_as_spanish(self):
        for sid, name in NAME_ES.items():
            if sid not in UNTRANSLATED:
                self.assertEqual(english_words(name), [], sid)


class Export(unittest.TestCase):
    def setUp(self):
        self.data = export_skills.export()

    def test_the_graph_is_valid(self):
        self.assertEqual(S.validate(), [])

    def test_every_skill_with_its_edges_tier_and_standard(self):
        by_id = {s["id"]: s for s in self.data["skills"]}
        self.assertEqual(len(by_id), len(S.SKILLS))
        mu = by_id["muscle_up"]
        self.assertEqual(mu["name"], "Muscle-up")
        self.assertTrue(mu["measurable"])
        self.assertEqual(mu["requires"], ["kipping_muscle_up"])
        self.assertEqual(mu["tier"], S.tiers()["muscle_up"])
        self.assertIn("reps", mu["standard"])
        self.assertIsNone(by_id["front_lever"]["standard"])

    def test_prerequisites_point_at_real_skills(self):
        ids = {s["id"] for s in self.data["skills"]}
        for s in self.data["skills"]:
            self.assertTrue(set(s["requires"]) <= ids, s["id"])

    def test_the_committed_asset_is_a_fresh_export(self):
        self.assertTrue(ASSET.exists(), "run: python scripts/export_skills.py")
        self.assertEqual(json.loads(ASSET.read_text()), self.data,
                         "skills.json is stale: run python scripts/export_skills.py")


if __name__ == "__main__":
    unittest.main()
