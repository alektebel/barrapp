"""Is the quality score measuring anything?

Not "is it right" - there is nothing to be right against. Movement quality has
no ground truth: two competent coaches disagree about the same rep, so a
labelled corpus would teach one person's aesthetic and call it truth. That is
the move that makes every "98% accurate" claim in this market meaningless.

The answerable question is **validity**: does the number respond to things it
should, and stay still for things it should not? That is testable with no
labels at all, because the experiments carry their own answers:

  1. CEILING       A component that never varies cannot measure. Free - it is a
                   property of scores already computed.
  2. RELIABILITY   Film one set from two phones. Same reps, so the same score.
                   The disagreement between them IS the noise floor, and every
                   other result in this file is judged against it.
  3. DEGRADATION   A set taken to failure orders its own reps: rep 1 is the best
                   the athlete has, the last is the worst. Nobody labels that -
                   the structure of the set does. If quality does not fall as
                   failure approaches, it is not tracking quality.
  4. SENSITIVITY   Do a set at deliberate half range, or deliberately jerky. You
                   created the manipulation, so you own the label. The drop has
                   to clear the noise floor from (2).

The order matters. Without (2) there is no scale to judge (3) and (4) against,
and a difference that does not exceed repeat-measurement noise is not a
difference. This is the same rule the deviation scoring already follows: no
number without its null.

A test that cannot discriminate says INCONCLUSIVE and why. That is not a
failure of the harness - a set that was never hard cannot test whether the
score notices fatigue, and reporting FAIL there would be the harness lying
about its own reach.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# A set that never slowed down was probably never near failure, so it cannot
# test whether the score notices fatigue. 10% is the convention borrowed from
# velocity-based training, where velocity loss across a set is the standard
# proxy for proximity to failure. It is a convention, not a measurement.
FATIGUE_SLOWDOWN = 0.10
# Below this many reps a rank correlation says almost nothing, whatever it
# comes out as.
MIN_REPS_FOR_TREND = 8
# A component sitting at one value in this fraction of reps is saturated: it is
# contributing a constant, and its weight is doing nothing.
SATURATED_FRAC = 0.80

PASS, FAIL, INCONCLUSIVE, NOT_RUN = "PASS", "FAIL", "INCONCLUSIVE", "NOT RUN"

# Only for the wording of the report - the authoritative weights live in
# quality.py and this must never be used to compute anything.
WEIGHT_HINT = {"range": "40% of the", "control": "25% of the",
               "smoothness": "35% of the"}


@dataclass
class Check:
    name: str
    verdict: str
    detail: str
    numbers: dict = field(default_factory=dict)
    advice: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "verdict": self.verdict, "detail": self.detail,
                "numbers": self.numbers, "advice": self.advice}


def _scores(reps: list[dict]) -> np.ndarray:
    return np.array([r["score"] for r in reps if r.get("score") is not None], float)


def _components(reps: list[dict]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in reps:
        if r.get("score") is None:
            continue
        for c in r.get("components") or []:
            if c.get("value") is not None:
                out.setdefault(str(c["name"]), []).append(float(c["value"]))
    return out


def _rep_times(reps: list[dict]) -> np.ndarray:
    out = []
    for r in reps:
        try:
            out.append(float(r["total_s"]))
        except (TypeError, ValueError, KeyError):
            out.append(np.nan)
    return np.array(out, float)


def _spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Rank correlation with a p-value, tie-aware.

    scipy is already a dependency, and its tie handling matters here: ranking a
    constant column by argsort produces a spurious perfect correlation, which
    is exactly the mistake a saturated component invites.
    """
    from scipy.stats import spearmanr
    if len(x) < 3 or np.all(y == y[0]):
        return float("nan"), float("nan")
    rho, p = spearmanr(x, y)
    return float(rho), float(p)


