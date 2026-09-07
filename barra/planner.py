"""Turn the skill graph into a week-by-week plan.

`skills.py` answers "what can I work on next?" and "am I ready?". This module
answers the question that follows: "if I am working towards X, what do I do
this week, and the week after?".

Two tracks, deliberately different in shape:

  * **skill** — a technique (front lever, planche, muscle-up, one-arm pull-up).
    The path is the chain of prerequisite positions the graph already encodes,
    and the plan walks it one rung at a time. A skill is not earned by volume;
    it is earned by mastering positions, so each week is one rung and the
    standard is the rung's *own* standard (a hold, a position, a rep count).

  * **strength** — a rep count on a measured movement (more push-ups, more
    dips, a heavier squat). The path is the movement itself and its
    prerequisites, and the plan is a volume/quality build-up against the
    published standard.

Everything is derived from the graph, never duplicated: the week's content
comes from `SKILLS[skill]`, the "what earns it" from `Standard`, and the
ordering from `tiers()`. If the graph changes, the plan follows.
"""
from __future__ import annotations

from dataclasses import dataclass

from .skills import SKILLS, Standard, ancestors, state, tiers

TRACKS = ("skill", "strength")

# A week is one position/rung for a skill track. For a strength track we keep
# the same shape (one movement per week) so the plan reads identically; the
# difference is in how many weeks and what "done" means.
WEEKS_PER_RUNG = 1


@dataclass(frozen=True)
class Week:
    index: int
    skill_id: str
    name: str
    family: str
    focus: str                    # what this week is about, in plain words
    target: str                   # the measurable bar / position
    reps: str                     # what counts as a working set
    transition: str               # the rung before it, or the base
    measurable: bool              # whether barra can referee this rung
    standard: str                 # the published standard, human-readable


@dataclass(frozen=True)
class Plan:
    track: str
    target: str                   # the goal skill id
    target_name: str
    weeks: tuple[Week, ...]
    total_weeks: int
    note: str = ""


def _path_to(target: str, depth: int | None = None) -> list[str]:
    """The prerequisite chain from the roots up to `target`, shallowest first.

    A skill with several prerequisites (muscle-up needs a pull and a dip) has a
    join point: we walk the deepest branch first, then the shallow one, then
    the skill itself. The result is a linear plan even though the graph is not
    a tree - the graph is the truth, the plan is the walk.

    `depth` keeps only prerequisites within N jumps of `target`. A skill track
    wants the chain of the movement itself, not every root it touches; a
    strength build-up wants the whole path.
    """
    if target not in SKILLS:
        raise KeyError(f"unknown skill {target!r}")
    t = tiers()
    anc = sorted(ancestors(target), key=lambda s: t.get(s, 0))
    if depth is not None:
        near = t.get(target, 0)
        anc = [s for s in anc if near - t.get(s, 0) <= depth]
    return [*anc, target]


def build_plan(
    track: str,
    target: str,
    verified: set[str] | None = None,
    claimed: set[str] | None = None,
    max_weeks: int = 16,
) -> Plan:
    """A week-by-week plan from where the athlete is (verified/claimed) to `target`.

    `verified` is what barra measured; `claimed` is what the athlete says they
    already can do. Skills already in either set are treated as done and the
    plan starts at the first rung that is not.
    """
    if track not in TRACKS:
        raise ValueError(f"track must be one of {TRACKS}, got {track!r}")
    verified = set(verified or ())
    claimed = set(claimed or ())
    done = set(verified) | set(claimed)
    # Done propagates down the graph: a verified kipping muscle-up is also a
    # verified transition drill, and a plan that re-asks for the rungs behind
    # something the athlete already measured is a plan that ignores its own
    # evidence.
    done |= {a for s in done for a in ancestors(s)}

    # A skill is its own chain of positions; a strength build-up uses the
    # whole prerequisite path (more volume on the base movements).
    chain = _path_to(target, depth=2 if track == "skill" else None)
    # Drop rungs already done; keep the rest as the walk.
    remaining = [sid for sid in chain if sid not in done]
    if not remaining:
        # Everything on the path is already done: nothing left to plan.
        return Plan(track, target, SKILLS[target].name, (), 0,
                    note=f"{SKILLS[target].name} is already on your path.")

    weeks: list[Week] = []
    for i, sid in enumerate(remaining):
        if len(weeks) >= max_weeks:
            break
        sk = SKILLS[sid]
        standard: Standard | None = sk.standard
        # The transition is the immediately-earlier rung in the chain, if any.
        prev = remaining[i - 1] if i > 0 else ""
        prev_name = SKILLS[prev].name if prev in SKILLS else "foundation"
        if standard is not None:
            target_txt = f"{standard.reps} verified reps at {standard.quality}+"
            if sk.family in ("CORE", "BALANCE"):
                target_txt = f"{standard.reps} verified reps/hold at {standard.quality}+"
            reps_txt = "3 sets of a working set, with full rest"
        else:
            target_txt = "position mastered to the standard"
            reps_txt = "short holds / controlled reps, quality first"
        weeks.append(Week(
            index=i + 1,
            skill_id=sid,
            name=sk.name,
            family=sk.family,
            focus=f"Master {sk.name}",
            target=target_txt,
            reps=reps_txt,
            transition=prev_name,
            measurable=sk.measurable,
            standard=sk.note or f"{sk.name} - {target_txt}",
        ))

    total = len(weeks)
    note = (
        f"{total} week plan to {SKILLS[target].name}."
        if track == "skill" else
        f"{total} week build-up to {SKILLS[target].name}."
    )
    return Plan(track, target, SKILLS[target].name, tuple(weeks), total, note)
