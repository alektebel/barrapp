#!/usr/bin/env python
"""Train the first exercise-type classification model (and the load head).

Extracts clip-level features (barra/classify.features) from the labelled
corpus (data/calisthenics/metadata.csv), trains a one-hidden-layer softmax
classifier (barra/model.py) over the movement labels, fits the load head, and
writes the model + a metrics report to models/. Features are cached so a rerun
after adding clips does not re-pose-estimate what is already extracted.

Usage:
  python scripts/train_model.py                    # all available classes
  python scripts/train_model.py --tricks squat,push_up --per-trick 10
  python scripts/train_model.py --out models/exercise_model.npz
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from barra.classify import features
from barra.ingest import probe_video
from barra.model import (FEATURE_NAMES, ExerciseModel, train_classifier,
                         train_load)
from barra.posecache import load_or_estimate, load as load_cached

METADATA = ROOT / "data" / "calisthenics" / "metadata.csv"
MANIFEST = ROOT / "data" / "evaluation" / "sample_manifest.json"
DEFAULT_OUT = ROOT / "models" / "exercise_model.npz"
FEATURE_CACHE = ROOT / "out" / "model_features" / "features.csv"
KEYPOINT_DIR = ROOT / "out" / "keypoints"


def _cache() -> tuple[dict[str, dict], Counter, list[str]]:
    rows: dict[str, dict] = {}
    by_class: Counter = Counter()
    order: list[str] = []
    if FEATURE_CACHE.exists():
        with FEATURE_CACHE.open() as f:
            for r in csv.DictReader(f):
                rows[r["clip"]] = {k: v for k, v in r.items()}
                by_class[r["trick"]] += 1
                order.append(r["clip"])
    return rows, by_class, order


def featurize_clip(path: Path, trick: str, cache: dict[str, dict],
                   no_live: bool = False) -> dict | None:
    """One feature row for a clip, preferring already-extracted keypoints.

    Live pose extraction is expensive and, in a constrained sandbox, can be
    killed by the host - so a clip whose keypoints are already in the cache
    (out/keypoints/<stem>.parquet) is featurized from them, and only a clip with
    no cache is posed. With `no_live` a clip with no cache is skipped instead,
    which makes a training run safe on a host where posing is flaky. A clip that
    fails to pose is skipped rather than counted as a bad feature.
    """
    key = f"{trick}/{path.name}"
    if key in cache:
        return cache[key]
    try:
        kp = load_cached(path)
        if kp is None:
            if no_live:
                return None
            info = probe_video(path)
            fps = float(info.get("fps") or 30.0) or 30.0
            pose = load_or_estimate(path, fresh=False, write_cache=True,
                                    fallback_fps=fps)
            kp, fps = pose.keypoints, fps
        else:
            info = probe_video(path)
            fps = float(info.get("fps") or 30.0) or 30.0
    except Exception:  # noqa: BLE001 - one bad clip must not end the corpus
        return None
    feat = features(kp, fps)
    row = {"clip": key, "trick": trick}
    for name in FEATURE_NAMES:
        row[name] = feat.get(name, "")
    cache[key] = row
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tricks", default="", help="comma-separated class filter")
    ap.add_argument("--per-trick", type=int, default=12)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--epochs", type=int, default=250)
    ap.add_argument("--val-fraction", type=float, default=0.20)
    ap.add_argument("--no-live", action="store_true",
                    help="only use clips whose keypoints are already cached; "
                         "skip (and never pose) anything without keypoints")
    args = ap.parse_args()

    want = {t.strip() for t in args.tricks.split(",") if t.strip()}
    cache, by_class, _ = _cache()

    # Ordered class selection: most clips first, capped per-trick.
    selected: list[str] = []
    if FEATURE_CACHE.exists():
        used = list(cache.values())
    else:
        used = []
    # Build the clip list from BOTH label sources, in class-major order. The
    # scraped corpus (metadata.csv) labels most clips; the reviewed sample
    # manifest (sample_manifest.json) labels the eight reviewed root clips,
    # whose keypoints are already cached - so a first training run has a real,
    # pose-complete (if small) corpus even on a host where live pose is flaky.
    clips_by_class: dict[str, list[tuple[str, float]]] = {}
    if METADATA.exists():
        with METADATA.open() as f:
            for r in csv.DictReader(f):
                trick = r.get("trick", "")
                if want and trick not in want:
                    continue
                path = METADATA.parent / r.get("file", "")
                if not path.exists():
                    continue
                dur = float(r.get("duration") or 0.0)
                clips_by_class.setdefault(trick, []).append((str(path), dur))
    if MANIFEST.exists():
        for clip in json.loads(MANIFEST.read_text()).get("clips", []):
            movement = clip.get("movement")
            if not movement or movement in ("unknown", None):
                continue
            if want and movement not in want:
                continue
            path = (ROOT / clip["file"])
            clips_by_class.setdefault(movement, []).append((str(path), 0.0))

    t0 = time.monotonic()
    for trick, path_dur in clips_by_class.items():
        # Cached-keypoint clips first (free), then the shortest live ones, so a
        # training run always uses what is on disk before costing an estimate.
        path_dur.sort(key=lambda pd: (0 if KEYPOINT_DIR.
                      joinpath(Path(pd[0]).stem + ".parquet").exists() else 1,
                      pd[1]))
        paths = [pd[0] for pd in path_dur[: args.per_trick]]
        for path in paths:
            row = featurize_clip(Path(path), trick, cache, no_live=args.no_live)
            if row:
                used.append(row)
                selected.append(str(Path(row["clip"])))

    # Persist the cache.
    FEATURE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with FEATURE_CACHE.open("w", newline="") as f:
        cols = ["clip", "trick"] + list(FEATURE_NAMES)
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        seen = set()
        for row in used:
            if row["clip"] in seen:
                continue
            seen.add(row["clip"])
            w.writerow(row)

    # Build X, y from the cached clip-keys that actually extracted.
    X_rows, y = [], []
    for row in cache.values():
        vals = []
        ok = True
        for name in FEATURE_NAMES:
            try:
                vals.append(float(row.get(name, "")))
            except (TypeError, ValueError):
                vals.append(float("nan"))
        X_rows.append(vals)
        y.append(row["trick"])
    X = np.asarray(X_rows, dtype=float)
    classes = sorted(set(y))
    if X.shape[0] < max(4, len(classes)):
        print(f"only {X.shape[0]} clips extracted - not enough to train", file=sys.stderr)
        return 2

    # Stratified holdout.
    rng = np.random.default_rng(0)
    train_i, val_i = [], []
    for c in set(y):
        idx = [i for i, cc in enumerate(y) if cc == c]
        rng.shuffle(idx)
        # A class must leave at least one clip FOR TRAINING, or the classifier
        # never sees it and can never predict it. (Careful: `idx[:-0]` is
        # `idx[:0]`, i.e. empty - so a zero-sized validation slice must be
        # handled as a whole-set training row, not by slicing with `-0`.)
        n_val = min(int(round(len(idx) * args.val_fraction)), len(idx) - 1)
        if n_val <= 0:
            train_i += idx
            continue
        val_i += idx[-n_val:]
        train_i += idx[:-n_val]
    if not val_i:
        train_i = list(range(len(y)))
        val_i = list(range(len(y)))
    print(f"train {len(train_i)}  val {len(val_i)}  classes {len(set(y))}: "
          f"{dict(Counter(y))}")

    model = train_classifier(X[train_i], [y[i] for i in train_i],
                             epochs=args.epochs)
    # Load head - the corpus is bodyweight, so this is the honest baseline.
    load_w, load_b, load_note = train_load(X, None)
    model.load_w, model.load_b, model.load_note = load_w, load_b, load_note
    model.save(args.out)

    # Evaluation on the holdout.
    labels = [y[i] for i in val_i]
    preds, probs, _ = model.predict(X[val_i])
    correct = sum(a == b for a, b in zip(preds, labels))
    confusion: dict[str, Counter] = {}
    for truth, pred in zip(labels, preds):
        confusion.setdefault(truth, Counter())[pred] += 1
    per_class = {}
    for truth, row in confusion.items():
        tp = row.get(truth, 0)
        fn = sum(row.values()) - tp
        fp = sum(c.get(truth, 0) for t, c in confusion.items() if t != truth)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
        per_class[truth] = {"support": tp + fn, "precision": prec, "recall": rec,
                            "f1": f1, "predicted": dict(row)}
    metrics = {
        "version": model.version,
        "classes": model.classes,
        "nTrain": len(train_i), "nVal": len(val_i),
        "valAccuracy": round(correct / len(val_i), 3) if val_i else None,
        "perClass": per_class,
        "load": {"note": load_note},
        "runtimeS": round(time.monotonic() - t0, 2),
    }
    (args.out.parent / "model_metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str))
    print(f"\nval accuracy {metrics['valAccuracy']}")
    for c, m in per_class.items():
        print(f"  {c:26s} f1={m['f1'] if m['f1'] is not None else 'n/a'} "
              f"support={m['support']}")
    print(f"\nmodel -> {args.out}")
    print(f"metrics -> {args.out.parent / 'model_metrics.json'}")
    print(f"features cache -> {FEATURE_CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
