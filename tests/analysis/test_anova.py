import unittest

import numpy as np
import pandas as pd

from analysis.anova import box_cox_two_way_anova


def balanced_frame(seed: int, shift_a: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for a in range(2):
        for b in range(3):
            for _ in range(20):
                rows.append({"A": f"a{a}", "B": f"b{b}", "y": float(np.exp(rng.normal(1.0 + shift_a * a, 0.2)))})
    return pd.DataFrame(rows)


class TwoWayAnovaTest(unittest.TestCase):
    def test_detects_main_effect_of_factor_a(self):
        table = box_cox_two_way_anova(balanced_frame(seed=4, shift_a=0.8), "A", "B", "y")
        effect = table.set_index("source").loc["A"]
        self.assertLess(effect.p_value, 0.001)

    def test_residual_degrees_of_freedom_match_design(self):
        table = box_cox_two_way_anova(balanced_frame(seed=5, shift_a=0.0), "A", "B", "y")
        residual = table.set_index("source").loc["residual"]
        self.assertEqual(residual.df, 2 * 3 * 20 - 2 * 3)

    def test_rejects_unbalanced_design(self):
        frame = balanced_frame(seed=6, shift_a=0.0).iloc[:-1]
        with self.assertRaises(ValueError):
            box_cox_two_way_anova(frame, "A", "B", "y")


if __name__ == "__main__":
    unittest.main()
