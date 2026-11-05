"""
src/verify_paper_claims.py

Recomputes the numbers quoted in the manuscript from the raw runs and the
derived metrics, and prints each claim with its computed value. Run after
src/build_artifacts.py. Exits non-zero if any check outside tolerance fails.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.histogram_pool import pool_buckets, weighted_percentile  # noqa: E402

METRICS = WORKSPACE / "results" / "metrics"
RAW = WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl"
ABLATION = WORKSPACE / "data" / "ablation"

FAILURES = []


def check(label: str, computed, expected, tolerance: float) -> None:
    ok = abs(float(computed) - float(expected)) <= tolerance
    status = "PASS" if ok else "FAIL"
    print(f"{status}  {label}: computed {float(computed):.4g}, text {float(expected):.4g}")
    if not ok:
        FAILURES.append(label)


def raw_path() -> Path:
    """Returns the plain JSON Lines file, or its gzip-compressed copy in the replication package."""
    if RAW.exists():
        return RAW
    return RAW.with_name(RAW.name + ".gz")


def load_raw() -> list:
    path = raw_path()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as handle:
        return [json.loads(line) for line in handle]


APPENDIX_SAMPLES = [
    ("mimalloc", 64, 8, "asymmetric_8_1", "event_p99_9_ns", 99.9),
    ("tcmalloc", 16384, 8, "asymmetric_8_1", "event_p99_99_ns", 99.99),
    ("libmalloc", 4096, 16, "ring", "event_p99_9_ns", 99.9),
    ("snmalloc", 262144, 32, "asymmetric_4_1", "event_p99_9_ns", 99.9),
    ("jemalloc", 1024, 4, "symmetric", "event_p99_9_ns", 99.9),
]


def recompute_from_raw(raw: list, allocator: str, size: int, threads: int, topology: str, percent: float):
    """Pools the alloc and free histograms of every iteration in one configuration, independently of the CSV."""
    results = [r["result"] for r in raw if "error" not in r
               and r["allocator"] == allocator and r["size"] == size
               and r["threads"] == threads and r["topology"] == topology]
    buckets = pool_buckets([x["alloc_counts"] for x in results] + [x["free_counts"] for x in results])
    return weighted_percentile(buckets, percent), len(results)


def check_appendix_cells(raw: list, configs: pd.DataFrame) -> None:
    for allocator, size, threads, topology, column, percent in APPENDIX_SAMPLES:
        label = f"appendix {allocator} {size} B {threads} T {topology} {column}"
        recomputed, iterations = recompute_from_raw(raw, allocator, size, threads, topology, percent)
        row = configs[(configs.allocator == allocator) & (configs.size_bytes == size)
                      & (configs.threads == threads) & (configs.topology == topology)].iloc[0]
        check(f"{label} iterations", iterations, 50, 0)
        check(label, recomputed, row[column], 0)


def check_extended_tables() -> None:
    """Cross-checks the all-size ANOVA and USL outputs against the earlier 64 B and 4 KB metric files."""
    anova = pd.read_csv(METRICS / "tier1_anova_all_sizes.csv")
    for size in (64, 4096):
        old = pd.read_csv(METRICS / f"tier1_anova_{size}.csv").set_index("source")
        new = anova[anova.size_bytes == size].set_index("source")
        for source in ("allocator", "topology", "allocator x topology"):
            check(f"ANOVA {size} B {source} F matches earlier metric", new.loc[source, "F"], old.loc[source, "F"], 1e-6)
        check(f"ANOVA {size} B residual eta matches", new.loc["residual", "eta_squared"],
              old.loc["residual", "eta_squared"], 1e-9)
    usl = pd.read_csv(METRICS / "tier1_usl_all_sizes.csv")
    old_usl = pd.read_csv(METRICS / "tier1_usl.csv")
    merged = usl.merge(old_usl, on=["allocator", "size_bytes"], suffixes=("", "_old"))
    check("USL all-size sigma_c matches earlier metric (max abs diff)",
          (merged.sigma_c - merged.sigma_c_old).abs().max(), 0.0, 1e-9)
    check("USL all-size kappa_c matches earlier metric (max abs diff)",
          (merged.kappa_c - merged.kappa_c_old).abs().max(), 0.0, 1e-12)
    check("USL all-size row count", len(usl), 40, 0)
    print("-- Shape parameter at 95 percent: pooled histogram versus mean of per-iteration fits")
    configs = pd.read_csv(METRICS / "tier1_configs.csv")
    spread = pd.read_csv(METRICS / "tier1_gpd_iteration_spread.csv")
    for allocator, size, pooled_text, mean_text in [("mimalloc", 64, 0.252, 0.363), ("tcmalloc", 4096, 0.626, 0.723)]:
        pooled = configs[(configs.allocator == allocator) & (configs.size_bytes == size)
                         & (configs.threads == 8) & (configs.topology == "asymmetric_8_1")].iloc[0].gpd_xi
        mean = spread[(spread.allocator == allocator) & (spread.size_bytes == size)
                      & (spread.topology == "asymmetric_8_1")].iloc[0].xi_iteration_mean
        check(f"pooled xi 95 {allocator} {size} B (Table A10)", pooled, pooled_text, 0.001)
        check(f"iteration-mean xi 95 {allocator} {size} B (Table 9)", mean, mean_text, 0.001)
    usl_monotone = usl[usl.t_star == 1.0]
    check("USL monotone cells (libmalloc 64 KB and 256 KB)", len(usl_monotone), 2, 0)


def main() -> int:
    raw = load_raw()
    configs = pd.read_csv(METRICS / "tier1_configs.csv")

    def cfg(allocator, threads, size, topology, column):
        row = configs[(configs.allocator == allocator) & (configs.threads == threads)
                      & (configs.size_bytes == size) & (configs.topology == topology)].iloc[0]
        return row[column]

    print("-- Counts")
    check("sweeps", len(raw), 42000, 0)
    check("configurations", len(configs), 840, 0)
    check("failed runs", sum("error" in r for r in raw), 0, 0)

    print("-- Symmetric P99.9, 8 threads, 64 B (text: 42-250 ns)")
    sym = {a: cfg(a, 8, 64, "symmetric", "event_p99_9_ns") for a in
           ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]}
    check("mimalloc sym", sym["mimalloc"], 42, 0)
    check("jemalloc sym", sym["jemalloc"], 42, 0)
    check("tcmalloc sym", sym["tcmalloc"], 125, 0)
    check("snmalloc sym", sym["snmalloc"], 85, 0)
    check("libmalloc sym", sym["libmalloc"], 250, 0)

    print("-- 8:1 P99.9, 8 threads, 64 B (text: 250-2976 ns; Gamma 21.9-175.0)")
    for a, expected in [("mimalloc", 250), ("jemalloc", 2976), ("tcmalloc", 1456),
                        ("snmalloc", 1040), ("libmalloc", 792)]:
        check(f"{a} 8:1 P99.9", cfg(a, 8, 64, "asymmetric_8_1", "event_p99_9_ns"), expected, 0)
    gammas = [cfg(a, 8, 64, "asymmetric_8_1", "gamma_tail") for a in
              ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]]
    check("Gamma min", min(gammas), 21.9, 0.05)
    check("Gamma max", max(gammas), 175.0, 0.05)

    print("-- Split at 8:1, 64 B (text: mimalloc free 250, alloc 1904; jemalloc alloc 1040, free 3232)")
    check("mimalloc free", cfg("mimalloc", 8, 64, "asymmetric_8_1", "free_p99_9_ns"), 250, 0)
    check("mimalloc alloc", cfg("mimalloc", 8, 64, "asymmetric_8_1", "alloc_p99_9_ns"), 1904, 0)
    check("jemalloc alloc", cfg("jemalloc", 8, 64, "asymmetric_8_1", "alloc_p99_9_ns"), 1040, 0)
    check("jemalloc free", cfg("jemalloc", 8, 64, "asymmetric_8_1", "free_p99_9_ns"), 3232, 0)

    print("-- 4 KB 8:1 tails (text: free 1072/1456/1552/1904/3040; alloc 6080/6336/7360/8320/17152)")
    for a, free, alloc in [("mimalloc", 1072, 8320), ("snmalloc", 1456, 6336), ("tcmalloc", 1552, 6080),
                           ("jemalloc", 1904, 7360), ("libmalloc", 3040, 17152)]:
        check(f"{a} 4KB free", cfg(a, 8, 4096, "asymmetric_8_1", "free_p99_9_ns"), free, 0)
        check(f"{a} 4KB alloc", cfg(a, 8, 4096, "asymmetric_8_1", "alloc_p99_9_ns"), alloc, 0)
    for a, pooled in [("tcmalloc", 3808), ("snmalloc", 4928), ("jemalloc", 5440), ("mimalloc", 6848),
                      ("libmalloc", 10624)]:
        check(f"{a} 4KB 8:1 P99.9", cfg(a, 8, 4096, "asymmetric_8_1", "event_p99_9_ns"), pooled, 0)

    print("-- tcmalloc large sizes (text: 80896 at 16KB, 1196032 at 256KB; other four 9-27 us at 16-256KB)")
    check("tcmalloc 16KB event", cfg("tcmalloc", 8, 16384, "asymmetric_8_1", "event_p99_9_ns"), 80896, 0)
    check("tcmalloc 256KB event", cfg("tcmalloc", 8, 262144, "asymmetric_8_1", "event_p99_9_ns"), 1196032, 0)
    for a in ["jemalloc", "libmalloc", "mimalloc", "snmalloc"]:
        for s in (16384, 65536, 262144):
            v = cfg(a, 8, s, "asymmetric_8_1", "event_p99_9_ns") / 1e3
            if not (9.0 <= v <= 27.5):
                FAILURES.append(f"{a} {s} outside 9-27us")
                print(f"FAIL  {a} {s} B event P99.9 {v:.1f} us outside 9-27 us")
    print("PASS  other four allocators 16-256KB event P99.9 within 9-27 us (checked above, no output means pass)")

    print("-- Per-iteration slow-mode fractions (text: tcmalloc 66% at 16KB, 98% at 256KB; others <=20%, <=8%)")
    for size, tc_expected, other_max in [(16384, 0.66, 0.20), (262144, 0.98, 0.08)]:
        by = {}
        for r in raw:
            if r["threads"] == 8 and r["topology"] == "asymmetric_8_1" and r["size"] == size:
                b = pool_buckets([r["result"]["alloc_counts"]])
                by.setdefault(r["allocator"], []).append(weighted_percentile(b, 99.9) > 100e3)
        check(f"tcmalloc slow fraction {size}", np.mean(by["tcmalloc"]), tc_expected, 0.01)
        others = max(np.mean(by[a]) for a in ["jemalloc", "libmalloc", "mimalloc", "snmalloc"])
        if others > other_max + 1e-9:
            FAILURES.append(f"other slow fraction {size}")
            print(f"FAIL  other allocators max slow fraction {others:.2f} > {other_max}")
        else:
            print(f"PASS  other allocators max slow fraction {others:.2f} <= {other_max} at {size} B")

    print("-- Ring and throughput (text: ring 372/372/460/1040/1136 ns; ring 32-37 Mops; 8:1 6-9 Mops)")
    for a, v in [("libmalloc", 372), ("tcmalloc", 372), ("mimalloc", 460), ("snmalloc", 1040), ("jemalloc", 1136)]:
        check(f"{a} ring P99.9", cfg(a, 8, 64, "ring", "event_p99_9_ns"), v, 0)
    ring_t = [cfg(a, 8, 64, "ring", "throughput_mops_mean") for a in
              ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]]
    check("ring Mops min", min(ring_t), 32.1, 0.1)
    check("ring Mops max", max(ring_t), 36.8, 0.1)
    eight = [cfg(a, 8, 64, "asymmetric_8_1", "throughput_mops_mean") for a in
             ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]]
    check("8:1 Mops min", min(eight), 5.99, 0.1)
    check("8:1 Mops max", max(eight), 8.74, 0.1)

    print("-- Throughput spread (text: 13-29% CV at 8 threads; median 21% across all configs)")
    cv = 100 * configs.throughput_mops_sd / configs.throughput_mops_mean
    sym_cv = 100 * configs[(configs.threads == 8) & (configs.topology == "symmetric")
                           & (configs.size_bytes.isin([64, 4096]))].pipe(
        lambda f: f.throughput_mops_sd / f.throughput_mops_mean)
    check("CV symmetric 8T min", sym_cv.min(), 12.8, 0.6)
    check("CV symmetric 8T max", sym_cv.max(), 28.5, 0.6)
    check("CV median all configs", cv.median(), 21.2, 0.3)
    mean_gap = (cfg("mimalloc", 8, 64, "symmetric", "throughput_mops_mean")
                - cfg("libmalloc", 8, 64, "symmetric", "throughput_mops_mean"))
    sem = math.sqrt(
        (cfg("mimalloc", 8, 64, "symmetric", "throughput_mops_sd") ** 2
         + cfg("libmalloc", 8, 64, "symmetric", "throughput_mops_sd") ** 2) / 50)
    print(f"INFO  mimalloc minus libmalloc symmetric 8T 64B throughput: {mean_gap:.1f} Mops/s, "
          f"standard error of the difference {sem:.2f} Mops/s")

    print("-- ANOVA (text: classical 18.6/62.5/15.2 at 64 B; 11.5/79.7/4.1 at 4 KB; partial 0.834/0.944/0.804, 0.714/0.945/0.474)")
    a64 = pd.read_csv(METRICS / "tier1_anova_64.csv").set_index("source")
    a4k = pd.read_csv(METRICS / "tier1_anova_4096.csv").set_index("source")
    check("64B allocator classical", a64.loc["allocator", "eta_squared"] * 100, 18.6, 0.05)
    check("64B topology classical", a64.loc["topology", "eta_squared"] * 100, 62.5, 0.05)
    check("64B interaction classical", a64.loc["allocator x topology", "eta_squared"] * 100, 15.2, 0.05)
    check("4KB allocator classical", a4k.loc["allocator", "eta_squared"] * 100, 11.5, 0.05)
    check("4KB topology classical", a4k.loc["topology", "eta_squared"] * 100, 79.7, 0.05)
    check("4KB interaction classical", a4k.loc["allocator x topology", "eta_squared"] * 100, 4.1, 0.05)
    check("64B allocator partial", a64.loc["allocator", "partial_eta_squared"], 0.834, 0.001)
    check("64B topology partial", a64.loc["topology", "partial_eta_squared"], 0.944, 0.001)
    check("64B interaction partial", a64.loc["allocator x topology", "partial_eta_squared"], 0.804, 0.001)
    check("4KB allocator partial", a4k.loc["allocator", "partial_eta_squared"], 0.714, 0.001)
    check("4KB topology partial", a4k.loc["topology", "partial_eta_squared"], 0.945, 0.001)
    check("4KB interaction partial", a4k.loc["allocator x topology", "partial_eta_squared"], 0.474, 0.001)
    total64 = a64.loc[["allocator", "topology", "allocator x topology", "residual"], "eta_squared"].sum()
    check("64B classical shares sum to one", total64, 1.0, 1e-6)

    print("-- Per-iteration medians 8:1 64 B (text: 210, 840, 1040, 1328, 2816)")
    unc = pd.read_csv(METRICS / "tier1_p999_uncertainty.csv")
    for a, v in [("mimalloc", 210), ("libmalloc", 840), ("snmalloc", 1040), ("tcmalloc", 1328), ("jemalloc", 2816)]:
        row = unc[(unc.allocator == a) & (unc.size_bytes == 64) & (unc.topology == "asymmetric_8_1")].iloc[0]
        check(f"{a} per-iteration median", row.median_p999_ns, v, 0)

    print("-- GPD quantile errors (text: -37% to +73%; threshold 90->98 mimalloc 4KB -53 to -8)")
    gpd = pd.read_csv(METRICS / "tier1_configs.csv")
    errs = []
    for a in ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]:
        for s in (64, 4096):
            row = gpd[(gpd.allocator == a) & (gpd.size_bytes == s) & (gpd.threads == 8)
                       & (gpd.topology == "asymmetric_8_1")].iloc[0]
            errs.append(100 * (row.gpd_q999_ns - row.event_p99_9_ns) / row.event_p99_9_ns)
    check("GPD error min", min(errs), -36.5, 0.6)
    check("GPD error max", max(errs), 73.2, 0.6)

    print("-- Batch-cap experiment (text: 737->74 us at 16 KB; 1245->1556 at 256 KB; 58->16 at 4 KB; 2.9->4.7 at 64 B)")
    cap = pd.read_csv(METRICS / "tcmalloc_batch_cap.csv")

    def capv(size, build, col):
        return cap[(cap.size_bytes == size) & (cap.build == build)].iloc[0][col]

    check("16KB default median", capv(16384, "default", "alloc_p99_9_median_us"), 737.3, 0.5)
    check("16KB patched median", capv(16384, "mod", "alloc_p99_9_median_us"), 73.7, 0.5)
    check("256KB default median", capv(262144, "default", "alloc_p99_9_median_us"), 1245.2, 0.5)
    check("256KB patched median", capv(262144, "mod", "alloc_p99_9_median_us"), 1556.5, 0.5)
    check("4KB default median", capv(4096, "default", "alloc_p99_9_median_us"), 58.4, 0.5)
    check("4KB patched median", capv(4096, "mod", "alloc_p99_9_median_us"), 16.0, 0.5)
    check("64B default median", capv(64, "default", "alloc_p99_9_median_us"), 2.88, 0.01)
    check("64B patched median", capv(64, "mod", "alloc_p99_9_median_us"), 4.74, 0.01)
    check("16KB slow fraction default", capv(16384, "default", "slow_mode_fraction"), 1.0, 0.0)
    check("16KB slow fraction patched", capv(16384, "mod", "slow_mode_fraction"), 0.1, 0.01)

    print("-- Ablation (text: default vs 256 MB medians 950/1016 and 942/1008 us; change under 10%)")
    ab = [json.loads(l) for l in (ABLATION / "tcmalloc_thread_cache_n10.jsonl").open()]
    for size, expected in [(16384, (950, 1016)), (262144, (942, 1008))]:
        meds = {}
        for mode in ("default", "big_cache"):
            vals = [r["alloc_latency_ns"]["p99_9"] / 1e3 for r in ab
                    if r["alloc_size_bytes"] == size and r["budget"] == mode]
            meds[mode] = float(np.median(vals))
        check(f"ablation {size} default median", meds["default"], expected[0], 1.0)
        check(f"ablation {size} 256MB median", meds["big_cache"], expected[1], 1.0)
        change = abs(meds["big_cache"] - meds["default"]) / meds["default"]
        if change >= 0.10:
            FAILURES.append(f"ablation change {size}")
            print(f"FAIL  ablation change {change:.2%} >= 10%")
        else:
            print(f"PASS  ablation change {change:.2%} < 10% at {size} B")

    print("-- Coherence stride (text: 8.7-9.4 ns and 23-25 cycles below 64 B; 2.4-2.6 ns and about 7 cycles at 64+)")
    fs = pd.read_csv(METRICS / "probe_false_sharing.csv")
    below = fs[(fs.threads == 2) & (fs.stride_bytes < 64)]
    above = fs[(fs.threads == 2) & (fs.stride_bytes >= 64)]
    check("2T below-64 ns min", below.ns_per_increment_mean.min(), 8.68, 0.05)
    check("2T below-64 ns max", below.ns_per_increment_mean.max(), 9.36, 0.05)
    check("2T below-64 cycles min", below.cycles_per_increment_mean.min(), 23.4, 0.1)
    check("2T below-64 cycles max", below.cycles_per_increment_mean.max(), 24.7, 0.1)
    check("2T above-64 ns min", above.ns_per_increment_mean.min(), 2.43, 0.05)
    check("2T above-64 ns max", above.ns_per_increment_mean.max(), 2.58, 0.05)
    check("instructions per increment min", fs.instructions_per_increment_mean.min(), 3.01, 0.02)
    check("instructions per increment max", fs.instructions_per_increment_mean.max(), 3.10, 0.02)
    four = fs[fs.threads == 4].set_index("stride_bytes")
    check("4T stride 8 ns", four.loc[8, "ns_per_increment_mean"], 27.37, 0.1)
    check("4T stride 8 cycles", four.loc[8, "cycles_per_increment_mean"], 60.6, 0.2)
    check("4T stride 32 cycles", four.loc[32, "cycles_per_increment_mean"], 35.9, 0.2)
    check("4T stride 48 cycles", four.loc[48, "cycles_per_increment_mean"], 17.9, 0.2)
    check("4T stride 128 cycles", four.loc[128, "cycles_per_increment_mean"], 6.7, 0.2)
    diff64_128 = max(abs(fs[(fs.threads == t) & (fs.stride_bytes == 64)].ns_per_increment_mean.values[0]
                         - fs[(fs.threads == t) & (fs.stride_bytes == 128)].ns_per_increment_mean.values[0])
                     for t in (2, 4))
    if diff64_128 > 0.9 or diff64_128 < 0.7:
        FAILURES.append("64 vs 128 B ns difference")
        print(f"FAIL  64 vs 128 B max ns difference {diff64_128:.2f} not in expected range")
    else:
        print(f"PASS  64 vs 128 B max ns difference {diff64_128:.2f} ns (text states 0.8 ns)")

    print("-- Purge probe (text: DONTNEED 513 MB; FREE min 508/487/449; FREE_REUSABLE 257; mean 384-388)")
    pr = pd.read_csv(METRICS / "probe_purge_runs.csv")
    g = pr.groupby(["policy", "interval_ms"]).footprint_min_mb.mean()
    check("DONTNEED min footprint 50ms", g[("dontneed", 50)], 513.3, 0.2)
    check("FREE min footprint 50ms", g[("free", 50)], 507.5, 0.5)
    check("FREE min footprint 200ms", g[("free", 200)], 486.7, 0.5)
    check("FREE min footprint 1000ms", g[("free", 1000)], 449.2, 0.5)
    check("FREE_REUSABLE min 1000ms", g[("free_reusable", 1000)], 257.3, 0.2)
    gm = pr.groupby(["policy", "interval_ms"]).footprint_mean_mb.mean()
    check("FREE_REUSABLE mean min", gm.xs("free_reusable").min(), 384.0, 0.5)
    check("FREE_REUSABLE mean max", gm.xs("free_reusable").max(), 387.6, 0.5)
    acc = pr.groupby(["policy", "interval_ms"]).access_p99_9_ns.mean()
    check("access P99.9 min", acc.min(), 436, 1)
    check("access P99.9 max", acc.max(), 651, 2)
    rp = pr.groupby(["policy", "interval_ms"]).reuse_p99_9_us.mean()
    check("DONTNEED reuse 50ms (us)", rp[("dontneed", 50)], 815, 2)
    check("FREE_REUSABLE reuse 50ms (us)", rp[("free_reusable", 50)], 552, 2)
    check("DONTNEED reuse 1000ms (us)", rp[("dontneed", 1000)], 2307, 2)
    check("FREE_REUSABLE reuse 1000ms (us)", rp[("free_reusable", 1000)], 2674, 2)
    ctrl = pr[pr.policy == "none"].groupby("interval_ms").page_faults.median()
    check("control median faults 50ms", ctrl[50], 49, 0)
    check("control median faults 200ms", ctrl[200], 43, 0)
    check("control median faults 1000ms", ctrl[1000], 47, 0)
    per_cell = pr[pr.policy != "none"].groupby(["policy", "interval_ms"]).page_faults.median()
    check("release-policy cell medians min", per_cell.min(), 944, 0)
    check("release-policy cell medians max", per_cell.max(), 35149, 0)

    print("-- Bloat (text: KV 4.2/3.9/3.8/4.7; AST 1.5-2.6; gRPC 1.6-4.9)")
    tr = pd.read_csv(METRICS / "tier2_trace_runs.csv")
    kv = tr[tr.workload == "kv_churn"].groupby("allocator").bloat_ratio.mean()
    check("KV jemalloc", kv["jemalloc"], 4.2, 0.05)
    check("KV mimalloc", kv["mimalloc"], 3.9, 0.05)
    check("KV snmalloc", kv["snmalloc"], 3.8, 0.05)
    check("KV tcmalloc", kv["tcmalloc"], 4.7, 0.05)
    ast = tr[tr.workload == "ast_graph"].groupby("allocator").bloat_ratio.mean()
    check("AST tcmalloc min", ast["tcmalloc"], 1.46, 0.05)
    check("AST mimalloc mean", ast["mimalloc"], 2.60, 0.05)
    grpc = tr[tr.workload == "grpc_pipeline"].groupby("allocator").bloat_ratio.mean()
    check("gRPC libmalloc", grpc["libmalloc"], 1.62, 0.05)
    check("gRPC jemalloc", grpc["jemalloc"], 4.84, 0.05)
    sup = pd.read_csv(METRICS / "tier2_kv_supplement.csv")
    sup_lib = sup[sup.allocator == "libmalloc"]
    check("supplement libmalloc min footprint MB", sup_lib.peak_footprint_mb.min(), 24.1, 0.2)
    check("supplement libmalloc max footprint MB", sup_lib.peak_footprint_mb.max(), 72.1, 0.2)
    check("supplement libmalloc median bloat", sup_lib.bloat_ratio.median(), 14.75, 0.05)

    print("-- USL (text: R2 97-99% at 64 B; sigma 0.05-0.10; kappa 0.0014-0.0039; T* 15-25)")
    usl = pd.read_csv(METRICS / "tier1_usl.csv")
    u64 = usl[usl.size_bytes == 64]
    check("USL R2 min 64B", u64.r_squared.min(), 0.972, 0.001)
    check("USL R2 max 64B", u64.r_squared.max(), 0.995, 0.001)
    check("USL sigma min", u64.sigma_c.min(), 0.050, 0.001)
    check("USL sigma max", u64.sigma_c.max(), 0.102, 0.001)
    check("USL kappa min", u64.kappa_c.min(), 0.00141, 0.00002)
    check("USL kappa max", u64.kappa_c.max(), 0.00386, 0.00002)
    check("USL T* min 64B", u64.t_star.min(), 15, 0)
    check("USL T* max 64B", u64.t_star.max(), 25, 0)
    print("-- Small objects and 4:1 thread counts (text: 16 B mimalloc 210 ns lowest; 4:1 64 B mimalloc 1840/210/1040; libmalloc 1072 at 8)")
    small = {a: cfg(a, 8, 16, "asymmetric_8_1", "event_p99_9_ns") for a in
             ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]}
    check("16B mimalloc lowest value", min(small.values()) - small["mimalloc"], 0, 0)
    check("16B mimalloc 8:1 P99.9", small["mimalloc"], 210, 0)
    check("16B libmalloc 8:1 P99.9", small["libmalloc"], 332, 0)
    check("mimalloc 4:1 64B at 2 threads", cfg("mimalloc", 2, 64, "asymmetric_4_1", "event_p99_9_ns"), 1840, 0)
    check("mimalloc 4:1 64B at 4 threads", cfg("mimalloc", 4, 64, "asymmetric_4_1", "event_p99_9_ns"), 210, 0)
    check("mimalloc 4:1 64B at 32 threads", cfg("mimalloc", 32, 64, "asymmetric_4_1", "event_p99_9_ns"), 1040, 0)
    check("libmalloc 4:1 64B at 8 threads", cfg("libmalloc", 8, 64, "asymmetric_4_1", "event_p99_9_ns"), 1072, 0)
    four_k = [cfg(a, 8, 4096, "asymmetric_4_1", "event_p99_9_ns") for a in
              ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]]
    check("4KB 4:1 at 8 threads min (us)", min(four_k) / 1e3, 2.7, 0.05)
    check("4KB 4:1 at 8 threads max (us)", max(four_k) / 1e3, 12.4, 0.05)

    print("-- Core-placement table (text: 4T CV 19-39% except tcmalloc 60-64%; 8T CV 16-25% except tcmalloc 72-74%)")
    for threads, lo, hi, tc_lo, tc_hi in [(4, 19, 39, 60, 64), (8, 16, 25, 72, 74)]:
        cvs = {(a, s): 100 * cfg(a, threads, s, "asymmetric_8_1", "throughput_mops_sd") / cfg(a, threads, s, "asymmetric_8_1", "throughput_mops_mean")
               for a in ["mimalloc", "jemalloc", "snmalloc", "libmalloc"] for s in (64, 4096)}
        tc = {s: 100 * cfg("tcmalloc", threads, s, "asymmetric_8_1", "throughput_mops_sd") / cfg("tcmalloc", threads, s, "asymmetric_8_1", "throughput_mops_mean")
              for s in (64, 4096)}
        check(f"{threads}T non-tcmalloc CV min", min(cvs.values()), lo, 1.0)
        check(f"{threads}T non-tcmalloc CV max", max(cvs.values()), hi, 1.0)
        check(f"{threads}T tcmalloc CV min", min(tc.values()), tc_lo, 1.0)
        check(f"{threads}T tcmalloc CV max", max(tc.values()), tc_hi, 1.0)

    print("-- Appendix atlas cells recomputed from the raw histograms")
    check_appendix_cells(raw, configs)
    print("-- Extended tables cross-checked against the earlier metrics")
    check_extended_tables()

    print("-- Harness and probes: CNTFRQ and counts are recorded in the README and paper methods")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
