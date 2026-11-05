"""
src/workload_probe_analyzer.py

Tier 2 and probe analysis. Summarizes sustained trace runs (footprint bloat,
latency tails), the page-release probe (footprint and purge/access tails per
policy and interval), and the coherence-stride probe. Writes CSV artifacts to
results/metrics/.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.histogram_pool import pool_buckets, weighted_percentile  # noqa: E402

WORKSPACE = Path(__file__).resolve().parent.parent
TIER2_INPUT = WORKSPACE / "data" / "tier2" / "trace_runs.jsonl"
PROBE_INPUT = WORKSPACE / "data" / "tier2" / "probes_v2.jsonl"
METRICS = WORKSPACE / "results" / "metrics"
TAIL_PERCENT = 99.9
BYTES_PER_MB = 1 << 20


def read_jsonl(path: Path):
    records, failures = [], []
    if not path.exists():
        return records, failures
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            (failures if "error" in record else records).append(record)
    return records, failures


def trace_summary(records) -> pd.DataFrame:
    rows = []
    for record in records:
        result = record["result"]
        pooled = pool_buckets([result["alloc_counts"], result["free_counts"]])
        rows.append({
            "workload": record["workload"], "allocator": record["allocator"],
            "repetition": record["repetition"],
            "throughput_mops": result["throughput_ops_per_sec"] / 1e6,
            "peak_footprint_mb": result["peak_footprint_bytes"] / BYTES_PER_MB,
            "peak_live_mb": result["peak_live_bytes"] / BYTES_PER_MB,
            "bloat_ratio": result["peak_footprint_bytes"] / result["peak_live_bytes"],
            "event_p99_9_ns": weighted_percentile(pooled, TAIL_PERCENT),
        })
    return pd.DataFrame(rows)


def trace_timeseries(records) -> pd.DataFrame:
    rows = []
    for record in records:
        if record["repetition"] != 0:
            continue
        for sample in record["result"]["samples"]:
            rows.append({"workload": record["workload"], "allocator": record["allocator"],
                         "t_s": sample["t"], "footprint_mb": sample["footprint"] / BYTES_PER_MB,
                         "live_mb": sample["live"] / BYTES_PER_MB})
    return pd.DataFrame(rows)


def purge_timeseries(records) -> pd.DataFrame:
    rows = []
    for record in records:
        if record.get("stage") != "purge" or record["repetition"] != 0 or record["interval_ms"] != 200:
            continue
        for sample in record["result"]["samples"]:
            rows.append({"policy": record["policy"], "t_s": sample["t"],
                         "footprint_mb": sample["footprint"] / BYTES_PER_MB})
    return pd.DataFrame(rows)


def purge_summary(records) -> pd.DataFrame:
    rows = []
    for record in records:
        if record.get("stage") != "purge":
            continue
        result = record["result"]
        footprints = np.array([s["footprint"] for s in result["samples"]], dtype=float) / BYTES_PER_MB
        rows.append({
            "policy": record["policy"], "interval_ms": record["interval_ms"], "repetition": record["repetition"],
            "footprint_min_mb": footprints.min(), "footprint_mean_mb": footprints.mean(),
            "footprint_max_mb": footprints.max(),
            "purge_p99_9_us": result["purge_latency_ns"]["p99_9"] / 1e3,
            "reuse_p99_9_us": result["reuse_latency_ns"]["p99_9"] / 1e3,
            "access_p99_9_ns": result["access_latency_ns"]["p99_9"],
            "access_p99_99_ns": result["access_latency_ns"]["p99_99"],
            "purge_calls_per_s": result["purge_calls"] / result["wall_seconds"],
            "page_faults": result["page_faults"],
            "cow_faults": result["cow_faults"],
        })
    return pd.DataFrame(rows)


def stride_summary(records) -> pd.DataFrame:
    rows = []
    for record in records:
        if record.get("stage") != "false_sharing":
            continue
        values = np.array(record["result"]["ns_per_increment"], dtype=float)
        cycles = np.array(record["result"]["cycles_per_increment"], dtype=float)
        instructions = np.array(record["result"]["instructions_per_increment"], dtype=float)
        rows.append({"stride_bytes": record["stride_bytes"], "threads": record["threads"],
                     "ns_per_increment_mean": values.mean(), "ns_per_increment_sd": values.std(ddof=1),
                     "cycles_per_increment_mean": cycles.mean(),
                     "instructions_per_increment_mean": instructions.mean(),
                     "reps": len(values)})
    return pd.DataFrame(rows).sort_values(["threads", "stride_bytes"])


SUPPLEMENT_INPUTS = [WORKSPACE / "data" / "ablation" / "libmalloc_kv_recheck.jsonl",
                     WORKSPACE / "data" / "ablation" / "kv_control_recheck.jsonl"]


def supplement_summary() -> pd.DataFrame:
    """Supplementary KV-churn runs taken after the main batch, for the same allocators."""
    rows = []
    for path in SUPPLEMENT_INPUTS:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            record = json.loads(line)
            rows.append({"allocator": record["allocator"], "workload": "kv_churn",
                         "seed": record["seed"],
                         "peak_footprint_mb": record["peak_footprint_bytes"] / BYTES_PER_MB,
                         "peak_live_mb": record["peak_live_bytes"] / BYTES_PER_MB,
                         "bloat_ratio": record["peak_footprint_bytes"] / record["peak_live_bytes"]})
    return pd.DataFrame(rows)


def main() -> int:
    METRICS.mkdir(parents=True, exist_ok=True)
    trace_records, trace_failures = read_jsonl(TIER2_INPUT)
    probe_records, probe_failures = read_jsonl(PROBE_INPUT)
    if trace_records:
        trace_summary(trace_records).to_csv(METRICS / "tier2_trace_runs.csv", index=False)
        trace_timeseries(trace_records).to_csv(METRICS / "tier2_footprint_timeseries.csv", index=False)
    supplement_summary().to_csv(METRICS / "tier2_kv_supplement.csv", index=False)
    if probe_records:
        purge_summary(probe_records).to_csv(METRICS / "probe_purge_runs.csv", index=False)
        stride_summary(probe_records).to_csv(METRICS / "probe_false_sharing.csv", index=False)
        purge_timeseries(probe_records).to_csv(METRICS / "probe_purge_timeseries.csv", index=False)
    print(json.dumps({"trace_runs": len(trace_records), "trace_failures": len(trace_failures),
                      "probe_runs": len(probe_records), "probe_failures": len(probe_failures)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
