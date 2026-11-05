import unittest

import numpy as np
from scipy import stats

from analysis.evt_gpd import extreme_quantile, fit_grouped_gpd

SAMPLE_SIZE = 400000
THRESHOLD = 1000.0
TRUE_SHAPE = 0.3
TRUE_SCALE = 50.0
RELATIVE_TOLERANCE = 0.10


class GpdQuantileTest(unittest.TestCase):
    def test_quantile_matches_known_gpd_tail(self):
        rng = np.random.default_rng(7)
        body = rng.uniform(20, THRESHOLD, size=SAMPLE_SIZE // 2)
        tail = THRESHOLD + stats.genpareto.rvs(TRUE_SHAPE, scale=TRUE_SCALE, size=SAMPLE_SIZE // 2, random_state=7)
        sample = np.concatenate([body, tail])
        values, counts = np.unique(np.round(sample).astype(int), return_counts=True)
        fit = fit_grouped_gpd(list(zip(values.tolist(), counts.tolist())), 95.0)
        empirical = float(np.percentile(sample, 99.9))
        self.assertLess(abs(fit["q0.999"] - empirical) / empirical, RELATIVE_TOLERANCE)

    def test_quantile_is_nan_below_threshold_tail_mass(self):
        self.assertTrue(np.isnan(extreme_quantile(100.0, 0.2, 10.0, 2.0, 0.4)))

    def test_exponential_limit_matches_closed_form(self):
        self.assertAlmostEqual(extreme_quantile(100.0, 0.0, 10.0, 4.0, 0.9), 100.0 - 10.0 * np.log(0.4))


if __name__ == "__main__":
    unittest.main()
