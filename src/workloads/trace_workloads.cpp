#include "workloads/trace_workloads.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>

#include "telemetry/process_memory.hpp"
#include "workloads/gated_workers.hpp"
#include "workloads/trace_bodies.hpp"

namespace r2 {
namespace {

constexpr unsigned SAMPLE_INTERVAL_MS = 100;
constexpr unsigned GRPC_RATIO = 8;
constexpr size_t GRPC_QUEUE_DEPTH = 1024;
constexpr unsigned MIN_GRPC_THREADS = 2;

void append_kv_bodies(TraceShared& shared, const TraceConfig& config, std::vector<std::function<void()>>& bodies) {
    for (unsigned t = 0; t < config.threads; ++t) {
        const uint64_t seed = config.seed + t;
        bodies.push_back([&shared, t, seed] { run_kv_worker(shared, t, seed); });
    }
}

void append_ast_bodies(TraceShared& shared, const TraceConfig& config, std::vector<std::function<void()>>& bodies) {
    for (unsigned t = 0; t < config.threads; ++t) {
        const uint64_t seed = config.seed + t;
        bodies.push_back([&shared, t, seed] { run_ast_worker(shared, t, seed); });
    }
}

void build_grpc_queues(TraceShared& shared, unsigned producers) {
    for (unsigned p = 0; p < producers; ++p) {
        shared.queues.push_back(std::make_unique<SpscQueue>(GRPC_QUEUE_DEPTH));
    }
}

void append_grpc_producers(TraceShared& shared, const TraceConfig& config, unsigned producers,
                           std::vector<std::function<void()>>& bodies) {
    for (unsigned p = 0; p < producers; ++p) {
        const uint64_t seed = config.seed + p;
        bodies.push_back([&shared, p, seed] { run_grpc_producer(shared, p, seed); });
    }
}

void append_grpc_consumers(TraceShared& shared, unsigned producers, std::vector<std::function<void()>>& bodies) {
    const unsigned consumers = consumer_count_for(shared.records.size(), GRPC_RATIO);
    for (unsigned c = 0; c < consumers; ++c) {
        std::vector<SpscQueue*> inputs;
        for (unsigned p = c; p < producers; p += consumers) {
            inputs.push_back(shared.queues[p].get());
        }
        const unsigned index = producers + c;
        bodies.push_back([&shared, inputs, index] { run_grpc_consumer(shared, inputs, index); });
    }
}

void append_grpc_bodies(TraceShared& shared, const TraceConfig& config, std::vector<std::function<void()>>& bodies) {
    if (config.threads < MIN_GRPC_THREADS) {
        throw std::invalid_argument("grpc pipeline requires at least two threads");
    }
    const unsigned consumers = consumer_count_for(config.threads, GRPC_RATIO);
    const unsigned producers = config.threads - consumers;
    shared.producer_count = producers;
    build_grpc_queues(shared, producers);
    append_grpc_producers(shared, config, producers, bodies);
    append_grpc_consumers(shared, producers, bodies);
}

std::vector<std::function<void()>> build_bodies(TraceShared& shared, const TraceConfig& config) {
    std::vector<std::function<void()>> bodies;
    switch (config.workload) {
        case TraceWorkload::GrpcPipeline:
            append_grpc_bodies(shared, config, bodies);
            break;
        case TraceWorkload::KvChurn:
            append_kv_bodies(shared, config, bodies);
            break;
        case TraceWorkload::AstGraph:
            append_ast_bodies(shared, config, bodies);
            break;
    }
    return bodies;
}

uint64_t live_bytes_total(const TraceShared& shared) {
    uint64_t total = 0;
    for (const PaddedCounter& counter : shared.live) {
        total += counter.value.load(std::memory_order_relaxed);
    }
    return total;
}

void record_sample(const TraceShared& shared, double elapsed_seconds, TraceResult& result) {
    const MemoryFootprint footprint = read_memory_footprint();
    const uint64_t live = live_bytes_total(shared);
    result.samples.push_back(FootprintSample{elapsed_seconds, footprint.phys_footprint_bytes, live});
    result.peak_footprint_bytes = std::max(result.peak_footprint_bytes, footprint.peak_phys_footprint_bytes);
    result.peak_footprint_bytes = std::max(result.peak_footprint_bytes, footprint.phys_footprint_bytes);
    result.peak_live_bytes = std::max(result.peak_live_bytes, live);
}

void sample_until_deadline(const TraceShared& shared, const GatedWorkers& workers, double duration_seconds,
                           TraceResult& result) {
    const auto sample_interval = std::chrono::milliseconds(SAMPLE_INTERVAL_MS);
    while (true) {
        std::this_thread::sleep_for(sample_interval);
        const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - workers.start_time()).count();
        record_sample(shared, elapsed, result);
        if (elapsed >= duration_seconds) {
            break;
        }
    }
}

void finalize_result(const TraceShared& shared, const GatedWorkers& workers, TraceResult& result) {
    result.wall_seconds = workers.elapsed_seconds();
    for (const PaddedCounter& counter : shared.operations) {
        result.operations += counter.value.load(std::memory_order_relaxed);
    }
    for (const ThreadRecord& record : shared.records) {
        result.alloc_events.merge_from(record.alloc_events);
        result.free_events.merge_from(record.free_events);
    }
}

}  // namespace

TraceWorkload parse_trace(const std::string& text) {
    if (text == "grpc_pipeline") {
        return TraceWorkload::GrpcPipeline;
    }
    if (text == "kv_churn") {
        return TraceWorkload::KvChurn;
    }
    if (text == "ast_graph") {
        return TraceWorkload::AstGraph;
    }
    throw std::invalid_argument("unknown trace workload: " + text);
}

const char* trace_name(TraceWorkload workload) {
    switch (workload) {
        case TraceWorkload::GrpcPipeline:
            return "grpc_pipeline";
        case TraceWorkload::KvChurn:
            return "kv_churn";
        case TraceWorkload::AstGraph:
            return "ast_graph";
    }
    return "unknown";
}

TraceResult run_trace(const AllocatorApi& api, const TraceConfig& config) {
    TraceShared shared(api, config.threads);
    std::vector<std::function<void()>> bodies = build_bodies(shared, config);
    GatedWorkers workers(bodies);
    workers.start();
    TraceResult result{};
    sample_until_deadline(shared, workers, config.duration_seconds, result);
    shared.stop.store(true, std::memory_order_release);
    workers.join();
    record_sample(shared, workers.elapsed_seconds(), result);
    finalize_result(shared, workers, result);
    return result;
}

}  // namespace r2
