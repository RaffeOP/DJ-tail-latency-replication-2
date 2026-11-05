#!/usr/bin/env bash
# Runs the allocator study in order. Each stage resumes from its JSON Lines
# file, so an interrupted run continues where it stopped.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
python3 src/allocator_runner.py --stage tier1 --iterations 50
python3 src/allocator_runner.py --stage probes
python3 src/allocator_runner.py --stage tier2 --repetitions 5
echo "$(date -u +%FT%TZ) study driver finished" >> data/logs/driver.log
