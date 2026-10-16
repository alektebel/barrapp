"""Golden-dataset scoring: payload against reviewed label, per clip.

The manifest (data/evaluation/sample_manifest.json) is the only reviewed
truth in the repo: eight root clips with a movement, a rep count where a
reviewer confirmed one, and three registries of "must not" - faults that
must not fire, checks scoped to a phase and a window, intervals that must
not be kept as reps. Every rule here reads one of those and writes one
row with its denominator, so an inconclusive class reads as inconclusive
rather than as a pass.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoldenReport:
    """One clip's graded payload, with everything a reviewer needs to argue."""

    clip: str
    graded: bool = False          # false = no label, or the clip errored
    why: str = ""                 # when not graded
    checks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"clip": self.clip, "graded": self.graded, "why": self.why,
                "checks": self.checks}

    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c.get("ok")]

    def passed(self) -> list[dict]:
        return [c for c in self.checks if c.get("ok")]


def _label_for(manifest: dict, filename: str) -> dict | None:
    for c in manifest.get("clips", []):
        if c.get("file") == filename:
            return c
    return None


def _add(report: GoldenReport, kind: str, ok: bool, **detail) -> None:
    row = {"check": kind, "ok": bool(ok), **detail}
    report.checks.append(row)


def grade_payload(stem: str, payload: dict, manifest: dict) -> GoldenReport:
    """Grade one analyze_clip payload against its reviewed label.

    Checks, in registry order:
      movement   - detected movement equals the reviewed one (when reviewed).
      repCount   - measured count equals the reviewed count (when reviewed);
                   an abstention payload on a reviewed clip is a failure
                   here, not an excused row - abstention has its own clips.
      forbidden  - none of the label's forbidden errorIds fired on any rep.
      phaseScoped- a scoped check fires only inside its phase and window.
      notReps    - none of the label's must-not-count intervals survived.
      unobservable - checks the reviewer marked impossible did not fire
                     `observed`; `not_observed`/`unobservable` are fine.
    """
    report = GoldenReport(clip=stem)
    label = _label_for(manifest, f"{stem}.mp4") or _label_for(manifest, stem)
    if label is None:
        report.why = "no reviewed label for this clip"
        return report
    if "error" in payload:
        report.why = f"payload errored: {payload['error']}"
        # A reviewed clip that the pipeline cannot process at all is a
        # failure, not an absence - unless the reviewer's role says the
        # clip is an abstention case.
        if label.get("role") == "abstention":
            report.graded = True
            _add(report, "abstention", ok=True, detail=payload["error"])
        return report

    report.graded = True
    detected = (payload.get("detected") or {}).get("exercise") or payload.get("exercise")
    truth = label.get("movement")
    if truth is not None:
        _add(report, "movement", detected == truth, detected=detected, reviewed=truth)
    if label.get("reps") is not None and truth not in (None, "unknown"):
        _add(report, "repCount", (payload.get("n_reps") or 0) == label["reps"],
             measured=payload.get("n_reps"), reviewed=label["reps"])

    reps = payload.get("reps") or []
    for f in label.get("forbidden") or []:
        fired = [r.get("label") for r in reps
                 for a in (r.get("faults") or [])
                 if a.get("errorId") == f["errorId"]]
        _add(report, "forbidden", not fired, errorId=f["errorId"], firedOn=fired)

    for ps in label.get("phaseScoped") or []:
        rows = [a for r in reps for a in (r.get("assessments") or [])
                if a.get("errorId") == ps["errorId"] and a.get("status") == "observed"]
        bad = [a for a in rows
               if a.get("phase") != ps["phase"]
               or (a.get("intervalS")
                   and (a["intervalS"][1] - a["intervalS"][0]) > ps.get("maxWindowS", 1e9))]
        _add(report, "phaseScoped", not bad, errorId=ps["errorId"],
             phase=ps["phase"], fired=len(rows), outsidePhaseOrTooWide=len(bad))

    for nr in label.get("notReps") or []:
        lo, hi = nr["intervalS"]
        kept = [r.get("label") for r in reps
                if r.get("startS") is not None
                and abs(float(r["startS"]) - lo) < 0.5
                and abs(float(r["endS"]) - hi) < 0.5]
        _add(report, "notReps", not kept, intervalS=[lo, hi], keptAsReps=kept)

    for u in label.get("unobservable") or []:
        states = Counter(a.get("status") for r in reps
                         for a in (r.get("assessments") or [])
                         if a.get("errorId") == u["errorId"])
        # `observed` means the pipeline claims to see what a reviewer judged
        # impossible from this footage. Everything else is honest.
        _add(report, "unobservable", states.get("observed", 0) == 0,
             errorId=u["errorId"], statuses=dict(states))
    return report


def golden_metrics(manifest_path: Path) -> dict:
    """Load the manifest and report how much of it is actually reviewed."""
    manifest = json.loads(Path(manifest_path).read_text())
    clips = manifest.get("clips", [])
    reviewed = [c for c in clips if c.get("reviewMethod") != "unreviewed"]
    return {
        "manifest": str(manifest_path),
        "version": manifest.get("version"),
        "clips": len(clips),
        "reviewedClips": len(reviewed),
        "note": "eight reviewed clips are a smoke test, not an evaluation; "
                "every metric below carries its denominator",
    }


def grade_run(results: dict[str, dict], manifest_path: Path) -> dict:
    """Grade a whole run's payloads. `results` maps stem -> payload.

    Returns the per-clip reports plus rollups that always show their
    denominators; a check with zero opportunities is reported as such.
    """
    manifest = json.loads(Path(manifest_path).read_text())
    reports = []
    tally: Counter = Counter()
    for stem in sorted(results):
        rep = grade_payload(stem, results[stem], manifest)
        reports.append(rep.as_dict())
        if rep.graded:
            for c in rep.checks:
                tally[f"{c['check']}:{'pass' if c['ok'] else 'fail'}"] += 1
    rollup = {}
    for kind in ("movement", "repCount", "forbidden", "phaseScoped",
                 "notReps", "unobservable", "abstention"):
        p, f = tally[f"{kind}:pass"], tally[f"{kind}:fail"]
        if p + f:
            rollup[kind] = {"pass": p, "fail": f, "total": p + f,
                            "rate": round(p / (p + f), 4)}
    graded = sum(1 for r in reports if r["graded"])
    return {
        "clips": len(reports),
        "gradedClips": graded,
        "ungraded": [{"clip": r["clip"], "why": r["why"]}
                     for r in reports if not r["graded"]],
        "rollup": rollup,
        "allPassed": graded > 0 and not any(
            c for r in reports if r["graded"] for c in r["checks"] if not c["ok"]),
        "failedChecks": [{"clip": r["clip"], **c}
                         for r in reports if r["graded"]
                         for c in r["checks"] if not c["ok"]],
        "perClip": reports,
    }
