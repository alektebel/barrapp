"""Pipeline speed: per-clip wall time, analyze time, pose extraction time.

Report-only by design. CI runners share hardware, so a seconds-level
timing gate would block on load spikes rather than on real regressions;
what a human needs is the distribution and the slowest clips.

`wallS` is measured by the runner around the whole clip. `analyzeS` is
what server.process reported for the measurement itself
(_runtimeS.analyze). The gap between them is dominated by pose
extraction (in cached mode load_or_estimate runs before analyze_clip),
so it is reported as `poseS`, not as generic overhead.
"""
from __future__ import annotations

from statistics import median


def _pctl(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile; empty input is the caller's problem."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def timing_summary(records: list[dict]) -> dict:
    """Aggregate per-clip timing records into one reportable block.

    Each record: {clip, wallS, analyzeS?, poseSource?, error?}.
    Errored clips are reported as such, never silently dropped - a clip
    that always crashes also always takes zero seconds, and averaging
    that in would flatter the pipeline.
    """
    ok = [r for r in records if not r.get("error")]
    failed = [r for r in records if r.get("error")]
    walls = sorted(float(r["wallS"]) for r in ok)
    analyzes = sorted(float(r["analyzeS"]) for r in ok if r.get("analyzeS") is not None)
    pose_s = sorted(
        float(r["wallS"]) - float(r["analyzeS"])
        for r in ok if r.get("analyzeS") is not None)
    by_source: dict[str, dict] = {}
    for r in ok:
        src = r.get("poseSource") or "unknown"
        row = by_source.setdefault(src, {"clips": 0, "meanWallS": 0.0, "walls": []})
        row["clips"] += 1
        row["walls"].append(float(r["wallS"]))
    for row in by_source.values():
        row["meanWallS"] = round(sum(row.pop("walls")) / row["clips"], 3)

    slowest = sorted(ok, key=lambda r: -float(r["wallS"]))[:3]
    return {
        "clips": len(records),
        "okClips": len(ok),
        "failedClips": [{"clip": r["clip"], "error": r["error"]} for r in failed],
        "wallS": {
            "total": round(sum(walls), 3),
            "mean": round(sum(walls) / len(walls), 3) if walls else None,
            "median": round(median(walls), 3) if walls else None,
            "p95": round(_pctl(walls, 95), 3) if walls else None,
            "max": round(walls[-1], 3) if walls else None,
        },
        "analyzeS": {
            "mean": round(sum(analyzes) / len(analyzes), 3) if analyzes else None,
            "median": round(median(analyzes), 3) if analyzes else None,
            "max": round(analyzes[-1], 3) if analyzes else None,
        },
        "poseS": {
            "mean": round(sum(pose_s) / len(pose_s), 3) if pose_s else None,
            "max": round(pose_s[-1], 3) if pose_s else None,
            "note": "wall minus analyze: dominated by pose extraction "
                    "(load_or_estimate), plus trace and payload I/O",
        },
        "byPoseSource": by_source,
        "slowest": [{"clip": r["clip"], "wallS": round(r["wallS"], 3),
                     "poseSource": r.get("poseSource")} for r in slowest],
    }
