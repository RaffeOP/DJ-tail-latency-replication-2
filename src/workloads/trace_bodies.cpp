#include "workloads/trace_bodies.hpp"

#include <algorithm>
#include <cmath>
#include <random>

namespace r2 {
namespace {

constexpr size_t KV_MIN_BYTES = 16;
constexpr size_t KV_MAX_BYTES = 4096;
constexpr double KV_PARETO_ALPHA = 1.1;
constexpr size_t KV_SHORT_SLOTS = 512;
constexpr size_t KV_LONG_SLOTS = 4096;
constexpr double KV_LONG_PROBABILITY = 0.05;

constexpr size_t GRPC_MIN_BYTES = 64;
constexpr size_t GRPC_MAX_BYTES = 4096;

constexpr size_t AST_NODES_PER_GRAPH = 20000;
constexpr size_t AST_SIZE_CLASS_COUNT = 8;
constexpr size_t AST_SIZE_CLASSES[AST_SIZE_CLASS_COUNT] = {48, 64, 96, 128, 192, 256, 384, 512};

size_t bounded_pareto_size(double unit) {
    const double ratio = static_cast<double>(KV_MIN_BYTES) / static_cast<double>(KV_MAX_BYTES);
    const double tail = 1.0 - unit * (1.0 - std::pow(ratio, KV_PARETO_ALPHA));
    return static_cast<size_t>(static_cast<double>(KV_MIN_BYTES) / std::pow(tail, 1.0 / KV_PARETO_ALPHA));
}

size_t log_uniform_size(double unit, size_t low, size_t high) {
    const double log_low = std::log(static_cast<double>(low));
    const double log_high = std::log(static_cast<double>(high));
    return static_cast<size_t>(std::exp(log_low + unit * (log_high - log_low)));
}

void release_object(TraceShared& shared, unsigned index, void* pointer, size_t size) {
    timed_release(shared.api, pointer, shared.records[index].free_events);
    shared.live[index].value.fetch_sub(size, std::memory_order_relaxed);
}

bool drain_once(TraceShared& shared, unsigned index, const std::vector<SpscQueue*>& inputs) {
    bool drained = false;
    for (SpscQueue* input : inputs) {
        void* pointer = nullptr;
        if (input->try_pop(pointer)) {
            const size_t size = *static_cast<size_t*>(pointer);
            release_object(shared, index, pointer, size);
            drained = true;
        }
    }
    return drained;
}

void hand_off(TraceShared& shared, unsigned index, SpscQueue& output, KvSlot slot) {
    while (!output.try_push(slot.pointer)) {
        if (shared.stop.load(std::memory_order_relaxed)) {
            release_slot(shared, index, slot);
            return;
        }
        cpu_relax();
    }
}

void build_ast_graph(TraceShared& shared, unsigned index, std::mt19937_64& generator, std::vector<KvSlot>& nodes) {
    void* parent = nullptr;
    for (size_t i = 0; i < AST_NODES_PER_GRAPH; ++i) {
        const size_t size = AST_SIZE_CLASSES[generator() % AST_SIZE_CLASS_COUNT];
        nodes.push_back(allocate_slot(shared, index, size));
        *static_cast<void**>(nodes.back().pointer) = parent;
        parent = nodes.back().pointer;
    }
}

}  // namespace

KvSlot allocate_slot(TraceShared& shared, unsigned index, size_t size) {
    void* pointer = timed_allocate(shared.api, size, shared.records[index].alloc_events);
    touch_object(pointer);
    shared.live[index].value.fetch_add(size, std::memory_order_relaxed);
    shared.operations[index].value.fetch_add(1, std::memory_order_relaxed);
    return KvSlot{pointer, size};
}

void release_slot(TraceShared& shared, unsigned index, KvSlot& slot) {
    if (slot.pointer == nullptr) {
        return;
    }
    release_object(shared, index, slot.pointer, slot.size);
    slot = KvSlot{};
}

void run_kv_worker(TraceShared& shared, unsigned index, uint64_t seed) {
    std::mt19937_64 generator(seed);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::vector<KvSlot> short_slots(KV_SHORT_SLOTS);
    std::vector<KvSlot> long_slots(KV_LONG_SLOTS);
    uint64_t step = 0;
    while (!shared.stop.load(std::memory_order_relaxed)) {
        const size_t size = bounded_pareto_size(unit(generator));
        if (unit(generator) < KV_LONG_PROBABILITY) {
            KvSlot& slot = long_slots[generator() % KV_LONG_SLOTS];
            release_slot(shared, index, slot);
            slot = allocate_slot(shared, index, size);
        } else {
            KvSlot& slot = short_slots[step % KV_SHORT_SLOTS];
            release_slot(shared, index, slot);
            slot = allocate_slot(shared, index, size);
        }
        ++step;
    }
    for (KvSlot& slot : short_slots) {
        release_slot(shared, index, slot);
    }
    for (KvSlot& slot : long_slots) {
        release_slot(shared, index, slot);
    }
}

void run_ast_worker(TraceShared& shared, unsigned index, uint64_t seed) {
    std::mt19937_64 generator(seed);
    std::vector<KvSlot> nodes;
    nodes.reserve(AST_NODES_PER_GRAPH);
    while (!shared.stop.load(std::memory_order_relaxed)) {
        build_ast_graph(shared, index, generator, nodes);
        std::shuffle(nodes.begin(), nodes.end(), generator);
        for (KvSlot& node : nodes) {
            release_slot(shared, index, node);
        }
        nodes.clear();
    }
}

void run_grpc_producer(TraceShared& shared, unsigned index, uint64_t seed) {
    std::mt19937_64 generator(seed);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    SpscQueue& output = *shared.queues[index];
    while (!shared.stop.load(std::memory_order_relaxed)) {
        const size_t size = log_uniform_size(unit(generator), GRPC_MIN_BYTES, GRPC_MAX_BYTES);
        KvSlot slot = allocate_slot(shared, index, size);
        *static_cast<size_t*>(slot.pointer) = size;
        hand_off(shared, index, output, slot);
    }
    shared.producers_finished.fetch_add(1, std::memory_order_release);
}

void run_grpc_consumer(TraceShared& shared, const std::vector<SpscQueue*>& inputs, unsigned index) {
    while (true) {
        const bool all_producers_done =
            shared.producers_finished.load(std::memory_order_acquire) == shared.producer_count;
        const bool drained = drain_once(shared, index, inputs);
        if (!drained && all_producers_done) {
            break;
        }
        if (!drained) {
            cpu_relax();
        }
    }
}

}  // namespace r2
