"""
src/build_artifacts.py

Rebuilds every analysis artifact from the raw JSON Lines data: metrics CSVs,
the ten figures, and the LaTeX tables. Run after the study completes.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

WORKSPACE = Path(__file__).resolve().parent.parent
METRICS = WORKSPACE / "results" / "metrics"

import tail_latency_profiler  # noqa: E402
from analysis.batch_cap import summarize as summarize_batch_cap  # noqa: E402
from analysis.uncertainty import per_iteration_p999, read_records, summarize  # noqa: E402
import workload_probe_analyzer  # noqa: E402
from plots.extra_figures import generate_extra_figures  # noqa: E402
from plots.probe_figures import generate_probe_figures  # noqa: E402
from plots.style import apply_style  # noqa: E402
from plots.tier1_figures import generate_tier1_figures  # noqa: E402
from table_appendix import generate_appendix_tables  # noqa: E402
from table_extended import generate_extended_tables  # noqa: E402
from table_probe_trace import generate_probe_trace_tables  # noqa: E402
from table_generator import generate_tables  # noqa: E402


def write_uncertainty() -> None:
    records = [r for r in read_records(WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl") if r["threads"] == 8]
    frame = per_iteration_p999(records)
    summarize(frame).to_csv(METRICS / "tier1_p999_uncertainty.csv", index=False)
    frame.to_csv(METRICS / "tier1_p999_per_iteration_t8.csv", index=False)


def main() -> int:
    write_uncertainty()
    summarize_batch_cap()
    tail_latency_profiler.main()
    workload_probe_analyzer.main()
    apply_style()
    generate_tier1_figures()
    generate_probe_figures()
    generate_extra_figures()
    generate_tables()
    generate_appendix_tables()
    generate_probe_trace_tables()
    generate_extended_tables()
    print("artifacts rebuilt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
