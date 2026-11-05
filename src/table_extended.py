"""
src/table_extended.py

Writes the extended appendix tables: producer and consumer tails (tabA6, tabA7),
allocation throughput and payload bandwidth (tabA8), the Box-Cox two-way ANOVA across
all eight size classes (tabA9), GPD threshold sensitivity (tabA10), 4:1 and ring thread
scaling (tabB11), and USL fits across all eight size classes (tabB12).

ANOVA, GPD, and USL values are recomputed from data/tier1/micro_sweeps.jsonl. Pooled
percentiles and means come from results/metrics/tier1_configs.csv, which the analysis
pipeline derives from the same file.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from analysis.anova import box_cox_two_way_anova
from analysis.evt_gpd import fit_grouped_gpd
from analysis.histogram_pool import pool_buckets, weighted_percentile
from analysis.uncertainty import read_records
from analysis.usl_model import fit_usl
from plots.style import ALLOCATOR_ORDER, METRICS_DIR
from table_appendix import ATLAS_SIZES, format_integer, lookup
from table_generator import PRIMARY_THREADS, TABLE_DIR, booktabs, format_p_value
from tail_latency_profiler import anova_frame

WORKSPACE = Path(__file__).resolve().parent.parent
RAW_PATH = WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl"
SYMMETRIC = "symmetric"
HANDOFF_4_1 = "asymmetric_4_1"
HANDOFF_8_1 = "asymmetric_8_1"
RING = "ring"
SCALING_THREADS = (2, 4, 8, 16, 32)
GPD_SIZES = (64, 4096)
GPD_THRESHOLDS = (90.0, 92.5, 95.0, 97.5, 98.0)
TAIL_PERCENT = 99.9
USL_BASELINE_THREADS = 1
BYTES_PER_GIB = 2 ** 30
MEGA = 1e6
ALLOCATOR_HEADER = " & ".join(ALLOCATOR_ORDER)
ANOVA_CSV = METRICS_DIR / "tier1_anova_all_sizes.csv"
USL_CSV = METRICS_DIR / "tier1_usl_all_sizes.csv"


def producer_consumer_rows(configs: pd.DataFrame, topologies: tuple) -> list:
    rows = []
    for size in ATLAS_SIZES:
        for allocator in ALLOCATOR_ORDER:
            cells = []
            for topology in topologies:
                cells.append(format_integer(lookup(configs, allocator, size, PRIMARY_THREADS, topology,
                                                   "alloc_p99_9_ns")))
                cells.append(format_integer(lookup(configs, allocator, size, PRIMARY_THREADS, topology,
                                                   "free_p99_9_ns")))
            rows.append(f"{size} & {allocator} & " + " & ".join(cells) + " \\\\")
    return rows


def table_a6(configs: pd.DataFrame) -> str:
    rows = []
    for size in ATLAS_SIZES:
        for allocator in ALLOCATOR_ORDER:
            pooled = lookup(configs, allocator, size, PRIMARY_THREADS, HANDOFF_8_1, "event_p99_9_ns")
            producer = lookup(configs, allocator, size, PRIMARY_THREADS, HANDOFF_8_1, "alloc_p99_9_ns")
            consumer = lookup(configs, allocator, size, PRIMARY_THREADS, HANDOFF_8_1, "free_p99_9_ns")
            rows.append(f"{size} & {allocator} & {format_integer(producer)} & {format_integer(consumer)} & "
                        f"{format_integer(pooled)} \\\\")
    header = "Size (B) & Allocator & Producer alloc $P_{99.9}$ & Consumer free $P_{99.9}$ & Pooled $P_{99.9}$\\\\"
    return booktabs("Producer-side allocation and consumer-side remote-free P99.9 latency (ns) under 8:1 handoff at "
                    "8 threads, all eight size classes. Pooled P99.9 is the event percentile over both paths.",
                    "tab:producer-consumer-8to1", "llrrr", header, rows)


def table_a7(configs: pd.DataFrame) -> str:
    rows = producer_consumer_rows(configs, (HANDOFF_4_1, RING))
    header = ("Size (B) & Allocator & 4:1 producer & 4:1 consumer & Ring producer & Ring consumer\\\\")
    return booktabs("Producer-side allocation and consumer-side remote-free P99.9 latency (ns) under 4:1 and "
                    "ring handoff at 8 threads, all eight size classes.",
                    "tab:producer-consumer-4to1-ring", "llrrrr", header, rows, size=r"\scriptsize")


def throughput_row(configs: pd.DataFrame, allocator: str, size: int) -> str:
    topologies = (SYMMETRIC, HANDOFF_4_1, HANDOFF_8_1, RING)
    mops = [lookup(configs, allocator, size, PRIMARY_THREADS, topology, "throughput_mops_mean")
            for topology in topologies]
    gib_per_s = [value * MEGA * size / BYTES_PER_GIB for value in mops]
    cells = [f"{value:.2f}" for value in mops] + [f"{value:.2f}" for value in gib_per_s]
    return f"{size} & {allocator} & " + " & ".join(cells) + " \\\\"


def table_a8(configs: pd.DataFrame) -> str:
    rows = [throughput_row(configs, allocator, size) for size in ATLAS_SIZES for allocator in ALLOCATOR_ORDER]
    spanning = ("& & \\multicolumn{4}{c}{Throughput (Mops/s)} & \\multicolumn{4}{c}{Payload bandwidth (GiB/s)}\\\\\n"
                "\\cmidrule(lr){3-6} \\cmidrule(lr){7-10}\n")
    labels = ("Size (B) & Allocator & Sym. & 4:1 & 8:1 & Ring & Sym. & 4:1 & 8:1 & Ring\\\\")
    return booktabs("Mean throughput and payload bandwidth at 8 threads for four topologies, all eight size classes. "
                    "Payload bandwidth is operations per second times object size, counting each allocation once.",
                    "tab:throughput-bandwidth", "llrrrrrrrr", spanning + labels, rows, size=r"\scriptsize")


def anova_rows_for_size(records: list, size: int) -> pd.DataFrame:
    table = box_cox_two_way_anova(anova_frame(records, size), "allocator", "topology", "p99_9_ns")
    table = table.copy()
    table["size_bytes"] = size
    return table


def anova_all_sizes(records: list) -> pd.DataFrame:
    frames = [anova_rows_for_size(records, size) for size in ATLAS_SIZES]
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(ANOVA_CSV, index=False)
    return combined


def anova_latex_row(row) -> str:
    if row.source == "residual":
        return f"{row.size_bytes} & Residual & {row.df} & -- & -- & {row.eta_squared:.3f} & -- & -- \\\\"
    return (f"{row.size_bytes} & {row.source.replace('_', ' ')} & {row.df} & {row.F:.2f} & "
            f"{format_p_value(row.p_value)} & {row.eta_squared:.3f} & {row.partial_eta_squared:.3f} & "
            f"{row.box_cox_lambda:.3f} \\\\")


def table_a9(anova: pd.DataFrame) -> str:
    rows = [anova_latex_row(row) for row in anova.itertuples()]
    header = ("Size (B) & Source & df & $F$ & $p$ & $\\eta^2$ & $\\eta_p^2$ & $\\hat{\\lambda}$\\\\")
    return booktabs("Box-Cox two-way parametric ANOVA on per-iteration P99.9 event latency at 8 threads, "
                    "all eight size classes. Factors are allocator (5 levels) and topology (4 levels), 50 replicates "
                    "per cell. The Box-Cox parameter $\\hat{\\lambda}$ is fitted per size class.",
                    "tab:anova-all", "llrrrrrr", header, rows, size=r"\scriptsize")


def pooled_tail_buckets(records: list) -> dict:
    grouped = {}
    for record in records:
        if record["threads"] != PRIMARY_THREADS or record["topology"] != HANDOFF_8_1:
            continue
        key = (record["allocator"], record["size"])
        grouped.setdefault(key, []).append(record["result"])
    return {key: pool_buckets([r["alloc_counts"] for r in group] + [r["free_counts"] for r in group])
            for key, group in grouped.items()}


def gpd_cell(buckets: list, threshold: float, empirical: float) -> str:
    fit = fit_grouped_gpd(buckets, threshold)
    if fit["status"] != "ok":
        return "--"
    error = 100.0 * (fit["q0.999"] - empirical) / empirical
    return f"{fit['xi_shape']:.3f} ({error:+.1f})"


def table_a10(records: list) -> str:
    pooled = pooled_tail_buckets(records)
    rows = []
    for size in GPD_SIZES:
        for threshold in GPD_THRESHOLDS:
            cells = []
            for allocator in ALLOCATOR_ORDER:
                buckets = pooled[(allocator, size)]
                empirical = float(weighted_percentile(buckets, TAIL_PERCENT))
                cells.append(gpd_cell(buckets, threshold, empirical))
            rows.append(f"{size} & {threshold:g} & " + " & ".join(cells) + " \\\\")
    header = (f"Size (B) & Pctl & {ALLOCATOR_HEADER}\\\\")
    return booktabs("GPD threshold sensitivity under 8:1 handoff at 8 threads. Each cell gives the shape of the GPD "
                    "fitted to the pooled histogram, $\\hat{\\xi}_{\\text{pooled}}$, and in parentheses the percent error of "
                    "the fitted $\\hat{Q}(0.999)$ against the empirical P99.9 of the same pooled distribution. The "
                    "95th-percentile pooled shape differs from the mean of the 50 per-iteration shapes in "
                    "Table~\\ref{tab:gpd}, because pooling mixes the iterations before the fit. Identical entries across thresholds "
                    "mean that the threshold percentile fell on the same histogram bucket.",
                    "tab:gpd-sensitivity", "llrrrrr", header, rows, size=r"\footnotesize", colsep="4pt")

def scaling_table(configs: pd.DataFrame, topology: str, label: str, name: str) -> str:
    rows = []
    for size in ATLAS_SIZES:
        for threads in SCALING_THREADS:
            cells = [format_integer(lookup(configs, allocator, size, threads, topology, "event_p99_9_ns"))
                     for allocator in ALLOCATOR_ORDER]
            rows.append(f"{size} & {threads} & " + " & ".join(cells) + " \\\\")
    header = f"Size (B) & Threads & {ALLOCATOR_HEADER}\\\\"
    return booktabs(f"Pooled P99.9 event latency (ns) under {name} handoff as the thread count varies, all eight "
                    "size classes. Each cell pools allocation and free events over 50 iterations.",
                    label, "rr" + "r" * len(ALLOCATOR_ORDER), header, rows, size=r"\scriptsize")


UNFITTED_USL = {"sigma_c": np.nan, "sigma_c_se": np.nan, "kappa_c": np.nan, "kappa_c_se": np.nan,
                "t_star": 1.0, "r_squared": np.nan}


def usl_row(configs: pd.DataFrame, allocator: str, size: int) -> tuple:
    sub = configs[(configs.allocator == allocator) & (configs.size_bytes == size)
                  & (configs.topology == SYMMETRIC)].sort_values("threads")
    base = sub[sub.threads == USL_BASELINE_THREADS]["throughput_mops_mean"].iloc[0]
    threads = sub["threads"].to_numpy(dtype=float)
    speedup = sub["throughput_mops_mean"].to_numpy(dtype=float) / base
    if speedup[1:].max() < 1.0:
        return allocator, size, {**UNFITTED_USL, "monotone": True}
    return allocator, size, {**fit_usl(threads, speedup), "monotone": False}


def usl_all_sizes(configs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for size in ATLAS_SIZES:
        for allocator in ALLOCATOR_ORDER:
            name, size_bytes, fit = usl_row(configs, allocator, size)
            rows.append({"allocator": name, "size_bytes": size_bytes, **fit})
    frame = pd.DataFrame(rows)
    frame.to_csv(USL_CSV, index=False)
    return frame


def usl_latex_row(row) -> str:
    if row.monotone:
        return (f"{row.size_bytes} & {row.allocator} & \\multicolumn{{2}}{{l}}{{--- (monotone decrease for $T \\ge 2$)}} "
                f"& 1 & -- \\\\")
    return (f"{row.size_bytes} & {row.allocator} & {row.sigma_c:.4f} $\\pm$ {1.96 * row.sigma_c_se:.4f} & "
            f"{row.kappa_c:.5f} $\\pm$ {1.96 * row.kappa_c_se:.5f} & {row.t_star:.0f} & {row.r_squared:.3f} \\\\")


def table_b12(usl: pd.DataFrame) -> str:
    rows = [usl_latex_row(row) for row in usl.itertuples()]
    header = ("Size (B) & Allocator & $\\sigma_c$ (95\\% CI) & $\\kappa_c$ (95\\% CI) & $T^*$ & $R^2$\\\\")
    return booktabs("Universal Scalability Law fits to symmetric throughput, $S(T)=\\Lambda(T)/\\Lambda(1)$, threads "
                    "1--32, all eight size classes and five allocators. A cell marked as a monotone decrease is not fitted: "
                    "throughput peaks at one thread and falls below the single-thread value for every $T \\ge 2$, so the "
                    "USL shape is undefined, and $T^*$ is reported as 1.", "tab:usl-all", "llrrrr", header, rows,
                    size=r"\scriptsize")


def generate_extended_tables() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    configs = pd.read_csv(METRICS_DIR / "tier1_configs.csv")
    records = read_records(RAW_PATH)
    anova = anova_all_sizes(records)
    usl = usl_all_sizes(configs)
    outputs = {
        "tabA6.tex": table_a6(configs),
        "tabA7.tex": table_a7(configs),
        "tabA8.tex": table_a8(configs),
        "tabA9.tex": table_a9(anova),
        "tabA10.tex": table_a10(records),
        "tabB11.tex": scaling_table(configs, HANDOFF_4_1, "tab:scaling-4to1", "4:1"),
        "tabB12.tex": scaling_table(configs, RING, "tab:scaling-ring", "ring"),
        "tabB13.tex": table_b12(usl),
    }
    for name, content in outputs.items():
        (TABLE_DIR / name).write_text(content)


if __name__ == "__main__":
    generate_extended_tables()
