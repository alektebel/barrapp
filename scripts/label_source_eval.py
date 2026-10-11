#!/usr/bin/env python
"""Is the pose model wrong, or are its labels wrong?

The corpus label is the folder a scraper dropped the clip into, chosen by the
search query that found it. An independent multimodal read of the pixels
disagrees with that folder on about one clip in eight. So a pose model trained
on folders is fitting some fraction of noise, and - worse - is then scored
against that same noise, which penalises it twice for one error it did not
make.

This runs the eval's own protocol unchanged (same folds, same augmentation,
same clip-grouped splits) over three label sources:

  folder   - what the scraper said, the current baseline
  vision   - the multimodal verdict where it has one, folder otherwise
  agreed   - only clips where the two independently agree; the cleanest
             benchmark available, and the honest read of what the features can
             do when the target is not noise

Reported side by side, because the interesting number is not any one of them
but the gap between them.
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path("/home/diego/Documents/Development/barrapp")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import classify_eval as ce  # noqa: E402
from barra.model import train_classifier  # noqa: E402

SIDECARS = Path(__file__).with_name("ds") / "labels"

AUGMENT, FOLDS, SEED = 4, 4, 0
HIDDEN, L2, EPOCHS, LR, ENSEMBLE = 48, 1e-3, 600, 0.08, 3


def sidecar_map() -> dict[str, dict]:
    """clip filename -> the multimodal verdict for it."""
    out: dict[str, dict] = {}
    for j in SIDECARS.rglob("*.json"):
        try:
            v = json.loads(j.read_text())
        except Exception:  # noqa: BLE001 - a half-written sidecar is not a label
            continue
        f = v.get("file")
        if f:
            out[Path(f).name] = v
    return out


def run(rows: list[dict], tag: str) -> tuple[float, dict]:
    """The eval's own k-fold protocol, on whatever labels `rows` carry."""
    X, names, y, owner, original = ce.feature_table(rows, AUGMENT, SEED)
    assignment = ce.folds_by_clip(owner, y, FOLDS, SEED)
    fold_of = np.array([assignment[c] for c in owner])

    pairs: list[tuple[str, str]] = []
    for k in range(FOLDS):
        train = fold_of != k
        test = (fold_of == k) & original
        if not train.any() or not test.any():
            continue
        y_train = [y[i] for i in np.where(train)[0]]
        proba, classes = None, []
        for m in range(ENSEMBLE):
            model = train_classifier(X[train], y_train, seed=SEED + 101 * m,
                                     epochs=EPOCHS, lr=LR, feature_names=names,
                                     hidden=HIDDEN, l2=L2)
            p = model.predict_proba(X[test])
            classes = model.classes
            proba = p if proba is None else proba + p
        got = [classes[i] for i in np.argmax(proba, axis=1)]
        for row, g in zip(np.where(test)[0], got):
            pairs.append((y[row], g))

    acc = sum(1 for t, g in pairs if t == g) / max(1, len(pairs))
    print(f"{tag:34s} {sum(1 for t, g in pairs if t == g):3d}/{len(pairs):3d} "
          f"= {acc:.3f}   ({len(set(t for t, _ in pairs))} classes)", flush=True)
    return acc, ce.per_class(pairs)


def main() -> int:
    warnings.simplefilter("ignore")
    base = ce.corpus("none")
    sc = sidecar_map()
    print(f"{len(base)} clips with keypoints, {len(sc)} with a vision verdict\n")

    folder = [dict(r) for r in base]

    vision = []
    for r in base:
        v = sc.get(r["clip"])
        got = (v or {}).get("detected_trick", "")
        row = dict(r)
        if got and got != "none":
            row["trick"] = got
        vision.append(row)

    agreed = []
    for r in base:
        v = sc.get(r["clip"])
        if v and v.get("detected_trick") == r["trick"]:
            agreed.append(dict(r))

    print(f"agreed subset: {len(agreed)} clips "
          f"({Counter(r['trick'] for r in agreed).most_common(3)})\n")

    results = {}
    results["folder"] = run(folder, "folder labels (baseline)")
    results["vision"] = run(vision, "vision labels where available")
    if len(agreed) >= 40:
        results["agreed"] = run(agreed, "vision-agreed clips only")

    print("\n=== per class, vision-agreed ===" if "agreed" in results else "")
    if "agreed" in results:
        for k, v in sorted(results["agreed"][1].items(),
                           key=lambda x: x[1]["recall"]):
            print(f"  {k:24s} {v['correct']:3d}/{v['support']:3d}  {v['recall']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
