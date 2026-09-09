"""The exercise catalogue, and the discipline that keeps it honest.

barra/movements.py names what barra can MEASURE. This module names what the app
SHOWS - the exercises a gym routine is made of - and for each one the 5 mistakes
a coach corrects most. The two are deliberately different sets:

    measurable=True   barra measures the fault, against a ruleId in
                      barra/rules.py, and reports it from footage.
    measurable=False  the faults are authored coaching knowledge (ruleId
                      null). Shown for teaching; never reported as a
                      measurement. This is the same "never promise a verdict
                      the pipeline cannot give" rule the onboarding uses.

`validate()` is the enforcement point and the thing the test suite calls: a row
that claims measurable must name a real movement with a real ruleId that
belongs to it, and a weighted variant must name a real base movement. Anything
else is an error, not a silent downgrade to 'catalog only' - the catalogue must
say honestly what barra measured and what it did not.
"""
from __future__ import annotations

import json
from pathlib import Path

from .movements import MOVEMENTS
from .rules import RULES

CATALOG = Path(__file__).resolve().parents[1] / "data" / "exercises" / "catalog.json"


class Exercise:
    def __init__(self, data: dict):
        self.id = data["id"]
        self.name_es = data.get("nameEs", self.id)
        self.name_en = data.get("nameEn", self.id)
        self.family = data.get("family", "")
        self.equipment = data.get("equipment", "")
        self.measurable = bool(data.get("measurable"))
        self.weight_supported = bool(data.get("weightSupported"))
        self.weighted = bool(data.get("weighted"))
        self.base_of = data.get("baseOf")
        self.errors = [Error(e) for e in data.get("errors", [])]

    def as_dict(self) -> dict:
        return {
            "id": self.id, "nameEs": self.name_es, "nameEn": self.name_en,
            "family": self.family, "equipment": self.equipment,
            "measurable": self.measurable,
            "weightSupported": self.weight_supported,
            "weighted": self.weighted, "baseOf": self.base_of,
            "errors": [e.as_dict() for e in self.errors],
        }

    def rule_ids(self) -> list[str]:
        return [e.rule_id for e in self.errors if e.rule_id]


class Error:
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.name_es = data.get("nameEs", self.name)
        self.rule_id = data.get("ruleId")
        self.why = data.get("why", "")
        self.fix = data.get("fix", "")

    def as_dict(self) -> dict:
        return {"name": self.name, "nameEs": self.name_es,
                "ruleId": self.rule_id, "why": self.why, "fix": self.fix}


_cache: list[Exercise] | None = None


def load(path: Path = CATALOG) -> list[Exercise]:
    global _cache
    if _cache is not None and path == CATALOG:
        return _cache
    raw = json.loads(Path(path).read_text())
    rows = list(raw.get("exercises", [])) + list(raw.get("weightedCalisthenics", []))
    _cache = [Exercise(r) for r in rows] if path == CATALOG else [
        Exercise(r) for r in rows]
    return _cache


def all_exercises() -> list[Exercise]:
    return list(load())


_DIACRITICS = {c: plain for c, plain in
               [("\u00e1", "a"), ("\u00e9", "e"), ("\u00ed", "i"),
                ("\u00f3", "o"), ("\u00fa", "u"), ("\u00fc", "u"),
                ("\u00f1", "n")]}


def _key(s: str) -> str:
    for acc, plain in _DIACRITICS.items():
        s = s.replace(acc, plain)
    return s.strip().lower().replace(" ", "_")


def get(exercise_id: str) -> Exercise | None:
    key = _key(exercise_id)
    for e in all_exercises():
        if (e.id == key
                or _key(e.name_en) == key
                or _key(e.name_es) == key):
            return e
    return None


def weighted_variants() -> list[Exercise]:
    return [e for e in all_exercises() if e.weighted]


def measurable() -> list[Exercise]:
    return [e for e in all_exercises() if e.measurable]


def group_by_family() -> dict[str, list[Exercise]]:
    out: dict[str, list[Exercise]] = {}
    for e in all_exercises():
        out.setdefault(e.family, []).append(e)
    return out


def all_error_names() -> list[str]:
    seen: list[str] = []
    for e in all_exercises():
        for err in e.errors:
            if err.name and err.name not in seen:
                seen.append(err.name)
    return seen


def validate() -> list[str]:
    """Structural problems with the catalogue. Empty when it is sound.

    The three rules a catalogue row cannot break without lying:

    * a `measurable` row must name a real movement in barra.movements (so the
      pipeline has geometry for it);
    * every ruleId on it must exist in barra.rules AND belong to that movement
      (a rule borrowed from another movement is not a measurement of this one);
    * a weighted variant must name a real base movement.
    """
    problems: list[str] = []

    def _rule_ids(owner: str) -> set[str]:
        return {r.id for r in RULES.get(owner, ())}

    for e in all_exercises():
        if e.measurable:
            if e.id not in MOVEMENTS:
                problems.append(f"{e.id} is measurable but not a known movement")
            for rid in e.rule_ids():
                parts = rid.split(".")
                rule_owner = parts[0] if len(parts) > 1 else ""
                if rule_owner not in RULES:
                    problems.append(f"{e.id} ruleId {rid!r} names an unknown rule owner")
                elif rule_owner != e.id:
                    problems.append(
                        f"{e.id} ruleId {rid!r} belongs to {rule_owner}, not {e.id}")
                elif rid not in _rule_ids(rule_owner):
                    problems.append(f"{e.id} ruleId {rid!r} is not a registered rule")
        else:
            for rid in e.rule_ids():
                problems.append(f"{e.id} is not measurable but carries ruleId {rid!r}")
        if e.weighted and not e.base_of:
            problems.append(f"{e.id} is weighted but has no base movement")
        if e.weighted and e.base_of and e.base_of not in MOVEMENTS:
            problems.append(f"{e.id} base movement {e.base_of!r} is not a known movement")
        if len(e.errors) != 5:
            problems.append(f"{e.id} lists {len(e.errors)} errors, expected 5")
    return sorted(set(problems))
