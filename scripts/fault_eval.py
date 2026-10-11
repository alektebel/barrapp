#!/usr/bin/env python
"""Do the fault thresholds fire where a second opinion says they should?

`barra.validate_faults` asks this question of the five legacy cue names and a
hand-labelled manifest, and with three rows in `faults.csv` it has only ever
been able to answer INCONCLUSIVE. Meanwhile `rules.py` grew to 55 thresholds
across 10 movements, and not one of them had ever been checked against
anything.

`scripts/label_faults.py` produces the missing half: an independent multimodal
read of each clip, asked in the rule table's own vocabulary. This script is the
comparison. For every clip that has both, it runs the real pipeline, reads the
per-rep assessments, and puts the two verdicts side by side:

    rule says      vision says     what it means
    observed       present         agreement - the threshold caught it
    not_observed   absent          agreement - the threshold stayed quiet
    observed       absent          a false alarm, or the model missed it
    not_observed   present         a miss, or the model imagined it

Two rules keep this honest. "unclear" from the model and "unobservable" from
the geometry are never folded into "absent": a fault nobody could see is not a
fault that is not there, and collapsing the two is how a harness manufactures
agreement with itself. And a rule with fewer than `--min-support` judgeable
clips is reported as INCONCLUSIVE with its support, never as a percentage -
two clips agreeing is not an eighty percent.

Because the per-rep primitive VALUES are recorded, not just the fired/not
booleans, `--tune` can then ask the other question: what threshold would this
rule need for the two to agree most often? That is a proposal for a human to
accept, not an edit - it prints the sweep and writes it to the report.

Usage:
  python scripts/fault_eval.py                       # measure and compare
  python scripts/fault_eval.py --tune                # + propose thresholds
  python scripts/fault_eval.py --movements pull_up,dip
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra.posecache import load as load_cached  # noqa: E402
from barra.posecache import load_or_estimate  # noqa: E402
from barra.rules import RULES  # noqa: E402

DATASET = ROOT / "data" / "calisthenics"
VIDEOS = DATASET / "videos"
FAULT_LABELS = ROOT / "out" / "fault-labels"
# Labels a person wrote, watching the reps. They outrank the model's read
# wherever both exist: the vision labels were only ever a stand-in for ground
# truth this corpus did not have, and they are what every fault number so far
# has been measured against - which is why none of those numbers can validate
# a vision-based detector. `scripts/label_reps.py` writes these.
HUMAN_LABELS = ROOT / "out" / "fault-labels-human"
MEASURED = ROOT / "out" / "fault-measured"
DEFAULT_OUT = ROOT / "out" / "fault-eval"

PRESENT, ABSENT, UNCLEAR = "present", "absent", "unclear"


# ---------------------------------------------------------------------------
# the geometry's side of the comparison
# ---------------------------------------------------------------------------
def measure_clip(video: Path, movement: str) -> dict:
    """Run the real pipeline on one clip and keep every rule's evidence.

    The cached keypoints are handed in rather than re-estimated: pose is the
    expensive stage and it has already been paid for, and a second opinion on
    frames that have not changed is a second answer to compare against by
    accident.

    A clip with no cache is SKIPPED, not posed. `load_or_estimate` would
    happily pose it here, in this process, which is how this script got
    OOM-killed mid-batch and lost the run: posing a long clip in-process is
    exactly the failure `scripts/extract_keypoints.py` exists to contain, by
    giving every clip its own subprocess. Pose is paid there, once.
    """
    from process import analyze_clip  # noqa: PLC0415 - server path, set up above

    if load_cached(video) is None:
        raise LookupError(
            f"no cached keypoints for {video.name} - run "
            "scripts/extract_keypoints.py first")
    pose = load_or_estimate(video, fresh=False, write_cache=False)
    payload = analyze_clip(video, exercise=movement, pose=pose)
    per_rule: dict[str, list[dict]] = defaultdict(list)
    for rep in payload.get("reps", []):
        for a in rep.get("assessments", []):
            ev = a.get("evidence", {})
            per_rule[a["errorId"]].append({
                "status": a.get("status"),
                "value": ev.get("value"),
                "threshold": ev.get("threshold"),
                "comparison": ev.get("comparison"),
                "coverage": ev.get("coverage"),
                # Why a rule could not be judged is the difference between
                # "the camera was wrong for it" and "nothing measures this",
                # and only the second is a rule that can never fire.
                "reason": (a.get("availability") or {}).get("reason"),
                "detail": (a.get("availability") or {}).get("detail"),
            })
    return {
        "clip": video.name, "movement": movement,
        "nReps": int(payload.get("n_reps") or 0),
        "view": payload.get("view"),
        "blockers": payload.get("blockers") or [],
        "rules": {k: v for k, v in per_rule.items()},
    }


def rule_verdict(reps: list[dict], min_reps: int = 1) -> str:
    """One clip-level verdict from a rule's per-rep assessments.

    By default a fault is a property of the clip if it happened in ANY rep -
    that is what the model was asked ("is it visible in this clip"). Production
    coaching uses a higher bar (`--min-reps` / THRESHOLDS.fault_min_reps) so a
    single jittered rep does not become the cue for the set. A rule that could
    not be evaluated on any rep is unclear, not clean.
    """
    if not reps:
        return UNCLEAR
    judged = [r for r in reps if r["status"] in ("observed", "not_observed")]
    if not judged:
        return UNCLEAR
    need = min(max(1, int(min_reps)), len(judged))
    observed = sum(1 for r in judged if r["status"] == "observed")
    if observed >= need:
        return PRESENT
    if any(r["status"] == "not_observed" for r in judged):
        return ABSENT
    return UNCLEAR


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def refresh_thresholds(row: dict) -> dict:
    """Re-apply current RULES thresholds to cached per-rep values.

    Pose measurement is expensive; threshold edits are not. A cached row still
    carries the value the primitive produced, so a threshold change can be
    scored without `--redo` as long as the comparison is re-run here.
    """
    movement = row.get("movement")
    rules = {r.id: r for r in RULES.get(movement, ())}
    refreshed = dict(row)
    new_rules = {}
    for eid, reps in (row.get("rules") or {}).items():
        rule = rules.get(eid)
        updated = []
        for r in reps:
            item = dict(r)
            if rule is not None and item.get("value") is not None:
                item["threshold"] = rule.threshold
                item["comparison"] = rule.comparison
                if item.get("status") in ("observed", "not_observed"):
                    v = float(item["value"])
                    t = float(rule.threshold)
                    c = rule.comparison
                    fired = (
                        v < t if c == "<" else
                        v > t if c == ">" else
                        v >= t if c == ">=" else
                        v <= t if c == "<=" else
                        False
                    )
                    item["status"] = "observed" if fired else "not_observed"
            updated.append(item)
        new_rules[eid] = updated
    refreshed["rules"] = new_rules
    return refreshed


def compare(measured: dict[str, dict], labels: dict[str, dict],
            min_support: int, min_reps: int = 1) -> dict:
    """Per rule: agreement, and the two ways the pair can disagree."""
    table: dict[str, dict] = {}
    for clip, m in measured.items():
        label = labels.get(clip)
        if not label:
            continue
        want = label.get("faults", {})
        for rule in RULES.get(m["movement"], []):
            key = rule.id.split(".", 1)[1]
            said = str(want.get(key, UNCLEAR)).lower()
            got = rule_verdict(m["rules"].get(rule.id, []), min_reps=min_reps)
            row = table.setdefault(rule.id, {
                "errorId": rule.id, "movement": rule.movement,
                "name": rule.name, "primitive": rule.primitive,
                "comparison": rule.comparison, "threshold": rule.threshold,
                "agree": 0, "falseAlarm": 0, "missed": 0,
                "visionUnclear": 0, "ruleUnclear": 0, "clips": [],
            })
            if said == UNCLEAR:
                row["visionUnclear"] += 1
                continue
            if got == UNCLEAR:
                row["ruleUnclear"] += 1
                continue
            if said == got:
                row["agree"] += 1
            elif got == PRESENT:
                row["falseAlarm"] += 1
            else:
                row["missed"] += 1
            row["clips"].append({"clip": clip, "vision": said, "rule": got})

    for row in table.values():
        judged = row["agree"] + row["falseAlarm"] + row["missed"]
        row["judged"] = judged
        # Faults are RARE here - the corpus is tutorials of people doing the
        # movement properly - so plain agreement is the wrong headline: a rule
        # that never fires scores well on a corpus that is 90% clean. The
        # positive class is reported next to it, and a rule that has never
        # seen a labelled instance of its own fault cannot be said to detect
        # it at all, however high its agreement.
        present = sum(1 for c in row["clips"] if c["vision"] == PRESENT)
        fired = sum(1 for c in row["clips"] if c["rule"] == PRESENT)
        caught = sum(1 for c in row["clips"]
                     if c["vision"] == PRESENT and c["rule"] == PRESENT)
        row["visionPresent"] = present
        row["ruleFired"] = fired
        row["recall"] = round(caught / present, 3) if present else None
        row["precision"] = round(caught / fired, 3) if fired else None
        row["fireRate"] = round(fired / judged, 3) if judged else None
        if judged < min_support:
            row["verdict"] = "INCONCLUSIVE"
            row["agreement"] = None
        elif present == 0:
            # Every judgeable clip was clean. That measures the false-alarm
            # rate and nothing else, so it is named for what it is.
            row["verdict"] = "NO-POSITIVES"
            row["agreement"] = round(row["agree"] / judged, 3)
        else:
            row["verdict"] = "MEASURED"
            row["agreement"] = round(row["agree"] / judged, 3)
    return table


def sweep(rule_id: str, measured: dict[str, dict], labels: dict[str, dict],
          comparison: str) -> dict | None:
    """What threshold would make this rule agree with the model most often?

    The rule is re-applied at every candidate cut point - the midpoints between
    the observed values - and scored the same way it was scored above. This is
    a proposal, not a tuning run: the same clips are used to pick the threshold
    and to score it, so the number it reports is an upper bound, and a rule
    whose best is barely above its current agreement has not learned anything.

    A rule with no labelled instance of its own fault gets no proposal at all.
    The corpus is people demonstrating correct technique, so most rules see
    only clean clips - and on an all-clean sample the threshold that "agrees"
    best is whichever one never fires. That is not a calibration, it is the
    rule being deleted by arithmetic, and it would look like a 100% result.
    Those rules need footage of the fault before anything can be said.
    """
    MIN_POSITIVES = 2
    rows: list[tuple[float, str]] = []
    for clip, m in measured.items():
        label = labels.get(clip)
        if not label:
            continue
        key = rule_id.split(".", 1)[1]
        said = str(label.get("faults", {}).get(key, UNCLEAR)).lower()
        if said == UNCLEAR:
            continue
        values = [r["value"] for r in m["rules"].get(rule_id, [])
                  if r.get("value") is not None]
        if not values:
            continue
        # The clip fires if any rep fires, so the rep that decides the clip is
        # the most extreme one in the direction the rule tests.
        rows.append((max(values) if comparison.startswith(">") else min(values),
                     said))
    positives = sum(1 for _, said in rows if said == PRESENT)
    if len(rows) < 4 or positives < MIN_POSITIVES:
        return {"n": len(rows), "positives": positives, "bestThreshold": None,
                "bestAgreement": None,
                "why": (f"only {positives} labelled instance(s) of this fault - "
                        "on an all-clean sample the best threshold is whichever "
                        "one never fires, which is not a calibration")}

    values = sorted({v for v, _ in rows})
    cuts = [(a + b) / 2 for a, b in zip(values, values[1:])]
    cuts = cuts or [values[0]]

    def score_at(t: float) -> tuple[int, int, int, int]:
        """(agreements, caught, false alarms, missed) at one cut point."""
        hit = tp = fp = fn = 0
        for v, said in rows:
            fires = v > t if comparison.startswith(">") else v < t
            if (PRESENT if fires else ABSENT) == said:
                hit += 1
            if fires and said == PRESENT:
                tp += 1
            elif fires:
                fp += 1
            elif said == PRESENT:
                fn += 1
        return hit, tp, fp, fn

    # A threshold that catches none of the labelled faults is not a
    # calibration of the rule, it is the rule switched off - and on a corpus
    # this clean it scores extremely well, because staying quiet is right
    # about nine clips in ten. The first pass therefore only considers cuts
    # that still catch at least one real instance; the unconstrained best is
    # reported beside it so the trade is visible rather than hidden.
    best = best_live = None
    curve = []
    for t in cuts:
        hit, tp, fp, fn = score_at(t)
        acc = hit / len(rows)
        curve.append((round(t, 4), round(acc, 3)))
        if best is None or acc > best[0]:
            best = (acc, t, tp, fp, fn)
        if tp >= 1 and (best_live is None or acc > best_live[0]):
            best_live = (acc, t, tp, fp, fn)

    chosen = best_live or best
    acc, t, tp, fp, fn = chosen
    out = {
        "n": len(rows),
        "positives": sum(1 for _, s in rows if s == PRESENT),
        "bestThreshold": round(t, 4),
        "bestAgreement": round(acc, 3),
        # What the proposal actually does to the faults it exists to find.
        # Agreement alone hides this: on nine clips with two faults, "0.889"
        # is what you get for catching neither and staying quiet on the rest.
        "caught": tp, "falseAlarms": fp, "missed": fn,
        "curve": curve[:40],
    }
    if best_live is None:
        out["why"] = ("no threshold catches a single labelled instance - the "
                      "primitive does not separate these clips at all")
        out["bestThreshold"] = None
    elif best is not None and best[1] != t:
        out["unconstrainedBest"] = {
            "threshold": round(best[1], 4), "agreement": round(best[0], 3),
            "caught": best[2],
            "note": "scores higher by catching fewer faults",
        }
    return out


def coverage(measured: dict[str, dict]) -> dict:
    """Per rule, how often it could be evaluated at all - and why not.

    This half needs no labels, and it asks the question that has to be
    answered before agreement means anything: can the rule ever fire? A
    threshold that is never reached because the primitive behind it is refused
    on every clip is not a strict rule, it is a dead one, and its silence
    reads in every report as a clean lift.
    """
    rows: dict[str, dict] = {}
    for m in measured.values():
        for rule in RULES.get(m["movement"], []):
            reps = m["rules"].get(rule.id, [])
            row = rows.setdefault(rule.id, {
                "errorId": rule.id, "movement": rule.movement,
                "primitive": rule.primitive, "comparison": rule.comparison,
                "threshold": rule.threshold,
                "clips": 0, "judgeable": 0, "fired": 0,
                "values": [], "reasons": defaultdict(int)})
            row["clips"] += 1
            row["values"] += [float(r["value"]) for r in reps
                              if r.get("value") is not None]
            verdict = rule_verdict(reps)
            if verdict == UNCLEAR:
                for r in reps:
                    row["reasons"][r.get("reason") or "no reps segmented"] += 1
                if not reps:
                    row["reasons"]["no reps segmented"] += 1
                continue
            row["judgeable"] += 1
            if verdict == PRESENT:
                row["fired"] += 1
    for row in rows.values():
        row["reasons"] = dict(sorted(row["reasons"].items(),
                                     key=lambda kv: -kv[1]))
        # Where the threshold sits relative to what the primitive actually
        # measures. A threshold outside the observed range is not a strict
        # rule or a lenient one - it is a rule with no decision in it, and it
        # answers the same way on every clip forever. That is a different
        # defect from being miscalibrated by a few percent, and it is usually
        # a constant shared by movements whose geometry is not comparable:
        # `lockout_min` is right for a muscle-up, which ends in support above
        # the bar, and meaningless for a pull-up, which does not.
        v = sorted(row.pop("values"))
        row["observed"] = None
        if v:
            def q(p: float) -> float:
                return round(v[min(len(v) - 1, int(len(v) * p))], 3)
            lo, hi = q(0.02), q(0.98)
            t = float(row["threshold"])
            row["observed"] = {"n": len(v), "p02": lo, "median": q(0.5),
                               "p98": hi, "min": round(v[0], 3),
                               "max": round(v[-1], 3)}
            row["thresholdOutsideRange"] = bool(t < v[0] or t > v[-1])
        row["judgeableRate"] = round(row["judgeable"] / max(1, row["clips"]), 3)
        row["fireRate"] = (round(row["fired"] / row["judgeable"], 3)
                           if row["judgeable"] else None)
        row["dead"] = row["judgeable"] == 0
    return rows


def config_field(threshold: float) -> list[str]:
    """Which `barra.config.Thresholds` fields currently hold this value.

    A proposal that says "0.35 should be 0.485" is not yet actionable: the
    number in `rules.py` is derived from a named constant, sometimes scaled
    (a percentage rule reads `T.lockout_min * 100`). Matching the rule's
    resolved threshold back to the fields that could have produced it turns
    the proposal into an edit someone can make.

    One field often drives several rules, which is exactly why this is worth
    printing: retuning `lockout_min` for the pull-up silently retunes it
    everywhere else it is used, and that has to be a decision rather than a
    surprise.
    """
    import dataclasses  # noqa: PLC0415 - only needed when tuning

    from barra.config import THRESHOLDS  # noqa: PLC0415

    hits = []
    for f in dataclasses.fields(THRESHOLDS):
        v = getattr(THRESHOLDS, f.name)
        if not isinstance(v, (int, float)):
            continue
        for scale, how in ((1.0, ""), (100.0, " x100")):
            if abs(float(v) * scale - float(threshold)) < 1e-9:
                hits.append(f"{f.name}{how}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--movements", default="", help="comma-separated filter")
    ap.add_argument("--min-support", type=int, default=6)
    ap.add_argument("--min-reps", type=int, default=1,
                    help="clip-level fault needs this many observed reps "
                         "(production coaching uses 2 via THRESHOLDS.fault_min_reps)")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--redo", action="store_true", help="re-measure cached clips")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    warnings.simplefilter("ignore")
    want = {m.strip() for m in args.movements.split(",") if m.strip()}

    labels: dict[str, dict] = {}
    sources: dict[str, int] = {"model": 0, "human": 0}
    for directory, kind in ((FAULT_LABELS, "model"), (HUMAN_LABELS, "human")):
        if not directory.exists():
            continue
        for j in sorted(directory.rglob("*.json")):
            try:
                v = json.loads(j.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            f = v.get("file")
            if f and (not want or v.get("movement") in want):
                # Human second, so it overwrites the model's entry.
                if kind == "human" and Path(f).name in labels:
                    sources["model"] -= 1
                labels[Path(f).name] = v
                v.setdefault("source", kind)
                sources[kind] += 1
    if not labels:
        print(f"no fault labels in {FAULT_LABELS} or {HUMAN_LABELS} - run "
              "scripts/label_faults.py or scripts/label_reps.py",
              file=sys.stderr)
        return 1
    print(f"{len(labels)} clips carry a fault label "
          f"({sources['human']} human, {sources['model']} model)", flush=True)
    if sources["human"]:
        print("  human labels outrank the model's where both exist", flush=True)

    MEASURED.mkdir(parents=True, exist_ok=True)
    measured: dict[str, dict] = {}
    todo = [v for v in sorted(VIDEOS.rglob("*.mp4")) if v.name in labels]
    if args.limit:
        todo = todo[: args.limit]
    for i, video in enumerate(todo, 1):
        cache = MEASURED / f"{video.stem}.json"
        if cache.exists() and not args.redo:
            try:
                measured[video.name] = refresh_thresholds(
                    json.loads(cache.read_text()))
                continue
            except json.JSONDecodeError:
                pass
        started = time.time()
        try:
            row = measure_clip(video, video.parent.name)
        except LookupError as e:
            print(f"  [{i}/{len(todo)}] skip {video.name}: {e}", flush=True)
            continue
        except Exception as e:  # noqa: BLE001 - one bad clip is not the batch
            print(f"  [{i}/{len(todo)}] ERR {video.name}: "
                  f"{type(e).__name__} {str(e)[:120]}", flush=True)
            continue
        cache.write_text(json.dumps(row, indent=1))
        measured[video.name] = row
        print(f"  [{i}/{len(todo)}] {video.parent.name}/{video.name} "
              f"reps={row['nReps']} {time.time() - started:.0f}s", flush=True)

    # Coverage is computed over EVERY clip already measured, not just the
    # labelled ones: whether a rule can fire at all is a property of the
    # geometry and the footage, and waiting for labels to ask it would throw
    # away most of the evidence.
    all_measured: dict[str, dict] = dict(measured)
    for cached in sorted(MEASURED.glob("*.json")):
        try:
            row = refresh_thresholds(json.loads(cached.read_text()))
        except json.JSONDecodeError:
            continue
        if not want or row.get("movement") in want:
            all_measured.setdefault(row["clip"], row)
    cover = coverage(all_measured)
    dead = [r for r in cover.values() if r["dead"]]
    crying = [r for r in cover.values()
              if not r["dead"] and (r["fireRate"] or 0) >= 0.5]
    print(f"\ncoverage, over {len(all_measured)} measured clips "
          f"(needs no labels):")
    print(f"  {len(dead)}/{len(cover)} rules could not be evaluated on a "
          f"single clip - they can never fire")
    for r in sorted(dead, key=lambda r: r["errorId"]):
        why = next(iter(r["reasons"]), "unknown")
        print(f"      {r['errorId']:42s} {why}")
    print(f"  {len(crying)}/{len(cover)} fire on at least half the clips they "
          f"can judge, on a corpus of people demonstrating correct form:")
    for r in sorted(crying, key=lambda r: -(r["fireRate"] or 0))[:12]:
        print(f"      {r['errorId']:42s} fires {r['fireRate']:.0%} of "
              f"{r['judgeable']}")
    outside = [r for r in cover.values() if r.get("thresholdOutsideRange")]
    if outside:
        print(f"  {len(outside)}/{len(cover)} have a threshold OUTSIDE the "
              f"range the primitive ever measured - no decision in them:")
        for r in sorted(outside, key=lambda r: r["errorId"]):
            o = r["observed"]
            print(f"      {r['errorId']:42s} {r['comparison']} "
                  f"{r['threshold']:<8g} measured {o['min']} .. {o['max']} "
                  f"(median {o['median']})")

    table = compare(measured, labels, args.min_support, min_reps=args.min_reps)
    if args.tune:
        for rule_id, row in table.items():
            row["tuning"] = sweep(rule_id, measured, labels, row["comparison"])

    args.out.mkdir(parents=True, exist_ok=True)
    judged = [r for r in table.values() if r["verdict"] in ("MEASURED", "NO-POSITIVES")]
    overall = (sum(r["agree"] for r in judged) /
               max(1, sum(r["judged"] for r in judged)))
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clipsLabelled": len(labels), "clipsMeasured": len(measured),
        "labelSources": sources,
        "rules": len(table), "rulesMeasured": len(judged),
        "clipsCovered": len(all_measured),
        "minSupport": args.min_support,
        "minReps": args.min_reps,
        "overallAgreement": round(overall, 3),
        "perRule": dict(sorted(table.items())),
        "coverage": dict(sorted(cover.items())),
        "deadRules": sorted(r["errorId"] for r in dead),
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n{'rule':38s} {'agree':>7s} {'judged':>7s} {'pos':>4s} "
          f"{'fired':>6s} {'FA':>4s} {'miss':>5s} {'uncl':>5s}  verdict")
    for rule_id, row in sorted(table.items(),
                               key=lambda kv: (kv[1]["agreement"] is None,
                                               kv[1]["agreement"] or 0)):
        agree = ("  n/a" if row["agreement"] is None
                 else f"{row['agreement']:.3f}")
        print(f"{rule_id:38s} {agree:>7s} {row['judged']:7d} "
              f"{row['visionPresent']:4d} {row['ruleFired']:6d} "
              f"{row['falseAlarm']:4d} {row['missed']:5d} "
              f"{row['visionUnclear'] + row['ruleUnclear']:5d}  "
              f"{row['verdict']}")
    with_pos = [r for r in table.values() if r["verdict"] == "MEASURED"]
    fired = sum(r["ruleFired"] for r in judged)
    pos = sum(r["visionPresent"] for r in judged)
    seen = sum(r["judged"] for r in judged)
    print(f"\n{len(judged)}/{len(table)} rules have >= {args.min_support} "
          f"judgeable clips; overall agreement on those {overall:.3f}")
    print(f"{len(with_pos)} of them ever saw a labelled instance of their own "
          f"fault; the rest only measure false alarms.")
    print(f"base rate: the rules fired on {fired}/{seen} "
          f"({fired / max(1, seen):.1%}) judged clip-rules, where the "
          f"independent read saw a fault on {pos}/{seen} "
          f"({pos / max(1, seen):.1%}).")
    if args.tune:
        print("\nproposed thresholds (upper bound - picked and scored on the "
              "same clips):")
        for rule_id, row in sorted(table.items()):
            t = row.get("tuning")
            if not t or row["agreement"] is None or t.get("bestThreshold") is None:
                continue
            if t["bestAgreement"] > (row["agreement"] or 0) + 0.05:
                fields = config_field(row["threshold"])
                where = (", ".join(fields) if fields
                         else "no matching Thresholds field - set in rules.py")
                print(f"  {rule_id:38s} {row['threshold']:>9.3f} -> "
                      f"{t['bestThreshold']:>9.3f}   agreement "
                      f"{row['agreement']:.3f} -> {t['bestAgreement']:.3f} "
                      f"(n={t['n']}, {t['positives']} present)")
                print(f"      catches {t['caught']}/{t['positives']} labelled "
                      f"faults, {t['falseAlarms']} false alarms, "
                      f"{t['missed']} missed")
                print(f"      edit: barra/config.py Thresholds.{where}")
                t["configField"] = fields
    print(f"\nwrote {args.out}/report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
