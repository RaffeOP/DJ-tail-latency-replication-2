"""
Gunther's Universal Scalability Law fitted to measured speedups.

S(T) = T / (1 + sigma_c (T - 1) + kappa_c T (T - 1)); the saturation point is
T* = floor(sqrt((1 - sigma_c) / kappa_c)). Standard errors come from the
covariance matrix of the nonlinear least-squares fit.
"""

from typing import Dict

import numpy as np
from scipy.optimize import curve_fit

INITIAL_GUESS = [0.02, 0.001]
PARAMETER_BOUNDS = ([0.0, 0.0], [1.0, 0.5])
MAX_FUNCTION_EVALUATIONS = 5000


def universal_scalability_law(threads: np.ndarray, sigma_c: float, kappa_c: float) -> np.ndarray:
    t = np.asarray(threads, dtype=np.float64)
    return t / (1.0 + sigma_c * (t - 1.0) + kappa_c * t * (t - 1.0))


def fit_usl(threads: np.ndarray, speedup: np.ndarray) -> Dict[str, float]:
    popt, pcov = curve_fit(universal_scalability_law, threads, speedup, p0=INITIAL_GUESS,
                           bounds=PARAMETER_BOUNDS, maxfev=MAX_FUNCTION_EVALUATIONS)
    sigma_c, kappa_c = float(popt[0]), float(popt[1])
    standard_errors = np.sqrt(np.diag(pcov))
    if kappa_c > 0.0 and sigma_c < 1.0:
        saturation = float(np.floor(np.sqrt((1.0 - sigma_c) / kappa_c)))
    else:
        saturation = float("inf")
    residuals = speedup - universal_scalability_law(threads, sigma_c, kappa_c)
    total = speedup - np.mean(speedup)
    r_squared = 1.0 - float(np.sum(residuals ** 2)) / float(np.sum(total ** 2))
    return {
        "sigma_c": sigma_c,
        "sigma_c_se": float(standard_errors[0]),
        "kappa_c": kappa_c,
        "kappa_c_se": float(standard_errors[1]),
        "t_star": saturation,
        "r_squared": r_squared,
    }
