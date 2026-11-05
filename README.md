# Tail-Latency Amplification Under Cross-Thread Handoff, Coherence Granularity, and Page-Release Footprint in Concurrent Memory Allocators

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![C++17](https://img.shields.io/badge/Standard-C%2B%2B17-blue.svg)](https://en.wikipedia.org/wiki/C%2B%2B17)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)

This repository contains the complete experimental replication suite, empirical datasets, micro-architectural probes, analytical models, and manuscript source files for the research paper:

> **Tail-Latency Amplification Under Cross-Thread Handoff, Coherence Granularity, and Page-Release Footprint in Concurrent Memory Allocators**  
> *Devarsh Patel, Adarsh Singh, and Deepika J*  
> School of Computer Science and Engineering (SCOPE), Vellore Institute of Technology (VIT), Vellore, Tamil Nadu, India.  
> Corresponding author: `deepika.j@vit.ac.in`  
> Contributing authors: `devarsh.patel2024@vitstudent.ac.in`, `adarsh.singh2024b@vitstudent.ac.in`

---

## Overview

In concurrent systems, allocation-intensive services frequently transfer heap objects across execution threads, making cross-thread deallocation (the *remote-free path*) a primary determinant of tail latency. Conventional benchmarking suites predominantly report aggregate throughput under symmetric workloads, obscuring substantial tail-latency amplification.

This benchmark suite and replication artifact provides:
1. **Dynamic Event-Level Benchmarking:** High-resolution per-event latency instrumentation across symmetric, asymmetric ($4:1$ and $8:1$), and ring producer–consumer handoff topologies.
2. **Evaluated Allocators:** Systematic evaluation of five production memory allocators:
   - **mimalloc 3.5.4**
   - **jemalloc 5.4.0**
   - **tcmalloc (gperftools 2.19.1)**
   - **snmalloc 0.6.2**
   - **System default allocator (`libmalloc`)**
3. **Hardware Coherence Probing:** Hardware probes isolating cache coherence line penalties (64-byte vs. 128-byte strides) using process-level performance counters (CPU cycles, instructions retired, and CPI).
4. **Virtual Memory Page-Release Analysis:** Kernel page-reclamation advice probes comparing `MADV_DONTNEED`, `MADV_FREE`, and `MADV_FREE_REUSABLE` semantics on physical resident memory footprint.
5. **Statistical Tail Modeling:** Grouped-likelihood Generalized Pareto Distribution (GPD) extreme value theory estimation, two-way Box-Cox ANOVA, and Universal Scalability Law (USL) modeling.

---

## Platform and Toolchain Specifications

All benchmarks were evaluated under the following standardized environment:

| Specification | Target Details |
| :--- | :--- |
| **Processor Architecture** | 8-core heterogeneous multicore processor (4 Performance cores + 4 Efficiency cores) |
| **Coherence Granule** | 128-byte cache line granularity |
| **Operating System** | 64-bit Unix-based operating system |
| **Compiler** | Clang (`clang++`) with `-std=c++17 -O3 -pthread` |
| **Python Environment** | Python 3.10+ (tested on Python 3.12) |
| **Allocators Tested** | `mimalloc 3.5.4`, `jemalloc 5.4.0`, `tcmalloc 2.19.1`, `snmalloc 0.6.2`, `libmalloc` |

---

## Repository Structure

```
├── data/                      # Empirical measurement datasets
│   ├── tier1/                 # 42,000 micro-sweep histograms (840 configs x 50 iterations)
│   ├── tier2/                 # Sustained multi-threaded trace runs
│   ├── ablation/              # tcmalloc transfer-batch cap and thread-cache ablations
│   └── logs/                  # Benchmark execution logs
├── figures/                   # Vector graphics publication figures (fig01–fig13 in PDF)
├── literature/                # Screened literature catalog (PRISMA 2020) and BibTeX citations
│   ├── prisma/                # PRISMA search, harvest, and screening records
│   └── peer_reviewed_papers.bib # Comprehensive bibliography database
├── paper/                     # LaTeX manuscript source and precompiled PDF
│   ├── sections/              # Manuscript content chapters (01_intro to 08_conclusion)
│   ├── listings/              # C++ benchmark code listings
│   ├── compile_paper.sh       # Automated manuscript compilation script
│   └── main.pdf               # Precompiled publication manuscript
├── results/                   # Derived metrics and statistical summary tables
│   └── metrics/               # Pooled quantiles, ANOVA tables, and uncertainty bounds
├── scripts/                   # Orchestration, probe drivers, and ablation runners
├── src/                       # Benchmark harness, probes, telemetry, and analytical pipelines
│   ├── allocators/            # Dynamic dlopen loader and symbol resolution
│   ├── analysis/              # GPD tail estimation, ANOVA, USL fits, and uncertainty pooling
│   ├── cli/                   # Benchmark harness argument parser
│   ├── plots/                 # Matplotlib generation scripts (Colorblind-safe Okabe-Ito)
│   ├── telemetry/             # Architectural timers, SPSC queues, HDR histograms, counters
│   ├── workloads/             # Micro-topologies (symmetric, R:1, ring) and trace workloads
│   ├── benchmark_harness.cpp  # Main multi-threaded event-level benchmarking engine
│   ├── false_sharing_probe.cpp# Coherence-stride atomic increment probe
│   ├── purge_probe.cpp        # Kernel virtual memory page-release probe
│   ├── table_generator.py     # LaTeX booktabs table generator
│   └── build_artifacts.py     # End-to-end artifact reconstruction script
├── tables/                    # Generated LaTeX publication tables (tab01–tab09, appendices)
├── tests/                     # Automated unit and analytical verification test suite
├── requirements.txt           # Python dependencies
├── LICENSE                    # MIT License
└── README.md                  # Replication documentation
```

---

## Getting Started

### 1. Prerequisites

Ensure you have a C++17 compatible compiler (`clang++` or `g++`) and Python 3.10+ installed.

Install the required Python scientific libraries:
```bash
pip install -r requirements.txt
```

### 2. Building Benchmark Binaries

Compile the core benchmarking engine and micro-architectural probes:
```bash
# Build the primary multi-threaded benchmark harness
clang++ -O3 -std=c++17 -pthread -Wall -Wextra -Isrc \
  src/benchmark_harness.cpp src/allocators/allocator_loader.cpp \
  src/workloads/micro_workloads.cpp src/workloads/trace_workloads.cpp \
  src/workloads/trace_bodies.cpp src/workloads/gated_workers.cpp \
  -o bin/benchmark_harness

# Build the kernel page-release probe
clang++ -O3 -std=c++17 -pthread -Wall -Wextra -Isrc \
  src/purge_probe.cpp -o bin/purge_probe

# Build the false-sharing / coherence-stride probe
clang++ -O3 -std=c++17 -pthread -Wall -Wextra -Isrc \
  src/false_sharing_probe.cpp -o bin/false_sharing_probe
```

---

## Experimental Replication

### Running Micro-Sweeps and Sustained Workloads

The benchmark orchestrator records complete log-linear histograms to avoid coordinated omission and capture true tail quantiles:

```bash
# Stage 1: Run Tier 1 micro-sweeps across all topologies and size classes (50 iterations)
python3 src/allocator_runner.py --stage tier1 --iterations 50

# Stage 2: Run hardware coherence and kernel page-release probes
python3 src/allocator_runner.py --stage probes

# Stage 3: Run Tier 2 sustained trace workloads (Redis, RocksDB, and Web Pipeline models)
python3 src/allocator_runner.py --stage tier2 --repetitions 5

# Or run the complete automated evaluation sequence:
bash scripts/run_study.sh
```

### Running Ablation Studies

To reproduce the source-level `gperftools` batch-cap ablation and thread-cache budget analyses:
```bash
bash scripts/tcmalloc_thread_cache_ablation.sh
```

---

## Artifact Generation & Analysis

To reproduce all derived metric tables (`results/metrics/`), publication figures (`figures/fig01`–`fig13.pdf`), and LaTeX tables (`tables/tab01`–`tab09.tex`) from the raw measurement datasets:

```bash
python3 src/build_artifacts.py
```

### Automated Verification Tests

Run the test suite to verify statistical routines (Box-Cox ANOVA, GPD MLE fits, USL non-linear regressions, histogram pooling):
```bash
pytest tests/
```

### Compiling the Manuscript PDF

To recompile the LaTeX manuscript with figures and tables:
```bash
cd paper
./compile_paper.sh
```
The compiled paper will be output to `paper/main.pdf`.

---

## Authors & Citation

If you use this benchmark suite, empirical data, or methodology in your research, please cite:

```bibtex
@article{patel2026taillatency,
  title={Tail-Latency Amplification Under Cross-Thread Handoff, Coherence Granularity, and Page-Release Footprint in Concurrent Memory Allocators},
  author={Patel, Devarsh and Singh, Adarsh and Deepika, J.},
  journal={School of Computer Science and Engineering, Vellore Institute of Technology},
  year={2026}
}
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
