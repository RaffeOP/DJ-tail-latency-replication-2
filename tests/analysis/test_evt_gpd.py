import unittest

import numpy as np
from scipy import stats

from analysis.evt_gpd import fit_grouped_gpd

TRUE_SHAPE = 0.3
TRUE_SCALE = 50.0
SHAPE_TOLERANCE = 0.05


def binned_gpd_sample(seed: int):
    rng = np.random.default_rng(seed)
    body = rng.uniform(20, 1000, size=200000)
    tail = 1000 + stats.genpareto.rvs(TRUE_SHAPE, scale=TRUE_SCALE, size=60000, random_state=seed)
    values, counts = np.unique(np.round(np.concatenate([body, tail])).astype(int), return_counts=True)
    return list(zip(values.tolist(), counts.tolist()))


class GroupedGpdTest(unittest.TestCase):
    def test_recovers_shape_of_known_gpd_tail(self):
        fit = fit_grouped_gpd(binned_gpd_sample(seed=1))
        self.assertEqual(fit["status"], "ok")
        self.assertLess(abs(fit["xi_shape"] - TRUE_SHAPE), SHAPE_TOLERANCE)

    def test_reports_standard_error_for_shape(self):
        fit = fit_grouped_gpd(binned_gpd_sample(seed=2))
        self.assertTrue(np.isfinite(fit["xi_shape_se"]))
        self.assertGreater(fit["xi_shape_se"], 0.0)

    def test_quantiles_are_monotone_in_probability(self):
        fit = fit_grouped_gpd(binned_gpd_sample(seed=3))
        self.assertLess(fit["threshold_ns"], fit["q0.999"])
        self.assertLess(fit["q0.999"], fit["q0.9999"])

    def test_refuses_fit_with_too_few_exceedances(self):
        fit = fit_grouped_gpd([(10, 100), (20, 5)])
        self.assertEqual(fit["status"], "insufficient_exceedances")


if __name__ == "__main__":
    unittest.main()
