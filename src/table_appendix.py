"""
src/table_appendix.py

Writes the appendix atlas tables (tables/tabA1.tex to tabA5.tex and
tables/tabB1.tex, tabB2.tex) from results/metrics/tier1_configs.csv. Every
cell is a percentile or mean pooled over the raw micro-sweep histograms, so
the appendix carries no value that is not in data/tier1/micro_sweeps.jsonl.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import pandas as pd

from plots.style import ALLOCATOR_ORDER, METRICS_DIR
from table_generator import PRIMARY_THREADS, TABLE_DIR, booktabs

ATLAS_SIZES = (16, 64, 256, 1024, 4096, 16384, 65536, 262144)
SCALING_SIZES = (64, 1024, 4096, 65536)
SCALING_THREADS = (2, 4, 8, 16, 32)
THROUGHPUT_THREADS = (1, 2, 4, 8, 16, 32)
ALLOCATOR_HEADER = " & ".join(ALLOCATOR_ORDER)
THOUSANDS_SEPARATOR = "{,}"


def format_integer(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", THOUSANDS_SEPARATOR)


def lookup(configs: pd.DataFrame, allocator: str, size: int, threads: int, topology: str, column: str) -> float:
    matches = configs[(configs.allocator == allocator) & (configs.size_bytes == size)
                      & (configs.threads == threads) & (configs.topology == topology)]
    if len(matches) != 1:
        raise ValueError(f"expected one configuration for {allocator} {size} B {threads} T {topology}, found {len(matches)}")
    return float(matches.iloc[0][column])


def atlas_rows(configs: pd.DataFrame, topology: str, column: str) -> list:
    rows = []
    for size in ATLAS_SIZES:
        cells = [format_integer(lookup(configs, allocator, size, PRIMARY_THREADS, topology, column))
                 for allocator in ALLOCATOR_ORDER]
        rows.append(f"{size} & " + " & ".join(cells) + " \\\\")
    return rows


def atlas_table(configs: pd.DataFrame, topology: str, column: str, label: str, caption: str) -> str:
    header = f"Size (B) & {ALLOCATOR_HEADER} \\\\"
    return booktabs(caption, label, "r" + "r" * len(ALLOCATOR_ORDER), header,
                    atlas_rows(configs, topology, column))


def scaling_table(configs: pd.DataFrame, value_column: str, threads_axis: tuple, topology: str,
                  decimals: int, label: str, caption: str) -> str:
    rows = []
    for size in SCALING_SIZES:
        for threads in threads_axis:
            cells = []
            for allocator in ALLOCATOR_ORDER:
                value = lookup(configs, allocator, size, threads, topology, value_column)
                cells.append(f"{value:,.{decimals}f}".replace(",", THOUSANDS_SEPARATOR))
            rows.append(f"{size} & {threads} & " + " & ".join(cells) + " \\\\")
    header = f"Size (B) & Threads & {ALLOCATOR_HEADER} \\\\"
    return booktabs(caption, label, "rr" + "r" * len(ALLOCATOR_ORDER), header, rows)


def generate_appendix_tables() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    configs = pd.read_csv(METRICS_DIR / "tier1_configs.csv")
    outputs = {
        "tabA1.tex": atlas_table(
            configs, "symmetric", "event_p99_9_ns", "tab:atlas-symmetric",
            "Pooled P99.9 event latency (ns) at 8 threads under symmetric handoff, all eight size classes. "
            "Each cell pools allocation and free events over 50 iterations."),
        "tabA2.tex": atlas_table(
            configs, "asymmetric_4_1", "event_p99_9_ns", "tab:atlas-4to1",
            "Pooled P99.9 event latency (ns) at 8 threads under 4:1 handoff, all eight size classes. "
            "Each cell pools allocation and free events over 50 iterations."),
        "tabA3.tex": atlas_table(
            configs, "asymmetric_8_1", "event_p99_9_ns", "tab:atlas-8to1",
            "Pooled P99.9 event latency (ns) at 8 threads under 8:1 handoff, all eight size classes. "
            "Each cell pools allocation and free events over 50 iterations."),
        "tabA4.tex": atlas_table(
            configs, "ring", "event_p99_9_ns", "tab:atlas-ring",
            "Pooled P99.9 event latency (ns) at 8 threads under ring handoff, all eight size classes. "
            "Each cell pools allocation and free events over 50 iterations."),
        "tabA5.tex": atlas_table(
            configs, "asymmetric_8_1", "event_p99_99_ns", "tab:atlas-p9999",
            "Pooled P99.99 event latency (ns) at 8 threads under 8:1 handoff, all eight size classes."),
        "tabB1.tex": scaling_table(
            configs, "event_p99_9_ns", SCALING_THREADS, "asymmetric_8_1", 0, "tab:scaling-p999",
            "Pooled P99.9 event latency (ns) under 8:1 handoff as the thread count varies, for four size classes. "
            "Thread counts of two to thirty-two are shown because the 8:1 topology needs at least two threads."),
        "tabB2.tex": scaling_table(
            configs, "throughput_mops_mean", THROUGHPUT_THREADS, "symmetric", 2, "tab:scaling-throughput",
            "Mean symmetric throughput (million operations per second) from one to thirty-two threads, "
            "for four size classes. Each cell averages 50 iterations."),
    }
    for name, content in outputs.items():
        (TABLE_DIR / name).write_text(content)


if __name__ == "__main__":
    generate_appendix_tables()
