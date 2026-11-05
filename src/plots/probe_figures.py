"""Figures 6-10: coherence stride, remote free, Tier 2 bloat, footprint, and page release."""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from plots.style import (ALLOCATOR_COLORS, ALLOCATOR_ORDER, METRICS_DIR, POLICY_LABELS, POLICY_ORDER, apply_style, save)

WORKLOAD_ORDER = ["grpc_pipeline", "kv_churn", "ast_graph"]
WORKLOAD_LABELS = {"grpc_pipeline": "gRPC-style pipeline", "kv_churn": "KV slab churn", "ast_graph": "AST graph"}
PROBE_INTERVAL_MS = 200
PERIOD_MARKERS = {50: "o", 200: "s", 1000: "^"}
PURGE_SERIES_COLORS = {"none": "#000000", "dontneed": "#D55E00", "free": "#0072B2", "free_reusable": "#009E73"}


def fig06_stride_penalty() -> None:
    stride = pd.read_csv(METRICS_DIR / "probe_false_sharing.csv")
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))
    for axis, column, spread, ylabel in (
        (axes[0], "ns_per_increment_mean", "ns_per_increment_sd", "ns per atomic increment"),
        (axes[1], "cycles_per_increment_mean", None, "CPU cycles per increment (process counter)"),
    ):
        for threads, marker in ((2, "o"), (4, "s")):
            sub = stride[stride.threads == threads].sort_values("stride_bytes")
            yerr = 1.96 * sub[spread] / np.sqrt(sub.reps) if spread else None
            axis.errorbar(sub.stride_bytes, sub[column], yerr=yerr, marker=marker, ms=3.5, capsize=2,
                          linewidth=0.9, label=f"{threads} threads")
        axis.axvline(64, color="black", linestyle=":", linewidth=0.7)
        axis.set_xscale("log", base=2)
        axis.set_xlabel("Counter stride (bytes)")
        axis.set_ylabel(ylabel)
    axes[0].set_title("Time per increment (95% CI)")
    axes[1].set_title("Cycles per increment")
    axes[0].legend(frameon=False)
    save(figure, "fig06")


def fig07_remote_free() -> None:
    configs = pd.read_csv(METRICS_DIR / "tier1_configs.csv")
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.6), sharey=True)
    for axis, size in zip(axes, [64, 4096]):
        sub = configs[(configs.threads == 8) & (configs.topology == "asymmetric_8_1") & (configs.size_bytes == size)]
        sub = sub.set_index("allocator").reindex(ALLOCATOR_ORDER)
        positions = np.arange(len(ALLOCATOR_ORDER))
        axis.bar(positions - 0.18, sub.alloc_p99_9_ns, width=0.34, color="#BBBBBB", label="Producer alloc")
        axis.bar(positions + 0.18, sub.free_p99_9_ns, width=0.34, color="#333333", label="Consumer (remote) free")
        axis.set_yscale("log")
        axis.set_xticks(positions)
        axis.set_xticklabels(ALLOCATOR_ORDER, rotation=30, ha="right")
        axis.set_title(f"{size} B objects, 8:1, 8 threads")
    axes[0].set_ylabel("P99.9 latency (ns)")
    axes[0].legend(frameon=False, loc="upper left")
    save(figure, "fig07")


