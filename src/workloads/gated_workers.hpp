#pragma once

#include <chrono>
#include <functional>
#include <thread>
#include <vector>

#include "workloads/worker_support.hpp"

namespace r2 {

// Runs one body per thread behind a common start gate. The measured interval
// begins when every worker has arrived, so thread creation is excluded.
class GatedWorkers {
public:
    explicit GatedWorkers(const std::vector<std::function<void()>>& bodies);
    ~GatedWorkers();

    GatedWorkers(const GatedWorkers&) = delete;
    GatedWorkers& operator=(const GatedWorkers&) = delete;

    void start();
    void join();
    std::chrono::steady_clock::time_point start_time() const { return start_time_; }
    double elapsed_seconds() const;

private:
    StartGate gate_;
    std::vector<std::thread> threads_;
    std::chrono::steady_clock::time_point start_time_{};
    std::chrono::steady_clock::time_point end_time_{};
};

}  // namespace r2
