"""
src/table_generator.py

Writes the booktabs tables (tables/tab01.tex to tables/tab09.tex) from
the analysis artifacts in results/metrics/.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import csv
import math
import re
from pathlib import Path

import pandas as pd

from plots.style import ALLOCATOR_ORDER, METRICS_DIR

WORKSPACE = Path(__file__).resolve().parent.parent
TABLE_DIR = WORKSPACE / "tables"
PRIMARY_THREADS = 8
P_VALUE_FLOOR = 1e-300


def booktabs(caption: str, label: str, column_spec: str, header: str, body: list,
             size: str = r"\footnotesize", colsep: str = "3pt") -> str:
    lines = [
        r"\begin{table}[!htbp]",
        r"\centering",
        size,
        rf"\setlength{{\tabcolsep}}{{{colsep}}}",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        rf"\begin{{tabular}}{{{column_spec}}}",
        r"\toprule",
        header,
        r"\midrule",
        *body,
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)


def ci(value: float, se: float, digits: int) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--"
    if se is None or (isinstance(se, float) and math.isnan(se)):
        return f"{value:.{digits}f}"
    return f"{value:.{digits}f} $\\pm$ {1.96 * se:.{digits}f}"


def table01(configs: pd.DataFrame) -> str:
    rows = []
    for allocator in ALLOCATOR_ORDER:
        sub = configs[(configs.allocator == allocator) & (configs.threads == PRIMARY_THREADS)
                      & (configs.size_bytes == 64)].set_index("topology")
        symmetric = sub.loc["symmetric"]
        rows.append(
            f"{allocator} & {symmetric.throughput_mops_mean:.1f} & "
            f"{symmetric.event_p99_9_ns:.0f} & {sub.loc['asymmetric_4_1'].event_p99_9_ns:.0f} & "
            f"{sub.loc['asymmetric_8_1'].event_p99_9_ns:.0f} & {sub.loc['asymmetric_8_1'].gamma_tail:.1f} \\\\"
        )
    header = ("Allocator & Sym.\\ Mops/s & Sym.\\ P99.9 (ns) & 4:1 P99.9 (ns) & 8:1 P99.9 (ns) & "
              "$\\Gamma_{\\mathrm{tail}}$ (8:1)\\\\")
    return booktabs("Tier 1 results at 8 threads, 64 B objects. Latencies pool alloc and free events over all iterations.",
                    "tab:tier1", "lrrrrr", header, rows)


def table02(configs: pd.DataFrame) -> str:
    spread = pd.read_csv(METRICS_DIR / "tier1_gpd_iteration_spread.csv")
    rows = []
    for size in (64, 4096):
        for allocator in ALLOCATOR_ORDER:
            row = configs[(configs.allocator == allocator) & (configs.threads == PRIMARY_THREADS)
                          & (configs.topology == "asymmetric_8_1") & (configs.size_bytes == size)].iloc[0]
            shape = spread[(spread.allocator == allocator) & (spread.size_bytes == size)
                           & (spread.topology == "asymmetric_8_1")].iloc[0]
            shape_ci = f"{shape.xi_iteration_mean:.3f} $\\pm$ {1.96 * shape.xi_iteration_sd / math.sqrt(shape.iterations):.3f}"
            relative_error = 100.0 * (row.gpd_q999_ns - row.event_p99_9_ns) / row.event_p99_9_ns
            rows.append(
                f"{size} & {allocator} & {shape_ci} & {row.gpd_threshold_ns:.0f} & "
                f"{row.event_p99_9_ns:.0f} & {row.gpd_q999_ns:.0f} & {relative_error:+.1f} & "
                f"{row.gpd_q9999_ns:.0f} \\\\"
            )
    header = ("Size (B) & Allocator & \\shortstack{$\\hat{\\xi}$\\\\(95\\% CI)} & \\shortstack{$u$\\\\(ns)} & "
              "\\shortstack{Empirical\\\\$P_{99.9}$ (ns)} & \\shortstack{$\\hat{Q}(0.999)$\\\\(ns)} & "
              "\\shortstack{Error\\\\(\\%)} & \\shortstack{$\\hat{Q}(0.9999)$\\\\(ns)}\\\\")
    return booktabs("Grouped GPD fits above the 95th percentile, 8:1 topology, 8 threads. Shape is the mean of 50 "
                    "per-iteration fits with a 95\\% interval of that mean. Quantile error compares the fitted "
                    "$\\hat{Q}(0.999)$ with the empirical P99.9 of the same pooled distribution.",
                    "tab:gpd", "llrrrrrr", header, rows, size=r"\scriptsize")


def format_p_value(p_value: float) -> str:
    if p_value < P_VALUE_FLOOR:
        return f"$<10^{{-{int(-math.log10(P_VALUE_FLOOR))}}}$"
    return f"{p_value:.2g}"


def anova_rows(size: int) -> list:
    table = pd.read_csv(METRICS_DIR / f"tier1_anova_{size}.csv")
    rows = []
    for row in table.itertuples():
        if row.source == "residual":
            rows.append(f"{size} & Residual & {row.df} & -- & -- & {row.eta_squared:.3f} & -- \\\\")
            continue
        rows.append(f"{size} & {row.source.replace('_', ' ')} & {row.df} & {row.F:.2f} & "
                     f"{format_p_value(row.p_value)} & {row.eta_squared:.3f} & {row.partial_eta_squared:.3f} \\\\")
    return rows


def table03() -> str:
    rows = anova_rows(64) + anova_rows(4096)
    header = ("Size (B) & Source & df & $F$ & $p$ & $\\eta^2$ (share of $SS_{\\mathrm{total}}$) & "
              "$\\eta_p^2$ (partial)\\\\")
    return booktabs("Box-Cox two-way parametric ANOVA on per-iteration P99.9 event latency (8 threads). "
                    "Factors: allocator (5 levels) and topology (4 levels), 50 replicates per cell. "
                    "Classical $\\eta^2$ values sum with the residual to one.",
                    "tab:anova", "llrrrrr", header, rows)


def table04(usl: pd.DataFrame) -> str:
    rows = []
    for size in (64, 4096):
        for allocator in ALLOCATOR_ORDER:
            row = usl[(usl.allocator == allocator) & (usl.size_bytes == size)].iloc[0]
            rows.append(
                f"{size} & {allocator} & {ci(row.sigma_c, row.sigma_c_se, 4)} & "
                f"{ci(row.kappa_c, row.kappa_c_se, 5)} & {row.t_star:.0f} & {row.r_squared:.3f} \\\\"
            )
    header = ("Size (B) & Allocator & $\\sigma_c$ (95\\% CI) & $\\kappa_c$ (95\\% CI) & $T^*$ & $R^2$\\\\")
    return booktabs("Universal Scalability Law fits to symmetric throughput, $S(T)=\\Lambda(T)/\\Lambda(1)$, "
                    "threads 1--32.", "tab:usl", "llrrrr", header, rows)


def table05(configs: pd.DataFrame) -> str:
    rows = []
    for allocator in ALLOCATOR_ORDER:
        for size in (64, 4096):
            cells = []
            for threads in (4, 8):
                row = configs[(configs.allocator == allocator) & (configs.threads == threads)
                              & (configs.topology == "asymmetric_8_1") & (configs.size_bytes == size)].iloc[0]
                cv = 100.0 * row.throughput_mops_sd / row.throughput_mops_mean
                cells.append(f"{cv:.0f} & {row.alloc_p99_9_ns:.0f} & {row.free_p99_9_ns:.0f}")
            rows.append(f"{allocator} & {size} & " + " & ".join(cells) + " \\\\")
    header = ("& & \\multicolumn{3}{c}{4 threads (3:1 effective)} & \\multicolumn{3}{c}{8 threads (7:1 effective)}\\\\\n"
              "\\cmidrule(lr){3-5}\\cmidrule(lr){6-8}\n"
              "Allocator & Size (B) & \\shortstack{CV\\\\(\\%)} & \\shortstack{Prod.\\ alloc\\\\$P_{99.9}$} & "
              "\\shortstack{Cons.\\ free\\\\$P_{99.9}$} & \\shortstack{CV\\\\(\\%)} & "
              "\\shortstack{Prod.\\ alloc\\\\$P_{99.9}$} & \\shortstack{Cons.\\ free\\\\$P_{99.9}$}\\\\")
    return booktabs("8:1 handoff at 4 and 8 threads. The effective producer-to-consumer ratio is 3:1 at 4 threads "
                    "(three producers, one consumer) and 7:1 at 8 threads (seven producers, one consumer), so the "
                    "4-thread case is a single performance-core cluster. CV is the coefficient of variation of "
                    "throughput across 50 iterations. Latencies are pooled P99.9 in nanoseconds.",
                    "tab:pcore", "llrrrrrrr", header, rows, size=r"\scriptsize")


def table06() -> str:
    uncertainty = pd.read_csv(METRICS_DIR / "tier1_p999_uncertainty.csv")
    rows = []
    for size in (64, 4096):
        for allocator in ALLOCATOR_ORDER:
            row = uncertainty[(uncertainty.allocator == allocator) & (uncertainty.size_bytes == size)
                              & (uncertainty.topology == "asymmetric_8_1") & (uncertainty.threads == PRIMARY_THREADS)].iloc[0]
            rows.append(f"{size} & {allocator} & {row.median_p999_ns:.0f} & [{row.ci_low_ns:.0f}, {row.ci_high_ns:.0f}] & "
                        f"{row.q25_ns:.0f}--{row.q75_ns:.0f} \\\\")
    header = ("Size (B) & Allocator & Median P99.9 (ns) & 95\\% bootstrap CI of median (ns) & "
              "Interquartile range (ns)\\\\")
    return booktabs("Per-iteration P99.9 event latency at 8 threads under 8:1 handoff, over 50 iterations. "
                    "The interval is a percentile bootstrap of the median with 2{,}000 resamples.",
                    "tab:uncertainty", "llrrr", header, rows)


def table08() -> str:
    cap = pd.read_csv(METRICS_DIR / "tcmalloc_batch_cap.csv")
    rows = []
    for size in (64, 4096, 16384, 262144):
        d = cap[(cap.size_bytes == size) & (cap.build == "default")].iloc[0]
        m = cap[(cap.size_bytes == size) & (cap.build == "mod")].iloc[0]
        rows.append(f"{size} & {d.transfer_cap} / {m.transfer_cap} & {d.alloc_p99_9_median_us:.1f} / "
                    f"{m.alloc_p99_9_median_us:.1f} & {d.slow_mode_fraction:.1f} / {m.slow_mode_fraction:.1f} & "
                    f"{d.free_p99_9_median_us:.1f} / {m.free_p99_9_median_us:.1f} & "
                    f"{d.mops_median:.2f} / {m.mops_median:.2f} \\\\")
    header = ("Size (B) & Cap: default / patched & Alloc P99.9 ($\\mu$s) & Slow-mode fraction & "
              "Free P99.9 ($\\mu$s) & Mops/s \\\\")
    return booktabs("tcmalloc transfer-batch cap experiment at 8 threads under 8:1 handoff, ten iterations per cell. "
                    "Values are default / patched. The patch raises the cap from min(32, 64~KB/size) to "
                    "min(256, 1~MB/size) and changes nothing else.",
                    "tab:batchcap", "lllrrr", header, rows)


GAP_ROWS = [
    ("Remote-free batching cost on producer--consumer loads",
     "BatchIt, ISMM 2024 (intellectual abstract): per-slab batching of remote frees",
     "Event-level distributions for mimalloc and snmalloc baselines (Table~\\ref{tab:uncertainty}); BatchIt not evaluated"),
    ("Coherence granule for atomic writes on ARM64 architectures",
     "No peer-reviewed 2024--2026 measurement found in our search",
     "64-byte step with process cycle counts (Fig.~\\ref{fig:fig06})"),
    ("Hardware false-sharing repair on commodity processors",
     "Patel et al., MICRO 2024: MESI extension evaluated in simulation",
     "Real-hardware latency and cycle probe; repair not implemented"),
    ("Defragmentation of unmanaged heaps",
     "Wanninger et al., ASPLOS 2024: handle-based heap with compiler and runtime support",
     "Footprint under OS page release advice without compiler changes (Fig.~\\ref{fig:fig10})"),
    ("Large-object tail mechanism in tcmalloc",
     "Fleet-scale TCMalloc characterization (ASPLOS 2024) covers production use, not the open-source build",
     "Source-level batch-cap experiment (Table~\\ref{tab:batchcap})"),
    ("TLB shootdown cost on commodity operating systems",
     "Amit (ATC 2017), LATR (ASPLOS 2018), DiDi (PACT 2011): Linux or hardware studies; Schimmelpfennig et al. (PDP 2025): Linux mmap page recycling",
     "Microarchitectural shootdown characterization (Section~\\ref{sec:threats})"),
    ("Event-level tail amplification under handoff for production allocators",
     "No controlled 2024+ study of handoff tails found; the fleet characterization (ASPLOS 2024) reports allocation patterns",
     "Five allocators, four topologies, eight sizes, six thread counts, 50 iterations"),
    ("Extreme quantiles from binned latency histograms",
     "Pickands 1975; Balkema and de Haan 1974; Hosking and Wallis 1987 (theory)",
     "Grouped likelihood with threshold sensitivity (Table~\\ref{tab:gpd})"),
    ("Scalability of allocators on heterogeneous cores",
     "Gunther 2007 (USL); no modern ARM64 allocator study found",
     "Symmetric USL fits with core-cluster caveats (Table~\\ref{tab:usl})"),
    ("Footprint bimodality of the system allocator under churn",
     "No literature found",
     "Reported with repeat runs; cause left open"),
]


def table07() -> str:
    rows = [f"{gap} & {basis} & {addressed} \\\\" for gap, basis, addressed in GAP_ROWS]
    header = "Open question & Representative prior work & How this study addresses it\\\\"
    return booktabs("Open questions in the literature and how this study addresses them. The 2024 onward entries are the "
                    "core peer-reviewed matches from the index search described in Section~\\ref{sec:background}.",
                    "tab:gaps", "p{0.28\\linewidth}"
                    "p{0.36\\linewidth}"
                    "p{0.28\\linewidth}", header, rows)


TAXONOMY_ROWS = [
    ("mimalloc 3.5.4",
     "Cross-thread frees go through \\texttt{mi\\_free\\_block\\_mt} (\\texttt{src/free.c}:70), which pushes onto the page's \\texttt{xthread\\_free} list (\\texttt{src/free.c}:86--91)",
     "64~KiB small, 512~KiB medium, 4~MiB large pages (\\texttt{include/mimalloc/types.h}:249--251)",
     "Reset \\texttt{MADV\\_FREE}; decommit \\texttt{MADV\\_FREE\\_REUSABLE} (\\texttt{src/prim/unix/prim.c}:546--585)"),
    ("jemalloc 5.4.0",
     "Frees return to the owning bin under \\texttt{bin->lock} (\\texttt{src/arena.c}, \\texttt{src/bin.c}:337)",
     "Size classes (\\texttt{include/jemalloc/internal/sc.h}); slabs tracked per bin (\\texttt{bin.h}); dirty decay 10~s by default (\\texttt{arena.h}:31)",
     "Lazy purge \\texttt{MADV\\_FREE} on POSIX (\\texttt{include/jemalloc/internal/os/\\allowbreak posix/vm.h}:268--271)"),
    ("tcmalloc (gperftools 2.19.1)",
     "\\texttt{ListTooLong} releases batches to the central list (\\texttt{src/thread\\_cache.cc}:158, 185), which inserts under a \\texttt{SpinLock} in \\texttt{CentralFreeList::InsertRange} (\\texttt{src/central\\_freelist.cc}:215)",
     "16~KiB pages on 64-bit ARM, 8~KiB elsewhere; 256~KiB maximum small size (\\texttt{src/common.h}:74--87)",
     "\\texttt{MADV\\_FREE} advisory release (\\texttt{src/system-alloc.cc}:425)"),
    ("snmalloc 0.6.2",
     "One multi-producer single-consumer queue per allocator, one atomic exchange per append (\\texttt{src/snmalloc/mem/remoteallocator.h})",
     "Size-class slabs (\\texttt{src/snmalloc/mem/sizeclasstable.h})",
     "\\texttt{MADV\\_FREE\\_REUSABLE} with paired \\texttt{MADV\\_FREE\\_REUSE} (\\texttt{src/snmalloc/pal/pal\\_apple.h}:119--141)"),
    ("libmalloc (system baseline)",
     "Closed source; not verifiable from source here",
     "Closed source; not verifiable from source here",
     "Not verifiable from source; footprint behaviour measured in Section~\\ref{sec:rq4}"),
]


def breakable_paths(latex: str) -> str:
    return re.sub(r"\\texttt\{([^}]*)\}",
                  lambda m: "\\texttt{" + m.group(1).replace("/", "/\\allowbreak ").replace(".", ".\\allowbreak ").replace(":", ":\\allowbreak ") + "}", latex)


def table09() -> str:
    rows = [f"{breakable_paths(a)} & {breakable_paths(b)} & {breakable_paths(c)} & {breakable_paths(d)} \\\\" for a, b, c, d in TAXONOMY_ROWS]
    header = "Allocator & Remote-free path & Page or slab granule & Release advice\\\\"
    return booktabs("Implementation facts for the evaluated allocators, read from the source trees at the tested versions. "
                    "File references are relative to each tree; libmalloc is closed source.",
                    "tab:taxonomy", "p{0.12\\linewidth}"
                    "p{0.30\\linewidth}"
                    "p{0.24\\linewidth}"
                    "p{0.22\\linewidth}",
                    header, rows, size=r"\scriptsize")


GAP_CSV_PATH = WORKSPACE / "literature" / "granular_gaps_and_scopes.csv"


def plain_text(latex: str) -> str:
    text = re.sub(r"\\ref\{([^}]*)\}", r"[\1]", latex)
    text = re.sub(r"\\(?:texttt|emph)\{([^}]*)\}", r"\1", text)
    return text.replace("~", " ").replace("--", "-").replace("  ", " ").strip()


def write_gap_csv() -> None:
    GAP_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GAP_CSV_PATH.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Gap_ID", "Open_Question", "Representative_Prior_Work", "How_This_Study_Addresses_It"])
        for index, (gap, basis, addressed) in enumerate(GAP_ROWS, start=1):
            writer.writerow([f"GAP-{index:02d}", plain_text(gap), plain_text(basis), plain_text(addressed)])


def generate_tables() -> None:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    configs = pd.read_csv(METRICS_DIR / "tier1_configs.csv")
    usl = pd.read_csv(METRICS_DIR / "tier1_usl.csv")
    outputs = {
        "tab01.tex": table01(configs),
        "tab02.tex": table02(configs),
        "tab03.tex": table03(),
        "tab04.tex": table04(usl),
        "tab05.tex": table05(configs),
        "tab06.tex": table06(),
        "tab07.tex": table07(),
        "tab08.tex": table08(),
        "tab09.tex": table09(),
    }
    write_gap_csv()
    for name, content in outputs.items():
        (TABLE_DIR / name).write_text(content)
