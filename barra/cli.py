"""Command line interface.

Every command is idempotent, reads its inputs from out/ and writes its outputs
to out/. There is no hidden state and no in-memory handoff between commands: if
a stage's artefacts are on disk, the next stage can run.
"""
from __future__ import annotations

import argparse
import sys

from . import schema as S
from .config import PATHS
from .io_utils import MissingArtefact


def _banner(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m")


# ---------------------------------------------------------------------------
def cmd_status(args) -> int:
    from .pose import available_backends

    _banner("status")
    print(f"  root          {PATHS.root.resolve()}")
    print(f"  videos        {PATHS.videos}")
    vids = sorted(PATHS.videos.glob("*")) if PATHS.videos.exists() else []
    vids = [v for v in vids if v.suffix.lower() in
            {".mp4", ".mov", ".m4v", ".avi", ".mkv"}]
    print(f"                {len(vids)} video file(s)")
    be = available_backends()
    print(f"  pose backend  {', '.join(be) if be else 'NONE INSTALLED'}")
    if not be:
        print('                install one:  uv pip install -e ".[mediapipe]"')
    if (PATHS.out / "SYNTHETIC").exists():
        print("  ! out/ holds SYNTHETIC self-test data, not real measurements")

    print("\n  artefact                      state")
    checks = [
        ("out/reps.csv", PATHS.o(S.P_REPS), "ingest"),
        ("out/subject_anatomy.json", PATHS.o(S.P_ANATOMY), "normalise"),
        ("out/viewpoints.csv", PATHS.o(S.P_VIEWPOINTS), "viewpoints"),
        ("out/reference_reps.csv", PATHS.o(S.P_REFERENCE), "mark-reference"),
        ("out/scores.csv", PATHS.o(S.P_SCORES), "score"),
        ("out/labels.csv", PATHS.o(S.P_LABELS), "written by you"),
        ("out/validation.json", PATHS.o(S.P_VALIDATION), "validate"),
        ("out/report.html", PATHS.o(S.P_REPORT), "report"),
    ]
    for label, path, by in checks:
        print(f"  {label:<29} {'present' if path.exists() else f'missing (run: {by})'}")
    tmpl = sorted(PATHS.out.glob("template_*.parquet"))
    print(f"  templates                     "
          f"{', '.join(t.stem.replace('template_', '') for t in tmpl) or 'none (run: template)'}")
    return 0


def cmd_ingest(args) -> int:
    from .ingest import ingest
    from pathlib import Path

    _banner("ingest")
    ingest(args.backend, force=args.force,
           from_part_a=Path(args.from_part_a) if args.from_part_a else None,
           videos_dir=Path(args.dir) if args.dir else None)
    return 0


def cmd_normalise(args) -> int:
    from .normalise import run

    _banner("normalise (stage 1)")
    run(scale_mode=args.scale)
    return 0


def cmd_viewpoints(args) -> int:
    from .viewpoint import run

    _banner("viewpoints (stage 2)")
    run(true_shoulder_ratio=args.true_shoulder_ratio)
    return 0


def cmd_mark_reference(args) -> int:
    from .template import mark_reference

    _banner("mark-reference (stage 3)")
    mark_reference(args.video, args.rep_ids, replace=args.replace)
    return 0


def cmd_template(args) -> int:
    from . import null as null_mod
    from .template import load_reference, run

    _banner("template (stage 3)")
    built = run()
    _banner("null distribution (stage 5)")
    ref = set(load_reference()["rep_id"])
    for b in built:
        null_mod.build(b["bin"], ref)
    return 0


def cmd_score(args) -> int:
    from .score import run

    _banner("score (stages 4-5)")
    run(video=args.video, render_qc=not args.no_qc)
    return 0


def cmd_validate(args) -> int:
    from .validate import run

    _banner("validate (stage 6)")
    run()
    return 0


def cmd_report(args) -> int:
    from .report import run

    _banner("report")
    run()
    return 0


def cmd_remember(args) -> int:
    from pathlib import Path

    from .memory import remember

    _banner("remember - fold this run into the persistent profile")
    remember(videos_dir=Path(args.dir) if args.dir else None,
             backend=args.backend, note=args.note or "")
    return 0


def cmd_progress(args) -> int:
    import numpy as np

    from .memory import read_reps, status
    from .metrics import METRIC_SPEC
    from .progress import compare

    _banner("progress - across every session in the profile")
    reps = read_reps()
    if reps.empty:
        raise SystemExit(
            "the profile holds no reps yet - run `barra remember` after ingesting"
        )
    st = status()
    if not st["ledger"].empty and "bin" in st["ledger"].columns:
        cols = [c for c in ("video_sha", "bin", "side") if c in st["ledger"].columns]
        reps = reps.merge(st["ledger"][cols], on="video_sha", how="left")
    res = compare(reps)

    print(f"  {'session':<14}{'reps':>5}{'usable':>8}{'quality':>9}  viewpoint")
    for _, r in res["sessions"].iterrows():
        print(f"  {r['session_id']:<14}{r['n_reps']:>5}{r['n_usable']:>8}"
              f"{r['mean_quality']:>9.2f}  {r['bins']}")

    comps = res["comparisons"]
    if not comps.empty:
        print(f"\n  {'metric':<32}{'from':>9}{'to':>9}{'change':>10}"
              f"{'x noise':>9}  supported")
        for _, c in comps[comps["from"] != comps["to"]].iterrows():
            eff = f"{c['effect']:.1f}" if np.isfinite(c["effect"]) else "n/a"
            mark = "yes" if c["supported"] else "no"
            print(f"  {c['label'][:31]:<32}{c['from_value']:>9.3f}"
                  f"{c['to_value']:>9.3f}{c['change']:>+10.3f}{eff:>9}  {mark}")

    print("\n  reps per session needed to detect a 10% change:")
    for m, r in sorted(res["requirements"].items(),
                       key=lambda kv: (kv[1]["reps_per_session"]
                                       if np.isfinite(kv[1]["reps_per_session"])
                                       else 1e9)):
        n = r["reps_per_session"]
        n_s = f"{int(n)}" if np.isfinite(n) else "unknown (no spread yet)"
        print(f"    {r['label'][:34]:<36}{r['robustness']:<11}{n_s}")

    print(f"\n  {res['verdict']['statement']}")
    return 0


def cmd_explain(args) -> int:
    from pathlib import Path

    from .explain import explain, recent, replay

    if args.list:
        rows = recent(args.limit)
        if not rows:
            print("  no traces yet - run `barra explain <video>`")
            return 0
        print(f"  {'trace':<22}{'subject':<34}{'rej':>5}{'err':>5}{'ms':>7}")
        for r in rows:
            print(f"  {r['traceId']:<22}{r['subject'][:33]:<34}"
                  f"{r['rejections']:>5}{r['errors']:>5}{r['durationMs']:>7}")
        return 0
    if args.replay:
        replay(args.replay, show=args.show)
        return 0
    if not args.video:
        raise SystemExit("give a video path, --replay <id>, or --list")

    path = Path(args.video)
    if not path.exists():
        guess = PATHS.videos / args.video
        if guess.exists():
            path = guess
        else:
            raise SystemExit(f"no such clip: {args.video}")
    _banner(f"explain {path.name}")
    explain(path, exercise=args.exercise, show=args.show,
            write=not args.no_write, fresh=args.fresh)
    return 0


def cmd_validate_quality(args) -> int:
    """Is the quality score measuring anything? Run the four checks."""
    import csv
    from pathlib import Path

    from .validate_quality import FAIL, NOT_RUN, PASS, PROTOCOL, run

    if args.protocol:
        print(PROTOCOL)
        return 0

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "server"))
    from process import process_job  # noqa: E402

    # The manifest says which clips are repeats of one set and which were
    # filmed with a deliberate fault. Without it only the ceiling check can
    # run, which the report then says plainly rather than implying the rest
    # passed.
    manifest: dict[str, dict] = {}
    mpath = PATHS.videos / "validation.csv"
    if mpath.exists():
        with mpath.open() as fh:
            for row in csv.DictReader(fh):
                if row.get("video"):
                    manifest[row["video"].strip()] = row

    clips = sorted({p.stem: p for d in (PATHS.videos, root)
                    for p in d.glob("*.mp4")}.items())
    if args.only:
        clips = [(k, v) for k, v in clips if any(o in k for o in args.only)]
    if not clips:
        raise SystemExit("no clips found - put .mp4 files in data/videos/")

    analysed: dict[str, list] = {}
    for stem, path in clips:
        out = process_job({"id": f"qv-{stem}", "exercise": "auto"}, path)
        analysed[stem] = out.get("reps") or []
        scored = sum(1 for r in analysed[stem] if r.get("score") is not None)
        print(f"  {stem:<24} {scored:>3} scored reps")

    sets = [(k, v) for k, v in analysed.items() if v]
    pairs, degraded = [], {}
    by_pair: dict[str, list[str]] = {}
    for stem, row in manifest.items():
        if stem not in analysed:
            continue
        role = (row.get("role") or "").strip().lower()
        if role.startswith("degraded:"):
            degraded[role.split(":", 1)[1] or "unspecified"] = analysed[stem]
        elif row.get("pair"):
            by_pair.setdefault(row["pair"].strip(), []).append(stem)
    for name, members in by_pair.items():
        if len(members) >= 2:
            pairs.append((name, analysed[members[0]], analysed[members[1]]))

    print()
    _banner("does the quality score measure anything?")
    worst = PASS
    for check in run(sets, pairs, degraded):
        mark = {"PASS": "ok ", "FAIL": " x ", "INCONCLUSIVE": " ? ",
                "NOT RUN": " - "}[check.verdict]
        print(f"{mark}{check.name.upper():<14}{check.verdict}")
        for line in _wrap(check.detail, 68):
            print(f"      {line}")
        if check.advice:
            for line in _wrap(check.advice, 68):
                print(f"      -> {line}")
        print()
        if check.verdict == FAIL:
            worst = FAIL
        elif check.verdict != PASS and worst == PASS:
            worst = check.verdict

    if not pairs:
        print("  No reliability pair on record, so there is no noise floor and "
              "nothing below can be called real.\n  Run `barra validate-quality "
              "--protocol` for what to film.")
    return 1 if worst == FAIL else 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def cmd_technique(args) -> int:
    from .holds import SKILL as HOLD_SKILL
    from .techniques import all_techniques, render, technique

    docs = all_techniques()
    if not args.skill:
        if not docs:
            print("nothing documented yet: run scripts/scrape_techniques.py")
            return 1
        _banner("documented skills")
        for sid, t in docs.items():
            flag = "measured" if t.measurable else "map only"
            print(f"  {sid:28s} {t.name:32s} {len(t.cues):2d} cues "
                  f"{len(t.faults):2d} faults  [{flag}]")
        return 0
    sid = HOLD_SKILL.get(args.skill, args.skill)
    t = technique(sid)
    if t is None:
        print(f"nothing documented for {args.skill!r}. Documented: "
              f"{', '.join(sorted(docs)) or 'nothing'}")
        return 1
    print(render(t))
    return 0


