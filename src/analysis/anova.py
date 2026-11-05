"""
Box-Cox transformed two-way parametric ANOVA for a balanced design.

The response is power-transformed with a maximum-likelihood lambda, then the
sums of squares are partitioned into factor A, factor B, interaction, and
residual. F statistics are referred to the F distribution.
"""

import numpy as np
import pandas as pd
from scipy import stats

MIN_RESPONSE_OFFSET = 1.0


def box_cox_transform(values: np.ndarray):
    """Returns the transformed values and the fitted lambda."""
    shifted = values - np.min(values) + MIN_RESPONSE_OFFSET if np.min(values) <= 0 else values
    transformed, lam = stats.boxcox(shifted)
    return transformed, float(lam)


def box_cox_two_way_anova(frame: pd.DataFrame, factor_a: str, factor_b: str, response: str) -> pd.DataFrame:
    transformed, lam = box_cox_transform(frame[response].to_numpy(dtype=np.float64))
    data = frame.assign(y=transformed)
    grand_mean = data["y"].mean()
    levels_a = data[factor_a].nunique()
    levels_b = data[factor_b].nunique()
    cells = data.groupby([factor_a, factor_b])["y"]
    replicates = int(cells.size().min())
    if int(cells.size().max()) != replicates:
        raise ValueError("ANOVA requires a balanced design")

    means_a = data.groupby(factor_a)["y"].mean()
    means_b = data.groupby(factor_b)["y"].mean()
    cell_means = cells.mean()
    ss_a = levels_b * replicates * float(np.sum((means_a - grand_mean) ** 2))
    ss_b = levels_a * replicates * float(np.sum((means_b - grand_mean) ** 2))
    with_cells = data.merge(cell_means.rename("cell_mean").reset_index(), on=[factor_a, factor_b])
    ss_error = float(np.sum((with_cells["y"] - with_cells["cell_mean"]) ** 2))
    ss_total = float(np.sum((data["y"] - grand_mean) ** 2))
    ss_ab = max(0.0, ss_total - ss_a - ss_b - ss_error)

    df_a, df_b = levels_a - 1, levels_b - 1
    df_ab = df_a * df_b
    df_error = len(data) - levels_a * levels_b
    ms_error = ss_error / df_error
    rows = []
    for source, ss, df in (
        (factor_a, ss_a, df_a),
        (factor_b, ss_b, df_b),
        (f"{factor_a} x {factor_b}", ss_ab, df_ab),
    ):
        f_value = (ss / df) / ms_error
        p_value = float(stats.f.sf(f_value, df, df_error))
        rows.append({"source": source, "ss": ss, "df": df, "F": f_value, "p_value": p_value,
                     "eta_squared": ss / ss_total, "partial_eta_squared": ss / (ss + ss_error),
                     "box_cox_lambda": lam})
    rows.append({"source": "residual", "ss": ss_error, "df": df_error, "F": np.nan, "p_value": np.nan,
                 "eta_squared": ss_error / ss_total, "partial_eta_squared": np.nan, "box_cox_lambda": lam})
    return pd.DataFrame(rows)
