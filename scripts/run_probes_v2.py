"""
Re-runs the coherence-stride and page-release probes with process-level cycle,
instruction, and fault counters enabled. Writes data/tier2/probes_v2.jsonl.
"""

import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
OUTPUT = WORKSPACE / "data" / "tier2" / "probes_v2.jsonl"
PURGE_PROBE = WORKSPACE / "bin" / "purge_probe"
FALSE_SHARING_PROBE = WORKSPACE / "bin" / "false_sharing_probe"
PURGE_POLICIES = ["none", "dontneed", "free", "free_reusable"]
PURGE_INTERVALS_MS = [50, 200, 1000]
PURGE_REPETITIONS = 5
STRIDES = [8, 16, 32, 48, 64, 96, 128, 256]
THREADS = [2, 4]
FALSE_SHARING_REPS = 20
INCREMENTS = 20000000


def run(command: list, meta: dict, output) -> None:
    result = subprocess.run(command, capture_output=True, text=True, cwd=WORKSPACE, timeout=600)
    if result.returncode != 0:
        output.write(json.dumps(dict(meta, error=result.stderr[-1000:])) + "\n")
        return
    output.write(json.dumps(dict(meta, result=json.loads(result.stdout.strip().splitlines()[-1]))) + "\n")
    output.flush()


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w") as output:
        for threads in THREADS:
            for stride in STRIDES:
                command = [str(FALSE_SHARING_PROBE), "run", "--stride", str(stride), "--threads", str(threads),
                           "--increments", str(INCREMENTS), "--reps", str(FALSE_SHARING_REPS)]
                run(command, {"stage": "false_sharing", "stride_bytes": stride, "threads": threads}, output)
        for repetition in range(PURGE_REPETITIONS):
            for interval in PURGE_INTERVALS_MS:
                for policy in PURGE_POLICIES:
                    command = [str(PURGE_PROBE), "run", "--policy", policy, "--region-mb", "512",
                               "--chunk-kb", "1024", "--interval-ms", str(interval), "--workers", "4",
                               "--duration", "6"]
                    run(command, {"stage": "purge", "policy": policy, "interval_ms": interval,
                                  "repetition": repetition}, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