def cmd_selftest(args) -> int:
    from .synthetic import generate

    _banner("selftest - SYNTHETIC data, exercises the pipeline, validates nothing")
    generate(seed=args.seed)
    return 0


def cmd_all(args) -> int:
    """Run the whole pipeline over artefacts already on disk."""
    from . import null as null_mod
    from .normalise import run as normalise
    from .report import run as report
    from .score import run as score
    from .template import load_reference, run as template
    from .validate import run as validate
    from .viewpoint import run as viewpoints

    _banner("normalise (stage 1)")
    normalise(scale_mode=args.scale)
    _banner("viewpoints (stage 2)")
    viewpoints(true_shoulder_ratio=args.true_shoulder_ratio)
    _banner("template (stage 3)")
    built = template()
    _banner("null distribution (stage 5)")
    ref = set(load_reference()["rep_id"])
    for b in built:
        null_mod.build(b["bin"], ref)
    _banner("score (stages 4-5)")
    score(video=None, render_qc=not args.no_qc)
    if PATHS.o(S.P_LABELS).exists():
        _banner("validate (stage 6)")
        try:
            validate()
        except SystemExit as e:
            print(f"  ! validation could not complete: {e}")
    else:
        print("\n  ! out/labels.csv absent - validation skipped, so nothing here "
              "has been shown to work")
    _banner("report")
    report()
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="barra",
        description="Does this rep deviate from the subject's own reference reps "
                    "by more than their own rep-to-rep variation?",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="what exists on disk and what is missing")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("ingest", help="pose extraction + rep segmentation")
    s.add_argument("dir", nargs="?", help="video directory (default data/videos)")
    s.add_argument("--backend", default="mediapipe",
                   help="pose backend: mediapipe | ultralytics")
    s.add_argument("--force", action="store_true", help="re-run pose on cached videos")
    s.add_argument("--from-part-a", help="load keypoint parquet from a Part A run")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("normalise", help="stage 1 - anatomy + normalised skeleton")
    s.add_argument("--scale", default="per_set", choices=["per_set", "per_frame"],
                   help="torso-length normalisation mode (see normalise.py)")
    s.set_defaults(func=cmd_normalise)

    s = sub.add_parser("viewpoints", help="stage 2 - azimuth estimate and binning")
    s.add_argument("--true-shoulder-ratio", type=float,
                   help="measured shoulder-width : torso-length, removes the "
                        "self-calibration guess")
    s.set_defaults(func=cmd_viewpoints)

    s = sub.add_parser("mark-reference", help="stage 3 - mark reference reps BY HAND")
    s.add_argument("video")
    s.add_argument("rep_ids", nargs="+",
                   help="rep indices (0 2 5), ranges (0-5), rep_ids, or 'all'")
    s.add_argument("--replace", action="store_true",
                   help="replace this video's existing marks instead of adding")
    s.set_defaults(func=cmd_mark_reference)

    s = sub.add_parser("template", help="stage 3+5 - DBA template and its null")
    s.set_defaults(func=cmd_template)

    s = sub.add_parser("score", help="stages 4-5 - deviation with its null percentile")
    s.add_argument("video", nargs="?", help="video stem; omit to score everything")
    s.add_argument("--no-qc", action="store_true", help="skip overlay videos")
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("validate", help="stage 6 - detection rate AND false positive rate")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("report", help="render out/report.html")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("explain",
                       help="why did it do that - the whole decision chain for one clip")
    s.add_argument("video", nargs="?", help="path to a clip, or a name in data/videos")
    s.add_argument("--exercise", default="auto",
                   help="force a movement instead of detecting it")
    s.add_argument("--show", default="decisions",
                   choices=["all", "decisions", "problems"],
                   help="all steps, just the choices (default), or only failures")
    s.add_argument("--replay", metavar="TRACE_ID",
                   help="print a trace written earlier, or copied off the server")
    s.add_argument("--list", action="store_true", help="list traces on disk")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--no-write", action="store_true", help="do not save the trace")
    s.add_argument("--fresh", action="store_true",
                   help="re-run pose estimation instead of reusing cached keypoints")
    s.set_defaults(func=cmd_explain)

    s = sub.add_parser("remember", help="fold this run into the persistent profile/")
    s.add_argument("dir", nargs="?", help="video directory (default data/videos)")
    s.add_argument("--backend", default="mediapipe", help="which backend produced the poses")
    s.add_argument("--note", help="free-text note stored with these records")
    s.set_defaults(func=cmd_remember)

    s = sub.add_parser("progress", help="compare sessions against within-session variation")
    s.set_defaults(func=cmd_progress)

    s = sub.add_parser("validate-quality",
                       help="is the quality score measuring anything?")
    s.add_argument("only", nargs="*", help="limit to clips matching these names")
    s.add_argument("--protocol", action="store_true",
                   help="print what to film, and why, then stop")
    s.set_defaults(func=cmd_validate_quality)

    s = sub.add_parser("technique",
                       help="what a movement is for: cues, faults and sources, quoted")
    s.add_argument("skill", nargs="?", help="a skill id (muscle_up, front_lever, ...) "
                                            "or a hold id; omit to list what is documented")
    s.set_defaults(func=cmd_technique)

    s = sub.add_parser("selftest", help="generate synthetic data and exercise the pipeline")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(func=cmd_selftest)

    s = sub.add_parser("all", help="run every stage after ingest")
    s.add_argument("--scale", default="per_set", choices=["per_set", "per_frame"])
    s.add_argument("--true-shoulder-ratio", type=float)
    s.add_argument("--no-qc", action="store_true")
    s.set_defaults(func=cmd_all)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except MissingArtefact as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 2
    except SystemExit as e:
        if isinstance(e.code, str):
            print(f"\nerror: {e.code}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
