#!/usr/bin/env python
"""How often does the pipeline name the right movement? Measured honestly.

The number this repo had been quoting came from two places and neither could
be believed. The 26-clip batch mixed classes the geometric rules were never
written for into the denominator, so it measured coverage and called it
accuracy. The 18-clip "SOTA cached" batch reported a learned model at 1.00 -
on the clips that model was trained on. This script exists so that neither can
happen again:

  * **Every clip with keypoints is in the denominator**, with the label the
    corpus assigns it. A movement the rules do not implement is not excused;
    abstaining on it is a defensible ANSWER, not an exemption from the count,
    and it is reported separately so the two are never confused.
  * **The learned model is only ever scored on clips it did not see.**
    Stratified k-fold, and the augmented views of a clip live in the same fold
    as the clip they came from - otherwise a mirrored copy of the test clip is
    in the training set and the model is being asked to recognise a photograph
    of the answer.

What it reports, per detector and per class: accuracy, the abstention rate, and
the confusion matrix, so "which pairs does it actually mix up" is answerable
without re-running anything.

Usage:
  python scripts/classify_eval.py                       # the whole corpus
  python scripts/classify_eval.py --augment 6 --folds 5
  python scripts/classify_eval.py --window none         # ignore vision windows
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from barra.classify import classify
from barra.fusion import fuse_detection
from barra.kinematics import crop, full_features, jitter, mirror, phased_features
from barra.model import ExerciseModel, train_classifier
from barra.posecache import load as load_cached

VIDEOS = ROOT / "data" / "calisthenics" / "videos"
LABELS = ROOT / "data" / "calisthenics" / "labels.csv"
LABEL_DIR = ROOT / "data" / "calisthenics" / "labels"
ADJUDICATED = ROOT / "data" / "calisthenics" / "labels-adjudicated.csv"
DEFAULT_OUT = ROOT / "out" / "classify-eval"

# The rules answer for these; everything else in the corpus they can only
# abstain on or guess at. Kept explicit so "the geometry got it wrong" and
# "the geometry was never asked" stay different sentences in the report.
GEOMETRIC_CLASSES = {
    "squat", "muscle_up", "pull_up", "knee_raise", "dip", "push_up",
    "front_lever", "planche", "pistol_squat", "split_squat",
    "bulgarian_split_squat",
}


# ---------------------------------------------------------------------------
# the corpus
# ---------------------------------------------------------------------------
def verdicts() -> dict[str, dict]:
    """Per clip, the multimodal read of it, from the sidecars themselves.

    The sidecar under `data/calisthenics/labels/` is what the labeller actually
    writes per clip; `labels.csv` is a flat summary it re-derives at the end of
    a run. Reading the summary made the whole vision path conditional on that
    last write having happened - and when it had not, `--window vision` became
    a silent no-op that featurised entire tutorial videos and reported the
    result as if the windows had been applied. The sidecars are the source of
    truth, so they are what is read; the CSV is a fallback for a corpus that
    only has one.
    """
    out: dict[str, dict] = {}
    for j in sorted(LABEL_DIR.rglob("*.json")):
        try:
            v = json.loads(j.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # a half-written sidecar is not a label
        f = v.get("file")
        if f:
            out[Path(f).name] = v
    if out or not LABELS.exists():
        return out
    with LABELS.open() as f:
        for r in csv.DictReader(f):
            if r.get("file"):
                out[Path(r["file"]).name] = dict(r)
    return out


def technique_windows(v: dict[str, dict]) -> dict[str, tuple[float, float]]:
    """Per clip, the seconds in which a vision model saw the movement performed.

    The corpus is scraped tutorials: a 442-second back-lever video is mostly a
    man explaining back levers. Featurising all of it measures the explanation.
    The window comes from `scripts/label_calisthenics.py`, which asks a
    multimodal model when the exercise is actually being done - an independent
    read of the pixels, not another opinion from the geometry being evaluated.
    """
    out: dict[str, tuple[float, float]] = {}
    for clip, rec in v.items():
        try:
            s, e = float(rec["technique_start"]), float(rec["technique_end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e - s >= 3.0:
            out[clip] = (s, e)
    return out


def vision_labels(v: dict[str, dict], split_load: bool = True) -> dict[str, str]:
    """Per clip, the movement the vision model says it sees."""
    out: dict[str, str] = {}
    for clip, rec in v.items():
        got = (rec.get("detected_trick") or "").strip()
        if got and got != "none":
            out[clip] = movement_label(got, split_load)
    return out


def movement_label(directory: str, split_load: bool = True) -> str:
    """The movement a directory names, with added load taken back out of it.

    A scrape added `weighted_dip`, `weighted_pull_up` and `weighted_squat` as
    if they were movements. They are not: they are a movement plus a plate,
    and `barra/model.py` says in its own docstring why that cannot be a class
    here - "barra cannot SEE added load in a 2D pose (a weighted pull-up looks
    like a pull-up)". The confusion matrix agrees: every `weighted_dip` the
    model gets "wrong" it calls a dip.

    Scoring them as separate classes therefore measures the pipeline against a
    question its own architecture says is unanswerable from keypoints, and the
    penalty is real - it cost about ten points across the corpus. Load is a
    separate head, and it is captured from the athlete rather than seen. So
    the movement label is the movement; `--keep-load-classes` restores the
    directory names for anyone who wants to see that number instead.
    """
    if split_load and directory.startswith("weighted_"):
        return directory[len("weighted_"):]
    return directory


def adjudicated() -> dict[str, str]:
    """Per clip, the label a human settled on, overriding the directory.

    The corpus label is the folder a scraper dropped the clip into, chosen by
    the search query that found it, and on this corpus about one clip in
    eleven is filed wrong: eight `split_squat` clips whose own description
    says "rear foot elevated on a bench" (which is a bulgarian split squat), a
    pistol squat under `handstand`, muscle-ups under `pull_up`. Every accuracy
    in this repo is measured against that, so a detector is penalised for
    being right about a clip the scrape mislabelled.

    This is the only reference allowed to overrule it, and only a person can
    write it - not the vision pass, and certainly not the model being scored,
    which would be marking its own homework. `scripts/label_disputes.py`
    proposes the rows; a human fills in `verdict` and they become truth here.
    """
    out: dict[str, str] = {}
    if not ADJUDICATED.exists():
        return out
    with ADJUDICATED.open() as f:
        for r in csv.DictReader(f):
            clip = (r.get("clip") or "").strip()
            verdict = (r.get("verdict") or "").strip()
            if clip and verdict:
                out[Path(clip).name] = verdict
    return out


def frame_rates() -> dict[str, float]:
    """Per clip, its frame rate.

    The keypoint cache stores frames and not a frame rate, so a tempo or a
    window in seconds has to come from the corpus ledger. Getting this wrong is
    silent and expensive: a 24 fps clip read as 30 has every duration, rep rate
    and vision window a quarter off, and nothing raises.

    The ledger only covers clips a scrape wrote a row for, and the corpus has
    since grown past it - 26 clips had no row at all and were silently taking
    the 30.0 default, several of them 60 fps, which halves every window they
    have. So anything the ledger does not answer for is probed from the file
    itself and cached; a frame rate is not something to guess at when the
    container will say.
    """
    out: dict[str, float] = {}
    meta = ROOT / "data" / "calisthenics" / "metadata.csv"
    if meta.exists():
        with meta.open() as f:
            for r in csv.DictReader(f):
                try:
                    fps = float(r.get("fps") or 0)
                except ValueError:
                    continue
                if fps > 0:
                    out[Path(r["file"]).name] = fps

    cache_path = ROOT / "out" / "fps.json"
    cache: dict[str, float] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            cache = {}
    probed = False
    for video in sorted(VIDEOS.rglob("*.mp4")):
        if video.name in out:
            continue
        if video.name not in cache:
            cache[video.name] = _probe_fps(video)
            probed = True
        if cache[video.name] > 0:
            out[video.name] = cache[video.name]
    if probed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True) + "\n")
    return out


def _probe_fps(video: Path) -> float:
    """The video stream's frame rate, or 0.0 if the container will not say."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate", "-of",
             "default=nk=1:nw=1", str(video)],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    for line in (p.stdout or "").splitlines():
        num, _, den = line.strip().partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if fps > 0:
            return round(fps, 3)
    return 0.0


