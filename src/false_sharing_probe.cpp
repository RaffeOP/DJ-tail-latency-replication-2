// src/false_sharing_probe.cpp
// Coherence-granularity probe. Each thread performs atomic increments on its
// own counter; counters are separated by a configurable stride. Strides below
// the coherence granule force cross-core line transfers, so the per-increment
// cost rises. On heterogeneous 64-bit ARM hardware the granule is 128 bytes; the 64-byte stride
// case therefore reproduces a 64-byte-padding layout on hardware that
// invalidates at 128-byte granularity.
//
//   false_sharing_probe run --stride BYTES --threads T --increments N --reps R

#include <atomic>
#include <memory>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <thread>
#include <vector>

#include "cli/arg_map.hpp"
#include "telemetry/hdr_histogram.hpp"
#include "telemetry/json_output.hpp"
#include "telemetry/process_counters.hpp"
#include "workloads/worker_support.hpp"

namespace r2 {
namespace {

constexpr size_t MAX_THREADS = 16;
constexpr size_t BUFFER_ALIGNMENT = 4096;
constexpr size_t BUFFER_BYTES = MAX_THREADS * 4096;
constexpr unsigned DEFAULT_THREADS = 2;
constexpr uint64_t DEFAULT_INCREMENTS = 20000000;
constexpr unsigned DEFAULT_REPS = 10;
constexpr unsigned DEFAULT_STRIDE = 128;

struct alignas(BUFFER_ALIGNMENT) CounterArena {
    unsigned char bytes[BUFFER_BYTES];
};

struct RunSpec {
    size_t stride;
    unsigned threads;
    uint64_t increments;
};

void run_incrementer(std::atomic<uint64_t>* counter, uint64_t increments, double* seconds_out) {
    const auto start = std::chrono::steady_clock::now();
    for (uint64_t i = 0; i < increments; ++i) {
        counter->fetch_add(1, std::memory_order_relaxed);
    }
    const auto end = std::chrono::steady_clock::now();
    *seconds_out = std::chrono::duration<double>(end - start).count();
}

struct RunOutcome {
    double seconds;
    uint64_t cycles;
    uint64_t instructions;
};

// Returns the slowest thread's time: the run completes when the last thread does.
RunOutcome run_once(const RunSpec& spec, CounterArena& arena) {
    std::vector<double> seconds(spec.threads, 0.0);
    const ProcessCounters counters_before = read_process_counters();
    std::vector<std::thread> workers;
    for (unsigned t = 0; t < spec.threads; ++t) {
        auto* counter = reinterpret_cast<std::atomic<uint64_t>*>(arena.bytes + t * spec.stride);
        counter->store(0);
        workers.emplace_back(run_incrementer, counter, spec.increments, &seconds[t]);
    }
    for (auto& worker : workers) {
        worker.join();
    }
    const ProcessCounters counters_after = read_process_counters();
    double slowest = 0.0;
    for (double value : seconds) {
        if (value > slowest) {
            slowest = value;
        }
    }
    return RunOutcome{slowest, counters_after.cycles - counters_before.cycles,
                      counters_after.instructions - counters_before.instructions};
}

}  // namespace
}  // namespace r2

int main(int argc, char** argv) {
    try {
        const r2::ArgMap args(argc, argv);
        const r2::RunSpec spec{static_cast<size_t>(args.number_or("stride", r2::DEFAULT_STRIDE)),
                               static_cast<unsigned>(args.number_or("threads", r2::DEFAULT_THREADS)),
                               args.number_or("increments", r2::DEFAULT_INCREMENTS)};
        const unsigned reps = static_cast<unsigned>(args.number_or("reps", r2::DEFAULT_REPS));
        if (spec.threads > r2::MAX_THREADS || spec.stride * spec.threads > r2::BUFFER_BYTES) {
            throw std::invalid_argument("stride and thread count exceed the counter arena");
        }
        auto arena = std::make_unique<r2::CounterArena>();
        const double total_increments = static_cast<double>(spec.increments) * spec.threads;
        std::printf("{\"schema\":\"r2.false_sharing.v2\",\"stride_bytes\":%zu,\"threads\":%u,\"increments\":%llu,"
                    "\"reps\":%u,\"ns_per_increment\":[",
                    spec.stride, spec.threads, static_cast<unsigned long long>(spec.increments), reps);
        std::vector<r2::RunOutcome> outcomes;
        for (unsigned rep = 0; rep < reps; ++rep) {
            const r2::RunOutcome outcome = r2::run_once(spec, *arena);
            outcomes.push_back(outcome);
            std::printf("%s%.4f", rep == 0 ? "" : ",", outcome.seconds * 1e9 / static_cast<double>(spec.increments));
        }
        std::printf("],\"cycles_per_increment\":[");
        for (size_t rep = 0; rep < outcomes.size(); ++rep) {
            std::printf("%s%.4f", rep == 0 ? "" : ",", static_cast<double>(outcomes[rep].cycles) / total_increments);
        }
        std::printf("],\"instructions_per_increment\":[");
        for (size_t rep = 0; rep < outcomes.size(); ++rep) {
            std::printf("%s%.4f", rep == 0 ? "" : ",",
                        static_cast<double>(outcomes[rep].instructions) / total_increments);
        }
        std::printf("]}\n");
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "false_sharing_probe: %s\n", error.what());
        return EXIT_FAILURE;
    }
}
