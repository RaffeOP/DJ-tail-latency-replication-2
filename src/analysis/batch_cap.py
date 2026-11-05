"""
Summarizes the tcmalloc transfer-batch-cap experiment: the unmodified and patched
gperftools 2.19.1 builds at 8 threads under 8:1 handoff, ten iterations per cell.
"""

import json

import numpy as np
import pandas as pd

from plots.style import METRICS_DIR, WORKSPACE

MAIN_INPUT = WORKSPACE / "data" / "ablation" / "tcmalloc_source_build_n10.jsonl"
SIDE_INPUT = WORKSPACE / "data" / "ablation" / "tcmalloc_source_build_side_effects_n10.jsonl"
SLOW_MODE_NS = 100e3
DEFAULT_CAP = 32
DEFAULT_BYTE_BUDGET = 64 * 1024
PATCHED_CAP = 256
PATCHED_BYTE_BUDGET = 1024 * 1024
SIZES = [64, 4096, 16384, 262144]


def transfer_cap(size: int, budget: int, ceiling: int) -> int:
    return min(ceiling, max(2, budget // size))


def load(path) -> list:
    with path.open() as handle:
        return [json.loads(line) for line in handle]


def summarize() -> pd.DataFrame:
    records = load(MAIN_INPUT) + load(SIDE_INPUT)
    rows = []
    for size in SIZES:
        for build in ("default", "mod"):
            runs = [r for r in records if r["alloc_size_bytes"] == size and r["build"] == build]
            alloc = np.array([r["alloc_latency_ns"]["p99_9"] for r in runs], dtype=float)
            free = np.array([r["free_latency_ns"]["p99_9"] for r in runs], dtype=float)
            mops = np.array([r["throughput_ops_per_sec"] for r in runs], dtype=float) / 1e6
            if build == "default":
                cap = transfer_cap(size, DEFAULT_BYTE_BUDGET, DEFAULT_CAP)
            else:
                cap = transfer_cap(size, PATCHED_BYTE_BUDGET, PATCHED_CAP)
            rows.append({"size_bytes": size, "build": build, "transfer_cap": cap, "runs": len(runs),
                         "alloc_p99_9_median_us": float(np.median(alloc)) / 1e3,
                         "alloc_p99_9_min_us": float(alloc.min()) / 1e3,
                         "alloc_p99_9_max_us": float(alloc.max()) / 1e3,
                         "slow_mode_fraction": float((alloc > SLOW_MODE_NS).mean()),
                         "free_p99_9_median_us": float(np.median(free)) / 1e3,
                         "mops_median": float(np.median(mops))})
    frame = pd.DataFrame(rows)
    frame.to_csv(METRICS_DIR / "tcmalloc_batch_cap.csv", index=False)
    return frame
