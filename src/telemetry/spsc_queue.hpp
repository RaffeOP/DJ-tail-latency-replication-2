#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace r2 {

// Heterogeneous 8-core ARM64 L1 and L2 coherence granule. Each hot index sits on its own
// line so producer and consumer never share a line with each other.
constexpr size_t CACHE_LINE_BYTES = 128;

// Single-producer single-consumer ring. Storage comes from the C++ runtime's
// operator new, never from the allocator under test.
class alignas(CACHE_LINE_BYTES) SpscQueue {
public:
    explicit SpscQueue(size_t depth) : mask_(depth - 1), buffer_(depth, nullptr) {}

    bool try_push(void* item) noexcept {
        const uint64_t write = write_index_.load(std::memory_order_relaxed);
        if (write - cached_read_index_ > mask_) {
            cached_read_index_ = read_index_.load(std::memory_order_acquire);
            if (write - cached_read_index_ > mask_) {
                return false;
            }
        }
        buffer_[write & mask_] = item;
        write_index_.store(write + 1, std::memory_order_release);
        return true;
    }

    bool try_pop(void*& item) noexcept {
        const uint64_t read = read_index_.load(std::memory_order_relaxed);
        if (read == cached_write_index_) {
            cached_write_index_ = write_index_.load(std::memory_order_acquire);
            if (read == cached_write_index_) {
                return false;
            }
        }
        item = buffer_[read & mask_];
        read_index_.store(read + 1, std::memory_order_release);
        return true;
    }

private:
    alignas(CACHE_LINE_BYTES) std::atomic<uint64_t> write_index_{0};
    alignas(CACHE_LINE_BYTES) uint64_t cached_read_index_{0};
    alignas(CACHE_LINE_BYTES) std::atomic<uint64_t> read_index_{0};
    alignas(CACHE_LINE_BYTES) uint64_t cached_write_index_{0};
    size_t mask_;
    std::vector<void*> buffer_;
};

}  // namespace r2
