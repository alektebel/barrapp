#!/usr/bin/env python3
"""Do the measured faults fire where they should, and stay quiet where they
should not?

The phone's coaching layer (Cues.kt, mirrored in barra/faults.py) names five
faults: momentum, lockout, dead hang, control, stall. Each is a threshold on
something measured, and every threshold is a claim: that a rep under it is
faulted and a rep over it is not. This harness is where that claim is checked
against clips someone actually watched.

The corpus is data/calisthenics/, and the labels live in
data/calisthenics/faults.csv - one row per clip:

    file,trick,expected,forbidden,observed,reps,note
    videos/muscle_up/youtube_x.mp4,muscle_up,;lockout,,,"kips into the bar"

`expected`  - `;`-separated faults that SHOULD fire on at least one rep.
`forbidden` - faults that must NOT fire anywhere in the clip.
`observed`  - what the last run measured; the reviewer moves entries from here
              into expected/forbidden, which is what makes the labels human.

The loop is: measure (--emit-candidates), watch the clips, label, re-run,
tune the threshold in faults.py AND Cues.kt together. A fault with no labelled
clips reports INCONCLUSIVE - an empty corpus cannot vindicate a threshold, and
pretending otherwise is the exact dishonesty the quality harness refuses.

Usage:
  python -m barra.validate_faults --emit-candidates       # measure + draft
  python -m barra.validate_faults                          # validate labels
  python -m barra.validate_faults --files a.mp4,b.mp4       # a subset
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra.faults import FAULT_NAMES, clip_fault_counts  # noqa: E402

MANIFEST = ROOT / "data" / "calisthenics" / "faults.csv"
FIELDNAMES = ["file", "trick", "expected", "forbidden", "observed", "reps", "note"]

# A clip whose pipeline produced no scored reps cannot confirm or deny
# anything: the faults are read off reps, and there are none to read.
MIN_REPS_TO_JUDGE = 1


def _ensure_pose_model() -> None:
    os.environ.setdefault(
        "BARRA_POSE_MODEL", str(ROOT / "models" / "pose_landmarker_heavy.task"))


def measure(video: Path, trick: str) -> tuple[dict[str, int], int]:
    """Run the full pipeline on one clip. Returns (fault counts, usable reps)."""
    _ensure_pose_model()
    from process import process_job

    payload = process_job({"id": f"faults_{video.stem}", "exercise": trick or "auto"},
                          video)
    reps = [r for r in payload.get("reps") or [] if r.get("plausible", True)]
    return clip_fault_counts(payload), len(reps)


def load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [r for r in csv.DictReader(f)]


def save_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def emit_candidates(files: list[tuple[Path, str]], out: Path, limit: int | None,
                    corpus: Path) -> None:
    """Measure every clip and write the draft manifest for human review."""
    rows = load_manifest(out)
    by_file = {r["file"]: r for r in rows}
    todo = files[:limit] if limit else files
    for i, (video, trick) in enumerate(todo):
        rel = str(video.relative_to(corpus))
        row = by_file.setdefault(rel, {"file": rel, "trick": trick,
                                       "expected": "", "forbidden": "",
                                       "observed": "", "reps": "", "note": ""})
        if row["expected"] or row["forbidden"]:
            print(f"[{i + 1}/{len(todo)}] {rel}: labeled, left as is")
            continue
        try:
            counts, reps = measure(video, trick)
        except Exception as exc:  # noqa: BLE001 - one bad clip must not kill the run
            print(f"[{i + 1}/{len(todo)}] {rel}: FAILED {type(exc).__name__}: {str(exc)[:120]}")
            continue
        row["trick"] = row["trick"] or trick
        row["observed"] = ";".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        row["reps"] = reps
        print(f"[{i + 1}/{len(todo)}] {rel}: {row['observed'] or 'clean'} ({reps} reps)")
    save_manifest(out, rows)
    print(f"\nmanifest -> {out}\nNext: watch the clips, move what you agree with into "
          "`expected` (or `forbidden`), then re-run without --emit-candidates.")


def validate(rows: list[dict], root: Path) -> int:
    """Check labels against measurement. Returns a process exit code."""
    tallies = {f: {"pos_labelled": 0, "fired": 0, "neg_labelled": 0, "false_fired": 0}
               for f in FAULT_NAMES}
    problems: list[str] = []

    for row in rows:
        expected = {x for x in (row.get("expected") or "").split(";") if x}
        forbidden = {x for x in (row.get("forbidden") or "").split(";") if x}
        if not expected and not forbidden:
            continue
        video = root / row["file"]
        if not video.exists():
            problems.append(f"{row['file']}: clip missing on disk")
            continue
        try:
            counts, reps = measure(video, row.get("trick") or "auto")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{row['file']}: pipeline failed ({type(exc).__name__})")
            continue
        fired = {f for f, n in counts.items() if n >= 1}
        if reps < MIN_REPS_TO_JUDGE:
            problems.append(f"{row['file']}: no usable reps, cannot judge")
            continue
        missed = expected - fired
        spurious = forbidden & fired
        for f in expected:
            tallies[f]["pos_labelled"] += 1
            tallies[f]["fired"] += 1 if f in fired else 0
        for f in forbidden:
            tallies[f]["neg_labelled"] += 1
            tallies[f]["false_fired"] += 1 if f in spurious else 0
        status = ("PASS" if not missed and not spurious
                  else f"MISS:{','.join(sorted(missed))}" if missed
                  else f"SPURIOUS:{','.join(sorted(spurious))}")
        print(f"{status:32s} {row['file']}  observed={counts or '{}'}")
        if missed:
            problems.append(f"{row['file']}: expected {sorted(missed)}, none fired")
        if spurious:
            problems.append(f"{row['file']}: forbidden {sorted(spurious)} fired")

    print("\n== per-fault ==")
    for f in FAULT_NAMES:
        t = tallies[f]
        if t["pos_labelled"] == 0 and t["neg_labelled"] == 0:
            print(f"{f:10s} INCONCLUSIVE - no clips labelled for it yet")
            continue
        recall = (f"{t['fired']}/{t['pos_labelled']}"
                  if t["pos_labelled"] else "no positives labelled")
        fpr = (f"{t['false_fired']}/{t['neg_labelled']}"
               if t["neg_labelled"] else "no negatives labelled")
        print(f"{f:10s} detected {recall:14s} false-fired {fpr}")

    if problems:
        print("\n== problems ==")
        for p in problems:
            print(f"  {p}")
        return 1
    print("\nAll labelled clips agree with their labels.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-candidates", action="store_true",
                    help="measure the corpus and draft the manifest")
    ap.add_argument("--tricks", default="",
                    help="restrict to these tricks (comma-separated)")
    ap.add_argument("--files", default="",
                    help="restrict to these files (comma-separated stems or paths)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--corpus", default=str(ROOT / "data" / "calisthenics"))
    a = ap.parse_args()

    corpus = Path(a.corpus)
    meta = corpus / "metadata.csv"
    if not meta.exists():
        raise SystemExit(f"no corpus ledger at {meta}")

    wanted = [s.strip() for s in a.tricks.split(",") if s.strip()]
    named = [s.strip() for s in a.files.split(",") if s.strip()]
    files: list[tuple[Path, str]] = []
    with open(meta) as f:
        for r in csv.DictReader(f):
            if wanted and r.get("trick") not in wanted:
                continue
            if named and not any(n in r["file"] for n in named):
                continue
            p = corpus / r["file"]
            if p.exists():
                files.append((p, r.get("trick") or "auto"))
    if not files:
        raise SystemExit("no clips matched")

    if a.emit_candidates:
        emit_candidates(files, Path(a.manifest), a.limit, corpus)
        return 0
    rows = load_manifest(Path(a.manifest))
    labelled = [r for r in rows if (r.get("expected") or r.get("forbidden"))]
    if not labelled:
        print("Nothing labelled yet. Run --emit-candidates, watch the clips, "
              "then fill `expected` / `forbidden`.")
        return 0
    return validate(labelled, corpus)


if __name__ == "__main__":
    raise SystemExit(main())
