#include "workloads/micro_workloads.hpp"

#include <functional>
#include <memory>
#include <stdexcept>
#include <vector>

#include "telemetry/spsc_queue.hpp"
#include "workloads/gated_workers.hpp"
#include "workloads/worker_support.hpp"

namespace r2 {
namespace {

constexpr size_t LIVE_BYTES_BUDGET = 256ULL << 20;
constexpr size_t MIN_QUEUE_DEPTH = 16;
constexpr size_t MAX_QUEUE_DEPTH = 4096;
constexpr unsigned MIN_THREADS_FOR_HANDOFF = 2;

struct SweepPlan {
    unsigned producers = 0;
    unsigned consumers = 0;
    unsigned queue_count = 0;
    uint64_t ops_per_worker = 0;
    uint64_t operations = 0;
    size_t queue_depth = 0;
};

struct SweepContext {
    SweepContext(const AllocatorApi& allocator, const MicroConfig& sweep_config)
        : api(allocator), config(sweep_config), records(sweep_config.threads) {}

    const AllocatorApi& api;
    MicroConfig config;
    SweepPlan plan;
    std::vector<ThreadRecord> records;
    std::vector<std::unique_ptr<SpscQueue>> queues;
    std::vector<std::function<void()>> bodies;
};

size_t round_down_to_power_of_two(size_t value) {
    size_t power = 1;
    while (power * 2 <= value) {
        power *= 2;
    }
    return power;
}

size_t bounded_queue_depth(size_t candidate) {
    if (candidate < MIN_QUEUE_DEPTH) {
        return MIN_QUEUE_DEPTH;
    }
    if (candidate > MAX_QUEUE_DEPTH) {
        return MAX_QUEUE_DEPTH;
    }
    return candidate;
}

// Bounds the number of live objects per sweep so that large size classes do
// not turn the queues into a multi-gigabyte working set.
size_t queue_depth_for(size_t alloc_size, unsigned queue_count) {
    if (queue_count == 0) {
        return MIN_QUEUE_DEPTH;
    }
    const size_t per_queue_objects = (LIVE_BYTES_BUDGET / queue_count) / alloc_size;
    return round_down_to_power_of_two(bounded_queue_depth(per_queue_objects));
}

SweepPlan make_plan(const MicroConfig& config) {
    SweepPlan plan;
    switch (config.topology) {
        case MicroTopology::Symmetric:
            plan.producers = config.threads;
            plan.ops_per_worker = config.total_ops / config.threads;
            plan.operations = plan.ops_per_worker * config.threads;
            break;
        case MicroTopology::Asymmetric:
            plan.consumers = consumer_count_for(config.threads, config.ratio);
            plan.producers = config.threads - plan.consumers;
            plan.queue_count = plan.producers;
            plan.ops_per_worker = config.total_ops / plan.producers;
            plan.operations = plan.ops_per_worker * plan.producers;
            break;
        case MicroTopology::RingPass:
            plan.producers = config.threads;
            plan.consumers = config.threads;
            plan.queue_count = config.threads;
            plan.ops_per_worker = config.total_ops / config.threads;
            plan.operations = plan.ops_per_worker * config.threads;
            break;
    }
    plan.queue_depth = queue_depth_for(config.alloc_size, plan.queue_count);
    return plan;
}

void run_symmetric_worker(const SweepContext& ctx, ThreadRecord& record) {
    for (uint64_t i = 0; i < ctx.plan.ops_per_worker; ++i) {
        void* pointer = timed_allocate(ctx.api, ctx.config.alloc_size, record.alloc_events);
        touch_object(pointer);
        timed_release(ctx.api, pointer, record.free_events);
    }
}

void run_producer(const SweepContext& ctx, SpscQueue& output, ThreadRecord& record) {
    for (uint64_t i = 0; i < ctx.plan.ops_per_worker; ++i) {
        void* pointer = timed_allocate(ctx.api, ctx.config.alloc_size, record.alloc_events);
        touch_object(pointer);
        while (!output.try_push(pointer)) {
            cpu_relax();
        }
    }
}

void run_consumer(const SweepContext& ctx, const std::vector<SpscQueue*>& inputs, uint64_t expected,
                  ThreadRecord& record) {
    uint64_t released = 0;
    while (released < expected) {
        for (SpscQueue* input : inputs) {
            void* pointer = nullptr;
            if (released < expected && input->try_pop(pointer)) {
                timed_release(ctx.api, pointer, record.free_events);
                ++released;
            }
        }
    }
}

// Each ring member allocates into its outgoing queue and frees from its
// incoming queue. A pending object is never dropped: the loop does not end
// until the last allocation has been pushed downstream.
void run_ring_member(const SweepContext& ctx, SpscQueue& outgoing, SpscQueue& incoming, ThreadRecord& record) {
    uint64_t allocated = 0;
    uint64_t released = 0;
    void* pending = nullptr;
    while (allocated < ctx.plan.ops_per_worker || released < ctx.plan.ops_per_worker || pending != nullptr) {
        void* arrived = nullptr;
        if (released < ctx.plan.ops_per_worker && incoming.try_pop(arrived)) {
            timed_release(ctx.api, arrived, record.free_events);
            ++released;
        }
        if (pending == nullptr && allocated < ctx.plan.ops_per_worker) {
            pending = timed_allocate(ctx.api, ctx.config.alloc_size, record.alloc_events);
            touch_object(pending);
            ++allocated;
        }
        if (pending != nullptr && outgoing.try_push(pending)) {
            pending = nullptr;
        }
    }
}

void append_symmetric_bodies(SweepContext& ctx) {
    for (unsigned t = 0; t < ctx.config.threads; ++t) {
        ThreadRecord* record = &ctx.records[t];
        ctx.bodies.push_back([&ctx, record] { run_symmetric_worker(ctx, *record); });
    }
}

void append_asymmetric_bodies(SweepContext& ctx) {
    for (unsigned p = 0; p < ctx.plan.producers; ++p) {
        SpscQueue* output = ctx.queues[p].get();
        ThreadRecord* record = &ctx.records[p];
        ctx.bodies.push_back([&ctx, output, record] { run_producer(ctx, *output, *record); });
    }
    for (unsigned c = 0; c < ctx.plan.consumers; ++c) {
        std::vector<SpscQueue*> inputs;
        for (unsigned p = c; p < ctx.plan.producers; p += ctx.plan.consumers) {
            inputs.push_back(ctx.queues[p].get());
        }
        const uint64_t expected = static_cast<uint64_t>(inputs.size()) * ctx.plan.ops_per_worker;
        ThreadRecord* record = &ctx.records[ctx.plan.producers + c];
        ctx.bodies.push_back([&ctx, inputs, expected, record] { run_consumer(ctx, inputs, expected, *record); });
    }
}

void append_ring_bodies(SweepContext& ctx) {
    for (unsigned t = 0; t < ctx.config.threads; ++t) {
        SpscQueue* outgoing = ctx.queues[t].get();
        SpscQueue* incoming = ctx.queues[(t + ctx.config.threads - 1) % ctx.config.threads].get();
        ThreadRecord* record = &ctx.records[t];
        ctx.bodies.push_back([&ctx, outgoing, incoming, record] { run_ring_member(ctx, *outgoing, *incoming, *record); });
    }
}

void build_queues(SweepContext& ctx) {
    for (unsigned q = 0; q < ctx.plan.queue_count; ++q) {
        ctx.queues.push_back(std::make_unique<SpscQueue>(ctx.plan.queue_depth));
    }
}

void build_bodies(SweepContext& ctx) {
    switch (ctx.config.topology) {
        case MicroTopology::Symmetric:
            append_symmetric_bodies(ctx);
            break;
        case MicroTopology::Asymmetric:
            append_asymmetric_bodies(ctx);
            break;
        case MicroTopology::RingPass:
            append_ring_bodies(ctx);
            break;
    }
}

MicroResult collect_result(const SweepContext& ctx, double wall_seconds) {
    MicroResult result{};
    result.producers = ctx.plan.producers;
    result.consumers = ctx.plan.consumers;
    result.queue_depth = ctx.plan.queue_depth;
    result.operations = ctx.plan.operations;
    result.wall_seconds = wall_seconds;
    for (const ThreadRecord& record : ctx.records) {
        result.alloc_events.merge_from(record.alloc_events);
        result.free_events.merge_from(record.free_events);
    }
    return result;
}

}  // namespace

MicroTopology parse_topology(const std::string& text) {
    if (text == "symmetric") {
        return MicroTopology::Symmetric;
    }
    if (text == "asymmetric") {
        return MicroTopology::Asymmetric;
    }
    if (text == "ring") {
        return MicroTopology::RingPass;
    }
    throw std::invalid_argument("unknown topology: " + text);
}

const char* topology_name(MicroTopology topology) {
    switch (topology) {
        case MicroTopology::Symmetric:
            return "symmetric";
        case MicroTopology::Asymmetric:
            return "asymmetric";
        case MicroTopology::RingPass:
            return "ring";
    }
    return "unknown";
}

bool topology_is_feasible(MicroTopology topology, unsigned threads) {
    if (topology == MicroTopology::Symmetric) {
        return threads >= 1;
    }
    return threads >= MIN_THREADS_FOR_HANDOFF;
}

MicroResult run_micro_sweep(const AllocatorApi& api, const MicroConfig& config) {
    if (!topology_is_feasible(config.topology, config.threads)) {
        throw std::invalid_argument("topology infeasible for thread count");
    }
    SweepContext ctx(api, config);
    ctx.plan = make_plan(config);
    if (ctx.plan.ops_per_worker == 0) {
        throw std::invalid_argument("total_ops smaller than worker count");
    }
    build_queues(ctx);
    build_bodies(ctx);
    GatedWorkers workers(ctx.bodies);
    workers.start();
    workers.join();
    return collect_result(ctx, workers.elapsed_seconds());
}

}  // namespace r2
