"""Recommend the next exercise, from the DAG and the failures just measured.

The product decision this answers: after a clip is classified into a track and
into failure types, what should the athlete work on next? The answer comes from
the DAG of prerequisite techniques (barra/skills.py) plus the failures - a
failure points at the drill that fixes it; a chain gap points at the rung that
is next.

This is deliberately a recommendation, not a verdict. It says what to try and
why; it does not claim the athlete has mastered anything, and it never invents
a standard the measurement did not support.
"""
from __future__ import annotations

from .skills import SKILLS, ancestors, state, tiers

# The order of a track's own progression chain, root to skill. These sit on top
# of the graph in barra/skills.py, which is the single source of truth for
# prerequisites - this is the route through it, not a second copy of it.
TRACK_CHAIN: dict[str, tuple[str, ...]] = {
    "front_lever": (
        "dead_hang", "scapular_pull", "tuck_front_lever",
        "adv_tuck_front_lever", "straddle_front_lever",
        "half_front_lever", "front_lever",
    ),
    "planche": (
        "push_up", "planche_lean", "frog_stand", "tuck_planche",
        "adv_tuck_planche", "straddle_planche", "full_planche",
    ),
    "muscle_up": (
        "pull_up", "chest_to_bar", "explosive_pull_up", "transition_drill",
        "dip", "kipping_muscle_up", "muscle_up",
    ),
    "pistol_squat": (
        "squat", "split_squat", "bulgarian_split_squat", "pistol_squat",
    ),
}

# A failure points at the drill that fixes it. The drill is a skill id in the
# graph; the reason is what the athlete actually has to change.
FAILURE_FIX: dict[str, tuple[str, str]] = {
    # front lever
    "poor scapular retraction": ("scapular_pull",
        "The shoulders are not held down and back, so the arms take the load. "
        "Work scapular pulls to own the retraction before you hang it out."),
    "piked hips": ("hollow_hold",
        "The hips drop out of the body line. A hollow body keeps the ribs down "
        "and the hips in line with the shoulders."),
    "bent knees": ("tuck_front_lever",
        "The legs are not straight. Tuck the knees first and own that line "
        "before extending."),
    "poor range of motion": ("tuck_front_lever",
        "The body is not held horizontal. Drop to the rung you can hold at the "
        "line and build the time there."),
    # planche
    "poor scapular protraction": ("planche_lean",
        "The shoulders are not pushed forward and up, so the elbows bend. "
        "Planche leans build the protraction that carries the body."),
    "piked body": ("frog_stand",
        "The hips pike. Frog stand teaches the hips to sit back into the line."),
    # muscle-up / bar
    "momentum": ("strict_pull_up",
        "The swing is doing the work. Strict, slow, no momentum - own the pull "
        "before you add the transition."),
    "lockout": ("chest_to_bar",
        "The top is not owned. Chest-to-bar pull-ups build a full lockout."),
    "dead hang": ("dead_hang",
        "The rep does not start from a full hang. Build the dead hang first."),
    "control": ("negative_pull_up",
        "The descent was dropped. Negatives teach control through the whole "
        "range."),
    "stall": ("explosive_pull_up",
        "The ascent grinds at the sticking point. Explosive pulls build the "
        "speed the transition needs."),
    "poor transition": ("transition_drill",
        "The bar is crossed slowly. The transition drill owns that crossing."),
    "bent arms": ("scapular_pull",
        "The arms give under load. Build the straight-arm strength first."),
    # pistol squat
    "poor range of motion": ("split_squat",
        "Not deep enough. Build depth in a split squat before you balance on "
        "one leg."),
    "knee valgus": ("bulgarian_split_squat",
        "The standing knee caves inward. Bulgarian split squats teach the knee "
        "to track over the foot."),
    "leaning back": ("split_squat",
        "The hips drift forward to compensate. Own the depth in a supported "
        "position first."),
    "heel raise": ("squat",
        "The standing heel lifts. Build ankle mobility and squat depth."),
    "uncontrolled descent": ("negative_pull_up",
        "The descent was dropped. Lower under control on the way down."),
    "arm swing": ("squat",
        "The arms are used for balance. Own the squat without the swing."),
}

