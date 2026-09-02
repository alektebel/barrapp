"""The calisthenics skill graph.

A graph, not a tree. A tree would say every skill has one parent, and the most
important skill in the sport does not: a muscle-up is a pull-up and a dip
joined by a transition, and you need both. Front lever needs the pull chain and
the core chain. Modelling that as a tree forces a lie about which prerequisite
matters, so this is a directed acyclic graph and `requires` is a tuple.

**Barra can verify six of these skills.** That is the number to keep in mind
while reading the other sixty-odd. The graph is a map of the sport; the
measured core is small and stated, and the two are never blurred:

    VERIFIED   barra measured it, against a published standard, with a trace
               id you can replay. Only possible for skills in MEASURED.
    CLAIMED    you told us you can do it. Useful for unlocking what comes next,
               worth nothing as evidence, and never counted as verification.
    AVAILABLE  every prerequisite is done, so this is what you can work on.
    LOCKED     something upstream is not done yet.

Anything else would be the thing this project exists not to do: a skill tree
that lights up on self-report and then reports itself back to you as progress.

Tiers are the longest path from a root, computed rather than declared, so a
skill cannot claim to be easier than its own prerequisites.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

# Quality bands, shared with the scorer. See barra/quality.py for why these
# numbers are what they are.
SOLID = 47
STRONG = 73

PUSH, PULL, CORE, LEGS, BALANCE, BAR = (
    "push", "pull", "core", "legs", "balance", "bar")

LOCKED, AVAILABLE, CLAIMED, VERIFIED = "locked", "available", "claimed", "verified"


@dataclass(frozen=True)
class Standard:
    """What counts as owning a skill well enough to move past it.

    A convention, not a discovery - the same status as the numbers it replaced.
    Close to the rule the sport already uses (roughly three sets of ten
    controlled reps), written in the open so it can be argued with.
    """
    reps: int
    quality: int = SOLID
    days: int = 2


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    family: str
    requires: tuple[str, ...] = ()
    # Can barra verify this from video? False for most of the graph, and the
    # UI must say so rather than implying a self-report is a measurement.
    measurable: bool = False
    standard: Standard | None = None
    note: str = ""


def _s(id, name, family, requires=(), measurable=False, standard=None, note=""):
    return Skill(id, name, family, tuple(requires), measurable, standard, note)


# ---------------------------------------------------------------------------
# The graph.
#
# Ordered by family for reading; the edges, not the order, define the
# structure. Where a skill is genuinely reachable from two directions both
# prerequisites are listed, because that is the honest shape.
# ---------------------------------------------------------------------------
SKILLS: dict[str, Skill] = {s.id: s for s in [
    # -- push -----------------------------------------------------------
    _s("wall_push_up", "Wall push-up", PUSH),
    _s("incline_push_up", "Incline push-up", PUSH, ["wall_push_up"]),
    _s("knee_push_up", "Knee push-up", PUSH, ["wall_push_up"]),
    _s("push_up", "Push-up", PUSH, ["incline_push_up", "knee_push_up"],
       measurable=True, standard=Standard(15),
       note="One of the six barra can verify."),
    _s("wide_push_up", "Wide push-up", PUSH, ["push_up"]),
    _s("diamond_push_up", "Diamond push-up", PUSH, ["push_up"]),
    _s("decline_push_up", "Decline push-up", PUSH, ["push_up"]),
    _s("archer_push_up", "Archer push-up", PUSH, ["diamond_push_up"]),
    _s("pseudo_planche_push_up", "Pseudo planche push-up", PUSH,
       ["decline_push_up", "planche_lean"]),
    _s("one_arm_push_up", "One-arm push-up", PUSH, ["archer_push_up"]),
    _s("bench_dip", "Bench dip", PUSH),
    _s("dip", "Dip", PUSH, ["bench_dip", "push_up"],
       measurable=True, standard=Standard(10),
       note="One of the six barra can verify."),
    _s("weighted_dip", "Weighted dip", PUSH, ["dip"],
       note="Barra cannot see added load, so this is yours to claim."),
    _s("ring_dip", "Ring dip", PUSH, ["dip"]),
    _s("korean_dip", "Korean dip", PUSH, ["dip"]),

    # -- pull -----------------------------------------------------------
    _s("dead_hang", "Dead hang", PULL),
    _s("scapular_pull", "Scapular pull", PULL, ["dead_hang"]),
    _s("australian_row", "Australian row", PULL),
    _s("negative_pull_up", "Negative pull-up", PULL,
       ["scapular_pull", "australian_row"]),
    _s("chin_up", "Chin-up", PULL, ["negative_pull_up"]),
    _s("pull_up", "Pull-up", PULL, ["negative_pull_up"],
       measurable=True, standard=Standard(8),
       note="One of the six barra can verify."),
    _s("chest_to_bar", "Chest-to-bar pull-up", PULL, ["pull_up"]),
    _s("weighted_pull_up", "Weighted pull-up", PULL, ["pull_up"],
       note="Barra cannot see added load, so this is yours to claim."),
    _s("typewriter_pull_up", "Typewriter pull-up", PULL, ["chest_to_bar"]),
    _s("archer_pull_up", "Archer pull-up", PULL, ["chest_to_bar"]),
    _s("one_arm_negative", "One-arm negative", PULL, ["archer_pull_up"]),
    _s("assisted_one_arm_pull_up", "Assisted one-arm pull-up", PULL,
       ["one_arm_negative"]),
    _s("one_arm_pull_up", "One-arm pull-up", PULL, ["assisted_one_arm_pull_up"]),

    # -- bar skills, where push and pull meet ---------------------------
    _s("explosive_pull_up", "Explosive pull-up", BAR, ["pull_up"]),
    _s("transition_drill", "Transition drill", BAR, ["explosive_pull_up"]),
    _s("kipping_muscle_up", "Kipping muscle-up", BAR,
       ["transition_drill", "dip"]),
    _s("muscle_up", "Muscle-up", BAR, ["kipping_muscle_up"],
       measurable=True, standard=Standard(5, quality=STRONG),
       note="One of the six barra can verify. A pull-up and a dip joined by a "
            "transition, which is why it needs both."),
    _s("strict_muscle_up", "Strict muscle-up", BAR, ["muscle_up"]),
    _s("weighted_muscle_up", "Weighted muscle-up", BAR, ["strict_muscle_up"],
       note="Barra cannot see added load, so this is yours to claim."),
    _s("ring_muscle_up", "Ring muscle-up", BAR, ["strict_muscle_up"]),
    _s("hefesto", "Hefesto", BAR, ["strict_muscle_up", "back_lever"]),
    _s("bar_360", "360 pull-up", BAR, ["kipping_muscle_up"]),

    # -- core -----------------------------------------------------------
    _s("plank", "Plank", CORE),
    _s("hollow_hold", "Hollow hold", CORE, ["plank"]),
    _s("knee_raise", "Hanging knee raise", CORE, ["dead_hang", "hollow_hold"],
       measurable=True, standard=Standard(12),
       note="One of the six barra can verify."),
    _s("leg_raise", "Hanging leg raise", CORE, ["knee_raise"]),
    _s("toes_to_bar", "Toes to bar", CORE, ["leg_raise"]),
    _s("l_sit", "L-sit", CORE, ["hollow_hold", "dip"]),
    _s("ab_wheel", "Ab wheel rollout", CORE, ["hollow_hold"]),
    _s("dragon_flag", "Dragon flag", CORE, ["hollow_hold", "leg_raise"]),
    _s("v_sit", "V-sit", CORE, ["l_sit", "toes_to_bar"]),
    _s("manna", "Manna", CORE, ["v_sit"]),

    # -- front lever chain ----------------------------------------------
    _s("tuck_front_lever", "Tuck front lever", CORE, ["pull_up", "hollow_hold"]),
    _s("adv_tuck_front_lever", "Advanced tuck front lever", CORE,
       ["tuck_front_lever"]),
    _s("straddle_front_lever", "Straddle front lever", CORE,
       ["adv_tuck_front_lever"]),
    _s("half_front_lever", "Half-lay front lever", CORE,
       ["straddle_front_lever"]),
    _s("front_lever", "Front lever", CORE, ["half_front_lever"]),
    _s("front_lever_pull_up", "Front lever pull-up", CORE, ["front_lever"]),
    _s("one_arm_front_lever", "One-arm front lever", CORE, ["front_lever"]),

    # -- back lever chain -----------------------------------------------
    _s("skin_the_cat", "Skin the cat", CORE, ["dead_hang"]),
    _s("tuck_back_lever", "Tuck back lever", CORE, ["skin_the_cat"]),
    _s("adv_tuck_back_lever", "Advanced tuck back lever", CORE,
       ["tuck_back_lever"]),
    _s("straddle_back_lever", "Straddle back lever", CORE,
       ["adv_tuck_back_lever"]),
    _s("back_lever", "Back lever", CORE, ["straddle_back_lever"]),

    # -- planche chain ---------------------------------------------------
    _s("planche_lean", "Planche lean", BALANCE, ["push_up"]),
    _s("frog_stand", "Frog stand", BALANCE, ["planche_lean"]),
    _s("tuck_planche", "Tuck planche", BALANCE, ["frog_stand"]),
    _s("adv_tuck_planche", "Advanced tuck planche", BALANCE, ["tuck_planche"]),
    _s("straddle_planche", "Straddle planche", BALANCE,
       ["adv_tuck_planche", "pseudo_planche_push_up"]),
    _s("full_planche", "Full planche", BALANCE, ["straddle_planche"]),
    _s("planche_push_up", "Planche push-up", BALANCE, ["full_planche"]),

    # -- handstand chain -------------------------------------------------
    _s("wall_plank", "Wall plank", BALANCE, ["plank"]),
    _s("chest_to_wall_handstand", "Chest-to-wall handstand", BALANCE,
       ["wall_plank"]),
    _s("freestanding_handstand", "Freestanding handstand", BALANCE,
       ["chest_to_wall_handstand"]),
    _s("wall_hspu", "Wall handstand push-up", BALANCE,
       ["chest_to_wall_handstand", "dip"]),
    _s("freestanding_hspu", "Freestanding handstand push-up", BALANCE,
       ["freestanding_handstand", "wall_hspu"]),
    _s("deficit_hspu", "Deficit handstand push-up", BALANCE, ["freestanding_hspu"]),
    _s("press_to_handstand", "Press to handstand", BALANCE,
       ["freestanding_handstand", "tuck_planche"]),
    _s("one_arm_handstand", "One-arm handstand", BALANCE, ["press_to_handstand"]),
    _s("ninety_degree_push_up", "90-degree push-up", BALANCE,
       ["freestanding_hspu", "straddle_planche"]),
    _s("elbow_lever", "Elbow lever", BALANCE, ["frog_stand"]),

    # -- human flag chain -------------------------------------------------
    _s("vertical_flag", "Vertical flag", BALANCE, ["pull_up", "hollow_hold"]),
    _s("tuck_human_flag", "Tuck human flag", BALANCE, ["vertical_flag"]),
    _s("straddle_human_flag", "Straddle human flag", BALANCE,
       ["tuck_human_flag"]),
    _s("human_flag", "Human flag", BALANCE, ["straddle_human_flag"]),

    # -- legs --------------------------------------------------------------
    _s("squat", "Bodyweight squat", LEGS,
       measurable=True, standard=Standard(20),
       note="One of the six barra can verify."),
    _s("split_squat", "Split squat", LEGS, ["squat"]),
    _s("jump_squat", "Jump squat", LEGS, ["squat"]),
    _s("bulgarian_split_squat", "Bulgarian split squat", LEGS, ["split_squat"]),
    _s("sissy_squat", "Sissy squat", LEGS, ["split_squat"]),
    _s("shrimp_squat", "Shrimp squat", LEGS, ["bulgarian_split_squat"]),
    _s("pistol_squat", "Pistol squat", LEGS, ["bulgarian_split_squat"],
       note="Single-leg, and barra measures the hips as one point, so it "
            "cannot tell a pistol from a two-legged squat."),
    _s("nordic_curl", "Nordic curl", LEGS, ["bulgarian_split_squat"]),
]}

# The six barra can verify from video. Everything else in the graph is a map,
# not a measurement.
MEASURED: tuple[str, ...] = tuple(
    k for k, s in SKILLS.items() if s.measurable)


@lru_cache(maxsize=1)
def unlocks() -> dict[str, tuple[str, ...]]:
    """Reverse edges: skill -> the skills it is a prerequisite for."""
    out: dict[str, list[str]] = {k: [] for k in SKILLS}
    for skill in SKILLS.values():
        for req in skill.requires:
            out[req].append(skill.id)
    return {k: tuple(v) for k, v in out.items()}


@lru_cache(maxsize=1)
def tiers() -> dict[str, int]:
    """Longest path from a root, so a skill can never sit at or before its own
    prerequisites. Computed rather than declared - a hand-written tier column
    drifts the moment an edge is added."""
    depth: dict[str, int] = {}

    def resolve(sid: str, seen: frozenset = frozenset()) -> int:
        if sid in depth:
            return depth[sid]
        if sid in seen:                       # cycle guard; validate() reports it
            return 0
        reqs = SKILLS[sid].requires
        d = 0 if not reqs else 1 + max(
            resolve(r, seen | {sid}) for r in reqs if r in SKILLS)
        depth[sid] = d
        return d

    for sid in SKILLS:
        resolve(sid)
    return depth


def validate() -> list[str]:
    """Structural problems with the graph itself. Empty when it is sound."""
    problems = []
    for skill in SKILLS.values():
        for req in skill.requires:
            if req not in SKILLS:
                problems.append(f"{skill.id} requires unknown skill {req!r}")
        if skill.measurable and skill.standard is None:
            problems.append(f"{skill.id} is measurable but has no standard")
        if skill.standard is not None and not skill.measurable:
            problems.append(f"{skill.id} has a standard but is not measurable")

    # Cycles: a skill that is its own ancestor.
    def ancestors(sid, seen=()):
        for r in SKILLS[sid].requires:
            if r not in SKILLS:
                continue
            if r in seen:
                problems.append(f"cycle through {r!r}")
                return
            ancestors(r, seen + (sid,))
    for sid in SKILLS:
        ancestors(sid)
    return sorted(set(problems))


def ancestors(sid: str) -> set[str]:
    """Everything upstream of a skill, transitively."""
    out: set[str] = set()
    stack = list(SKILLS[sid].requires) if sid in SKILLS else []
    while stack:
        cur = stack.pop()
        if cur in out or cur not in SKILLS:
            continue
        out.add(cur)
        stack.extend(SKILLS[cur].requires)
    return out


def state(verified: set[str], claimed: set[str]) -> dict[str, str]:
    """Every skill's state, given what has been verified and what was claimed.

    Verified beats claimed: if barra measured it, the self-report is redundant.
    Claimed unlocks what comes next but is never itself evidence - it is how
    someone who could already do handstands before installing this gets a
    useful graph without barra having to pretend it saw them.

    Doing a skill implies its prerequisites. Without that closure the graph
    tells a verified pull-up owner to go and work on a dead hang, which is both
    useless and slightly insulting. Implied prerequisites count as CLAIMED
    rather than VERIFIED: they were inferred, not measured, and the distinction
    is the whole point of the two words.
    """
    implied: set[str] = set()
    for sid in set(verified) | set(claimed):
        if sid in SKILLS:
            implied |= ancestors(sid)
    claimed = set(claimed) | (implied - set(verified))
    done = set(verified) | claimed
    out = {}
    for sid, skill in SKILLS.items():
        if sid in verified:
            out[sid] = VERIFIED
        elif sid in claimed:
            out[sid] = CLAIMED
        elif all(r in done for r in skill.requires):
            out[sid] = AVAILABLE
        else:
            out[sid] = LOCKED
    return out


def next_up(verified: set[str], claimed: set[str], limit: int = 5) -> list[Skill]:
    """What to work on: available skills, the ones barra can verify first.

    Measurable skills lead because they are the ones where the app can tell you
    something you did not already know. Then shallowest first, so the answer is
    the next step rather than the most impressive unlocked thing.
    """
    st = state(verified, claimed)
    t = tiers()
    ready = [SKILLS[k] for k, v in st.items() if v == AVAILABLE]
    ready.sort(key=lambda s: (not s.measurable, t[s.id], s.name))
    return ready[:limit]


def families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for sid, skill in SKILLS.items():
        out.setdefault(skill.family, []).append(sid)
    return out
