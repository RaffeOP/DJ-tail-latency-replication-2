// src/purge_probe.cpp
// Page-release primitive study. A worker pool performs timed random accesses
// over a touched region while a purger thread releases chunks with
// madvise(MADV_DONTNEED), madvise(MADV_FREE), or not at all. The study measures
// the purge call cost, worker access tails, and physical footprint over time.
//
//   purge_probe run --policy none|dontneed|free|free_reusable --region-mb MB --chunk-kb KB
//       --interval-ms MS --workers W --duration SECONDS

#include <sys/mman.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "cli/arg_map.hpp"
#include "telemetry/cycle_timer.hpp"
#include "telemetry/hdr_histogram.hpp"
#include "telemetry/json_output.hpp"
#include "telemetry/process_counters.hpp"
#include "telemetry/process_memory.hpp"
#include "workloads/worker_support.hpp"

namespace r2 {
namespace {

constexpr size_t PAGE_BYTES = 16384;
constexpr size_t BYTES_PER_MB = 1ULL << 20;
constexpr size_t BYTES_PER_KB = 1ULL << 10;
constexpr unsigned SAMPLE_INTERVAL_MS = 50;
constexpr uint64_t RNG_SEED_BASE = 0x9E3779B97F4A7C15ULL;

enum class PurgePolicy { None, DontNeed, Free, FreeReusable };

PurgePolicy parse_policy(const std::string& text) {
    if (text == "none") {
        return PurgePolicy::None;
    }
    if (text == "dontneed") {
        return PurgePolicy::DontNeed;
    }
    if (text == "free") {
        return PurgePolicy::Free;
    }
    if (text == "free_reusable") {
        return PurgePolicy::FreeReusable;
    }
    throw std::invalid_argument("unknown policy: " + text);
}

int release_advice_for(PurgePolicy policy) {
    switch (policy) {
        case PurgePolicy::DontNeed:
            return MADV_DONTNEED;
        case PurgePolicy::Free:
            return MADV_FREE;
        case PurgePolicy::FreeReusable:
            return MADV_FREE_REUSABLE;
        case PurgePolicy::None:
            break;
    }
    return MADV_FREE;
}

// The Unix kernel requires MADV_FREE_REUSE before a reusable range is written again,
// as the system allocator does. The call is part of the reuse cost.
bool needs_reuse_advice(PurgePolicy policy) {
    return policy == PurgePolicy::FreeReusable;
}

// The region is split in two. Workers only access the live half, and the
// purger releases and then reuses the pool half. This mirrors an allocator
// that frees spans and later hands them back out.
struct ProbeShared {
    unsigned char* base = nullptr;
    size_t region_bytes = 0;
    std::atomic<bool> stop{false};
    std::vector<HdrHistogram> access_histograms;
    HdrHistogram purge_histogram;
    HdrHistogram reuse_histogram;
    uint64_t purge_calls = 0;
    uint64_t purged_bytes = 0;

