"""
src/table_probe_trace.py

Writes the appendix tables for the coherence stride probe, the page-release
probe, and the sustained trace workloads (tables/tabC1.tex to tabC3.tex). Each
cell is a summary of the per-repetition metrics CSVs in results/metrics/, which
the analysis pipeline derives from data/tier2/ and the probe JSON Lines files.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import math

import pandas as pd

from plots.style import ALLOCATOR_ORDER, METRICS_DIR
from table_generator import TABLE_DIR, booktabs

Z_95 = 1.96
POLICY_LABELS = {
    "none": "No release",
    "dontneed": "DONTNEED",
    "free": "FREE",
    "free_reusable": "FREE\\_REUSABLE",
}
POLICY_ORDER = ["none", "dontneed", "free", "free_reusable"]
WORKLOAD_LABELS = {"grpc_pipeline": "gRPC pipeline", "kv_churn": "KV churn", "ast_graph": "AST graph"}
WORKLOAD_ORDER = ["grpc_pipeline", "kv_churn", "ast_graph"]


def format_integer(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", "{,}")


def stride_table() -> str:
    frame = pd.read_csv(METRICS_DIR / "probe_false_sharing.csv")
    rows = []
    for row in frame.sort_values(["threads", "stride_bytes"]).itertuples():
        half_width = Z_95 * row.ns_per_increment_sd / math.sqrt(row.reps)
        cpi = row.cycles_per_increment_mean / row.instructions_per_increment_mean
        rows.append(
            f"{row.stride_bytes} & {row.threads} & {row.ns_per_increment_mean:.2f} $\\pm$ {half_width:.2f} & "
            f"{row.cycles_per_increment_mean:.1f} & {row.instructions_per_increment_mean:.2f} & {cpi:.2f} \\\\"
        )
    header = ("Stride (B) & Threads & ns/op (95\\% CI) & Cycles/op & Instr./op & CPI\\\\")
    return booktabs("Relaxed atomic increment cost by stride on 8-core heterogeneous processor, 2 and 4 threads. Each row averages "
                    "20 repetitions. Cycles come from the process counters of the probe.",
                    "tab:stride", "rrrrrr", header, rows, size=r"\scriptsize")


def purge_table() -> str:
    frame = pd.read_csv(METRICS_DIR / "probe_purge_runs.csv")
    rows = []
    for policy in POLICY_ORDER:
        for interval in (50, 200, 1000):
            cell = frame[(frame.policy == policy) & (frame.interval_ms == interval)]
            rows.append(
                f"{POLICY_LABELS[policy]} & {interval} & {cell.footprint_min_mb.mean():.1f} & "
                f"{cell.footprint_mean_mb.mean():.1f} & {cell.access_p99_9_ns.median():.0f} & "
                f"{cell.access_p99_99_ns.median():.0f} & {cell.purge_p99_9_us.median():.1f} & "
                f"{cell.page_faults.median():.0f} \\\\"
            )
    header = (r"Advice & \shortstack{Period\\(ms)} & \shortstack{Min\\(MB)} & \shortstack{Mean\\(MB)} & "
              r"\shortstack{Access\\P99.9} & \shortstack{Access\\P99.99} & \shortstack{Purge\\P99.9} & "
              r"\shortstack{Faults\\(median)}\\")
    return booktabs("Page-release probe on 8-core heterogeneous hardware under Unix-based OS. Min and mean are footprints in MB, means over "
                    "five repetitions. Access latencies are in ns, purge latency in $\\mu$s; those values and faults are medians.",
                    "tab:purge", "llrrrrrr", header, rows, size=r"\scriptsize")


def trace_table() -> str:
    frame = pd.read_csv(METRICS_DIR / "tier2_trace_runs.csv")
    rows = []
    for workload in WORKLOAD_ORDER:
        for allocator in ALLOCATOR_ORDER:
            cell = frame[(frame.workload == workload) & (frame.allocator == allocator)]
            rows.append(
                f"{WORKLOAD_LABELS[workload]} & {allocator} & {len(cell)} & "
                f"{cell.throughput_mops.median():.2f} & {cell.peak_footprint_mb.median():.1f} & "
                f"{cell.peak_live_mb.median():.1f} & {cell.bloat_ratio.median():.2f} & "
                f"{format_integer(cell.event_p99_9_ns.median())} \\\\"
            )
    header = (r"Workload & Allocator & $n$ & \shortstack{Throughput\\(Mops/s)} & "
              r"\shortstack{Peak footprint\\(MB)} & \shortstack{Peak live\\(MB)} & "
              r"\shortstack{Bloat\\ratio} & \shortstack{Event P99.9\\(ns)}\\")
    return booktabs("Sustained trace workloads on 8-core heterogeneous hardware under Unix-based OS. Each cell reports medians "
                    "over $n$ repetitions. Bloat is peak footprint divided by peak live bytes.",
                    "tab:trace", "llrrrrrr", header, rows, size=r"\scriptsize")


def generate_probe_trace_tables() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "tabC1.tex": stride_table(),
        "tabC2.tex": purge_table(),
        "tabC3.tex": trace_table(),
    }
    for name, content in outputs.items():
        (TABLE_DIR / name).write_text(content)


if __name__ == "__main__":
    generate_probe_trace_tables()
