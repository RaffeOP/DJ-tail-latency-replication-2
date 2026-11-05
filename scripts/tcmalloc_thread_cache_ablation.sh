#!/usr/bin/env bash
# Ablation: does a larger tcmalloc per-process thread-cache budget change the
# 16 KB and 256 KB 8:1 handoff tails? Ten iterations per cell. The op count
# follows the harness rule: min(2.5M, 4 GiB / size).
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
OUT=data/ablation/tcmalloc_thread_cache_n10.jsonl
CAP_OPS=2500000
BYTE_BUDGET=4294967296
mkdir -p data/ablation
: > "$OUT"
for size in 16384 262144; do
  ops=$(( BYTE_BUDGET / size ))
  if [ "$ops" -gt "$CAP_OPS" ]; then ops=$CAP_OPS; fi
  for mode in default big_cache; do
    if [ "$mode" = big_cache ]; then
      setting="TCMALLOC_MAX_TOTAL_THREAD_CACHE_BYTES=268435456"
    else
      setting="R2_UNUSED=1"
    fi
    for iteration in 0 1 2 3 4 5 6 7 8 9; do
      env "$setting" bin/benchmark_harness micro --alloc tcmalloc --lib-dir "$DIR/lib" \
        --size "$size" --threads 8 --ops "$ops" --ratio 8 --topology asymmetric \
        --iteration "$iteration" | python3 -c "import json,sys; r=json.load(sys.stdin); r['budget']='$mode'; print(json.dumps(r))" >> "$OUT"
    done
  done
done
