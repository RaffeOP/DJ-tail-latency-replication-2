#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace r2 {

// Parses "--key value" pairs after a leading subcommand. Flags without a
// value are not used by the harness, so every key takes exactly one value.
class ArgMap {
public:
    ArgMap(int argc, char** argv) {
        if (argc < 2) {
            throw std::invalid_argument("missing subcommand");
        }
        command_ = argv[1];
        for (int i = 2; i + 1 < argc; i += 2) {
            const std::string key = argv[i];
            if (key.rfind("--", 0) != 0) {
                throw std::invalid_argument("expected --key, got " + key);
            }
            values_[key.substr(2)] = argv[i + 1];
        }
    }

    const std::string& command() const { return command_; }

    std::string require(const std::string& key) const {
        const auto found = values_.find(key);
        if (found == values_.end()) {
            throw std::invalid_argument("missing required argument --" + key);
        }
        return found->second;
    }

    std::string value_or(const std::string& key, const std::string& fallback) const {
        const auto found = values_.find(key);
        return found == values_.end() ? fallback : found->second;
    }

    unsigned long long number_or(const std::string& key, unsigned long long fallback) const {
        const auto found = values_.find(key);
        return found == values_.end() ? fallback : std::stoull(found->second);
    }

    double real_or(const std::string& key, double fallback) const {
        const auto found = values_.find(key);
        return found == values_.end() ? fallback : std::stod(found->second);
    }

private:
    std::string command_;
    std::map<std::string, std::string> values_;
};

}  // namespace r2
