#pragma once

#include <cstddef>
#include <string>

namespace r2 {

using AllocateFn = void* (*)(size_t);
using ReleaseFn = void (*)(void*);

struct AllocatorApi {
    std::string name;
    std::string image_path;
    AllocateFn allocate;
    ReleaseFn release;
};

// Resolves one allocator's entry points by dlopen/dlsym from lib_dir.
// The baseline "libmalloc" resolves from the system library instead.
// Throws std::runtime_error when the library or symbol cannot be resolved.
AllocatorApi load_allocator(const std::string& name, const std::string& lib_dir);

}  // namespace r2