    size_t live_bytes() const { return region_bytes / 2; }
};

uint64_t next_random(uint64_t& state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

void run_accessor(ProbeShared& shared, unsigned index) {
    uint64_t state = RNG_SEED_BASE + index;
    HdrHistogram& histogram = shared.access_histograms[index];
    volatile unsigned char sink = 0;
    while (!shared.stop.load(std::memory_order_relaxed)) {
        const size_t offset = next_random(state) % shared.live_bytes();
        volatile unsigned char* cell = shared.base + offset;
        const uint64_t start = read_counter();
        sink = static_cast<unsigned char>(sink + *cell);
        *cell = sink;
        const uint64_t end = read_counter();
        histogram.record(ticks_to_nanoseconds(end - start));
    }
}

void release_pool(ProbeShared& shared, int advice, size_t chunk_bytes) {
    for (size_t offset = shared.live_bytes(); offset < shared.region_bytes; offset += chunk_bytes) {
        unsigned char* chunk = shared.base + offset;
        const uint64_t start = read_counter();
        if (madvise(chunk, chunk_bytes, advice) != 0) {
            std::fprintf(stderr, "madvise failed\n");
            std::_Exit(ALLOCATION_FAILURE_EXIT_CODE);
        }
        const uint64_t end = read_counter();
        shared.purge_histogram.record(ticks_to_nanoseconds(end - start));
        shared.purge_calls++;
        shared.purged_bytes += chunk_bytes;
    }
}

// Reuse faults the released pages back in, as an allocator does when it
// hands a span out again. Each page is written once.
void reuse_pool(ProbeShared& shared, size_t chunk_bytes, bool reuse_advice) {
    for (size_t offset = shared.live_bytes(); offset < shared.region_bytes; offset += chunk_bytes) {
        unsigned char* chunk = shared.base + offset;
        const uint64_t start = read_counter();
        if (reuse_advice) {
            madvise(chunk, chunk_bytes, MADV_FREE_REUSE);
        }
        for (size_t page = 0; page < chunk_bytes; page += PAGE_BYTES) {
            chunk[page] = 1;
        }
        const uint64_t end = read_counter();
        shared.reuse_histogram.record(ticks_to_nanoseconds(end - start));
    }
}

void run_purger(ProbeShared& shared, PurgePolicy policy, size_t chunk_bytes, unsigned interval_ms) {
    const int advice = release_advice_for(policy);
    const bool reuse_advice = needs_reuse_advice(policy);
    const auto half_cycle = std::chrono::milliseconds(interval_ms / 2);
    while (!shared.stop.load(std::memory_order_relaxed)) {
        std::this_thread::sleep_for(half_cycle);
        release_pool(shared, advice, chunk_bytes);
        std::this_thread::sleep_for(half_cycle);
        reuse_pool(shared, chunk_bytes, reuse_advice);
    }
}

void touch_region(unsigned char* base, size_t bytes) {
    for (size_t offset = 0; offset < bytes; offset += PAGE_BYTES) {
        base[offset] = 1;
    }
}

std::string samples_json(const std::vector<FootprintSample>& samples) {
    std::string out = "[";
    for (size_t i = 0; i < samples.size(); ++i) {
        if (i > 0) {
            out += ",";
        }
        out += "{\"t\":" + std::to_string(samples[i].elapsed_seconds) +
               ",\"footprint\":" + std::to_string(samples[i].phys_footprint_bytes) + "}";
    }
    return out + "]";
}

void print_result(const ArgMap& args, const ProbeShared& shared, const std::vector<FootprintSample>& samples,
                  double wall_seconds, uint64_t faults, uint64_t cow_faults) {
    HdrHistogram access_total;
    for (const HdrHistogram& histogram : shared.access_histograms) {
        access_total.merge_from(histogram);
    }
    std::printf("{\"schema\":\"r2.purge.v1\",\"policy\":%s,\"region_mb\":%s,\"chunk_kb\":%s,\"interval_ms\":%s,"
                "\"workers\":%s,\"wall_seconds\":%.6f,\"purge_calls\":%llu,\"purged_bytes\":%llu,"
                "\"purge_latency_ns\":%s,\"reuse_latency_ns\":%s,\"access_latency_ns\":%s,\"samples\":%s,"
                "\"page_faults\":%llu,\"cow_faults\":%llu}\n",
                json_string(args.value_or("policy", "none")).c_str(),
                args.value_or("region-mb", "512").c_str(), args.value_or("chunk-kb", "256").c_str(),
                args.value_or("interval-ms", "5").c_str(), args.value_or("workers", "4").c_str(), wall_seconds,
                static_cast<unsigned long long>(shared.purge_calls),
                static_cast<unsigned long long>(shared.purged_bytes),
                histogram_json(shared.purge_histogram).c_str(), histogram_json(shared.reuse_histogram).c_str(),
                histogram_json(access_total).c_str(), samples_json(samples).c_str(),
                static_cast<unsigned long long>(faults), static_cast<unsigned long long>(cow_faults));
}

}  // namespace
}  // namespace r2

int main(int argc, char** argv) {
    using r2::ProbeShared;
    try {
        const r2::ArgMap args(argc, argv);
        const r2::PurgePolicy policy = r2::parse_policy(args.value_or("policy", "none"));
        const size_t region_bytes = args.number_or("region-mb", 512) * r2::BYTES_PER_MB;
        const size_t chunk_bytes = args.number_or("chunk-kb", 256) * r2::BYTES_PER_KB;
        const unsigned interval_ms = static_cast<unsigned>(args.number_or("interval-ms", 5));
        const unsigned workers = static_cast<unsigned>(args.number_or("workers", 4));
        const double duration = args.real_or("duration", 10.0);

        void* mapping = mmap(nullptr, region_bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
        if (mapping == MAP_FAILED) {
            throw std::runtime_error("mmap failed");
        }
        ProbeShared shared;
        shared.base = static_cast<unsigned char*>(mapping);
        shared.region_bytes = region_bytes;
        shared.access_histograms.resize(workers);
        r2::touch_region(shared.base, region_bytes);

        std::vector<std::thread> threads;
        for (unsigned w = 0; w < workers; ++w) {
            threads.emplace_back([&shared, w] { r2::run_accessor(shared, w); });
        }
        if (policy != r2::PurgePolicy::None) {
            threads.emplace_back([&shared, policy, chunk_bytes, interval_ms] {
                r2::run_purger(shared, policy, chunk_bytes, interval_ms);
            });
        }

        std::vector<r2::FootprintSample> samples;
        const r2::ProcessCounters counters_before = r2::read_process_counters();
        const auto start = std::chrono::steady_clock::now();
        while (std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() < duration) {
            std::this_thread::sleep_for(std::chrono::milliseconds(r2::SAMPLE_INTERVAL_MS));
            const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
            samples.push_back({elapsed, r2::read_memory_footprint().phys_footprint_bytes, 0});
        }
        shared.stop.store(true);
        for (auto& thread : threads) {
            thread.join();
        }
        const double wall = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        const r2::ProcessCounters counters_after = r2::read_process_counters();
        r2::print_result(args, shared, samples, wall, counters_after.faults - counters_before.faults,
                         counters_after.cow_faults - counters_before.cow_faults);
        munmap(mapping, region_bytes);
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "purge_probe: %s\n", error.what());
        return EXIT_FAILURE;
    }
}
