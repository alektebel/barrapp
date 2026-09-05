"""What a movement is for: cues, faults and sources, read from the ledger that
scripts/scrape_techniques.py builds.

This module never writes a sentence of its own. Everything it returns was
published under a licence that allows reuse and carries the record it came
from, so the app can say "keep the elbows close - free-exercise-db" rather
than presenting a coaching opinion as though barra had measured it. The
distinction is the same one the rest of the project lives by: measured, or
quoted with a source. Never invented.

    from barra.techniques import technique, cues, for_hold
    technique("muscle_up")          # the whole record, or None
    cues("pull_up", limit=3)        # the first three mined cues
    for_hold("inverted_hang")       # the skill-graph entry a hold maps to
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .holds import SKILL as HOLD_SKILL

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "techniques" / "techniques.json"


@dataclass(frozen=True)
class Source:
    source: str
    title: str
    url: str
    license: str
    attribution: str


@dataclass(frozen=True)
class Technique:
    id: str
    name: str
    family: str
    measurable: bool
    summary: str
    instructions: tuple[str, ...]
    cues: tuple[str, ...]
    faults: tuple[str, ...]
    muscles: tuple[str, ...]
    equipment: tuple[str, ...]
    level: str
    sources: tuple[Source, ...] = field(default_factory=tuple)

    @property
    def attribution(self) -> str:
        """One line naming where the words came from."""
        seen: list[str] = []
        for s in self.sources:
            tag = f"{s.source} ({s.license})"
            if tag not in seen:
                seen.append(tag)
        return "; ".join(seen)


def _path() -> Path:
    return Path(os.environ.get("BARRA_TECHNIQUES", str(DEFAULT_PATH)))


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"skills": {}, "sources": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def reload() -> None:
    _load.cache_clear()


def all_techniques() -> dict[str, Technique]:
    doc = _load(str(_path()))
    out: dict[str, Technique] = {}
    for sid, e in (doc.get("skills") or {}).items():
        out[sid] = Technique(
            id=sid, name=e.get("name") or sid, family=e.get("family") or "",
            measurable=bool(e.get("measurable")), summary=e.get("summary") or "",
            instructions=tuple(e.get("instructions") or ()),
            cues=tuple(e.get("cues") or ()), faults=tuple(e.get("faults") or ()),
            muscles=tuple(e.get("muscles") or ()), equipment=tuple(e.get("equipment") or ()),
            level=e.get("level") or "",
            sources=tuple(Source(s.get("source", ""), s.get("title", ""), s.get("url", ""),
                                 s.get("license", ""), s.get("attribution", ""))
                          for s in (e.get("sources") or ())),
        )
    return out


def technique(skill_id: str) -> Technique | None:
    return all_techniques().get(skill_id)


def cues(skill_id: str, limit: int = 3) -> list[str]:
    t = technique(skill_id)
    return list(t.cues[:limit]) if t else []


def faults(skill_id: str, limit: int = 3) -> list[str]:
    t = technique(skill_id)
    return list(t.faults[:limit]) if t else []


def for_hold(hold_id: str) -> Technique | None:
    """The technique record for a held position, via the skill graph."""
    sid = HOLD_SKILL.get(hold_id)
    return technique(sid) if sid else None


def render(t: Technique, width: int = 88) -> str:
    """A plain-text card, for the CLI."""
    import textwrap

    lines = [t.name.upper(), ""]
    if t.summary:
        lines += textwrap.wrap(t.summary, width) + [""]
    if t.instructions:
        lines.append("How it is done")
        for i, step in enumerate(t.instructions, 1):
            lines += textwrap.wrap(f"{i}. {step}", width, subsequent_indent="   ")
        lines.append("")
    if t.cues:
        lines.append("Cues (mined from the source text)")
        for c in t.cues:
            lines += textwrap.wrap(f"- {c}", width, subsequent_indent="  ")
        lines.append("")
    if t.faults:
        lines.append("Faults to avoid (mined)")
        for c in t.faults:
            lines += textwrap.wrap(f"- {c}", width, subsequent_indent="  ")
        lines.append("")
    if t.muscles:
        lines.append("Muscles: " + ", ".join(t.muscles))
    lines.append("Sources: " + t.attribution)
    for s in t.sources:
        lines.append(f"  {s.title} - {s.url}")
    lines.append("")
    lines.append("Quoted, not measured. Barra measures reps and holds; it does not "
                 "hold opinions about technique.")
    return "\n".join(lines)
