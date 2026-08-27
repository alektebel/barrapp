"""Invariant tests for the measurement core.

Run with:  python -m unittest discover -s tests -v

These check the properties the method depends on. They are not validation:
nothing here says the tool detects real technique errors, only that it computes
what it claims to compute.
"""
from __future__ import annotations

import unittest

import numpy as np

from barra import dtw
from barra import schema as S
from barra.normalise import torso_length
from barra.score import joint_weights, phase_slices, score_rep
from barra.synthetic import make_rep
from barra.viewpoint import _theta_deg, _bin_of, _bin_with_uncertainty
from barra.null import percentile_of, threshold


def _normalise(kp: np.ndarray) -> np.ndarray:
    hip = 0.5 * (kp[:, S.KP_INDEX["left_hip"], :2] + kp[:, S.KP_INDEX["right_hip"], :2])
    t = float(np.median(torso_length(kp)))
    return (kp[:, S.ANALYSIS_IDX, :2] - hip[:, None, :]) / t


class TestNormalisation(unittest.TestCase):
    def setUp(self):
        self.kp, _ = make_rep(np.random.default_rng(0), 10.0, 60)

    def test_hip_midpoint_is_origin(self):
        X = _normalise(self.kp)
        li = S.ANALYSIS_JOINTS.index("left_hip")
        ri = S.ANALYSIS_JOINTS.index("right_hip")
        mid = 0.5 * (X[:, li] + X[:, ri])
        self.assertLess(np.abs(mid).max(), 1e-6)

    def test_torso_is_unit_length(self):
        X = _normalise(self.kp)
        sh = 0.5 * (X[:, S.ANALYSIS_JOINTS.index("left_shoulder")]
                    + X[:, S.ANALYSIS_JOINTS.index("right_shoulder")])
        self.assertAlmostEqual(float(np.median(np.linalg.norm(sh, axis=1))), 1.0, places=2)

    def test_rotation_is_not_removed(self):
        """Torso lean must survive normalisation - it is the signal, not noise.

        A rep with extra forward lean must stay measurably different from one
        without it after normalisation. If a Procrustes rotation ever creeps
        in, this is the test that fails."""
        rng = np.random.default_rng(3)
        plain = _normalise(make_rep(rng, 10.0, 60)[0])
        leaned = _normalise(make_rep(rng, 10.0, 60, error="excess_forward_lean")[0])
        i = S.ANALYSIS_JOINTS.index("left_shoulder")
        self.assertGreater(
            abs(np.median(leaned[:, i, 0]) - np.median(plain[:, i, 0])), 0.10
        )

    def test_scale_invariance_to_camera_distance(self):
        rng = np.random.default_rng(4)
        near, _ = make_rep(rng, 10.0, 60, px_per_torso=300.0)
        rng = np.random.default_rng(4)
        far, _ = make_rep(rng, 10.0, 60, px_per_torso=120.0)
        d = np.abs(_normalise(near) - _normalise(far)).max()
        self.assertLess(d, 0.05)


class TestDTW(unittest.TestCase):
    def test_identical_series_align_exactly(self):
        X = dtw.resample(_normalise(make_rep(np.random.default_rng(1), 10.0, 60)[0]), 100)
        self.assertLess(np.abs(dtw.align_to(X, X) - X).max(), 1e-9)
        self.assertLess(dtw.distance(X, X), 1e-6)

    def test_resample_preserves_endpoints(self):
        X = _normalise(make_rep(np.random.default_rng(2), 10.0, 55)[0])
        R = dtw.resample(X, 100)
        self.assertEqual(R.shape, (100,) + X.shape[1:])
        np.testing.assert_allclose(R[0], X[0], atol=1e-9)
        np.testing.assert_allclose(R[-1], X[-1], atol=1e-9)

    def test_alignment_is_monotone_and_complete(self):
        rng = np.random.default_rng(5)
        A = dtw.resample(_normalise(make_rep(rng, 10.0, 50)[0]), 100)
        B = dtw.resample(_normalise(make_rep(rng, 10.0, 70)[0]), 100)
        p = dtw.path(A, B)
        js = [j for _, j in p]
        self.assertEqual(js, sorted(js))
        self.assertEqual(set(js), set(range(100)))