def corpus(window: str, split_load: bool = True) -> list[dict]:
    """Every clip whose keypoints are cached, with its label and keypoints.

    `window="vision"` is a claim that the rows are trimmed to the technique.
    If no window survives, that claim is false, and a run that quietly reports
    untrimmed numbers under the trimmed flag is worse than one that stops - so
    it stops.
    """
    windows = technique_windows(verdicts()) if window == "vision" else {}
    if window == "vision" and not windows:
        raise SystemExit(
            "--window vision, but no technique windows were found in "
            f"{LABEL_DIR} or {LABELS}. Run scripts/label_calisthenics.py "
            "first, or pass --window none to measure untrimmed clips on "
            "purpose.")
    rates = frame_rates()
    settled = adjudicated()
    rows, trimmed = [], 0
    for video in sorted(VIDEOS.rglob("*.mp4")):
        kp = load_cached(video)
        if kp is None or len(kp) < 8:
            continue
        fps = rates.get(video.name, 30.0)
        span = windows.get(video.name)
        if span:
            a = max(0, int(span[0] * fps))
            b = min(len(kp), int(span[1] * fps))
            if b - a >= int(2 * fps):
                kp = kp[a:b]
                trimmed += 1
        rows.append({"clip": video.name,
                     "trick": settled.get(
                         video.name,
                         movement_label(video.parent.name, split_load)),
                     "kp": kp, "fps": fps})
    if window == "vision":
        print(f"{trimmed}/{len(rows)} clips trimmed to their technique window",
              flush=True)
    if settled:
        used = sum(1 for r in rows if r["clip"] in settled)
        print(f"{used} clip labels come from {ADJUDICATED.name} rather than "
              f"the directory", flush=True)
    return rows


