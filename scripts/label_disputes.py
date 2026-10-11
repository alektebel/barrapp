#!/usr/bin/env python
"""Which corpus labels are disputed, and by what - for a human to settle.

Every accuracy this repo reports is measured against the directory a clip sits
in, and that directory is the search query a scraper used to find it. On this
corpus roughly one clip in eleven is filed wrong, and the clips' own
descriptions say so: eight `split_squat` clips described as "rear foot elevated
on a bench" (which is the definition of a bulgarian split squat), a pistol
squat under `handstand`, muscle-ups under `pull_up`. A detector that names
those correctly is marked wrong for it.

That noise is not evenly harmless. It sets a ceiling on every number - the
vision read scores 0.907 against the directory and 0.951 once eight of these
are corrected - and it is concentrated in exactly the neighbouring classes the
model already struggles to separate, so it lands on the hardest cases twice.

This script does NOT fix the labels. It cannot: the only reference allowed to
overrule the directory is a person who watched the clip, and a correction
proposed and accepted by the same detector being scored is the model marking
its own homework. What it does is narrow the work to the clips worth watching
and lay out the evidence for each:

  * the directory's label,
  * what the vision pass read off the frames,
  * what the out-of-fold pose model said, having never seen either,
  * and the clip's one-line description.

Fill in the `verdict` column - the movement actually performed - and
`classify_eval.py` reads it as truth from then on. Leave it blank and nothing
changes. A row where you agree with the directory is worth writing down too:
it records that the clip was watched and the filing was right.

Usage:
  python scripts/label_disputes.py                 # write the review sheet
  python scripts/label_disputes.py --all           # every clip, not just disputes
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import classify_eval as ce  # noqa: E402

PER_CLIP = ROOT / "out" / "classify-eval" / "per-clip.json"
FIELDS = ["clip", "directory", "vision", "model", "verdict", "reason",
          "description"]


def existing_rows(path) -> dict[str, dict]:
    """What the sheet already holds, keyed by clip name.

    This script rebuilds the sheet from the corpus every run, and used to
    carry only `verdict` across. Two things were therefore lost each time:
    the REASON a person gave for a correction, and every row for a clip that
    is not in the scraped corpus at all - which is exactly what
    `scripts/label_reps.py` writes when someone labels their own filmed clips.
    Both are human work and neither is recoverable, so both are preserved.
    """
    if not path.exists():
        return {}
    with path.open() as f:
        return {(r.get("clip") or "").strip(): r
                for r in csv.DictReader(f) if (r.get("clip") or "").strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ce.ADJUDICATED)
    ap.add_argument("--all", action="store_true",
                    help="include clips where every source already agrees")
    args = ap.parse_args()

    prior = existing_rows(args.out)
    verdicts = ce.verdicts()
    vision = ce.vision_labels(verdicts)
    settled = ce.adjudicated()
    model: dict[str, str] = {}
    if PER_CLIP.exists():
        for clip, row in json.loads(PER_CLIP.read_text()).items():
            if row.get("model"):
                model[clip] = row["model"]
    else:
        print(f"no {PER_CLIP} - run scripts/classify_eval.py first for the "
              "model column", file=sys.stderr)

    rows = []
    for video in sorted(ce.VIDEOS.rglob("*.mp4")):
        clip = video.name
        directory = video.parent.name
        seen = vision.get(clip, "")
        guess = model.get(clip, "")
        disputed = (seen and seen != directory) or (guess and guess != directory)
        if not disputed and not args.all:
            continue
        rows.append({
            "clip": clip,
            "directory": directory,
            "vision": seen,
            "model": guess,
            # An existing verdict is never overwritten - the sheet is a
            # worklist that survives being regenerated.
            "verdict": settled.get(clip, ""),
            "reason": (prior.get(clip, {}).get("reason") or ""),
            "description": (verdicts.get(clip, {}).get("description") or ""
                            ).replace("\n", " ")[:300],
        })

    # Rows the corpus knows nothing about - somebody's own filmed clips,
    # settled by hand - are carried through untouched rather than dropped.
    known = {r["clip"] for r in rows}
    kept = [r for clip, r in prior.items()
            if clip not in known and (r.get("verdict") or "").strip()]
    if kept:
        print(f"keeping {len(kept)} hand-settled row(s) that are not in the "
              "corpus")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows + kept:
            w.writerow({k: row.get(k, "") for k in FIELDS})

    both = [r for r in rows
            if r["vision"] and r["vision"] == r["model"]
            and r["vision"] != r["directory"]]
    done = sum(1 for r in rows if r["verdict"])
    print(f"{len(rows)} clips need a look, {done} already settled -> {args.out}")
    print(f"{len(both)} of them are ones where the vision read and the pose "
          f"model independently agree AGAINST the directory:")
    for r in both:
        print(f"   {r['directory']:24s} -> {r['vision']:24s} {r['clip']}")
    print("\nFill in `verdict` with the movement actually performed. "
          "classify_eval.py reads it as truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
