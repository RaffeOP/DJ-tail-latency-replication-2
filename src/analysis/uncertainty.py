"""
Per-iteration uncertainty of the P99.9 event latency: bootstrap intervals of the
median over the 50 iterations of each configuration, and per-iteration quartiles.
"""

import json

import numpy as np
import pandas as pd

from analysis.histogram_pool import pool_buckets, weighted_percentile

BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE = 0.95
RANDOM_SEED = 20261023
TAIL_PERCENT = 99.9


def per_iteration_p999(records) -> pd.DataFrame:
    rows = []
    for record in records:
        buckets = pool_buckets([record["result"]["alloc_counts"], record["result"]["free_counts"]])
        rows.append({"allocator": record["allocator"], "size_bytes": record["size"],
                     "threads": record["threads"], "topology": record["topology"],
                     "iteration": record["iteration"],
                     "p999_ns": weighted_percentile(buckets, TAIL_PERCENT)})
    return pd.DataFrame(rows)


def bootstrap_median_ci(values: np.ndarray, generator: np.random.Generator) -> tuple:
    draws = generator.choice(values, size=(BOOTSTRAP_RESAMPLES, values.size), replace=True)
    medians = np.median(draws, axis=1)
    lower = (1.0 - CONFIDENCE) / 2.0
    return float(np.quantile(medians, lower)), float(np.quantile(medians, 1.0 - lower))


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    generator = np.random.default_rng(RANDOM_SEED)
    rows = []
    for key, group in frame.groupby(["allocator", "size_bytes", "threads", "topology"]):
        values = group.p999_ns.to_numpy(dtype=float)
        low, high = bootstrap_median_ci(values, generator)
        rows.append({"allocator": key[0], "size_bytes": key[1], "threads": key[2], "topology": key[3],
                     "iterations": values.size, "median_p999_ns": float(np.median(values)),
                     "ci_low_ns": low, "ci_high_ns": high,
                     "q25_ns": float(np.quantile(values, 0.25)), "q75_ns": float(np.quantile(values, 0.75))})
    return pd.DataFrame(rows)


def read_records(path) -> list:
    with path.open() as handle:
        return [json.loads(line) for line in handle if '"error"' not in line]
