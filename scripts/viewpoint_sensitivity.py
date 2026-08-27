"""How much deviation does a camera-angle change cause, compared with a
technique error?

This is the question that decides whether the whole approach is viable, and it
can be answered without any footage: the geometry of projecting a 3D body onto
a 2D image is not in doubt. It runs on the synthetic model, so the numbers are
a property of the projection and the chosen error magnitudes, not of any real
subject or any pose estimator.

    python scripts/viewpoint_sensitivity.py
"""
from __future__ import annotations

import numpy as np

from barra import dtw
from barra.schema import ANALYSIS_IDX, KP_INDEX
from barra.synthetic import make_rep

N_PER_CELL = 8
REP_FRAMES = 60
BASE_AZ = 10.0
ERRORS = ["excess_forward_lean", "shallow_depth", "knee_travel",
          "knee_valgus", "lateral_shift"]


def normalise(kp: np.ndarray) -> np.ndarray:
    hip = 0.5 * (kp[:, KP_INDEX["left_hip"], :2] + kp[:, KP_INDEX["right_hip"], :2])
    sh = 0.5 * (kp[:, KP_INDEX["left_shoulder"], :2] + kp[:, KP_INDEX["right_shoulder"], :2])
    torso = float(np.median(np.linalg.norm(sh - hip, axis=1)))
    return (kp[:, ANALYSIS_IDX, :2] - hip[:, None, :]) / torso


def bank(rng, az: float, n: int, error: str | None = None) -> list[np.ndarray]:
    return [
        dtw.resample(normalise(make_rep(rng, az, REP_FRAMES, error=error)[0]), 100)
        for _ in range(n)
    ]


def mean_deviation(a: list[np.ndarray], b: list[np.ndarray]) -> float:
    return float(np.mean([
        np.linalg.norm(dtw.align_to(x, y) - y, axis=2).mean() for x in a for y in b
    ]))


def main() -> None:
    rng = np.random.default_rng(1)
    ref = bank(rng, BASE_AZ, N_PER_CELL)
    a, b = ref[: N_PER_CELL // 2], ref[N_PER_CELL // 2:]
    floor = mean_deviation(a, b)

    print(f"reference: same technique, same {BASE_AZ:.0f} deg viewpoint")
    print(f"  rep-to-rep noise floor                {floor:.4f} torso-lengths\n")

    print("same technique, camera moved:")
    view = {}
    for delta in (2, 4, 6, 8, 10, 15):
        view[delta] = mean_deviation(bank(rng, BASE_AZ + delta, N_PER_CELL // 2), b)
        print(f"  +{delta:>2} deg azimuth                      {view[delta]:.4f}"
              f"   ({view[delta] / floor:.1f}x the noise floor)")

    print(f"\nsame {BASE_AZ:.0f} deg viewpoint, deliberate technique error:")
    err = {}
    for e in ERRORS:
        err[e] = mean_deviation(bank(rng, BASE_AZ, N_PER_CELL // 2, error=e), b)
        print(f"  {e:<24}          {err[e]:.4f}   ({err[e] / floor:.1f}x)")

    weakest = min(err.values())
    tolerable = [d for d, v in view.items() if v < weakest]
    print("\n---")
    print(f"Weakest induced error signal: {weakest:.4f}.")
    if tolerable:
        print(f"Camera azimuth must be repeatable to about +/-{max(tolerable)} deg "
              "for viewpoint drift to stay below it.")
    else:
        print("Even a 2 deg camera move exceeds the weakest error signal.")
    swamped = [e for e, v in err.items() if v < view.get(10, np.inf)]
    print(f"Inside a 20 deg-wide bin, a 10 deg camera move ({view[10]:.4f}) exceeds "
          f"{len(swamped)}/{len(ERRORS)} of the induced errors: {', '.join(swamped)}.")


if __name__ == "__main__":
    main()
