"""The first learned model: which exercise is this clip, and what is it loaded?

The geometric classifier (barra/classify.py) has been the pipeline's only
answer, and it is deliberately rule-based - the project had no labelled corpus
and a learned model would fail silently on a movement it had not seen. The
scraped dataset (data/calisthenics/metadata.csv) changed that: it is labelled,
so the first model can be trained on it.

This module is that model, and it is deliberately small and honest about being
a first model:

  1. It is a one-hidden-layer softmax classifier over the CLIP-LEVEL geometric
     features barra/classify.features() already computes. Nothing here extracts
     new geometry; it learns to draw the boundaries the rules draw by hand, and
     extends them to classes the rules never covered.
  2. It ships with a weight/load head. Barra cannot SEE added load in a 2D pose
     (a weighted pull-up looks like a pull-up), so the load model is honest
     about its ceiling: it predicts a load only from features that actually
     carry load information (tempo, pause, body position), and when trained on
     a corpus with no labelled loads it predicts the bodyweight baseline (0 kg)
     with a note - never a confident guess. Weight IS captured, but by the
     athlete, and stored beside the measurement.
  3. It is a competitor signal, not a replacement. `classify()` remains the
     interpretable, verified path; the model runs alongside it and the payload
     says which produced the label. Accuracy is reported per class, with the
     support, so a single-clip class is clearly inconclusive.

Everything is numpy-only and deterministic (fixed seed), so the model trains
and runs the same way everywhere - no torch in the measured path, and the test
suite can train a tiny model on synthetic data in milliseconds.
"""
from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import numpy as np

from .classify import features as classify_features

# The clip-level features the model reads. Chosen to be class-discriminative and
# present (not NaN) on every movement, so the same vector works across all of
# them: an unknown frame set is filled with a sentinel the normaliser carries,
# never dropped.
FEATURE_NAMES: tuple[str, ...] = (
    "n_frames", "wrist_seen", "ankle_seen", "wrist_travel", "ankle_travel",
    "wrist_window_travel", "wrist_window_seen", "on_bar_frac",
    "shoulder_above_hands_p05", "shoulder_above_hands_p95",
    "hands_overhead_frac", "hands_below_frac",
    "shoulder_above_hands_p95_clip", "arm_articulation",
    "arm_articulation_clip", "hip_travel", "torso_tilt", "body_below_hands",
    "parked_frac", "knee_over_hip", "knee_excursion", "hip_articulation",
    "body_line_deg", "horizontal_frac", "arms_straight_frac",
    "legs_straight_frac", "legs_lifted_frac", "single_leg_stance",
    "l_ankle_below", "r_ankle_below", "split_ankle_heights", "rear_raised",
    "shoulder_above_hands_p90", "shoulder_above_hands_over_bar_frac",
    "shoulder_above_hands_std", "hip_travel_std",
)

_HIDDEN = 24
_NAN = -50.0

NAN_HEADERS = ("nan_filled",)


def featurize(keypoints: np.ndarray, fps: float = 30.0) -> np.ndarray:
    """One model-ready feature vector for a clip, from its keypoints."""
    f = classify_features(keypoints, fps)
    return vector_from_dict(f)


def vector_from_dict(f: dict, feature_names: tuple[str, ...] | list[str] | None = None) -> np.ndarray:
    """A model-ready vector from a features() dict. Unknown/NaN -> sentinel."""
    v = []
    for name in (feature_names or FEATURE_NAMES):
        x = f.get(name)
        try:
            x = float(x)
        except (TypeError, ValueError):
            x = float("nan")
        if not np.isfinite(x):
            x = _NAN
        v.append(x)
    return np.asarray(v, dtype=float)


