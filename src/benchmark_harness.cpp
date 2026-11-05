// src/benchmark_harness.cpp
// Command-line driver for the allocator study. Each invocation runs one
// configuration in a fresh process and writes a single JSON object to stdout.
//
//   benchmark_harness micro --alloc NAME --lib-dir DIR --size BYTES --threads T
//       --ops TOTAL --topology symmetric|asymmetric|ring [--ratio R] [--iteration I]
//   benchmark_harness trace --alloc NAME --lib-dir DIR --workload grpc_pipeline|kv_churn|ast_graph
//       --threads T --duration SECONDS [--seed S]
//
// Build: clang++ -O3 -std=c++17 -pthread -Isrc src/benchmark_harness.cpp -o bin/benchmark_harness

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "allocators/allocator_loader.hpp"
#include "cli/arg_map.hpp"
#include "telemetry/cycle_timer.hpp"
#include "telemetry/json_output.hpp"
#include "telemetry/process_memory.hpp"
#include "workloads/micro_workloads.hpp"
#include "workloads/trace_workloads.hpp"

namespace r2 {
namespace {

constexpr int USAGE_EXIT_CODE = 2;
constexpr size_t TIMER_PROBE_COUNT = 1000000;
constexpr unsigned DEFAULT_RATIO = 4;
constexpr unsigned DEFAULT_ITERATION = 0;
constexpr uint64_t DEFAULT_SEED = 20261022;
constexpr size_t DEFAULT_ALLOC_SIZE = 64;
constexpr unsigned DEFAULT_THREADS = 1;
constexpr uint64_t DEFAULT_TOTAL_OPS = 2500000;
constexpr double DEFAULT_DURATION_SECONDS = 20.0;

// Mean cost of one counter read. Individual back-to-back reads often return
// the same tick, so the cost is averaged over a long chain of reads.
uint64_t measure_timer_overhead_ns() {
    volatile uint64_t sink = 0;
    const uint64_t start = read_counter();
    for (size_t i = 0; i < TIMER_PROBE_COUNT; ++i) {
        sink = read_counter();
    }
    const uint64_t end = read_counter();
    static_cast<void>(sink);
    return ticks_to_nanoseconds(end - start) / TIMER_PROBE_COUNT;
}

std::string common_header(const AllocatorApi& api, uint64_t timer_overhead_ns) {
    std::ostringstream out;
    out << "\"allocator\":" << json_string(api.name) << ",\"allocator_image\":" << json_string(api.image_path)
        << ",\"counter_hz\":" << COUNTER_HZ << ",\"timer_overhead_ns\":" << timer_overhead_ns;
    return out.str();
}

std::string footprint_json() {
    const MemoryFootprint footprint = read_memory_footprint();
    std::ostringstream out;
    out << "{\"phys_footprint_bytes\":" << footprint.phys_footprint_bytes
        << ",\"peak_phys_footprint_bytes\":" << footprint.peak_phys_footprint_bytes << "}";
    return out.str();
}

std::string effective_ratio_json(const MicroResult& result) {
    if (result.consumers == 0) {
        return "null";
    }
    std::ostringstream out;
    out << static_cast<double>(result.producers) / static_cast<double>(result.consumers);
    return out.str();
}

std::string micro_json(const AllocatorApi& api, const MicroConfig& config, const MicroResult& result,
                       unsigned iteration, uint64_t timer_overhead_ns) {
    std::ostringstream out;
    out << "{\"schema\":\"r2.micro.v1\"," << common_header(api, timer_overhead_ns)
        << ",\"topology\":" << json_string(topology_name(config.topology))
        << ",\"alloc_size_bytes\":" << config.alloc_size << ",\"threads\":" << config.threads
        << ",\"producers\":" << result.producers << ",\"consumers\":" << result.consumers
        << ",\"effective_ratio\":" << effective_ratio_json(result) << ",\"queue_depth\":" << result.queue_depth
        << ",\"iteration\":" << iteration << ",\"operations\":" << result.operations
        << ",\"wall_seconds\":" << result.wall_seconds
        << ",\"throughput_ops_per_sec\":" << static_cast<double>(result.operations) / result.wall_seconds
        << ",\"alloc_latency_ns\":" << histogram_json(result.alloc_events)
        << ",\"free_latency_ns\":" << histogram_json(result.free_events) << ",\"footprint\":" << footprint_json()
        << ",\"alloc_counts\":" << histogram_counts_json(result.alloc_events)
        << ",\"free_counts\":" << histogram_counts_json(result.free_events) << "}";
    return out.str();
}

int run_micro_command(const ArgMap& args, const AllocatorApi& api) {
    MicroConfig config{};
    config.alloc_size = args.number_or("size", DEFAULT_ALLOC_SIZE);
    config.threads = static_cast<unsigned>(args.number_or("threads", DEFAULT_THREADS));
    config.total_ops = args.number_or("ops", DEFAULT_TOTAL_OPS);
    config.ratio = static_cast<unsigned>(args.number_or("ratio", DEFAULT_RATIO));
    config.topology = parse_topology(args.require("topology"));
    const unsigned iteration = static_cast<unsigned>(args.number_or("iteration", DEFAULT_ITERATION));
    const uint64_t timer_overhead_ns = measure_timer_overhead_ns();
    const MicroResult result = run_micro_sweep(api, config);
    std::cout << micro_json(api, config, result, iteration, timer_overhead_ns) << std::endl;
    return EXIT_SUCCESS;
}

std::string samples_json(const std::vector<FootprintSample>& samples) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < samples.size(); ++i) {
        if (i > 0) {
            out << ",";
        }
        out << "{\"t\":" << samples[i].elapsed_seconds << ",\"footprint\":" << samples[i].phys_footprint_bytes
            << ",\"live\":" << samples[i].live_bytes << "}";
    }
    out << "]";
    return out.str();
}

