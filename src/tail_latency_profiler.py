"""
src/tail_latency_profiler.py

Tier 1 analysis. Pools latency histograms per configuration across repetitions,
fits grouped Generalized Pareto tails, computes the tail-amplification factor,
fits Gunther's USL to symmetric throughput, and runs a Box-Cox two-way ANOVA.
Writes CSV and JSON artifacts to results/metrics/.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.anova import box_cox_two_way_anova  # noqa: E402
from analysis.evt_gpd import fit_grouped_gpd  # noqa: E402
from analysis.histogram_pool import pool_buckets, weighted_mean, weighted_percentile  # noqa: E402
from analysis.usl_model import fit_usl  # noqa: E402

WORKSPACE = Path(__file__).resolve().parent.parent
TIER1_INPUT = WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl"
METRICS = WORKSPACE / "results" / "metrics"

TAIL_PERCENT = 99.9
SHAPE_SPREAD_TOPOLOGIES = ["asymmetric_8_1", "ring"]
ANOVA_SIZES = [64, 4096]
ANOVA_THREADS = 8
USL_SIZES = [64, 4096]
USL_BASELINE_THREADS = 1


def load_successful_records(path: Path):
    records, failures = [], 0
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            if "error" in record:
                failures += 1
                continue
            records.append(record)
    return records, failures


def group_by_configuration(records):
    groups = {}
    for record in records:
        key = (record["allocator"], record["size"], record["threads"], record["topology"])
        groups.setdefault(key, []).append(record["result"])
    return groups


def event_buckets(results, role: str):
    """Pools alloc, free, or both event histograms across iterations."""
    if role == "event":
        lists = [r["alloc_counts"] for r in results] + [r["free_counts"] for r in results]
    else:
        lists = [r[f"{role}_counts"] for r in results]
    return pool_buckets(lists)


def tail_row(results, key):
    allocator, size, threads, topology = key
    pooled = event_buckets(results, "event")
    tail = fit_grouped_gpd(pooled)
    row = {
        "allocator": allocator, "size_bytes": size, "threads": threads, "topology": topology,
        "replicates": len(results),
        "effective_ratio": results[0]["effective_ratio"],
        "throughput_mops_mean": float(np.mean([r["throughput_ops_per_sec"] for r in results])) / 1e6,
        "throughput_mops_sd": float(np.std([r["throughput_ops_per_sec"] for r in results], ddof=1)) / 1e6,
        "event_mean_ns": weighted_mean(pooled),
        "event_p99_ns": weighted_percentile(pooled, 99.0),
        "event_p99_9_ns": weighted_percentile(pooled, TAIL_PERCENT),
        "event_p99_99_ns": weighted_percentile(pooled, 99.99),
        "gpd_status": tail["status"],
        "gpd_xi": tail.get("xi_shape", math.nan),
        "gpd_xi_se": tail.get("xi_shape_se", math.nan),
        "gpd_sigma_ns": tail.get("sigma_scale_ns", math.nan),
        "gpd_threshold_ns": tail.get("threshold_ns", math.nan),
        "gpd_exceedances": tail.get("n_exceedances", math.nan),
        "gpd_q999_ns": tail.get("q0.999", math.nan),
        "gpd_q9999_ns": tail.get("q0.9999", math.nan),
    }
    for role in ("alloc", "free"):
        role_buckets = event_buckets(results, role)
        role_fit = fit_grouped_gpd(role_buckets)
        row[f"{role}_p99_9_ns"] = weighted_percentile(role_buckets, TAIL_PERCENT)
        row[f"{role}_gpd_xi"] = role_fit.get("xi_shape", math.nan)
    return row


def add_amplification(frame: pd.DataFrame) -> pd.DataFrame:
    """Gamma_tail = P99.9 event latency / mean event cost of symmetric T=1 for the same allocator and size."""
    baseline = frame[(frame.topology == "symmetric") & (frame.threads == USL_BASELINE_THREADS)]
    means = baseline.set_index(["allocator", "size_bytes"])["event_mean_ns"]
    frame["gamma_tail"] = [
        row.event_p99_9_ns / means.loc[(row.allocator, row.size_bytes)] for row in frame.itertuples()
    ]
    return frame


def usl_rows(frame: pd.DataFrame):
    rows = []
    for size in USL_SIZES:
        for allocator, sub in frame[(frame.topology == "symmetric") & (frame.size_bytes == size)].groupby("allocator"):
            sub = sub.sort_values("threads")
            base = sub[sub.threads == USL_BASELINE_THREADS]["throughput_mops_mean"].iloc[0]
            threads = sub["threads"].to_numpy(dtype=float)
            speedup = sub["throughput_mops_mean"].to_numpy(dtype=float) / base
            fit = fit_usl(threads, speedup)
            rows.append({"allocator": allocator, "size_bytes": size, **fit,
                         "threads_list": ",".join(str(int(t)) for t in threads),
                         "speedup_list": ",".join(f"{s:.6f}" for s in speedup)})
    return rows


def iteration_shape_rows(groups) -> list:
    """Per-iteration GPD shape spread for the 8:1 and ring topologies at 8 threads."""
    rows = []
    for key, results in sorted(groups.items()):
        allocator, size, threads, topology = key
        if threads != ANOVA_THREADS or topology not in SHAPE_SPREAD_TOPOLOGIES:
            continue
        shapes = []
        for result in results:
            fit = fit_grouped_gpd(pool_buckets([result["alloc_counts"], result["free_counts"]]))
            shapes.append(fit.get("xi_shape", math.nan))
        shapes = np.array(shapes, dtype=float)
        rows.append({"allocator": allocator, "size_bytes": size, "topology": topology,
                     "xi_iteration_mean": float(np.nanmean(shapes)),
                     "xi_iteration_sd": float(np.nanstd(shapes, ddof=1)),
                     "iterations": int(np.isfinite(shapes).sum())})
    return rows


def anova_frame(records, size: int) -> pd.DataFrame:
    rows = []
    for record in records:
        if record["size"] != size or record["threads"] != ANOVA_THREADS:
            continue
        buckets = pool_buckets([record["result"]["alloc_counts"], record["result"]["free_counts"]])
        rows.append({"allocator": record["allocator"], "topology": record["topology"],
                     "iteration": record["iteration"],
                     "p99_9_ns": weighted_percentile(buckets, TAIL_PERCENT)})
    return pd.DataFrame(rows)


def main() -> int:
    METRICS.mkdir(parents=True, exist_ok=True)
    records, failures = load_successful_records(TIER1_INPUT)
    groups = group_by_configuration(records)
    frame = pd.DataFrame([tail_row(results, key) for key, results in sorted(groups.items())])
    frame = add_amplification(frame)
    frame.to_csv(METRICS / "tier1_configs.csv", index=False)

    pd.DataFrame(iteration_shape_rows(groups)).to_csv(METRICS / "tier1_gpd_iteration_spread.csv", index=False)

    usl = pd.DataFrame(usl_rows(frame))
    usl.to_csv(METRICS / "tier1_usl.csv", index=False)

    for size in ANOVA_SIZES:
        table = box_cox_two_way_anova(anova_frame(records, size), "allocator", "topology", "p99_9_ns")
        table.to_csv(METRICS / f"tier1_anova_{size}.csv", index=False)

    summary = {"records": len(records), "failed_runs": failures, "configurations": len(groups),
               "iterations_min": int(frame.replicates.min()), "iterations_max": int(frame.replicates.max())}
    (METRICS / "tier1_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
