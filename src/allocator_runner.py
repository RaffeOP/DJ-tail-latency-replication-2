"""
src/allocator_runner.py

Orchestrates the allocator study: Tier 1 micro-sweeps, Tier 2 sustained trace
runs, and the page-release and coherence probes. Every configuration runs in a
fresh process, one at a time, so timing runs never overlap. Results append to
JSON Lines files; a rerun skips configurations already recorded.

Principal Investigator: Devarsh Patel (24BCT0267), VIT Vellore.
"""

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
HARNESS = WORKSPACE / "bin" / "benchmark_harness"
PURGE_PROBE = WORKSPACE / "bin" / "purge_probe"
FALSE_SHARING_PROBE = WORKSPACE / "bin" / "false_sharing_probe"
LIB_DIR = WORKSPACE / "lib"
TIER1_OUTPUT = WORKSPACE / "data" / "tier1" / "micro_sweeps.jsonl"
TIER2_OUTPUT = WORKSPACE / "data" / "tier2" / "trace_runs.jsonl"
PROBE_OUTPUT = WORKSPACE / "data" / "tier2" / "probe_runs.jsonl"
LOG_DIR = WORKSPACE / "data" / "logs"

ALLOCATORS = ["mimalloc", "jemalloc", "tcmalloc", "snmalloc", "libmalloc"]
SIZE_CLASSES = [16, 64, 256, 1024, 4096, 16384, 65536, 262144]
THREAD_SCALES = [1, 2, 4, 8, 16, 32]
TOPOLOGIES = ["symmetric", "asymmetric_4_1", "asymmetric_8_1", "ring"]
TOTAL_OPS_PER_SWEEP = 2500000
BYTE_BUDGET_PER_SWEEP = 4 * 1024**3
DEFAULT_ITERATIONS = 5

TRACE_WORKLOADS = ["grpc_pipeline", "kv_churn", "ast_graph"]
TRACE_THREADS = 8
TRACE_DURATION_SECONDS = 20
TRACE_REPETITIONS = 5

PURGE_POLICIES = ["none", "dontneed", "free", "free_reusable"]
PURGE_INTERVALS_MS = [50, 200, 1000]
PURGE_REGION_MB = 512
PURGE_CHUNK_KB = 1024
PURGE_WORKERS = 4
PURGE_DURATION_SECONDS = 6
PURGE_REPETITIONS = 5

FALSE_SHARING_STRIDES = [8, 16, 32, 48, 64, 96, 128, 256]
FALSE_SHARING_THREADS = [2, 4]
FALSE_SHARING_REPS = 20

PROGRESS_EVERY = 25
RUN_TIMEOUT_SECONDS = 120
# 07:30 IST on Friday 2026-10-23. Every loop stops here and resumes on a rerun.


def is_feasible(topology: str, threads: int) -> bool:
    """Asymmetric and ring topologies need at least two threads."""
    return topology == "symmetric" or threads >= 2


