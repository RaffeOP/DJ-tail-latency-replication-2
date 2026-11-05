#include "workloads/gated_workers.hpp"

namespace r2 {

GatedWorkers::GatedWorkers(const std::vector<std::function<void()>>& bodies) : gate_(static_cast<unsigned>(bodies.size())) {
    threads_.reserve(bodies.size());
    for (const auto& body : bodies) {
        threads_.emplace_back([this, &body] {
            join_worker_qos();
            gate_.arrive_and_wait();
            body();
        });
    }
}

GatedWorkers::~GatedWorkers() {
    join();
}

void GatedWorkers::start() {
    gate_.wait_for_all_arrivals();
    start_time_ = std::chrono::steady_clock::now();
    gate_.open();
}

void GatedWorkers::join() {
    for (auto& thread : threads_) {
        if (thread.joinable()) {
            thread.join();
        }
    }
    if (end_time_ == std::chrono::steady_clock::time_point{}) {
        end_time_ = std::chrono::steady_clock::now();
    }
}

double GatedWorkers::elapsed_seconds() const {
    return std::chrono::duration<double>(end_time_ - start_time_).count();
}

}  // namespace r2
