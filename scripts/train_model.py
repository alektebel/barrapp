#!/usr/bin/env python
"""Train the shipped exercise classifier - on exactly what the eval measures.

This used to build its own corpus and its own feature vector, and both had
drifted from `scripts/classify_eval.py`:

  * it read `metadata.csv` for the clip list, which had stopped covering the
    corpus, and capped each class at twelve clips;
  * it featurised with `barra.classify.features` - the 36 names the geometric
    thresholds need - while the eval had moved to the 106-name kinematic
    vector;
  * it never applied the vision technique windows, so it trained on whole
    tutorial videos including the talking-head half;
  * and it never augmented, so it saw one view per clip.

The result was a shipped model that knew seven classes out of seventeen, read
a third of the features the measured model reads, and had no relationship to
any number this repo published. A model that is not the thing that was
measured cannot inherit the measurement.

So the corpus, the windows, the features and the fold discipline all come from
`classify_eval` now, and the only thing this script adds is what the eval
deliberately does not do: fit a model on ALL the clips and write it to
`models/`. The metrics it reports come from the held-out folds, never from the
shipped fit - a model scored on its own training data reports 1.00 and means
nothing.

Usage:
  python scripts/train_model.py
  python scripts/train_model.py --window none --augment 1
  python scripts/train_model.py --out models/exercise_model.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import classify_eval as ce  # noqa: E402
from barra.model import train_classifier, train_load  # noqa: E402

DEFAULT_OUT = ROOT / "models" / "exercise_model.npz"


def holdout_metrics(X, names, y, owner, original, folds: int, seed: int,
                    **hp) -> dict:
    """Per-class precision/recall/f1 from clips no fold trained on.

    Folds are assigned by clip, so every augmented view of a clip is on the
    same side of the split as the clip it came from; scoring is on original
    views only.
    """
    assignment = ce.folds_by_clip(owner, y, folds, seed)
    fold_of = np.array([assignment[c] for c in owner])
    pairs: list[tuple[str, str]] = []
    for k in range(folds):
        train = fold_of != k
        test = (fold_of == k) & original
        if not train.any() or not test.any():
            continue
        model = train_classifier(X[train], [y[i] for i in np.where(train)[0]],
                                 seed=seed, feature_names=names, **hp)
        got, _, _ = model.predict(X[test])
        pairs += [(y[i], g) for i, g in zip(np.where(test)[0], got)]

    confusion: dict[str, Counter] = {}
    for truth, pred in pairs:
        confusion.setdefault(truth, Counter())[pred] += 1
    per_class = {}
    for truth, row in confusion.items():
        tp = row.get(truth, 0)
        fn = sum(row.values()) - tp
        fp = sum(c.get(truth, 0) for t, c in confusion.items() if t != truth)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
        per_class[truth] = {"support": tp + fn, "precision": prec,
                            "recall": rec, "f1": f1, "predicted": dict(row)}
    correct = sum(1 for t, g in pairs if t == g)
    return {"nScored": len(pairs),
            "accuracy": round(correct / max(1, len(pairs)), 3),
            "perClass": per_class,
            "confusion": {k: dict(v) for k, v in confusion.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", choices=("vision", "none"), default="vision")
    ap.add_argument("--augment", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=800)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--hidden", type=int, default=48)
    ap.add_argument("--l2", type=float, default=5e-2)
    ap.add_argument("--optimizer", default="adam", choices=("adam", "sgd"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    warnings.simplefilter("ignore")
    t0 = time.monotonic()
    hp = {"epochs": args.epochs, "lr": args.lr, "hidden": args.hidden,
          "l2": args.l2, "optimizer": args.optimizer}

    rows = ce.corpus(args.window)
    if not rows:
        print("no clips with cached keypoints - run scripts/extract_keypoints.py",
              file=sys.stderr)
        return 1
    X, names, y, owner, original = ce.feature_table(rows, args.augment, args.seed)
    print(f"{len(rows)} clips, {len(set(y))} classes, {X.shape[0]} rows, "
          f"{X.shape[1]} features\n{dict(Counter(r['trick'] for r in rows))}\n",
          flush=True)

    metrics = holdout_metrics(X, names, y, owner, original, args.folds,
                              args.seed, **hp)
    print(f"held-out accuracy {metrics['accuracy']} "
          f"over {metrics['nScored']} clips", flush=True)

    # The shipped fit sees every clip. Its quality is the held-out number
    # above - this fit has no honest score of its own and is not given one.
    model = train_classifier(X, y, seed=args.seed, feature_names=names, **hp)
    load_w, load_b, load_note = train_load(X, None)
    model.load_w, model.load_b, model.load_note = load_w, load_b, load_note
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model.save(args.out)

    report = {
        "version": model.version,
        "classes": model.classes,
        "features": len(names),
        "clips": len(rows),
        "window": args.window,
        "augment": args.augment,
        "hyperparameters": hp,
        "heldOut": metrics,
        "shippedFit": "trained on all clips; its accuracy is the held-out "
                      "number, not a score of its own",
        "load": {"note": load_note},
        "runtimeS": round(time.monotonic() - t0, 2),
    }
    (args.out.parent / "model_metrics.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n")

    for c, m in sorted(metrics["perClass"].items(),
                       key=lambda kv: (kv[1]["recall"] is None,
                                       kv[1]["recall"] or 0)):
        f1 = "n/a" if m["f1"] is None else f"{m['f1']:.2f}"
        print(f"  {c:26s} f1={f1:>5s} support={m['support']}")
    print(f"\nmodel   -> {args.out}")
    print(f"metrics -> {args.out.parent / 'model_metrics.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