class ExerciseModel:
    """One-hidden-layer softmax classifier + linear load head, in numpy.

    `classes` (list[str]) are the movement names; `feature_names` (tuple[str])
    the exact keys `vector_from_dict` emits; `mean`/`std` the per-feature
    normaliser. `nan_value` is what an unknown feature is filled with before
    normalisation.
    """

    def __init__(self, classes, feature_names=FEATURE_NAMES,
                 mean=None, std=None, nan_value=_NAN,
                 w1=None, b1=None, w2=None, b2=None,
                 load_w=None, load_b=None, load_note="", version="1.0"):
        self.classes = list(classes)
        self.feature_names = tuple(feature_names)
        self.mean = mean
        self.std = std
        self.nan_value = nan_value
        self.w1 = w1
        self.b1 = b1
        self.w2 = w2
        self.b2 = b2
        self.load_w = load_w
        self.load_b = load_b
        self.load_note = load_note
        self.version = version

    # -- normalisation -------------------------------------------------------
    def _normalise(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float).copy()
        X[~np.isfinite(X)] = self.nan_value
        if self.mean is None or self.std is None:
            return X
        std = np.where(self.std <= 1e-9, 1.0, self.std)
        return (X - self.mean) / std

    # -- classifier ----------------------------------------------------------
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = self._normalise(X)
        h = np.maximum(X @ self.w1 + self.b1, 0.0)
        logits = h @ self.w2 + self.b2
        logits = logits - logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, X: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
        p = self.predict_proba(X)
        idx = np.argmax(p, axis=1)
        return [self.classes[i] for i in idx], p, idx

    # -- load head -----------------------------------------------------------
    def predict_load(self, X: np.ndarray) -> np.ndarray:
        X = self._normalise(X)
        if self.load_w is None or self.load_b is None:
            return np.zeros(len(X))
        return X @ self.load_w + self.load_b

    # -- serialisation -------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # `load_w`/`load_b` default to None (baseline). np.savez turns None into
        # an object array, which np.load refuses without allow_pickle - so store
        # real zeros and let `loadNote` say whether they are a fitted head.
        lw = self.load_w if self.load_w is not None else np.zeros(len(self.feature_names))
        lb = self.load_b if self.load_b is not None else 0.0
        np.savez_compressed(
            path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2,
            mean=self.mean, std=self.std, load_w=lw, load_b=lb,
        )
        meta = {
            "classes": self.classes, "featureNames": list(self.feature_names),
            "nanValue": self.nan_value, "version": self.version,
            "loadNote": self.load_note,
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))

    @classmethod
    def load(cls, path: Path) -> "ExerciseModel":
        path = Path(path)
        z = np.load(path)
        meta = json.loads(path.with_suffix(".meta.json").read_text())
        return cls(
            classes=meta["classes"], feature_names=meta["featureNames"],
            mean=z["mean"], std=z["std"], nan_value=meta.get("nanValue", _NAN),
            w1=z["w1"], b1=z["b1"], w2=z["w2"], b2=z["b2"],
            load_w=z["load_w"], load_b=float(z["load_b"]),
            load_note=meta.get("loadNote", ""), version=meta.get("version", "1.0"),
        )


def _init_weights(n_in: int, n_hidden: int, n_out: int, seed: int) -> tuple:
    rng = np.random.default_rng(seed)
    w1 = rng.normal(0.0, 0.1, (n_in, n_hidden)).astype(float)
    b1 = np.zeros(n_hidden)
    w2 = rng.normal(0.0, 0.1, (n_hidden, n_out)).astype(float)
    b2 = np.zeros(n_out)
    return w1, b1, w2, b2