# The failure that should lead the recommendation, by track - the one the
# athlete most needs to hear first.
PRIORITY: dict[str, tuple[str, ...]] = {
    "front_lever": ("poor scapular retraction", "piked hips", "bent knees",
                    "poor range of motion", "momentum"),
    "planche": ("poor scapular protraction", "piked body", "bent knees",
                "poor range of motion", "momentum"),
    "muscle_up": ("momentum", "stall", "poor transition", "lockout",
                  "dead hang", "control", "bent arms"),
    "pistol_squat": ("knee valgus", "poor range of motion", "leaning back",
                     "heel raise", "uncontrolled descent", "arm swing"),
}


def _state(verified: set[str], claimed: set[str]) -> dict[str, str]:
    return state(verified, claimed)


def next_in_chain(track: str, verified: set[str], claimed: set[str],
                  st: dict[str, str] | None = None) -> str | None:
    """The next rung of the track's chain that is ready to work.

    The first skill in the chain that is AVAILABLE (its prerequisites are done)
    but not yet verified or claimed. Where the athlete has verified past a rung,
    that rung is skipped. Returns None when the whole chain is done or unknown.
    """
    st = st if st is not None else _state(verified, claimed)
    chain = TRACK_CHAIN.get(track)
    if not chain:
        return None
    done = set(verified) | set(claimed)
    for sid in chain:
        if sid in done:
            continue
        if st.get(sid) == "available":
            return sid
    return None


def recommend(track: str, failures: list[str],
              verified: set[str] | None = None,
              claimed: set[str] | None = None) -> dict:
    """The recommendation for one analysis.

    `verified` / `claimed` are the athlete's skill states when the caller has
    them; otherwise the recommendation is driven by the failures alone, which is
    what a single clip supports.
    """
    verified = verified or set()
    claimed = claimed or set()
    st = _state(verified, claimed)

    # Pick the failure that matters most for this track.
    lead = None
    for f in PRIORITY.get(track, ()):
        if f in failures:
            lead = f
            break
    if lead is None and failures:
        lead = failures[0]

    rec: dict = {
        "track": track,
        "failures": failures,
        "nextExercise": None,
        "reason": "",
        "chain": [],
    }

    # If a failure has a fix, the fix is what to do next - it is more specific
    # than the next generic rung, and it is where the athlete's problem is.
    if lead and lead in FAILURE_FIX:
        skill, reason = FAILURE_FIX[lead]
        rec["nextExercise"] = skill
        rec["reason"] = reason
    else:
        # No specific failure (or a clean set): take the next rung of the chain.
        nxt = next_in_chain(track, verified, claimed, st)
        if nxt:
            rec["nextExercise"] = nxt
            rec["reason"] = (f"The next rung of the {track.replace('_', ' ')} "
                             "progression.")
        else:
            rec["nextExercise"] = None
            rec["reason"] = (f"Nothing in the {track.replace('_', ' ')} chain is "
                             "left to work from what you've shown.")

    # The chain, with each rung's state, so the UI can draw the DAG.
    for sid in TRACK_CHAIN.get(track, ()):
        if sid not in SKILLS:
            continue
        sk = SKILLS[sid]
        rec["chain"].append({
            "id": sid,
            "name": sk.name,
            "state": st.get(sid, "locked"),
            "measurable": sk.measurable,
            "standard": (f"{sk.standard.reps} verified reps at "
                         f"{sk.standard.quality}+ on {sk.standard.days} days")
            if sk.standard else None,
        })
    return rec


def recommend_for_payload(payload: dict, verified: set[str] | None = None,
                          claimed: set[str] | None = None) -> dict:
    """The recommendation for a full server payload, keyed off its track."""
    track = payload.get("track")
    if not track:
        track = payload.get("exercise")
    failures = payload.get("failures") or []
    # Clip-level failures are counts; turn them into a list of the types seen.
    if isinstance(failures, dict):
        failures = [k for k, v in failures.items() if v > 0]
    if not track or track not in TRACK_CHAIN:
        return {"track": track, "failures": failures, "nextExercise": None,
                "reason": "No progression chain for this movement yet.",
                "chain": []}
    return recommend(track, failures, verified, claimed)
