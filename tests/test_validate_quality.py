"""The quality-validation harness.

What is under test is mostly the harness's honesty: that it refuses to
conclude from evidence that cannot support the conclusion, and that it never
calls an effect real when it is smaller than repeat-measurement noise.
"""
import unittest

import numpy as np

from barra.validate_quality import (FAIL, INCONCLUSIVE, NOT_RUN, PASS, ceiling,
                                    degradation, reliability, run, sensitivity)


def rep(score, total_s=1.0, **components):
    comps = [{"name": k, "value": v, "weight": 0.33, "why": ""}
             for k, v in components.items()]
    return {"score": score, "total_s": f"{total_s:.2f}", "plausible": True,
            "components": comps}


def varied_set(n=12, start=90, drop=0.0, slow=0.0):
    """A set whose score falls by `drop` points and whose reps slow by `slow`."""
    out = []
    for i in range(n):
        f = i / max(1, n - 1)
        out.append(rep(int(round(start - drop * f)), total_s=1.0 * (1 + slow * f),
                       range=0.9 - 0.3 * f, control=0.9 - 0.2 * f,
                       smoothness=0.9 - 0.4 * f))
    return out


class TestCeiling(unittest.TestCase):
    def test_a_constant_component_is_a_failure(self):
        reps = [rep(90, range=0.8, control=1.0, smoothness=0.5 + 0.02 * i)
                for i in range(10)]
        c = ceiling([("clip", reps)])
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("control", c.detail.lower())

    def test_a_component_no_rep_could_measure_is_reported(self):
        """Its weight silently vanishes and the score is renormalised without
        saying so - which is what happened on a real 19-rep push-up clip."""
        reps = [rep(90 + i, control=0.5 + 0.03 * i, smoothness=0.4 + 0.04 * i)
                for i in range(10)]
        c = ceiling([("clip", reps)])
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("range was measurable in no rep", c.detail.lower())
        self.assertIn("40% of the weight", c.detail.lower())

    def test_a_compressed_scale_is_a_failure(self):
        reps = [rep(94 + (i % 3), range=0.5 + 0.04 * i,
                    smoothness=0.3 + 0.06 * i) for i in range(10)]
        c = ceiling([("clip", reps)])
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("spans", c.detail)

    def test_span_is_not_judged_on_too_few_reps(self):
        """Three reps four points apart is a statement about the sample."""
        reps = [rep(55 + i, range=0.5 + 0.1 * i, smoothness=0.4 + 0.1 * i)
                for i in range(3)]
        self.assertNotIn("spans", ceiling([("clip", reps)]).detail)

    def test_the_component_list_follows_the_score(self):
        """A hardcoded list drifted once already: after control stopped being a
        term in the mean, the check went on reporting it missing everywhere."""
        from barra.quality import WEIGHTS
        reps = [rep(50 + 5 * i, **{k: 0.3 + 0.05 * i for k in WEIGHTS})
                for i in range(10)]
        c = ceiling([("clip", reps)])
        self.assertNotIn("measurable in no rep", c.detail.lower())

    def test_a_healthy_spread_passes(self):
        reps = [rep(40 + 5 * i, range=0.2 + 0.07 * i, control=0.3 + 0.06 * i,
                    smoothness=0.1 + 0.08 * i) for i in range(11)]
        self.assertEqual(ceiling([("clip", reps)]).verdict, PASS)


class TestReliability(unittest.TestCase):
    def test_missing_pairs_are_not_run_rather_than_passed(self):
        c = reliability([])
        self.assertEqual(c.verdict, NOT_RUN)
        self.assertIn("two phones", c.advice)

    def test_agreement_sets_a_small_noise_floor(self):
        a = [rep(80, range=0.8)] * 5
        b = [rep(82, range=0.8)] * 5
        c = reliability([("setA", a, b)])
        self.assertEqual(c.verdict, PASS)
        self.assertAlmostEqual(c.numbers["noise_floor"], 2.0, places=1)

    def test_disagreement_fails_and_says_what_it_invalidates(self):
        c = reliability([("setA", [rep(80)] * 5, [rep(60)] * 5)])
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("mean nothing", c.advice)


