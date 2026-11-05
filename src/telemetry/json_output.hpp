#pragma once

#include <sstream>
#include <string>

#include "telemetry/hdr_histogram.hpp"

namespace r2 {

// Escapes the characters that can appear in allocator names and image paths.
inline std::string json_string(const std::string& text) {
    std::string escaped = "\"";
    for (const char character : text) {
        if (character == '"' || character == '\\') {
            escaped += '\\';
        }
        escaped += character;
    }
    escaped += '"';
    return escaped;
}

// Sparse bucket counts as [[representative_ns, count], ...].
inline std::string histogram_counts_json(const HdrHistogram& histogram) {
    std::ostringstream out;
    out << "[";
    bool first = true;
    for (const auto& [representative, count] : histogram.occupied_buckets()) {
        out << (first ? "" : ",") << "[" << representative << "," << count << "]";
        first = false;
    }
    out << "]";
    return out.str();
}

// Emits the percentile summary used by every latency field in the results.
inline std::string histogram_json(const HdrHistogram& histogram) {
    std::ostringstream out;
    out << "{\"count\":" << histogram.total() << ",\"p50\":" << histogram.percentile(50.0)
        << ",\"p90\":" << histogram.percentile(90.0) << ",\"p99\":" << histogram.percentile(99.0)
        << ",\"p99_9\":" << histogram.percentile(99.9) << ",\"p99_99\":" << histogram.percentile(99.99)
        << ",\"max\":" << histogram.max() << "}";
    return out.str();
}

}  // namespace r2
