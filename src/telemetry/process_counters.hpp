#pragma once

#include <libproc.h>
#include <mach/mach.h>
#include <mach/task_info.h>
#include <sys/resource.h>
#include <unistd.h>

#include <cstdint>

namespace r2 {

// Process-level counters readable without privileges on Unix-based OS: CPU cycles and
// instructions retired from proc_pid_rusage, and fault counts from task_info.
// Values cover every thread of the process, so probes that run alone in their
// process attribute all counted work to the measured loop.
struct ProcessCounters {
    uint64_t cycles;
    uint64_t instructions;
    uint64_t faults;
    uint64_t cow_faults;
};

inline ProcessCounters read_process_counters() noexcept {
    ProcessCounters counters{0, 0, 0, 0};
    rusage_info_v6 usage{};
    if (proc_pid_rusage(getpid(), RUSAGE_INFO_V6, reinterpret_cast<rusage_info_t*>(&usage)) == 0) {
        counters.cycles = usage.ri_cycles;
        counters.instructions = usage.ri_instructions;
    }
    task_events_info_data_t events{};
    mach_msg_type_number_t count = TASK_EVENTS_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_EVENTS_INFO, reinterpret_cast<task_info_t>(&events), &count) == KERN_SUCCESS) {
        counters.faults = static_cast<uint64_t>(events.faults);
        counters.cow_faults = static_cast<uint64_t>(events.cow_faults);
    }
    return counters;
}

}  // namespace r2
