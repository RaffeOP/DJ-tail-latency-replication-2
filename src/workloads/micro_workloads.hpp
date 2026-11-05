#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

#include "allocators/allocator_loader.hpp"
#include "telemetry/hdr_histogram.hpp"

namespace r2 {

enum class MicroTopology { Symmetric, Asymmetric, RingPass };

struct MicroConfig {
    size_t alloc_size;
    unsigned threads;
    uint64_t total_ops;
    unsigned ratio;
    MicroTopology topology;
};

struct MicroResult {
    unsigned producers;
    unsigned consumers;
    size_t queue_depth;
    uint64_t operations;
    double wall_seconds;
    HdrHistogram alloc_events;
    HdrHistogram free_events;
};

MicroTopology parse_topology(const std::string& text);
const char* topology_name(MicroTopology topology);

// Returns false when the topology cannot be formed with the thread count,
// for example asymmetric or ring topologies with a single thread.
bool topology_is_feasible(MicroTopology topology, unsigned threads);

MicroResult run_micro_sweep(const AllocatorApi& api, const MicroConfig& config);

}  // namespace r2
