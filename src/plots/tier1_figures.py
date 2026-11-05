"""Figures 1-5: Tier 1 micro-sweep results (RQ1 tail amplification, RQ5 scalability)."""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from plots.style import (ALLOCATOR_COLORS, ALLOCATOR_ORDER, METRICS_DIR, TOPOLOGY_LABELS, TOPOLOGY_ORDER, apply_style, save)

TAIL_SIZES = [64, 4096]
PRIMARY_THREADS = 8
MARKER_SIZE = 3.5


def load_configs() -> pd.DataFrame:
    return pd.read_csv(METRICS_DIR / "tier1_configs.csv")


def fig01_tail_vs_asymmetry(configs: pd.DataFrame) -> None:
    figure, axes = plt.subplots(1, len(TAIL_SIZES), figsize=(7.0, 2.6), sharey=True)
    for axis, size in zip(axes, TAIL_SIZES):
        sub = configs[(configs.threads == PRIMARY_THREADS) & (configs.size_bytes == size)]
        for allocator in ALLOCATOR_ORDER:
            rows = sub[sub.allocator == allocator].set_index("topology").reindex(TOPOLOGY_ORDER)
            axis.plot(range(len(TOPOLOGY_ORDER)), rows.event_p99_9_ns, marker="o", ms=MARKER_SIZE,
                      color=ALLOCATOR_COLORS[allocator], label=allocator)
        axis.set_xticks(range(len(TOPOLOGY_ORDER)))
        axis.set_xticklabels([TOPOLOGY_LABELS[t] for t in TOPOLOGY_ORDER])
        axis.set_yscale("log")
        axis.set_title(f"{size} B objects, 8 threads")
        axis.set_xlabel("Producer:consumer topology")
    axes[0].set_ylabel("P99.9 event latency (ns)")
    axes[-1].legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    save(figure, "fig01")


def fig02_amplification_heatmap(configs: pd.DataFrame) -> None:
    sub = configs[(configs.threads == PRIMARY_THREADS) & (configs.size_bytes == 64)]
    grid = sub.pivot(index="allocator", columns="topology", values="gamma_tail").reindex(
        index=ALLOCATOR_ORDER, columns=TOPOLOGY_ORDER)
    figure, axis = plt.subplots(figsize=(3.5, 2.4))
    image = axis.imshow(np.log10(grid.to_numpy(dtype=float)), cmap="magma_r", aspect="auto")
    for row in range(grid.shape[0]):
        for col in range(grid.shape[1]):
            axis.text(col, row, f"{grid.iat[row, col]:.0f}x", ha="center", va="center", fontsize=6,
                      color="white" if np.log10(grid.iat[row, col]) > 1.5 else "black")
    axis.set_xticks(range(len(TOPOLOGY_ORDER)))
    axis.set_xticklabels([TOPOLOGY_LABELS[t] for t in TOPOLOGY_ORDER])
    axis.set_yticks(range(len(ALLOCATOR_ORDER)))
    axis.set_yticklabels(ALLOCATOR_ORDER)
    axis.set_xlabel("Producer:consumer topology")
    colorbar = figure.colorbar(image, ax=axis, shrink=0.8)
    colorbar.set_label(r"$\log_{10}\,\Gamma_{\mathrm{tail}}$")
    save(figure, "fig02")


def fig03_tail_shape(configs: pd.DataFrame) -> None:
    spread = pd.read_csv(METRICS_DIR / "tier1_gpd_iteration_spread.csv")
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.4), sharey=True)
    for axis, topology in zip(axes, ["asymmetric_8_1", "ring"]):
        for offset, size in enumerate(TAIL_SIZES):
            sub = spread[(spread.topology == topology) & (spread.size_bytes == size)].set_index("allocator")
            sub = sub.reindex(ALLOCATOR_ORDER)
            positions = np.arange(len(ALLOCATOR_ORDER)) + (offset - 0.5) * 0.36
            se = sub.xi_iteration_sd / np.sqrt(sub.iterations)
            axis.bar(positions, sub.xi_iteration_mean, width=0.34, yerr=1.96 * se, capsize=2,
                     color=[ALLOCATOR_COLORS[a] for a in ALLOCATOR_ORDER], alpha=1.0 if offset == 0 else 0.45,
                     edgecolor="black", linewidth=0.4)
        axis.axhline(0.0, color="black", linewidth=0.6)
        axis.set_xticks(range(len(ALLOCATOR_ORDER)))
        axis.set_xticklabels(ALLOCATOR_ORDER, rotation=30, ha="right")
        axis.set_title(f"{TOPOLOGY_LABELS.get(topology, 'Ring')} topology")
    axes[0].set_ylabel(r"GPD shape $\hat{\xi}$ (mean of iterations, 95% CI)")
    handles = [Patch(facecolor="#999999", edgecolor="black", linewidth=0.4, label="64 B"),
               Patch(facecolor="#999999", alpha=0.45, edgecolor="black", linewidth=0.4, label="4 KB")]
    axes[0].legend(handles=handles, frameon=False, loc="upper left")
    save(figure, "fig03")


def fig04_usl_curves() -> None:
    usl = pd.read_csv(METRICS_DIR / "tier1_usl.csv")
    sub = usl[usl.size_bytes == 64]
    figure, axis = plt.subplots(figsize=(3.6, 2.8))
    threads = np.linspace(1, 32, 200)
    for row in sub.itertuples():
        measured_t = np.array([float(v) for v in row.threads_list.split(",")])
        measured_s = np.array([float(v) for v in row.speedup_list.split(",")])
        fitted = threads / (1 + row.sigma_c * (threads - 1) + row.kappa_c * threads * (threads - 1))
        color = ALLOCATOR_COLORS[row.allocator]
        axis.plot(threads, fitted, color=color, linewidth=1.0, label=row.allocator)
        axis.scatter(measured_t, measured_s, s=8, color=color, zorder=3)
    axis.set_xscale("log", base=2)
    axis.set_yscale("log", base=2)
    axis.set_xlabel("Threads T")
    axis.set_ylabel(r"Speedup $S(T)=\Lambda(T)/\Lambda(1)$")
    axis.set_title("Symmetric 64 B sweeps with USL fits")
    axis.legend(frameon=False, loc="upper left")
    save(figure, "fig04")


def fig05_tail_vs_threads(configs: pd.DataFrame) -> None:
    sub = configs[(configs.topology == "asymmetric_4_1") & (configs.size_bytes == 64)]
    figure, axis = plt.subplots(figsize=(3.6, 2.8))
    for allocator in ALLOCATOR_ORDER:
        rows = sub[sub.allocator == allocator].sort_values("threads")
        axis.plot(rows.threads, rows.event_p99_9_ns, marker="o", ms=MARKER_SIZE,
                  color=ALLOCATOR_COLORS[allocator], label=allocator)
    axis.set_xscale("log", base=2)
    axis.set_yscale("log")
    axis.set_xlabel("Threads T (oversubscribed beyond 8 cores)")
    axis.set_ylabel("P99.9 event latency (ns)")
    axis.set_title("4:1 producer-consumer, 64 B")
    axis.axvline(8, color="black", linestyle=":", linewidth=0.7)
    axis.legend(frameon=False)
    save(figure, "fig05")


def generate_tier1_figures() -> None:
    apply_style()
    configs = load_configs()
    fig01_tail_vs_asymmetry(configs)
    fig02_amplification_heatmap(configs)
    fig03_tail_shape(configs)
    fig04_usl_curves()
    fig05_tail_vs_threads(configs)
