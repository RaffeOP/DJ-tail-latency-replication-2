#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "allocators/allocator_loader.hpp"
#include "telemetry/hdr_histogram.hpp"
#include "telemetry/process_memory.hpp"

namespace r2 {

// Synthetic workload models. They reproduce the size and lifetime structure
// described in the study design; they are not captured production traces.
enum class TraceWorkload { GrpcPipeline, KvChurn, AstGraph };

struct TraceConfig {
    TraceWorkload workload;
    unsigned threads;
    double duration_seconds;
    uint64_t seed;
};

struct TraceResult {
    uint64_t operations;
    double wall_seconds;
    uint64_t peak_footprint_bytes;
    uint64_t peak_live_bytes;
    HdrHistogram alloc_events;
    HdrHistogram free_events;
    std::vector<FootprintSample> samples;
};

TraceWorkload parse_trace(const std::string& text);
const char* trace_name(TraceWorkload workload);

TraceResult run_trace(const AllocatorApi& api, const TraceConfig& config);

}  // namespace r2