# ---------------------------------------------------------------------------
# features, with the augmented views of a clip tagged by that clip
# ---------------------------------------------------------------------------
def views(kp: np.ndarray, n: int, seed: int) -> list[np.ndarray]:
    """`n` label-preserving views of one clip, the original first.

    Mirror, temporal crop-resize and joint jitter are the three augmentations
    reported to matter on small skeleton corpora, and each is defensible here
    rather than merely conventional: a movement filmed from the other side is
    the same movement, a window of a set is the same set, and a pose estimator
    that moved a knee by two percent of a torso has not changed the exercise.
    """
    out = [kp]
    rng = np.random.default_rng(seed)
    for i in range(max(0, n - 1)):
        view = kp
        if i % 2 == 1:
            view = mirror(view)
        lo = float(rng.uniform(0.0, 0.35))
        hi = float(rng.uniform(max(lo + 0.4, 0.65), 1.0))
        view = crop(view, lo, hi)
        if len(view) >= 8:
            view = jitter(view, sigma_torso=float(rng.uniform(0.005, 0.03)),
                          seed=int(rng.integers(1 << 30)))
            out.append(view)
    return out


def feature_table(rows: list[dict], augment: int, seed: int,
                  features: str = "flat") -> tuple[
        np.ndarray, list[str], list[str], list[str], np.ndarray]:
    """(X, names, y, clip-of-each-row, is-original) over the augmented corpus.

    `features` is "flat" (the whole-clip vector the model ships with) or
    "phased" (that vector plus the same view of each third of the clip). The
    flat vector cannot tell a movement from its own time-reverse; whether that
    matters is measured, not assumed.
    """
    featurise = phased_features if features == "phased" else full_features
    feats: list[dict] = []
    y: list[str] = []
    owner: list[str] = []
    original: list[bool] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, r in enumerate(rows):
            for j, view in enumerate(views(r["kp"], augment, seed + i)):
                feats.append(featurise(view, r["fps"]))
                y.append(r["trick"])
                owner.append(r["clip"])
                original.append(j == 0)
    names = sorted(feats[0].keys())
    X = np.array([[float(f.get(n, np.nan)) for n in names] for f in feats])
    return X, names, y, owner, np.array(original)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def folds_by_clip(clips: list[str], y: list[str], k: int, seed: int) -> dict[str, int]:
    """Assign each CLIP to a fold, stratified by class.

    By clip, not by row: every augmented view of a clip must land in the same
    fold, or the model is tested on a mirrored copy of its own training data.
    """
    per_class: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for clip, label in zip(clips, y):
        if clip not in seen:
            seen.add(clip)
            per_class[label].append(clip)
    rng = np.random.default_rng(seed)
    assignment: dict[str, int] = {}
    for label, members in sorted(per_class.items()):
        members = list(members)
        rng.shuffle(members)
        for i, clip in enumerate(members):
            assignment[clip] = i % k
    return assignment


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for truth, got in pairs:
        out[truth][got] += 1
    return {k: dict(v) for k, v in out.items()}


