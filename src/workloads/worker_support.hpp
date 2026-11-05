#pragma once

#include <pthread/qos.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <thread>

#include "allocators/allocator_loader.hpp"
#include "telemetry/cycle_timer.hpp"
#include "telemetry/hdr_histogram.hpp"

namespace r2 {

constexpr int ALLOCATION_FAILURE_EXIT_CODE = 3;

#if defined(__aarch64__)
inline void cpu_relax() noexcept { asm volatile("yield" ::: "memory"); }
#else
inline void cpu_relax() noexcept { asm volatile("pause" ::: "memory"); }
#endif

// The host platform scheduler prioritizes execution via a user-initiated QoS class to keep
// workers on performance cores when they are available.
inline void join_worker_qos() noexcept { pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0); }

// Releases all workers at once so the measured interval excludes thread
// creation. Workers spin on the gate; the controller waits for arrivals.
class StartGate {
public:
    explicit StartGate(unsigned expected_arrivals) : expected_(expected_arrivals) {}

    void arrive_and_wait() noexcept {
        arrived_.fetch_add(1, std::memory_order_acq_rel);
        while (!open_.load(std::memory_order_acquire)) {
            cpu_relax();
        }
    }

    void wait_for_all_arrivals() const noexcept {
        while (arrived_.load(std::memory_order_acquire) < expected_) {
            std::this_thread::yield();
        }
    }

    void open() noexcept { open_.store(true, std::memory_order_release); }

private:
    unsigned expected_;
    std::atomic<unsigned> arrived_{0};
    std::atomic<bool> open_{false};
};

inline void* timed_allocate(const AllocatorApi& api, size_t size, HdrHistogram& alloc_events) {
    const uint64_t start = read_counter();
    void* pointer = api.allocate(size);
    const uint64_t end = read_counter();
    if (pointer == nullptr) {
        std::fprintf(stderr, "allocation of %zu bytes failed under %s\n", size, api.name.c_str());
        std::_Exit(ALLOCATION_FAILURE_EXIT_CODE);
    }
    alloc_events.record(ticks_to_nanoseconds(end - start));
    return pointer;
}

inline void timed_release(const AllocatorApi& api, void* pointer, HdrHistogram& free_events) {
    const uint64_t start = read_counter();
    api.release(pointer);
    const uint64_t end = read_counter();
    free_events.record(ticks_to_nanoseconds(end - start));
}

// One write per object forces the page-level backing store to exist, as a
// request handler would. The write sits outside the timed interval.
inline void touch_object(void* pointer) noexcept {
    *static_cast<volatile unsigned char*>(pointer) = 1;
}

struct ThreadRecord {
    HdrHistogram alloc_events;
    HdrHistogram free_events;
};

// Effective consumer count for an R:1 producer-to-consumer ratio. Rounds to
// the nearest integer and clamps to at least one consumer.
inline unsigned consumer_count_for(unsigned threads, unsigned ratio) {
    const unsigned group_size = ratio + 1;
    const unsigned rounded = (threads + group_size / 2) / group_size;
    return rounded == 0 ? 1 : rounded;
}

}  // namespace r2
