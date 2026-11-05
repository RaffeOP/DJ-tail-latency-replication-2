"""
Grouped maximum-likelihood fit of the Generalized Pareto Distribution (GPD)
to binned latency data above a high threshold u (Pickands-Balkema-de Haan).

The likelihood treats each occupied bucket's representative value as the
observation and its count as the weight. Bucket width is at most 3.1% of the
value, so the representative error is bounded by about 1.6%.
"""

from typing import Dict, Sequence

import numpy as np
from scipy import optimize

from analysis.histogram_pool import Bucket, total_count, weighted_percentile

MIN_EXCEEDANCES = 30
SHAPE_EPSILON = 1e-8
INITIAL_SHAPE = 0.1
HESSIAN_STEP = 1e-4
QUANTILE_PROBABILITIES = (0.999, 0.9999)
PENALTY_NLL = 1e18


def gpd_log_density(excess: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """Log density of GPD(xi, sigma) at excesses; exponential limit at xi = 0."""
    if abs(shape) < SHAPE_EPSILON:
        return -np.log(scale) - excess / scale
    base = 1.0 + shape * excess / scale
    return -np.log(scale) - (1.0 / shape + 1.0) * np.log(base)


def negative_log_likelihood(params: np.ndarray, excess: np.ndarray, weights: np.ndarray) -> float:
    shape = float(params[0])
    scale = float(np.exp(params[1]))
    if abs(shape) >= SHAPE_EPSILON and np.any(1.0 + shape * excess / scale <= 0.0):
        return PENALTY_NLL
    return float(-np.sum(weights * gpd_log_density(excess, shape, scale)))


def observed_information_covariance(params: np.ndarray, excess: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Inverse of the numerical Hessian of the negative log-likelihood."""
    dimension = len(params)
    hessian = np.zeros((dimension, dimension))
    for i in range(dimension):
        for j in range(dimension):
            step_i = np.zeros(dimension)
            step_j = np.zeros(dimension)
            step_i[i] = HESSIAN_STEP
            step_j[j] = HESSIAN_STEP
            hessian[i, j] = (
                negative_log_likelihood(params + step_i + step_j, excess, weights)
                - negative_log_likelihood(params + step_i - step_j, excess, weights)
                - negative_log_likelihood(params - step_i + step_j, excess, weights)
                + negative_log_likelihood(params - step_i - step_j, excess, weights)
            ) / (4.0 * HESSIAN_STEP * HESSIAN_STEP)
    try:
        return np.linalg.inv(hessian)
    except np.linalg.LinAlgError:
        return np.full((dimension, dimension), np.nan)


def extreme_quantile(threshold: float, shape: float, scale: float, total_over_exceedances: float,
                     probability: float) -> float:
    """Parametric quantile Q(p) = u + sigma/xi * [((N/N_u)(1-p))^(-xi) - 1].

    The argument is N/N_u. The quantile lies above u only when (N/N_u)(1-p) < 1,
    so the function returns NaN for any probability below the threshold's tail mass.
    """
    scaled_tail = total_over_exceedances * (1.0 - probability)
    if scaled_tail >= 1.0:
        return float("nan")
    if abs(shape) < SHAPE_EPSILON:
        return threshold - scale * np.log(scaled_tail)
    return threshold + (scale / shape) * (scaled_tail ** (-shape) - 1.0)


def fit_grouped_gpd(buckets: Sequence[Bucket], threshold_percent: float = 95.0) -> Dict[str, object]:
    """Fits GPD above the weighted threshold percentile and returns parameters with SEs."""
    total = total_count(buckets)
    threshold = weighted_percentile(buckets, threshold_percent)
    values = np.array([value for value, _ in buckets], dtype=np.float64)
    counts = np.array([count for _, count in buckets], dtype=np.float64)
    above = values > threshold
    excess = values[above] - threshold
    weights = counts[above]
    exceedances = float(weights.sum())
    if exceedances < MIN_EXCEEDANCES:
        return {"status": "insufficient_exceedances", "threshold_ns": float(threshold), "n_exceedances": exceedances}

    initial_scale = float(np.average(excess, weights=weights))
    start = np.array([INITIAL_SHAPE, np.log(max(initial_scale, 1.0))])
    fit = optimize.minimize(negative_log_likelihood, start, args=(excess, weights), method="Nelder-Mead",
                            options={"xatol": 1e-8, "fatol": 1e-8, "maxiter": 5000})
    shape, scale = float(fit.x[0]), float(np.exp(fit.x[1]))
    covariance = observed_information_covariance(fit.x, excess, weights)
    shape_se = float(np.sqrt(covariance[0, 0])) if np.isfinite(covariance[0, 0]) else float("nan")
    rate = total / exceedances
    quantiles = {
        f"q{probability}": extreme_quantile(threshold, shape, scale, rate, probability)
        for probability in QUANTILE_PROBABILITIES
    }
    return {
        "status": "ok" if fit.success else "not_converged",
        "threshold_ns": float(threshold),
        "n_total": float(total),
        "n_exceedances": exceedances,
        "xi_shape": shape,
        "xi_shape_se": shape_se,
        "sigma_scale_ns": scale,
        "log_likelihood": -float(fit.fun),
        **quantiles,
    }
