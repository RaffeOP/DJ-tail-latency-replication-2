#pragma once

#include <chrono>
#include <cstdint>

namespace r2 {

constexpr uint64_t NANOSECONDS_PER_SECOND = 1000000000ULL;

#if defined(__aarch64__)

// ISB orders the read against preceding instructions; CNTVCT_EL0 is the
// architectural virtual count. On 64-bit ARM hardware it ticks at 1 GHz.
inline uint64_t read_counter() noexcept {
    uint64_t value;
    asm volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(value)::"memory");
    return value;
}

inline uint64_t counter_frequency_hz() noexcept {
    uint64_t frequency;
    asm volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    return frequency;
}

#else

inline uint64_t read_counter() noexcept {
    const auto since_epoch = std::chrono::steady_clock::now().time_since_epoch();
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(since_epoch).count());
}

inline uint64_t counter_frequency_hz() noexcept { return NANOSECONDS_PER_SECOND; }

#endif

inline const uint64_t COUNTER_HZ = counter_frequency_hz();

// Converts a counter delta to nanoseconds. Deltas stay far below the
// 64-bit overflow point of ticks * 1e9 for any interval under 18 seconds.
inline uint64_t ticks_to_nanoseconds(uint64_t ticks) noexcept {
    if (COUNTER_HZ == NANOSECONDS_PER_SECOND) {
        return ticks;
    }
    return static_cast<uint64_t>(static_cast<double>(ticks) * static_cast<double>(NANOSECONDS_PER_SECOND) /
                                 static_cast<double>(COUNTER_HZ));
}

}  // namespace r2
