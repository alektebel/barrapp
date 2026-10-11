#!/usr/bin/env python
"""Compare classifier variants on one cached feature table.

`classify_eval.py` answers "how good is the pipeline right now" and writes a
report. This answers a different question - "which of these changes helps" -
and the difference that matters is cost. Featurising the corpus dominates a run
(pose is already cached, but the kinematics are recomputed for every augmented
view of every clip), so a sweep that re-featurises per variant spends all its
time re-deriving numbers that did not change, and the temptation is then to
compare two variants on one seed and believe the gap.

So the feature table is built once and cached, keyed by everything that would
change it, and each variant is a cheap re-train over the same matrix. That buys
the thing a small corpus actually needs: every variant scored over several
seeds, with the spread reported next to the mean, because on 199 clips a
1-point difference between two single runs is noise wearing a result's clothes.

Usage:
  python scripts/classify_sweep.py --list                 # the built-in variants
  python scripts/classify_sweep.py --seeds 3
  python scripts/classify_sweep.py --only baseline,adam
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import classify_eval as ce  # noqa: E402
from barra.model import train_classifier  # noqa: E402
from barra.posecache import cache_path  # noqa: E402

CACHE = ROOT / "out" / "sweep-cache"

# Each variant is the keyword arguments one training run is given. They are
# named so a result can be quoted ("adam beats sgd by 9 points") without
# anyone having to reconstruct which knobs were turned.
VARIANTS: dict[str, dict] = {
    "baseline-sgd":  {"optimizer": "sgd",  "lr": 0.08, "epochs": 600, "hidden": 48, "l2": 1e-3},
    "adam":          {"optimizer": "adam", "lr": 0.01, "epochs": 600, "hidden": 48, "l2": 1e-3},
    "adam-wide":     {"optimizer": "adam", "lr": 0.01, "epochs": 600, "hidden": 96, "l2": 1e-3},
    "adam-wide-reg": {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 96, "l2": 5e-3},
    "adam-narrow":   {"optimizer": "adam", "lr": 0.01, "epochs": 600, "hidden": 24, "l2": 1e-3},
    "adam-heavy-reg": {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 48, "l2": 5e-2},
    "adam-tiny":     {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 12, "l2": 1e-2},
    "l2-1e-2":       {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 48, "l2": 1e-2},
    "l2-2e-2":       {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 48, "l2": 2e-2},
    "l2-5e-2-w96":   {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 96, "l2": 5e-2},
    "l2-1e-1":       {"optimizer": "adam", "lr": 0.01, "epochs": 800, "hidden": 48, "l2": 1e-1},
    "l2-2e-1":       {"optimizer": "adam", "lr": 0.01, "epochs": 1200, "hidden": 48, "l2": 2e-1},
    "adam-long":     {"optimizer": "adam", "lr": 0.01, "epochs": 1500, "hidden": 96, "l2": 5e-3},
}


def fingerprint(window: str, augment: int, seed: int, features: str = "flat") -> str:
    """Everything that decides the feature table, including the corpus itself.

    A cache that ignores which clips exist is worse than no cache: pose another
    twenty videos and the sweep silently keeps scoring the old corpus.
    """
    parts = [window, str(augment), str(seed), features]
    for video in sorted(ce.VIDEOS.rglob("*.mp4")):
        kp = cache_path(video)
        stamp = kp.stat().st_mtime_ns if kp.exists() else 0
        parts.append(f"{video.name}:{stamp}")
    # The labels only reach the feature table through the technique window, so
    # they belong in the key only when a window is being applied. Including
    # them unconditionally meant every sweep run during a labelling batch
    # re-featurised the whole corpus to arrive at exactly the same matrix.
    if window == "vision":
        for sidecar in sorted(
                (ROOT / "data" / "calisthenics" / "labels").rglob("*.json")):
            parts.append(f"{sidecar.name}:{sidecar.stat().st_mtime_ns}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def feature_table(window: str, augment: int, seed: int, features: str = "flat") -> tuple:
    """(X, names, y, owner, original), cached on disk by fingerprint."""
    key = fingerprint(window, augment, seed, features)
    path = CACHE / f"{key}.npz"
    if path.exists():
        z = np.load(path, allow_pickle=True)
        print(f"feature table from cache ({path.name})", flush=True)
        return (z["X"], list(z["names"]), list(z["y"]), list(z["owner"]),
                z["original"])
    rows = ce.corpus(window)
    print(f"featurising {len(rows)} clips x {augment} views", flush=True)
    started = time.time()
    X, names, y, owner, original = ce.feature_table(rows, augment, seed, features)
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, X=X, names=np.array(names), y=np.array(y),
                        owner=np.array(owner), original=original)
    print(f"  {X.shape[0]} rows x {X.shape[1]} features "
          f"in {time.time() - started:.0f}s", flush=True)
    return X, names, y, owner, original


def score(X, names, y, owner, original, folds: int, seed: int,
          ensemble: int, **hp) -> tuple[float, list[tuple[str, str]]]:
    """Out-of-fold accuracy for one variant at one seed."""
    assignment = ce.folds_by_clip(owner, y, folds, seed)
    fold_of = np.array([assignment[c] for c in owner])
    pairs: list[tuple[str, str]] = []
    for k in range(folds):
        train = fold_of != k
        test = (fold_of == k) & original
        if not train.any() or not test.any():
            continue
        y_train = [y[i] for i in np.where(train)[0]]
        proba, classes = None, []
        for m in range(max(1, ensemble)):
            model = train_classifier(X[train], y_train, seed=seed + 101 * m,
                                     feature_names=names, **hp)
            p = model.predict_proba(X[test])
            classes = model.classes
            proba = p if proba is None else proba + p
        got = [classes[i] for i in np.argmax(proba, axis=1)]
        pairs += [(y[row], g) for row, g in zip(np.where(test)[0], got)]
    acc = sum(1 for t, g in pairs if t == g) / max(1, len(pairs))
    return acc, pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", choices=("vision", "none"), default="vision")
    ap.add_argument("--augment", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--ensemble", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated variant names")
    ap.add_argument("--features", choices=("flat", "phased"), default="flat")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "classify-sweep.json")
    args = ap.parse_args()

    if args.list:
        for name, hp in VARIANTS.items():
            print(f"{name:16s} {hp}")
        return 0

    want = [w.strip() for w in args.only.split(",") if w.strip()] or list(VARIANTS)
    unknown = [w for w in want if w not in VARIANTS]
    if unknown:
        print(f"unknown variants: {unknown}", file=sys.stderr)
        return 1

    warnings.simplefilter("ignore")
    X, names, y, owner, original = feature_table(args.window, args.augment, 0, args.features)
    print(f"{len(set(owner))} clips, {len(set(y))} classes, "
          f"{X.shape[0]} rows, {X.shape[1]} features\n", flush=True)

    results = {}
    for name in want:
        hp = VARIANTS[name]
        accs, best_pairs = [], None
        started = time.time()
        for s in range(args.seeds):
            acc, pairs = score(X, names, y, owner, original, args.folds, s,
                               args.ensemble, **hp)
            accs.append(acc)
            if best_pairs is None:
                best_pairs = pairs
        mean, sd = float(np.mean(accs)), float(np.std(accs))
        results[name] = {"mean": round(mean, 4), "sd": round(sd, 4),
                         "runs": [round(a, 4) for a in accs],
                         "hyperparameters": hp,
                         "perClass": ce.per_class(best_pairs),
                         "runtimeS": round(time.time() - started, 1)}
        print(f"{name:16s} {mean:.3f} +/- {sd:.3f}   "
              f"({', '.join(f'{a:.3f}' for a in accs)})  "
              f"{results[name]['runtimeS']}s", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(
        {"window": args.window, "augment": args.augment, "folds": args.folds,
         "seeds": args.seeds, "ensemble": args.ensemble,
         "clips": len(set(owner)), "classes": sorted(set(y)),
         "results": results}, indent=2) + "\n")
    ranked = sorted(results.items(), key=lambda kv: -kv[1]["mean"])
    print(f"\nbest: {ranked[0][0]} at {ranked[0][1]['mean']:.3f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
