#!/usr/bin/env python
"""Which uncertainty signal best predicts a wrong exercise label?

Uses the labelled calisthenics corpus (directory / adjudicated trick) and the
out-of-fold model answers in `out/classify-eval/per-clip.json`, re-running
geometry + `fuse_detection` so fusion status/confidence and geometry margin
are available.

    python scripts/uncertainty_eval.py
    python scripts/uncertainty_eval.py --per-clip out/classify-eval/per-clip.json

Writes `out/uncertainty-eval/report.json` with AUROC / AP rankings for each
signal against fusion(+vision) error — the production auto-detect path.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from barra.classify import classify  # noqa: E402
from barra.fusion import fuse_detection  # noqa: E402
from barra.uncertainty import rank_signals, signals_from_detectors  # noqa: E402
from classify_eval import (  # noqa: E402
    adjudicated,
    corpus,
    movement_label,
    verdicts,
    vision_labels,
)

SIGNAL_KEYS = [
    "model_inv_confidence",
    "model_inv_margin",
    "model_binary_entropy",
    "geometry_inv_confidence",
    "fusion_inv_confidence",
    "fusion_status_uncertainty",
    "risky_fusion_status",
    "vote_entropy",
    "n_unique_votes",
    "model_geometry_disagree",
    "model_vision_disagree",
    "geometry_vision_disagree",
    "any_pair_disagree",
    "fusion_abstain",
    "gate_margin_or_disagree",
]


def _geometry(kp, fps: float) -> dict:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            c = classify(kp, fps=fps)
        return {
            "exercise": c.exercise or "unknown",
            "confidence": float(getattr(c, "confidence", 0.0) or 0.0),
        }
    except Exception:  # noqa: BLE001
        return {"exercise": "unknown", "confidence": 0.0}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-clip", type=Path,
                    default=ROOT / "out" / "classify-eval" / "per-clip.json")
    ap.add_argument("--window", choices=("vision", "none"), default="vision")
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "uncertainty-eval")
    args = ap.parse_args()

    if not args.per_clip.exists():
        print(f"missing {args.per_clip} — run scripts/classify_eval.py first",
              file=sys.stderr)
        return 1

    predicted = json.loads(args.per_clip.read_text())
    rows = corpus(args.window, split_load=True)
    by_clip = {r["clip"]: r for r in rows}
    vision = vision_labels(verdicts(), split_load=True)
    settled = adjudicated()

    started = time.time()
    enriched: list[dict] = []
    skipped = 0
    for clip, p in predicted.items():
        if "model" not in p:
            skipped += 1
            continue
        row = by_clip.get(clip)
        if row is None:
            # Fall back: no windowed keypoints in this checkout — still score
            # model-only signals from the saved per-clip record.
            trick = settled.get(clip) or p.get("trick")
            if not trick:
                skipped += 1
                continue
            geom = {"exercise": p.get("geometry") or "unknown", "confidence": 0.0}
            fps = 30.0
            kp = None
        else:
            trick = row["trick"]
            kp, fps = row["kp"], row["fps"]
            geom = _geometry(kp, fps)

        learned = {
            "exercise": p["model"],
            "confidence": p.get("modelConfidence", 0.0),
            "marginToRunnerUp": p.get("modelMargin", 0.0),
        }
        vision_lab = vision.get(clip)
        fusion = fuse_detection(geom, learned, vision_lab)
        fusion_nov = fuse_detection(geom, learned, None)

        sig = signals_from_detectors(
            truth=trick,
            model=p["model"],
            model_confidence=p.get("modelConfidence"),
            model_margin=p.get("modelMargin"),
            geometry=geom["exercise"],
            geometry_confidence=geom["confidence"],
            vision=vision_lab,
            fusion=fusion,
            fusion_label=fusion.get("exercise"),
        )
        # Also score the no-vision fusion error (shipped when locate is late).
        f_nov = fusion_nov.get("exercise") or "unknown"
        t = movement_label(trick)
        sig["error_fusion_no_vision"] = (
            1.0 if (t and f_nov not in ("unknown", "") and t != f_nov)
            else (1.0 if f_nov in ("unknown", "") else 0.0)
        )
        # Prefer fusion-with-vision as the production error label.
        if "error_fusion" not in sig or sig["error_fusion"] != sig["error_fusion"]:
            got = fusion.get("exercise") or "unknown"
            sig["error_fusion"] = (
                1.0 if (t and got not in ("unknown", "") and t != got)
                else (1.0 if got in ("unknown", "") else 0.0)
            )

        enriched.append({
            "clip": clip,
            "trick": trick,
            "model": p["model"],
            "geometry": geom["exercise"],
            "vision": vision_lab,
            "fusion": fusion.get("exercise"),
            "fusionStatus": fusion.get("status"),
            "fusionNoVision": f_nov,
            "hadKeypoints": kp is not None,
            **sig,
        })

    ranking_vision = rank_signals(enriched, "error_fusion", SIGNAL_KEYS)
    ranking_nov = rank_signals(enriched, "error_fusion_no_vision", SIGNAL_KEYS)
    ranking_model = rank_signals(enriched, "error_model", SIGNAL_KEYS)

    n_err = sum(1 for r in enriched if r.get("error_fusion") == 1.0)
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clips": len(enriched),
        "skipped": skipped,
        "fusionWithVisionErrors": n_err,
        "fusionWithVisionAccuracy": round(
            1.0 - n_err / len(enriched), 4) if enriched else None,
        "predictErrorOf": {
            "fusionWithVision": ranking_vision,
            "fusionNoVision": ranking_nov,
            "modelAlone": ranking_model,
        },
        "winner": {
            "fusionWithVision": (ranking_vision[0]["signal"]
                                 if ranking_vision else None),
            "fusionNoVision": (ranking_nov[0]["signal"] if ranking_nov else None),
            "modelAlone": (ranking_model[0]["signal"] if ranking_model else None),
        },
        "runtimeS": round(time.time() - started, 1),
        "note": "Higher AUROC = better at ranking clips the fusion got wrong. "
                "bestGate is an F1-maximising threshold on that signal "
                "(recall ≥ 0.5) for a confirmation prompt.",
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.out / "per-clip.json").write_text(json.dumps(enriched, indent=2) + "\n")

    print(f"{len(enriched)} clips, fusion+vision errors "
          f"{n_err}/{len(enriched)}", flush=True)
    print("\nRanked signals → predict fusion+vision error (AUROC / AP):")
    for row in ranking_vision[:8]:
        gate = row.get("bestGate") or {}
        g = (f"  gate≥{gate.get('threshold')} "
             f"P={gate.get('precision')} R={gate.get('recall')}"
             if gate else "")
        print(f"  {row['signal']:28s}  AUC={row['auroc']}  AP={row['ap']}{g}")
    print(f"\nwrote {args.out}/report.json")
    return 0


if __name__ == "__main__":
    # Allow `from scripts.classify_eval import …` when run as a file.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