# ---------------------------------------------------------------------------
# 1. Ceiling
# ---------------------------------------------------------------------------
def ceiling(sets: list[tuple[str, list[dict]]]) -> Check:
    """Does the score have room to move, and does each part of it vary?

    Takes sets rather than a flat list of reps because the most damaging form
    of this fault is per clip, and pooling hides it: on one real 19-rep
    push-up clip the range component was unmeasurable for every single rep, so
    40% of the weight silently vanished and the score was renormalised without
    saying so. Pooled against two other clips where range did work, that
    disappears entirely.
    """
    reps = [r for _, rs in sets for r in rs]
    s = _scores(reps)
    comps = _components(reps)
    if s.size < 3:
        return Check("ceiling", NOT_RUN, "Fewer than 3 scored reps.",
                     advice="Analyse more clips.")

    numbers = {"reps": int(s.size), "min": float(s.min()), "max": float(s.max()),
               "mean": round(float(s.mean()), 1), "sd": round(float(s.std()), 2),
               "span": float(s.max() - s.min())}

    problems: list[str] = []
    for name, vals in sorted(comps.items()):
        a = np.array(vals, float)
        distinct = len(np.unique(np.round(a, 4)))
        top = float(np.mean(a >= 0.999))
        numbers[f"{name}_distinct"] = distinct
        numbers[f"{name}_at_ceiling"] = round(top, 3)
        if distinct == 1:
            problems.append(f"{name} is constant at {a[0]:.3f}")
        elif top >= SATURATED_FRAC:
            problems.append(f"{name} sits at its ceiling in {top:.0%} of reps")
        elif distinct <= 3 and a.size >= 8:
            problems.append(f"{name} takes only {distinct} distinct values "
                            f"across {a.size} reps")

    # A component no rep of a clip could measure is worse than a saturated one:
    # its weight silently vanishes and the score is renormalised without
    # saying so. Checked per clip, because that is where it happens.
    for name in ("range", "control", "smoothness"):
        blind = []
        for set_name, rs in sets:
            scored = [r for r in rs if r.get("score") is not None]
            if not scored:
                continue
            seen = sum(1 for r in scored for c in (r.get("components") or [])
                       if c.get("name") == name and c.get("value") is not None)
            if seen == 0:
                blind.append(f"{set_name} ({len(scored)} reps)")
        if blind:
            numbers[f"{name}_blind_sets"] = blind
            problems.append(f"{name} was measurable in no rep of "
                            + ", ".join(blind)
                            + f" - {WEIGHT_HINT.get(name, 'its')} weight "
                              "vanished from those scores")

    if numbers["span"] < 20:
        problems.append(f"the score only spans {numbers['span']:.0f} points "
                        f"({numbers['min']:.0f}-{numbers['max']:.0f})")

    if not problems:
        return Check("ceiling", PASS,
                     f"Scores span {numbers['min']:.0f}-{numbers['max']:.0f} "
                     f"(sd {numbers['sd']}), every component varies.", numbers)
    # Not .capitalize(): that lowercases the rest of the string, which mangles
    # the clip names in the message - and those are what you would grep for.
    joined = "; ".join(problems)
    return Check("ceiling", FAIL, joined[0].upper() + joined[1:] + ".", numbers,
                 advice="A component that does not vary cannot measure. Widen "
                        "or replace it before trusting any comparison - no "
                        "amount of data fixes a constant.")


# ---------------------------------------------------------------------------
# 2. Reliability - the noise floor everything else is judged against
# ---------------------------------------------------------------------------
def reliability(pairs: list[tuple[str, list[dict], list[dict]]]) -> Check:
    """The same set, filmed twice. Disagreement between the two IS the noise."""
    if not pairs:
        return Check("reliability", NOT_RUN,
                     "No repeat-filmed sets on record.",
                     advice="Film one set with two phones at once, or the same "
                            "set from two angles, and declare them a pair in "
                            "data/videos/validation.csv. Until this exists "
                            "there is no scale to judge any other result on.")
    rows, deltas = [], []
    for name, a, b in pairs:
        sa, sb = _scores(a), _scores(b)
        if sa.size == 0 or sb.size == 0:
            rows.append(f"{name}: one clip produced no scored reps")
            continue
        d = abs(float(sa.mean()) - float(sb.mean()))
        deltas.append(d)
        rows.append(f"{name}: {sa.mean():.1f} vs {sb.mean():.1f} "
                    f"(diff {d:.1f}, {sa.size} vs {sb.size} reps)")
    if not deltas:
        return Check("reliability", INCONCLUSIVE, "; ".join(rows),
                     advice="Neither clip in any pair produced scored reps.")
    noise = float(np.mean(deltas))
    numbers = {"pairs": len(deltas), "noise_floor": round(noise, 2),
               "worst": round(float(np.max(deltas)), 2)}
    verdict = PASS if noise <= 5.0 else FAIL
    detail = ("; ".join(rows) + f". Noise floor {noise:.1f} points.")
    return Check("reliability", verdict, detail, numbers,
                 advice="" if verdict == PASS else
                 "The same set scores differently depending on the clip, so "
                 "differences smaller than this mean nothing - including every "
                 "session-to-session change the app currently reports.")


