#pragma once

#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>

namespace r2 {

// Log-linear histogram: exact below 64 ns, then 32 linear sub-buckets per
// octave. Relative bucket width is at most 1/32, so percentile reports carry
// at most about 1.6% error from the midpoint representative.
constexpr unsigned SUB_BUCKET_BITS = 5;
constexpr uint64_t SUB_BUCKET_COUNT = 1ULL << SUB_BUCKET_BITS;
constexpr uint64_t LINEAR_LIMIT = SUB_BUCKET_COUNT << 1;
constexpr unsigned MAX_LOG2 = 40;
constexpr size_t OCTAVE_COUNT = MAX_LOG2 - SUB_BUCKET_BITS;
constexpr size_t HISTOGRAM_BUCKETS = LINEAR_LIMIT + OCTAVE_COUNT * SUB_BUCKET_COUNT;

class HdrHistogram {
public:
    void record(uint64_t nanoseconds) noexcept {
        counts_[bucket_index(nanoseconds)]++;
        total_++;
        if (nanoseconds > max_) {
            max_ = nanoseconds;
        }
    }

    void merge_from(const HdrHistogram& other) noexcept {
        for (size_t i = 0; i < HISTOGRAM_BUCKETS; ++i) {
            counts_[i] += other.counts_[i];
        }
        total_ += other.total_;
        if (other.max_ > max_) {
            max_ = other.max_;
        }
    }

    uint64_t percentile(double percent) const noexcept {
        if (total_ == 0) {
            return 0;
        }
        if (percent >= 100.0) {
            return max_;
        }
        const double exact_rank = std::ceil(percent / 100.0 * static_cast<double>(total_));
        const uint64_t target = exact_rank < 1.0 ? 1 : static_cast<uint64_t>(exact_rank);
        uint64_t cumulative = 0;
        for (size_t i = 0; i < HISTOGRAM_BUCKETS; ++i) {
            cumulative += counts_[i];
            if (cumulative >= target) {
                return bucket_representative(i);
            }
        }
        return max_;
    }

    uint64_t total() const noexcept { return total_; }
    uint64_t max() const noexcept { return max_; }

    // Occupied buckets as (representative nanoseconds, count) pairs. Grouped
    // maximum-likelihood fits consume these directly.
    std::vector<std::pair<uint64_t, uint64_t>> occupied_buckets() const {
        std::vector<std::pair<uint64_t, uint64_t>> occupied;
        for (size_t i = 0; i < HISTOGRAM_BUCKETS; ++i) {
            if (counts_[i] != 0) {
                occupied.emplace_back(bucket_representative(i), counts_[i]);
            }
        }
        return occupied;
    }

private:
    static size_t bucket_index(uint64_t value) noexcept {
        if (value < LINEAR_LIMIT) {
            return static_cast<size_t>(value);
        }
        const unsigned log2_value = 63U - static_cast<unsigned>(__builtin_clzll(value));
        if (log2_value > MAX_LOG2) {
            return HISTOGRAM_BUCKETS - 1;
        }
        const unsigned shift = log2_value - SUB_BUCKET_BITS;
        const uint64_t sub_bucket = (value >> shift) - SUB_BUCKET_COUNT;
        return static_cast<size_t>(
            LINEAR_LIMIT + (log2_value - SUB_BUCKET_BITS - 1) * SUB_BUCKET_COUNT + sub_bucket);
    }

    static uint64_t bucket_representative(size_t index) noexcept {
        if (index < LINEAR_LIMIT) {
            return index;
        }
        const size_t offset = index - LINEAR_LIMIT;
        const unsigned shift = static_cast<unsigned>(offset / SUB_BUCKET_COUNT) + 1;
        const uint64_t sub_bucket = offset % SUB_BUCKET_COUNT;
        const uint64_t lower_bound = (SUB_BUCKET_COUNT + sub_bucket) << shift;
        return lower_bound + ((1ULL << shift) >> 1);
    }

    std::array<uint64_t, HISTOGRAM_BUCKETS> counts_{};
    uint64_t total_ = 0;
    uint64_t max_ = 0;
};

}  // namespace r2