std::string trace_json(const AllocatorApi& api, const TraceConfig& config, const TraceResult& result,
                       uint64_t timer_overhead_ns) {
    std::ostringstream out;
    out << "{\"schema\":\"r2.trace.v1\"," << common_header(api, timer_overhead_ns)
        << ",\"workload\":" << json_string(trace_name(config.workload)) << ",\"threads\":" << config.threads
        << ",\"seed\":" << config.seed << ",\"operations\":" << result.operations
        << ",\"wall_seconds\":" << result.wall_seconds
        << ",\"throughput_ops_per_sec\":" << static_cast<double>(result.operations) / result.wall_seconds
        << ",\"peak_footprint_bytes\":" << result.peak_footprint_bytes
        << ",\"peak_live_bytes\":" << result.peak_live_bytes
        << ",\"alloc_latency_ns\":" << histogram_json(result.alloc_events)
        << ",\"free_latency_ns\":" << histogram_json(result.free_events)
        << ",\"alloc_counts\":" << histogram_counts_json(result.alloc_events)
        << ",\"free_counts\":" << histogram_counts_json(result.free_events)
        << ",\"samples\":" << samples_json(result.samples) << "}";
    return out.str();
}

int run_trace_command(const ArgMap& args, const AllocatorApi& api) {
    TraceConfig config{};
    config.workload = parse_trace(args.require("workload"));
    config.threads = static_cast<unsigned>(args.number_or("threads", DEFAULT_THREADS));
    config.duration_seconds = args.real_or("duration", DEFAULT_DURATION_SECONDS);
    config.seed = args.number_or("seed", DEFAULT_SEED);
    const uint64_t timer_overhead_ns = measure_timer_overhead_ns();
    const TraceResult result = run_trace(api, config);
    std::cout << trace_json(api, config, result, timer_overhead_ns) << std::endl;
    return EXIT_SUCCESS;
}

}  // namespace
}  // namespace r2

int main(int argc, char** argv) {
    try {
        const r2::ArgMap args(argc, argv);
        const r2::AllocatorApi api = r2::load_allocator(args.require("alloc"), args.value_or("lib-dir", "lib"));
        if (args.command() == "micro") {
            return r2::run_micro_command(args, api);
        }
        if (args.command() == "trace") {
            return r2::run_trace_command(args, api);
        }
        throw std::invalid_argument("unknown subcommand: " + args.command());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "benchmark_harness: %s\n", error.what());
        return r2::USAGE_EXIT_CODE;
    }
}
