import unittest

import numpy as np

from analysis.uncertainty import bootstrap_median_ci


class BootstrapMedianTest(unittest.TestCase):
    def test_interval_brackets_the_sample_median(self):
        values = np.random.default_rng(1).lognormal(mean=6.0, sigma=0.2, size=50)
        low, high = bootstrap_median_ci(values, np.random.default_rng(2))
        self.assertLessEqual(low, float(np.median(values)))
        self.assertGreaterEqual(high, float(np.median(values)))

    def test_constant_sample_has_zero_width_interval(self):
        values = np.full(50, 210.0)
        low, high = bootstrap_median_ci(values, np.random.default_rng(3))
        self.assertEqual((low, high), (210.0, 210.0))


if __name__ == "__main__":
    unittest.main()
