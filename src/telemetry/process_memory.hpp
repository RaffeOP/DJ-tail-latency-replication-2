#pragma once

#include <mach/mach.h>
#include <cstdint>

namespace r2 {

struct MemoryFootprint {
    uint64_t phys_footprint_bytes;
    uint64_t peak_phys_footprint_bytes;
};

struct FootprintSample {
    double elapsed_seconds;
    uint64_t phys_footprint_bytes;
    uint64_t live_bytes;
};

// Reads the kernel's physical footprint for this process. This is the
// Unix kernel analogue of RSS: it counts dirty and compressed pages and excludes
// clean file-backed pages.
inline MemoryFootprint read_memory_footprint() noexcept {
    task_vm_info_data_t info{};
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    const kern_return_t status =
        task_info(mach_task_self(), TASK_VM_INFO, reinterpret_cast<task_info_t>(&info), &count);
    if (status != KERN_SUCCESS) {
        return {0, 0};
    }
    return {static_cast<uint64_t>(info.phys_footprint), static_cast<uint64_t>(info.ledger_phys_footprint_peak)};
}

}  // namespace r2
