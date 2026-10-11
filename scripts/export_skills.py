"""Export the skill graph for the app.

    python scripts/export_skills.py      # writes app/src/main/assets/skills.json

The graph is defined once, in barra/skills.py (with Spanish names in
barra/skills_es.py). tests/test_skills_export.py fails when the committed JSON
is not a fresh export, so the phone never shows a stale graph.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra import skills as S  # noqa: E402
from barra.skills_es import FAMILY_ES, NAME_ES  # noqa: E402

ASSET = ROOT / "app" / "src" / "main" / "assets" / "skills.json"


def export() -> dict:
    tiers = S.tiers()
    skills = []
    for s in S.SKILLS.values():
        skills.append({
            "id": s.id,
            "name": NAME_ES[s.id],
            "family": s.family,
            "requires": list(s.requires),
            "tier": tiers[s.id],
            "measurable": bool(s.measurable),
            "standard": ({"reps": s.standard.reps, "quality": s.standard.quality,
                          "days": s.standard.days} if s.standard else None),
        })
    return {"version": 1, "families": FAMILY_ES, "skills": skills}


def main() -> None:
    ASSET.parent.mkdir(parents=True, exist_ok=True)
    ASSET.write_text(json.dumps(export(), ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {ASSET} ({len(S.SKILLS)} skills)")


if __name__ == "__main__":
    main()