def fig08_bloat() -> None:
    runs = pd.read_csv(METRICS_DIR / "tier2_trace_runs.csv")
    supplement = pd.read_csv(METRICS_DIR / "tier2_kv_supplement.csv")
    figure, axis = plt.subplots(figsize=(7.0, 2.6))
    width = 0.15
    for offset, allocator in enumerate(ALLOCATOR_ORDER):
        means, spreads = [], []
        for workload in WORKLOAD_ORDER:
            values = runs[(runs.workload == workload) & (runs.allocator == allocator)].bloat_ratio
            means.append(values.mean())
            spreads.append(values.std(ddof=1))
        positions = np.arange(len(WORKLOAD_ORDER)) + (offset - 2) * width
        axis.bar(positions, means, width=width, yerr=spreads, capsize=2, color=ALLOCATOR_COLORS[allocator],
                 label=allocator, edgecolor="black", linewidth=0.3)
        if allocator == "libmalloc":
            extra = supplement[supplement.allocator == allocator].bloat_ratio.to_numpy()
            axis.scatter(np.full(len(extra), positions[1]) + np.linspace(-0.05, 0.05, len(extra)), extra,
                         s=10, facecolors="none", edgecolors="black", linewidths=0.6, zorder=4)
    axis.set_xticks(range(len(WORKLOAD_ORDER)))
    axis.set_xticklabels([WORKLOAD_LABELS[w] for w in WORKLOAD_ORDER])
    axis.set_ylabel(r"$B_{\mathrm{RSS}}$ = peak footprint / peak live bytes")
    axis.text(positions[1] + 0.2, 20.5, "open circles: 15 supplementary runs", fontsize=6)
    axis.axhline(1.0, color="black", linewidth=0.6)
    axis.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.18))
    save(figure, "fig08")


def fig09_footprint_traces() -> None:
    series = pd.read_csv(METRICS_DIR / "tier2_footprint_timeseries.csv")
    figure, axes = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=False)
    for axis, workload in zip(axes, WORKLOAD_ORDER):
        for allocator in ALLOCATOR_ORDER:
            sub = series[(series.workload == workload) & (series.allocator == allocator)]
            axis.plot(sub.t_s, sub.footprint_mb, linewidth=0.8, color=ALLOCATOR_COLORS[allocator], label=allocator)
        axis.set_title(WORKLOAD_LABELS[workload])
        axis.set_xlabel("Time (s)")
    axes[0].set_ylabel("Physical footprint (MB)")
    axes[-1].legend(frameon=False, fontsize=6, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    save(figure, "fig09")


def fig10_page_release() -> None:
    series = pd.read_csv(METRICS_DIR / "probe_purge_timeseries.csv")
    runs = pd.read_csv(METRICS_DIR / "probe_purge_runs.csv")
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.6))
    for policy in POLICY_ORDER:
        sub = series[series.policy == policy]
        axes[0].plot(sub.t_s, sub.footprint_mb, linewidth=0.8, color=PURGE_SERIES_COLORS[policy],
                     label=POLICY_LABELS[policy])
    axes[0].set_xlabel("Time (s)")
    axes[0].set_ylabel("Physical footprint (MB)")
    axes[0].set_title(f"Release every {PROBE_INTERVAL_MS} ms, 512 MB region")
    axes[0].legend(frameon=False, fontsize=6, loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2)
    grouped = runs.groupby(["policy", "interval_ms"]).agg(
        footprint=("footprint_min_mb", "mean"), access=("access_p99_9_ns", "mean")).reset_index()
    for policy in POLICY_ORDER:
        sub = grouped[grouped.policy == policy].sort_values("interval_ms")
        axes[1].plot(sub.access, sub.footprint, linewidth=0.8,
                     color=PURGE_SERIES_COLORS[policy], label=POLICY_LABELS[policy])
        for row in sub.itertuples():
            axes[1].scatter([row.access], [row.footprint], marker=PERIOD_MARKERS[row.interval_ms], s=14,
                            color=PURGE_SERIES_COLORS[policy], zorder=3)
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Worker access P99.9 (ns)")
    axes[1].set_ylabel("Minimum footprint (MB)")
    axes[1].set_title("Footprint versus access tail, by period")
    period_handles = [Line2D([], [], marker=PERIOD_MARKERS[ms], linestyle="", color="black", markersize=4,
                             label=f"{ms} ms") for ms in PERIOD_MARKERS]
    axes[1].legend(handles=period_handles, frameon=False, fontsize=6, loc="lower right", title="Period",
                   title_fontsize=6)
    save(figure, "fig10")


def generate_probe_figures() -> None:
    apply_style()
    fig06_stride_penalty()
    fig07_remote_free()
    fig08_bloat()
    fig09_footprint_traces()
    fig10_page_release()
