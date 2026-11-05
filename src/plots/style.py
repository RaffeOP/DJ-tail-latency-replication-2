"""Shared plotting style: Okabe-Ito palette, Type-42 PDF fonts, 300 DPI rasters."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[2]
FIGURE_DIR = WORKSPACE / "figures"
METRICS_DIR = WORKSPACE / "results" / "metrics"

ALLOCATOR_ORDER = ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]
ALLOCATOR_COLORS = {
    "mimalloc": "#0072B2",
    "jemalloc": "#D55E00",
    "tcmalloc": "#009E73",
    "snmalloc": "#CC79A7",
    "libmalloc": "#7F7F7F",
}
TOPOLOGY_ORDER = ["symmetric", "asymmetric_4_1", "asymmetric_8_1", "ring"]
TOPOLOGY_LABELS = {
    "symmetric": "Symmetric",
    "asymmetric_4_1": "4:1",
    "asymmetric_8_1": "8:1",
    "ring": "Ring",
}
POLICY_ORDER = ["none", "dontneed", "free", "free_reusable"]
POLICY_LABELS = {
    "none": "No release",
    "dontneed": "MADV_DONTNEED",
    "free": "MADV_FREE",
    "free_reusable": "MADV_FREE_REUSABLE",
}


def apply_style() -> None:
    plt.rcParams.update({
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 300,
        "figure.dpi": 150,
    })


def save(figure, name: str) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURE_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close(figure)