def ops_for_size(alloc_size: int) -> int:
    """Caps the bytes churned per sweep so large size classes stay tractable."""
    return min(TOTAL_OPS_PER_SWEEP, BYTE_BUDGET_PER_SWEEP // alloc_size)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_completed(path: Path) -> set:
    if not path.exists():
        return set()
    completed = set()
    with path.open() as handle:
        for line in handle:
            record = json.loads(line)
            completed.add(record["key"])
    return completed


def execute(command: list) -> dict:
    """Runs one command; returns the parsed result or a failure description."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=WORKSPACE,
                                timeout=RUN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {"error": {"returncode": None, "stderr": f"timeout after {RUN_TIMEOUT_SECONDS}s"}}
    if result.returncode != 0:
        return {"error": {"returncode": result.returncode, "stderr": result.stderr.strip()[-2000:]}}
    return {"result": json.loads(result.stdout.strip().splitlines()[-1])}


def run_command(command: list, key: str, meta: dict, output: Path) -> dict:
    """Runs one configuration and appends the parsed JSON or the failure."""
    record = dict(meta, key=key, recorded_at=utc_now(), **execute(command))
    with output.open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def log_line(log: Path, message: str) -> None:
    with log.open("a") as handle:
        handle.write(f"{utc_now()} {message}\n")


def micro_plan(iterations: int) -> list:
    """Every feasible (allocator, size, threads, topology, iteration) tuple."""
    plan = []
    for iteration in range(iterations):
        configs = []
        for alloc in ALLOCATORS:
            for size in SIZE_CLASSES:
                for threads in THREAD_SCALES:
                    for topology in TOPOLOGIES:
                        if is_feasible(topology, threads):
                            configs.append((alloc, size, threads, topology))
        random.Random(iteration).shuffle(configs)
        plan.extend((iteration, *config) for config in configs)
    return plan


def run_micro(iterations: int, limit: int | None) -> None:
    TIER1_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / "tier1.log"
    completed = load_completed(TIER1_OUTPUT)
    plan = micro_plan(iterations)
    if limit is not None:
        plan = plan[:limit]
    done_now = 0
    for iteration, alloc, size, threads, topology in plan:
        ratio = 4 if topology == "asymmetric_4_1" else 8 if topology == "asymmetric_8_1" else 4
        key = f"tier1|{alloc}|{size}|{threads}|{topology}|{iteration}"
        if key in completed:
            continue
        command = [
            str(HARNESS), "micro", "--alloc", alloc, "--lib-dir", str(LIB_DIR), "--size", str(size),
            "--threads", str(threads), "--ops", str(ops_for_size(size)), "--ratio", str(ratio),
            "--topology", topology.split("_")[0], "--iteration", str(iteration),
        ]
        meta = {"stage": "tier1", "allocator": alloc, "size": size, "threads": threads, "topology": topology,
                "iteration": iteration}
        run_command(command, key, meta, TIER1_OUTPUT)
        done_now += 1
        if done_now % PROGRESS_EVERY == 0:
            log_line(log, f"tier1 completed {done_now} new sweeps (iteration {iteration})")
    log_line(log, f"tier1 finished pass, {done_now} new sweeps this invocation")


def run_trace(repetitions: int) -> None:
    TIER2_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / "tier2.log"
    completed = load_completed(TIER2_OUTPUT)
    for repetition in range(repetitions):
        configs = [(workload, alloc) for workload in TRACE_WORKLOADS for alloc in ALLOCATORS]
        random.Random(1000 + repetition).shuffle(configs)
        for workload, alloc in configs:
            key = f"tier2|{workload}|{alloc}|{repetition}"
            if key in completed:
                continue
            command = [
                str(HARNESS), "trace", "--alloc", alloc, "--lib-dir", str(LIB_DIR), "--workload", workload,
                "--threads", str(TRACE_THREADS), "--duration", str(TRACE_DURATION_SECONDS),
                "--seed", str(repetition),
            ]
            meta = {"stage": "tier2", "workload": workload, "allocator": alloc, "repetition": repetition}
            run_command(command, key, meta, TIER2_OUTPUT)
            log_line(log, f"tier2 done {key}")


def run_probes() -> None:
    PROBE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / "probes.log"
    completed = load_completed(PROBE_OUTPUT)
    for repetition in range(PURGE_REPETITIONS):
        for interval in PURGE_INTERVALS_MS:
            for policy in PURGE_POLICIES:
                key = f"purge|{policy}|{interval}|{repetition}"
                if key in completed:
                    continue
                command = [
                    str(PURGE_PROBE), "run", "--policy", policy, "--region-mb", str(PURGE_REGION_MB),
                    "--chunk-kb", str(PURGE_CHUNK_KB), "--interval-ms", str(interval),
                    "--workers", str(PURGE_WORKERS), "--duration", str(PURGE_DURATION_SECONDS),
                ]
                meta = {"stage": "purge", "policy": policy, "interval_ms": interval, "repetition": repetition}
                run_command(command, key, meta, PROBE_OUTPUT)
                log_line(log, f"purge done {key}")
    for threads in FALSE_SHARING_THREADS:
        for stride in FALSE_SHARING_STRIDES:
            key = f"false_sharing|{stride}|{threads}"
            if key in completed:
                continue
            command = [
                str(FALSE_SHARING_PROBE), "run", "--stride", str(stride), "--threads", str(threads),
                "--increments", "20000000", "--reps", str(FALSE_SHARING_REPS),
            ]
            meta = {"stage": "false_sharing", "stride_bytes": stride, "threads": threads}
            run_command(command, key, meta, PROBE_OUTPUT)
            log_line(log, f"false sharing done {key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=["tier1", "tier2", "probes"], required=True)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--repetitions", type=int, default=TRACE_REPETITIONS)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N planned sweeps")
    parser.add_argument("--dry-run", action="store_true", help="print the plan size and exit")
    args = parser.parse_args()

    if args.dry_run:
        plan = micro_plan(args.iterations)
        print(f"tier1 planned sweeps: {len(plan)} (configs per iteration: {len(plan) // max(args.iterations, 1)})")
        return 0
    if args.stage == "tier1":
        run_micro(args.iterations, args.limit)
    elif args.stage == "tier2":
        run_trace(args.repetitions)
    else:
        run_probes()
    return 0


if __name__ == "__main__":
    sys.exit(main())