# ---------------------------------------------------------------------------
# 3. Within-set degradation - free labels from a set to failure
# ---------------------------------------------------------------------------
def degradation(sets: list[tuple[str, list[dict]]], noise: float | None = None) -> Check:
    """Does quality fall as failure approaches?"""
    usable = [(n, r) for n, r in sets
              if len([x for x in r if x.get("score") is not None]) >= MIN_REPS_FOR_TREND]
    if not usable:
        return Check("degradation", NOT_RUN,
                     f"No set with {MIN_REPS_FOR_TREND} or more scored reps.",
                     advice=f"Film one set to genuine failure, {MIN_REPS_FOR_TREND}+ "
                            "reps. That single clip is worth more than a hundred "
                            "labelled reps: the set orders its own quality, so "
                            "the labels come free.")
    rows, verdicts, numbers = [], [], {}
    for name, reps in usable:
        scored = [r for r in reps if r.get("score") is not None]
        s = _scores(scored)
        t = _rep_times(scored)
        idx = np.arange(s.size)
        rho, p = _spearman(idx, s)

        # Did this set actually get hard? If it never slowed down it cannot
        # test whether the score notices fatigue, and calling that a failure of
        # the score would be the harness overreaching.
        third = max(1, s.size // 3)
        fatigued = False
        slowdown = float("nan")
        if np.isfinite(t).all() and t[:third].mean() > 0:
            slowdown = float(t[-third:].mean() / t[:third].mean() - 1.0)
            fatigued = slowdown >= FATIGUE_SLOWDOWN

        numbers[name] = {"reps": int(s.size), "rho": None if not np.isfinite(rho) else round(rho, 3),
                         "p": None if not np.isfinite(p) else round(p, 3),
                         "first_third": round(float(s[:third].mean()), 1),
                         "last_third": round(float(s[-third:].mean()), 1),
                         "slowdown": None if not np.isfinite(slowdown) else round(slowdown, 3),
                         "reached_failure": bool(fatigued)}
        if not fatigued:
            rows.append(f"{name}: rep times did not slow "
                        f"({slowdown:+.0%} across the set) - this set was not "
                        "near failure, so it cannot test the score")
            verdicts.append(INCONCLUSIVE)
            continue
        drop = float(s[:third].mean() - s[-third:].mean())
        ok = np.isfinite(rho) and rho < 0 and (p < 0.05) and \
            (noise is None or drop > noise)
        rows.append(f"{name}: rho={rho:+.3f} p={p:.3f}, "
                    f"{s[:third].mean():.1f} -> {s[-third:].mean():.1f} "
                    f"(drop {drop:+.1f})")
        verdicts.append(PASS if ok else FAIL)

    if all(v == INCONCLUSIVE for v in verdicts):
        return Check("degradation", INCONCLUSIVE, "; ".join(rows), numbers,
                     advice="Film a set taken to actual failure. A comfortable "
                            "set should not degrade, so it proves nothing "
                            "either way.")
    verdict = PASS if all(v in (PASS, INCONCLUSIVE) for v in verdicts) else FAIL
    return Check("degradation", verdict, "; ".join(rows), numbers,
                 advice="" if verdict == PASS else
                 "Quality did not fall as failure approached. Either the "
                 "components are saturated (see the ceiling check) or they are "
                 "not measuring what fatigue changes.")


# ---------------------------------------------------------------------------
# 4. Induced-error sensitivity
# ---------------------------------------------------------------------------
def sensitivity(baseline: list[dict], degraded: dict[str, list[dict]],
                noise: float | None = None) -> Check:
    """A deliberately worse set must score lower by more than the noise floor."""
    if not degraded:
        return Check("sensitivity", NOT_RUN, "No deliberately degraded sets on record.",
                     advice="Film one set at deliberate half range and one "
                            "deliberately jerky, and mark them in "
                            "data/videos/validation.csv. You created the fault, "
                            "so you own the label.")
    base = _scores(baseline)
    if base.size == 0:
        return Check("sensitivity", NOT_RUN, "No scored baseline set to compare against.")
    rows, verdicts, numbers = [], [], {}
    for kind, reps in sorted(degraded.items()):
        s = _scores(reps)
        if s.size == 0:
            rows.append(f"{kind}: produced no scored reps")
            verdicts.append(INCONCLUSIVE)
            continue
        drop = float(base.mean() - s.mean())
        detected = drop > (noise if noise is not None else 0.0)
        numbers[kind] = {"baseline": round(float(base.mean()), 1),
                         "degraded": round(float(s.mean()), 1),
                         "drop": round(drop, 1), "detected": bool(detected)}
        rows.append(f"{kind}: {base.mean():.1f} -> {s.mean():.1f} (drop {drop:+.1f})")
        verdicts.append(PASS if detected else FAIL)
    verdict = FAIL if FAIL in verdicts else (PASS if PASS in verdicts else INCONCLUSIVE)
    return Check("sensitivity", verdict, "; ".join(rows), numbers,
                 advice="" if verdict == PASS else
                 "A fault you introduced on purpose did not move the score "
                 "further than repeat-filming noise does. The score cannot see "
                 "that fault.")


# ---------------------------------------------------------------------------
def run(sets: list[tuple[str, list[dict]]],
        pairs: list[tuple[str, list[dict], list[dict]]] | None = None,
        degraded: dict[str, list[dict]] | None = None) -> list[Check]:
    """All four checks, in the order that makes each one interpretable."""
    rel = reliability(pairs or [])
    noise = rel.numbers.get("noise_floor") if rel.verdict in (PASS, FAIL) else None
    baseline = max((reps for _, reps in sets), key=lambda r: len(_scores(r)), default=[])
    return [ceiling(sets), rel, degradation(sets, noise),
            sensitivity(baseline, degraded or {}, noise)]


PROTOCOL = """\
What to film, in the order that makes each result mean something

  1. RELIABILITY - one set, two phones at once (or two clips of one set).
     Establishes the noise floor. Nothing else is interpretable without it,
     because a difference smaller than this is not a difference.

  2. DEGRADATION - one set taken to genuine failure, 8+ reps.
     The set orders its own reps: the first is the best you have, the last is
     the worst. That is a free label on every rep, and no human judgement is
     involved. This single clip is worth more than a hundred labelled reps.

  3. SENSITIVITY - one set at deliberate half range, one deliberately jerky.
     You created the fault, so you know the answer. The score has to drop by
     more than the noise floor from (1).

Declare them in data/videos/validation.csv:

  video,role,pair,note
  CLIP_A,normal,setA,first phone
  CLIP_B,repeat,setA,second phone, same set
  CLIP_C,failure,,taken to failure
  CLIP_D,degraded:range,,deliberate half range
  CLIP_E,degraded:tempo,,deliberately jerky

What NOT to do: label reps by eye. Movement quality has no ground truth - two
good coaches disagree about the same rep - so labels teach one aesthetic and
call it truth. If you ever do want human judgement, ask for PAIRWISE
comparisons ("which of these two is better?") rather than ratings. People are
far more reliable at ordering than at scoring, and a few hundred comparisons
recover a scale that thousands of ratings would not.
"""
