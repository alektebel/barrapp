"""Multivariate DTW helpers.

All alignment in this project is multivariate: a rep is a single sequence whose
observation at each frame is the whole scored skeleton, not one channel per
joint aligned independently. Aligning joints independently would let each joint
choose its own time warp and would destroy the coordination information that a
technique deviation actually lives in.
"""
from __future__ import annotations

import numpy as np
from dtaidistance import dtw_ndim

from .config import DTW_WINDOW_FRAC


def flatten(X: np.ndarray) -> np.ndarray:
    """(T, J, 2) -> (T, 2J), C-contiguous float64 as dtaidistance requires."""
    return np.ascontiguousarray(X.reshape(X.shape[0], -1).astype(np.float64))


def resample(X: np.ndarray, length: int) -> np.ndarray:
    """Linear time-normalisation to a fixed number of frames.

    Time normalisation on its own is not alignment: it only removes gross
    duration differences so DTW starts from a sane place. The within-rep timing
    structure DTW cares about survives it.
    """
    T = X.shape[0]
    if T == length:
        return X.astype(np.float64)
    src = np.linspace(0.0, 1.0, T)
    dst = np.linspace(0.0, 1.0, length)
    flat = X.reshape(T, -1)
    out = np.empty((length, flat.shape[1]), dtype=np.float64)
    for k in range(flat.shape[1]):
        out[:, k] = np.interp(dst, src, flat[:, k])
    return out.reshape((length,) + X.shape[1:])


def _window(n: int, m: int) -> int:
    return max(4, int(DTW_WINDOW_FRAC * max(n, m)))


def path(query: np.ndarray, ref: np.ndarray) -> list[tuple[int, int]]:
    """Warping path between two (T, J, 2) sequences, Sakoe-Chiba banded.

    The band stops DTW from explaining a genuine technique deviation as an
    extreme time warp - without it, a rep that stalls badly can be warped onto
    the template at near-zero residual cost, which is exactly the failure this
    tool must not have.
    """
    a, b = flatten(query), flatten(ref)
    return dtw_ndim.warping_path(a, b, window=_window(len(a), len(b)))


def distance(query: np.ndarray, ref: np.ndarray) -> float:
    a, b = flatten(query), flatten(ref)
    return float(dtw_ndim.distance(a, b, window=_window(len(a), len(b)), use_c=True))


def align_to(query: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Warp `query` onto `ref`'s timeline.

    Where several query frames map to one reference frame they are averaged;
    where none map (impossible for a valid DTW path, but guarded anyway) the
    previous value is held.
    """
    p = path(query, ref)
    n_ref = ref.shape[0]
    acc = np.zeros((n_ref,) + query.shape[1:], dtype=np.float64)
    cnt = np.zeros(n_ref, dtype=np.int64)
    for i, j in p:
        acc[j] += query[i]
        cnt[j] += 1
    out = np.zeros_like(acc)
    last = np.zeros(query.shape[1:], dtype=np.float64)
    for j in range(n_ref):
        if cnt[j]:
            last = acc[j] / cnt[j]
        out[j] = last
    return out


def align_weights(query_w: np.ndarray, ref_len: int, p: list[tuple[int, int]]) -> np.ndarray:
    """Warp a per-frame, per-joint weight array along an existing path."""
    acc = np.zeros((ref_len,) + query_w.shape[1:], dtype=np.float64)
    cnt = np.zeros(ref_len, dtype=np.int64)
    for i, j in p:
        acc[j] += query_w[i]
        cnt[j] += 1
    cnt = np.maximum(cnt, 1)
    return acc / cnt.reshape((-1,) + (1,) * (query_w.ndim - 1))