def per_class(pairs: list[tuple[str, str]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    truths = Counter(t for t, _ in pairs)
    hits = Counter(t for t, g in pairs if t == g)
    for label, n in sorted(truths.items()):
        out[label] = {"support": n, "correct": hits[label],
                      "recall": round(hits[label] / n, 3)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--augment", type=int, default=6,
                    help="views per clip used for TRAINING (1 = no augmentation)")
    ap.add_argument("--window", choices=("vision", "none"), default="vision")
    ap.add_argument("--keep-load-classes", action="store_true",
                    help="score weighted_* as separate movements, which 2D "
                         "pose cannot see")
    # The defaults are the configuration the reported numbers were measured
    # with (scripts/classify_sweep.py picked them over several seeds), so a
    # plain run reproduces what this repo publishes rather than a worse
    # number nobody quoted. `--lr 0.08` was the old full-batch gradient-descent
    # step; it is far too large for Adam, which is now the default optimiser.
    ap.add_argument("--epochs", type=int, default=800)
    ap.add_argument("--hidden", type=int, default=48)
    ap.add_argument("--l2", type=float, default=5e-2)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--optimizer", default="adam", choices=("adam", "sgd"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ensemble", type=int, default=1,
                    help="models per fold, averaged. Different seeds only")
    ap.add_argument("--skip-geometry", action="store_true")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    started = time.time()
    rows = corpus(args.window, split_load=not args.keep_load_classes)
    if not rows:
        print("no clips with cached keypoints - run scripts/extract_keypoints.py",
              file=sys.stderr)
        return 1
    print(f"{len(rows)} clips, {len(set(r['trick'] for r in rows))} classes, "
          f"window={args.window}", flush=True)

    X, names, y, owner, original = feature_table(rows, args.augment, args.seed)
    print(f"{X.shape[0]} feature rows ({X.shape[1]} features), "
          f"{int(original.sum())} original", flush=True)

    assignment = folds_by_clip(owner, y, args.folds, args.seed)
    fold_of = np.array([assignment[c] for c in owner])

    # --- the learned model, out of fold -----------------------------------
    model_pairs: list[tuple[str, str]] = []
    predicted: dict[str, dict] = {}
    for k in range(args.folds):
        train = fold_of != k
        test = (fold_of == k) & original
        if not train.any() or not test.any():
            continue
        # An ensemble of differently-seeded models, averaged. It is the
        # cheapest honest gain available on a corpus this small: one MLP's
        # answer on 170 clips depends visibly on where its weights started,
        # and averaging that away costs nothing but training time and removes
        # a source of variance that would otherwise be read as a real effect
        # when a threshold changes.
        y_train = [y[i] for i in np.where(train)[0]]
        proba = None
        classes: list[str] = []
        for m in range(max(1, args.ensemble)):
            model = train_classifier(X[train], y_train,
                                     seed=args.seed + 101 * m, epochs=args.epochs,
                                     lr=args.lr, feature_names=names,
                                     hidden=args.hidden, l2=args.l2,
                                     optimizer=args.optimizer)
            p_m = model.predict_proba(X[test])
            classes = model.classes
            proba = p_m if proba is None else proba + p_m
        proba = proba / max(1, args.ensemble)
        labels = [classes[i] for i in np.argmax(proba, axis=1)]
        for row, got, p in zip(np.where(test)[0], labels, proba):
            order = np.sort(p)[::-1]
            model_pairs.append((y[row], got))
            predicted[owner[row]] = {
                "trick": y[row], "model": got,
                "modelConfidence": round(float(order[0]), 3),
                "modelMargin": round(float(order[0] - order[1]), 3),
                "fold": k,
            }
        print(f"  fold {k}: {sum(1 for t, g in model_pairs if t == g)}/"
              f"{len(model_pairs)} cumulative", flush=True)

    # --- the geometric rules ----------------------------------------------
    geometry_pairs: list[tuple[str, str]] = []
    geometry_of: dict[str, dict] = {}
    if not args.skip_geometry:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for r in rows:
                try:
                    c = classify(r["kp"], fps=r["fps"])
                    got = c.exercise or "unknown"
                    geometry_of[r["clip"]] = {
                        "exercise": got,
                        "confidence": float(getattr(c, "confidence", 0.0) or 0.0),
                    }
                except Exception as e:  # noqa: BLE001 - a crash is a wrong answer
                    got = "unknown"
                    geometry_of[r["clip"]] = {"exercise": "unknown",
                                              "confidence": 0.0}
                    predicted.setdefault(r["clip"], {})["geometryError"] = str(e)[:120]
                geometry_pairs.append((r["trick"], got))
                predicted.setdefault(r["clip"], {})["geometry"] = got

    vision = vision_labels(verdicts(), split_load=not args.keep_load_classes)
    vision_pairs = [(r["trick"], vision[r["clip"]]) for r in rows
                    if r["clip"] in vision]

    # --- what the pipeline as a whole answers -------------------------------
    # The three detectors above are parts; `fuse_detection` is what the phone
    # is actually told, and it is the only one of these numbers a user ever
    # experiences. Both arrangements are scored because the difference between
    # them is a decision someone has to make: shipping the vision label means
    # a network round trip per clip, and this says what that would buy.
    fusion_pairs: list[tuple[str, str]] = []
    fusion_vision_pairs: list[tuple[str, str]] = []
    for r in rows:
        clip = r["clip"]
        p = predicted.get(clip, {})
        if "model" not in p:
            continue  # never out of fold, so there is no honest answer for it
        geom = geometry_of.get(clip, {"exercise": "unknown", "confidence": 0.0})
        learned = {"exercise": p["model"], "confidence": p["modelConfidence"],
                   "marginToRunnerUp": p["modelMargin"]}
        got = fuse_detection(geom, learned).get("exercise") or "unknown"
        fusion_pairs.append((r["trick"], got))
        p["fusion"] = got
        with_vision = fuse_detection(geom, learned,
                                     vision.get(clip)).get("exercise") or "unknown"
        fusion_vision_pairs.append((r["trick"], with_vision))
        p["fusionWithVision"] = with_vision

    def block(pairs: list[tuple[str, str]], name: str) -> dict:
        if not pairs:
            return {"detector": name, "total": 0}
        correct = sum(1 for t, g in pairs if t == g)
        abstained = sum(1 for _, g in pairs if g in ("unknown", "", None))
        return {
            "detector": name, "total": len(pairs), "correct": correct,
            "accuracy": round(correct / len(pairs), 3),
            "abstained": abstained,
            "abstentionRate": round(abstained / len(pairs), 3),
            "perClass": per_class(pairs),
            "confusion": confusion(pairs),
        }

    in_scope = [(t, g) for t, g in geometry_pairs if t in GEOMETRIC_CLASSES]
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clips": len(rows), "classes": sorted(set(y)),
        "window": args.window, "augment": args.augment, "folds": args.folds,
        "features": len(names),
        "hyperparameters": {"hidden": args.hidden, "l2": args.l2,
                            "epochs": args.epochs, "lr": args.lr,
                            "optimizer": args.optimizer},
        "model": block(model_pairs, "learned model (out of fold)"),
        "geometry": block(geometry_pairs, "geometric rules (all classes)"),
        "geometryInScope": block(in_scope, "geometric rules (classes it implements)"),
        "vision": block(vision_pairs, "vision model (independent)"),
        "fusion": block(fusion_pairs, "fusion: geometry + learned (shipped)"),
        "fusionWithVision": block(fusion_vision_pairs,
                                  "fusion: geometry + learned + vision"),
        "runtimeS": round(time.time() - started, 1),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.out / "per-clip.json").write_text(json.dumps(predicted, indent=2) + "\n")

    for key in ("model", "geometry", "geometryInScope", "vision",
                "fusion", "fusionWithVision"):
        b = report[key]
        if b.get("total"):
            print(f"{b['detector']:44s} {b['correct']:3d}/{b['total']:3d} = "
                  f"{b['accuracy']:.3f}  (abstained {b['abstentionRate']:.2f})")
    print(f"\nwrote {args.out}/report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