class TestScoring(unittest.TestCase):
    def test_low_confidence_joint_is_downweighted(self):
        J = len(S.ANALYSIS_JOINTS)
        test_c = np.ones((100, J)); test_c[:, 0] = 0.05
        tmpl_c = np.ones((100, J))
        w = joint_weights(test_c, tmpl_c)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)
        self.assertLess(w[0], w[1] / 5)

    def test_weights_sum_to_one_even_when_all_dead(self):
        J = len(S.ANALYSIS_JOINTS)
        w = joint_weights(np.zeros((10, J)), np.zeros((10, J)))
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)

    def test_phases_tile_the_timeline_without_gaps(self):
        for bottom in (10, 43, 50, 90):
            sl = phase_slices(100, bottom)
            self.assertEqual(len(sl), len(S.PHASE_NAMES))
            covered = np.zeros(100, dtype=bool)
            for _, s in sl:
                covered[s] = True
            self.assertTrue(covered.all(), f"gap for bottom={bottom}")

    def test_identical_rep_scores_zero(self):
        X = dtw.resample(_normalise(make_rep(np.random.default_rng(6), 10.0, 60)[0]), 100)
        C = np.ones(X.shape[:2])
        sc = score_rep(X, C, X, C, 43)
        self.assertLess(sc.total, 1e-9)
        self.assertLess(sc.per_joint.max(), 1e-9)

    def test_bigger_error_scores_higher(self):
        rng = np.random.default_rng(7)
        T = dtw.resample(_normalise(make_rep(rng, 10.0, 60)[0]), 100)
        C = np.ones(T.shape[:2])
        clean = dtw.resample(_normalise(make_rep(rng, 10.0, 60)[0]), 100)
        leaned = dtw.resample(
            _normalise(make_rep(rng, 10.0, 60, error="excess_forward_lean")[0]), 100)
        self.assertGreater(score_rep(leaned, C, T, C, 43).total,
                           score_rep(clean, C, T, C, 43).total)


class TestViewpoint(unittest.TestCase):
    def test_azimuth_recovered_from_synthetic_camera(self):
        """The estimator must recover an azimuth it was never told."""
        rng = np.random.default_rng(8)
        r_true = 1.10
        for truth in (5.0, 15.0, 35.0, 70.0):
            kp, _ = make_rep(rng, truth, 80)
            ls, rs = S.KP_INDEX["left_shoulder"], S.KP_INDEX["right_shoulder"]
            w = np.linalg.norm(kp[:, ls, :2] - kp[:, rs, :2], axis=1)
            est = float(_theta_deg(np.median(w / torso_length(kp)), r_true))
            self.assertLess(abs(est - truth), 8.0, f"{truth} deg -> {est:.1f} deg")

    def test_bins_match_the_spec_edges(self):
        self.assertEqual(_bin_of(0.0), "SAGITTAL")
        self.assertEqual(_bin_of(19.9), "SAGITTAL")
        self.assertEqual(_bin_of(20.0), "OBLIQUE")
        self.assertEqual(_bin_of(64.9), "OBLIQUE")
        self.assertEqual(_bin_of(65.0), "FRONTAL")
        self.assertEqual(_bin_of(90.0), "FRONTAL")

    def test_wide_interval_across_a_boundary_becomes_unknown(self):
        self.assertEqual(_bin_with_uncertainty(20.0, 5.0, 60.0)[0], "UNKNOWN")
        self.assertEqual(_bin_with_uncertainty(10.0, 8.0, 12.0), ("SAGITTAL", False))


class TestNull(unittest.TestCase):
    def test_percentile_bounds(self):
        v = np.arange(100.0)
        self.assertLess(percentile_of(-1.0, v), 1.0)
        self.assertGreater(percentile_of(1000.0, v), 99.0)
        self.assertAlmostEqual(percentile_of(49.5, v), 50.0, places=1)

    def test_ties_do_not_saturate(self):
        v = np.ones(10)
        self.assertAlmostEqual(percentile_of(1.0, v), 50.0)

    def test_threshold_is_the_95th_percentile(self):
        v = np.arange(1000.0)
        self.assertAlmostEqual(threshold(v), np.percentile(v, 95))


class TestReportingDiscipline(unittest.TestCase):
    def test_no_verdict_without_a_percentile(self):
        """Section 11.4: no verdict may be printed without its null percentile.

        Checks the two places a verdict reaches a human - the score printout
        and the report template - and asserts a percentile is rendered in the
        same breath."""
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[1] / "barra"
        score_src = (src / "score.py").read_text()
        i = score_src.index("FLAGGED")
        window = score_src[max(0, i - 700):i + 200]
        self.assertIn("null pct", window)
        self.assertIn("pct=", window)

        tpl = (src / "templates" / "report.html.j2").read_text()
        j = tpl.index("exceeds own variation")
        self.assertIn("percentile", tpl[j:j + 1400])


if __name__ == "__main__":
    unittest.main()
