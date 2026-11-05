"""Figures 11-12: full size-class spectrum and empirical tail survival curves."""

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.histogram_pool import pool_buckets
from plots.style import ALLOCATOR_COLORS, ALLOCATOR_ORDER, METRICS_DIR, WORKSPACE, apply_style, save

TIER1_INPUT = WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl"
SIZE_CLASSES = [16, 64, 256, 1024, 4096, 16384, 65536, 262144]
SIZE_LABELS = ["16 B", "64 B", "256 B", "1 KB", "4 KB", "16 KB", "64 KB", "256 KB"]
TAIL_SIZES = [64, 4096]
CCDF_FLOOR = 1e-5


def fig11_size_spectrum() -> None:
    configs = pd.read_csv(METRICS_DIR / "tier1_configs.csv")
    sub = configs[(configs.threads == 8) & (configs.topology == "asymmetric_8_1")]
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.7), sharey=True)
    for allocator in ALLOCATOR_ORDER:
        rows = sub[sub.allocator == allocator].set_index("size_bytes").reindex(SIZE_CLASSES)
        axes[0].plot(range(len(SIZE_CLASSES)), rows.alloc_p99_9_ns, marker="o", ms=3,
                     color=ALLOCATOR_COLORS[allocator], label=allocator)
        axes[1].plot(range(len(SIZE_CLASSES)), rows.free_p99_9_ns, marker="s", ms=3,
                     color=ALLOCATOR_COLORS[allocator], label=allocator)
    for axis, title in ((axes[0], "Producer allocation P99.9"), (axes[1], "Consumer remote-free P99.9")):
        axis.set_yscale("log")
        axis.set_xticks(range(len(SIZE_CLASSES)))
        axis.set_xticklabels(SIZE_LABELS, rotation=45, ha="right")
        axis.set_title(f"{title}, 8:1, 8 threads")
    axes[0].set_ylabel("P99.9 latency (ns)")
    axes[1].legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    save(figure, "fig11")


def load_pooled_event_buckets() -> dict:
    """Pools alloc and free histogram buckets per allocator for 8 threads, 8:1, tail sizes."""
    buckets = {}
    with TIER1_INPUT.open() as handle:
        for line in handle:
            record = json.loads(line)
            if record["threads"] != 8 or record["topology"] != "asymmetric_8_1":
                continue
            if record["size"] not in TAIL_SIZES:
                continue
            key = (record["allocator"], record["size"])
            buckets.setdefault(key, []).append(record["result"]["alloc_counts"])
            buckets[key].append(record["result"]["free_counts"])
    return {key: pool_buckets(lists) for key, lists in buckets.items()}


def fig12_ccdf_tails() -> None:
    pooled = load_pooled_event_buckets()
    figure, axes = plt.subplots(1, 2, figsize=(7.0, 2.8), sharey=True)
    for axis, size in zip(axes, TAIL_SIZES):
        for allocator in ALLOCATOR_ORDER:
            bins = pooled[(allocator, size)]
            values = np.array([value for value, _ in bins], dtype=float)
            counts = np.array([count for _, count in bins], dtype=float)
            survival = 1.0 - np.cumsum(counts) / counts.sum()
            keep = (survival >= CCDF_FLOOR) & (survival < 1.0)
            axis.step(values[keep], survival[keep], where="post", linewidth=1.0,
                      color=ALLOCATOR_COLORS[allocator], label=allocator)
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_xlabel("Event latency t (ns)")
        axis.set_title(f"{size} B objects, 8:1, 8 threads")
        axis.axhline(1e-3, color="gray", linestyle="--", linewidth=0.7)
        axis.axhline(1e-4, color="black", linestyle=":", linewidth=0.7)
    axes[0].set_ylabel("Exceedance probability $1-F(t)$")
    axes[0].text(axes[0].get_xlim()[0], 1.2e-3, "P99.9", fontsize=6)
    axes[1].legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=6)
    save(figure, "fig12")


BATCH_SIZES = [64, 4096, 16384, 262144]
BATCH_LABELS = {"default": "Default cap", "mod": "Patched cap"}


def fig13_batch_cap() -> None:
    import json as _json
    runs = []
    for name in ("tcmalloc_source_build_n10.jsonl", "tcmalloc_source_build_side_effects_n10.jsonl"):
        with (WORKSPACE / "data" / "ablation" / name).open() as handle:
            runs.extend(_json.loads(line) for line in handle)
    figure, axes = plt.subplots(1, len(BATCH_SIZES), figsize=(7.0, 2.4), sharey=True)
    rng = np.random.default_rng(3)
    for axis, size in zip(axes, BATCH_SIZES):
        for position, build in enumerate(("default", "mod")):
            values = np.array([r["alloc_latency_ns"]["p99_9"] / 1e3 for r in runs
                               if r["alloc_size_bytes"] == size and r["build"] == build])
            axis.scatter(position + rng.uniform(-0.08, 0.08, values.size), values, s=8,
                         color="#0072B2" if build == "default" else "#D55E00", zorder=3)
            axis.hlines(np.median(values), position - 0.25, position + 0.25, color="black", linewidth=1.0)
        axis.set_yscale("log")
        axis.set_xticks([0, 1])
        axis.set_xticklabels(["default", "patched"])
        axis.set_xlim(-0.5, 1.5)
        axis.set_title({64: "64 B", 4096: "4 KB", 16384: "16 KB", 262144: "256 KB"}[size])
        axis.axhline(100, color="gray", linestyle=":", linewidth=0.7)
    axes[0].set_ylabel("Alloc P99.9 per run ($\\mu$s)")
    save(figure, "fig13")


def generate_extra_figures() -> None:
    apply_style()
    fig11_size_spectrum()
    fig12_ccdf_tails()
    fig13_batch_cap()
