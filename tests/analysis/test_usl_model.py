import unittest

import numpy as np

from analysis.usl_model import fit_usl, universal_scalability_law

THREADS = np.array([1, 2, 4, 8, 16, 32], dtype=float)


class UslModelTest(unittest.TestCase):
    def test_recovers_parameters_from_noiseless_curve(self):
        speedup = universal_scalability_law(THREADS, 0.05, 0.002)
        fit = fit_usl(THREADS, speedup)
        self.assertAlmostEqual(fit["sigma_c"], 0.05, places=4)
        self.assertAlmostEqual(fit["kappa_c"], 0.002, places=5)

    def test_saturation_point_matches_closed_form(self):
        speedup = universal_scalability_law(THREADS, 0.05, 0.002)
        fit = fit_usl(THREADS, speedup)
        self.assertEqual(fit["t_star"], np.floor(np.sqrt((1 - 0.05) / 0.002)))

    def test_perfect_fit_has_unit_r_squared(self):
        speedup = universal_scalability_law(THREADS, 0.1, 0.001)
        self.assertAlmostEqual(fit_usl(THREADS, speedup)["r_squared"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