class TestDegradation(unittest.TestCase):
    def test_an_easy_set_is_inconclusive_not_a_failure(self):
        """A set that never got hard cannot test whether the score notices
        fatigue. Calling that FAIL would be the harness overreaching."""
        flat = varied_set(n=12, drop=0.0, slow=0.0)
        c = degradation([("easy", flat)])
        self.assertEqual(c.verdict, INCONCLUSIVE)
        self.assertIn("not near failure", c.detail)
        self.assertIn("failure", c.advice)

    def test_a_hard_set_whose_score_falls_passes(self):
        c = degradation([("toFailure", varied_set(n=12, drop=25, slow=0.4))])
        self.assertEqual(c.verdict, PASS)
        self.assertLess(c.numbers["toFailure"]["rho"], 0)
        self.assertTrue(c.numbers["toFailure"]["reached_failure"])

    def test_a_hard_set_whose_score_does_not_fall_fails(self):
        flat_but_slow = [rep(90, total_s=1.0 * (1 + 0.4 * i / 11),
                             range=0.8, control=0.8, smoothness=0.8)
                         for i in range(12)]
        c = degradation([("toFailure", flat_but_slow)])
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("did not fall", c.advice)

    def test_a_short_set_is_not_run(self):
        c = degradation([("short", varied_set(n=4, drop=20, slow=0.4))])
        self.assertEqual(c.verdict, NOT_RUN)
        self.assertIn("to genuine failure", c.advice)

    def test_a_drop_smaller_than_the_noise_floor_does_not_pass(self):
        """The whole point of measuring reliability first."""
        c = degradation([("toFailure", varied_set(n=12, drop=4, slow=0.4))],
                        noise=20.0)
        self.assertEqual(c.verdict, FAIL)


class TestSensitivity(unittest.TestCase):
    def test_no_degraded_sets_is_not_run(self):
        c = sensitivity([rep(90)], {})
        self.assertEqual(c.verdict, NOT_RUN)
        self.assertIn("you own the label", c.advice)

    def test_a_detected_fault_passes(self):
        c = sensitivity([rep(90)] * 5, {"range": [rep(60)] * 5}, noise=3.0)
        self.assertEqual(c.verdict, PASS)
        self.assertTrue(c.numbers["range"]["detected"])

    def test_a_fault_inside_the_noise_band_fails(self):
        c = sensitivity([rep(90)] * 5, {"tempo": [rep(88)] * 5}, noise=5.0)
        self.assertEqual(c.verdict, FAIL)
        self.assertIn("cannot see that fault", c.advice)


class TestRunOrder(unittest.TestCase):
    def test_reliability_noise_is_carried_into_the_other_checks(self):
        """Reliability establishes the scale; the later checks must use it."""
        sets = [("toFailure", varied_set(n=12, drop=6, slow=0.4))]
        pairs = [("setA", [rep(80)] * 5, [rep(60)] * 5)]     # noisy: floor 20
        checks = run(sets, pairs, {"range": [rep(76)] * 5})
        by = {c.name: c for c in checks}
        self.assertEqual(by["reliability"].numbers["noise_floor"], 20.0)
        # A 6-point degradation and a 4-point induced drop are both inside a
        # 20-point noise floor, so neither may be called real.
        self.assertEqual(by["degradation"].verdict, FAIL)
        self.assertEqual(by["sensitivity"].verdict, FAIL)

    def test_every_check_reports_something(self):
        checks = run([("a", varied_set(n=10, drop=20, slow=0.3))])
        self.assertEqual([c.name for c in checks],
                         ["ceiling", "reliability", "degradation", "sensitivity"])
        for c in checks:
            self.assertIn(c.verdict, (PASS, FAIL, INCONCLUSIVE, NOT_RUN))
            self.assertTrue(c.detail or c.advice, c.name)


class TestStatistics(unittest.TestCase):
    def test_a_constant_column_does_not_produce_a_spurious_correlation(self):
        """Ranking a constant by argsort gives a perfect correlation with the
        index. That artifact is exactly what a saturated component invites, and
        it is how a broken score would look validated."""
        from barra.validate_quality import _spearman
        rho, p = _spearman(np.arange(10), np.full(10, 0.9))
        self.assertTrue(np.isnan(rho), rho)


if __name__ == "__main__":
    unittest.main()


class TestReportWording(unittest.TestCase):
    def test_clip_names_are_not_mangled_by_capitalisation(self):
        """`.capitalize()` lowercases the rest of the string. The clip name is
        the one thing in the message you would grep for."""
        reps = [rep(90 + i, control=0.5 + 0.03 * i, smoothness=0.4 + 0.04 * i)
                for i in range(10)]
        c = ceiling([("VID-20260827-WA0020", reps)])
        self.assertIn("VID-20260827-WA0020", c.detail)