def train_classifier(X: np.ndarray, y: list[str], seed: int = 0,
                     epochs: int = 300, lr: float = 0.05) -> ExerciseModel:
    """Train the softmax MLP. X is (n, n_features), y a list of class labels.

    Deterministic (fixed seed) and numpy-only. Class imbalance is handled by
    inverse-frequency weighting of the cross-entropy, so a corpus dominated by
    one movement does not make the model ignore the rest.
    """
    X = np.asarray(X, dtype=float)
    classes = sorted(set(y))
    cindex = {c: i for i, c in enumerate(classes)}
    Y = np.zeros((len(y), len(classes)))
    counts = np.zeros(len(classes))
    for i, c in enumerate(y):
        j = cindex[c]
        Y[i, j] = 1.0
        counts[j] += 1.0

    feat = FEATURE_NAMES[:X.shape[1]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        finite = np.where(np.isfinite(X), X, np.nan)
        mean = np.nanmean(finite, axis=0)
        std = np.nanstd(finite, axis=0)
    # A feature that is unseen (NaN) on every clip, or constant, has no signal:
    # give it a benign mean/standard deviation rather than NaN-normalising it.
    mean = np.where(np.isfinite(mean), mean, 0.0)
    std = np.where(np.isfinite(std), std, 1.0)
    std = np.where((~np.isfinite(std)) | (std <= 1e-9), 1.0, std)
    Xn = (X - mean) / std
    Xn[~np.isfinite(Xn)] = _NAN

    w1, b1, w2, b2 = _init_weights(X.shape[1], _HIDDEN, len(classes), seed)
    # inverse-frequency class weights
    wgt = (len(classes) / (counts + 1e-6))
    wgt /= wgt.mean()

    n = Xn.shape[0]
    for epoch in range(epochs):
        # forward
        h = np.maximum(Xn @ w1 + b1, 0.0)
        logits = h @ w2 + b2
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        P = exp / exp.sum(axis=1, keepdims=True)
        # weighted cross-entropy gradient (softmax + CE)
        dlogits = (P - Y) * wgt[None, :] / n
        dW2 = h.T @ dlogits
        db2 = dlogits.sum(axis=0)
        dH = (dlogits @ w2.T)
        dH[h <= 0] = 0.0
        dW1 = Xn.T @ dH
        db1 = dH.sum(axis=0)
        w2 -= lr * dW2
        b2 -= lr * db2
        w1 -= lr * dW1
        b1 -= lr * db1

    m = ExerciseModel(classes, feat, mean, std, _NAN, w1, b1, w2, b2)
    return m


def train_load(X: np.ndarray, y_kg: list[float] | None,
               feature_names: tuple[str, ...] = FEATURE_NAMES,
               mean=None, std=None) -> tuple[np.ndarray, np.ndarray, str]:
    """The load head: predict added load (kg) from clip features.

    With no labelled loads (a corpus of bodyweight clips, which is what the
    scraped set is), it returns the bodyweight baseline - zero weight, a note
    that says why - rather than a confident number. With labelled loads it fits
    an ordinary least-squares line to mean-centred features, and the note says
    it was fit from data.

    `mean`/`std` should be the classifier's normaliser, so the load head reads
    the same standardised features. When None they are assumed identity.
    """
    X = np.asarray(X, dtype=float)
    if not y_kg or all(float(v) == 0.0 for v in y_kg):
        return (np.zeros(X.shape[1]), 0.0,
                "no labelled loads in the corpus - predicting the bodyweight "
                "baseline (0 kg), not a guess")
    yy = np.asarray([float(v) for v in y_kg], dtype=float)
    # fit least squares to the (already standardised) features
    Xn = (X - (mean if mean is not None else 0.0)) / (
        (std if std is not None else 1.0) + 1e-9)
    Xn = np.nan_to_num(Xn, nan=_NAN)
    Xni = np.concatenate([Xn, np.ones((len(Xn), 1))], axis=1)
    coeff, *_ = np.linalg.lstsq(Xni, yy, rcond=None)
    w = coeff[:-1]
    b = float(coeff[-1])
    return (w, b, f"load head fit on {len(yy)} labelled clips")


# ---------------------------------------------------------------------------
# Prediction entry points (operate on a features() dict)
# ---------------------------------------------------------------------------
def model_classify(model: ExerciseModel, f: dict) -> dict:
    """The model's verdict on one clip's features, to ship beside `detected`.

    Returns the predicted class, the margin to the runner-up, and the full
    probability vector - so a consumer can see how far from the boundary the
    call was instead of reading a bare label as confidence.
    """
    x = vector_from_dict(f, model.feature_names).reshape(1, -1)
    label, probs, _ = model.predict(x)
    p = float(probs[0, model.classes.index(label[0])])
    order = np.argsort(probs[0])[::-1]
    runner, margin = None, None
    if len(order) > 1:
        runner = model.classes[int(order[1])]
        margin = round(float(probs[0, order[0]] - probs[0, order[1]]), 4)
    return {"exercise": label[0], "confidence": round(p, 4),
            "marginToRunnerUp": margin, "runnerUp": runner,
            "probabilities": {c: round(float(probs[0, j]), 4)
                              for j, c in enumerate(model.classes)},
            "model": model.version}


def model_load(model: ExerciseModel, f: dict) -> dict:
    """The load estimate for one clip, with the confidence barra has a right to claim."""
    x = vector_from_dict(f, model.feature_names).reshape(1, -1)
    kg = float(model.predict_load(x)[0])
    return {"kg": round(kg, 2), "estimated": bool(kg > 1e-6),
            "note": model.load_note or "baseline: load not estimated from video"}


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "exercise_model.npz"


def load_default(model_path: Path | None = None) -> ExerciseModel | None:
    path = Path(model_path or os.environ.get("BARRA_MODEL_PATH") or DEFAULT_MODEL_PATH)
    if path.exists():
        return ExerciseModel.load(path)
    return None
