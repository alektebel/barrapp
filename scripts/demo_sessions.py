#!/usr/bin/env python3
"""End to end on real clips: classify, describe the session, report the week.

Runs exactly what the server runs - no labels, no hints, the movement inferred
from the footage - and then folds the results into days and writes the weekly
report over them. It exists so the claim "the app result makes sense" can be
checked against the actual clips rather than taken on trust.

    python scripts/demo_sessions.py                 # every clip it can find
    python scripts/demo_sessions.py 0010 0012       # just these

Dates come from data/videos/sessions.csv when it names the clip. Classification
never does: that is the point.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

BAND_ORDER = ["broken down", "shaky", "solid", "strong", "unmeasured"]
FLOOR = 3
MIN_MEANINGFUL_DELTA = 8


def find_clips(only: list[str]) -> list[Path]:
    seen: dict[str, Path] = {}
    for d in (ROOT / "data" / "videos", ROOT):
        for p in sorted(d.glob("*.mp4")):
            seen.setdefault(p.stem, p)
    clips = [p for _, p in sorted(seen.items())]
    if only:
        clips = [p for p in clips if any(o in p.stem for o in only)]
    return clips


def dates() -> dict[str, str]:
    path = ROOT / "data" / "videos" / "sessions.csv"
    if not path.exists():
        return {}
    with path.open() as fh:
        return {r["video"]: r["session_id"] for r in csv.DictReader(fh)
                if r.get("video") and r.get("session_id")}


def fold(days: dict, date: str, out: dict) -> None:
    """One day is one training day: reps add up, and the score is the
    rep-weighted mean, so a one-rep clip cannot outvote a five-rep one. Same
    rule as SessionStore on the phone."""
    d = days.setdefault(date, {"date": date, "reps": 0, "weighted": 0,
                               "measured": 0, "labels": {}, "blank": 0})
    n = int(out.get("n_reps") or 0)
    scored = [r for r in (out.get("reps") or []) if r.get("score") is not None]
    d["reps"] += n
    if scored:
        d["weighted"] += sum(int(r["score"]) for r in scored)
        d["measured"] += len(scored)
        label = (out.get("detected") or {}).get("label") or out.get("exercise") or "?"
        d["labels"][label] = d["labels"].get(label, 0) + n
    else:
        d["blank"] += 1


def band_for(score):
    if score is None:
        return "unmeasured"
    return ("strong" if score >= 80 else "solid" if score >= 60
            else "shaky" if score >= 40 else "broken down")


def weekly(days: dict, since: str, until: str) -> str:
    """The same arithmetic as ReviewText on the phone, in Python, so the
    reasoning can be read next to the numbers it came from."""
    week = [d for d in days.values() if since <= d["date"] <= until]
    if not week:
        return "No sessions in this window."
    week.sort(key=lambda d: d["date"])
    for d in week:
        d["score"] = round(d["weighted"] / d["measured"]) if d["measured"] else None

    reps = sum(d["reps"] for d in week)
    comparable = sum(1 for d in week if d["reps"] >= FLOOR)
    measured = [d for d in week if d["score"] is not None]

    out = [f"{reps} rep{'' if reps == 1 else 's'} measured across "
           f"{len(week)} day{'' if len(week) == 1 else 's'}."]

    totals: dict[str, list] = {}
    for d in week:
        for label, n in d["labels"].items():
            t = totals.setdefault(label, [0, 0])
            t[0] += n
            t[1] += 1
    if totals:
        parts = [f"{label.lower()} ({n} rep{'' if n == 1 else 's'} over "
                 f"{days_}  day{'' if days_ == 1 else 's'})".replace("  ", " ")
                 for label, (n, days_) in sorted(totals.items(),
                                                 key=lambda kv: -kv[1][0])]
        out.append((parts[0].capitalize() + (
            " and " + parts[1] if len(parts) == 2 else
            ", " + ", ".join(parts[1:]) if len(parts) > 2 else "")) + ".")

    if comparable == 0:
        out.append(f"None reached {FLOOR} measured reps, so none can be compared "
                   "with another session yet.")
    elif comparable == 1:
        out.append(f"One session reached the {FLOOR}-rep floor. One more and there "
                   "is something to compare it against.")
    else:
        out.append(f"{comparable} sessions cleared the {FLOOR}-rep floor.")

    if len(measured) >= 2:
        delta = measured[-1]["score"] - measured[0]["score"]
        if abs(delta) < MIN_MEANINGFUL_DELTA:
            out.append("Scores held level within their own spread.")
        elif delta > 0:
            out.append(f"The baseline proxy is up {delta} points across the week, "
                       "which is worth a look but has not been tested against your "
                       "own rep-to-rep variation.")
        else:
            out.append(f"The baseline proxy is down {-delta} points across the week.")

    best = max((d for d in measured if d["reps"] >= FLOOR),
               key=lambda d: d["score"], default=None)
    if best:
        out.append(f"Best day was {best['date']} at {best['score']} "
                   f"({band_for(best['score'])}).")

    prior = [d for d in days.values() if d["date"] < since]
    before = sum(d["reps"] for d in prior)
    if before:
        out.append(f"Volume is {'up' if reps > before else 'down' if reps < before else 'level'} "
                   f"from {before} rep{'' if before == 1 else 's'} beforehand.")

    blank = sum(d["blank"] for d in week)
    if blank:
        out.append(f"{blank} clip{'' if blank == 1 else 's'} produced no measurable "
                   "reps - worth checking the framing on those.")
    return " ".join(out)


def main() -> int:
    from process import process_job

    clips = find_clips(sys.argv[1:])
    if not clips:
        print("no clips found - put .mp4 files in data/videos/")
        return 1
    known = dates()
    days: dict = {}

    for clip in clips:
        out = process_job({"id": f"demo-{clip.stem}", "exercise": "auto"}, clip)
        detected = out.get("detected") or {}
        print(f"\n{'=' * 74}\n{clip.name}")
        print(f"  detected : {detected.get('label') or '-'} "
              f"(confidence {detected.get('confidence')})")
        print(f"  because  : {detected.get('reason', '')[:200]}")
        print(f"  trace    : {out.get('traceId')}   "
              f"replay with: barra explain --replay {out.get('traceId')}")
        print(f"\n  {out.get('headline')}")
        for line in _wrap(out.get("narrative") or "", 70):
            print(f"    {line}")
        date = known.get(clip.stem)
        if date:
            fold(days, date, out)

    if days:
        print(f"\n{'=' * 74}\nWEEKLY REPORT")
        ordered = sorted(days)
        since = ordered[-1] if len(ordered) == 1 else _shift(ordered[-1], -6)
        print(f"  week of {since} to {ordered[-1]}\n")
        for line in _wrap(weekly(days, since, ordered[-1]), 70):
            print(f"    {line}")
        undated = [c.stem for c in clips if c.stem not in known]
        if undated:
            print(f"\n  ({len(undated)} clip(s) left out of the week: no date on file. "
                  "Add them to data/videos/sessions.csv to include them.)")
    return 0


def _shift(date: str, days_: int) -> str:
    from datetime import date as D, timedelta
    y, m, d = (int(x) for x in date.split("-"))
    return (D(y, m, d) + timedelta(days=days_)).isoformat()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
