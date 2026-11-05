#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

#include "allocators/allocator_loader.hpp"
#include "telemetry/spsc_queue.hpp"
#include "workloads/worker_support.hpp"

namespace r2 {

struct alignas(CACHE_LINE_BYTES) PaddedCounter {
    std::atomic<uint64_t> value{0};
};

// State shared by all workers of one sustained trace run. Live bytes are
// summed across per-thread counters with wrap-around arithmetic, so a
// cross-thread free decrements the counter of the freeing thread.
struct TraceShared {
    TraceShared(const AllocatorApi& allocator, unsigned worker_count)
        : api(allocator), records(worker_count), live(worker_count), operations(worker_count) {}

    const AllocatorApi& api;
    std::atomic<bool> stop{false};
    std::atomic<unsigned> producers_finished{0};
    unsigned producer_count = 0;
    std::vector<ThreadRecord> records;
    std::vector<PaddedCounter> live;
    std::vector<PaddedCounter> operations;
    std::vector<std::unique_ptr<SpscQueue>> queues;
};

struct KvSlot {
    void* pointer = nullptr;
    size_t size = 0;
};

KvSlot allocate_slot(TraceShared& shared, unsigned index, size_t size);
void release_slot(TraceShared& shared, unsigned index, KvSlot& slot);

void run_kv_worker(TraceShared& shared, unsigned index, uint64_t seed);
void run_ast_worker(TraceShared& shared, unsigned index, uint64_t seed);
void run_grpc_producer(TraceShared& shared, unsigned index, uint64_t seed);
void run_grpc_consumer(TraceShared& shared, const std::vector<SpscQueue*>& inputs, unsigned index);

}  // namespace r2
