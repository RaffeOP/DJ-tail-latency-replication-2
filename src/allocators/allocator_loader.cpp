#include "allocators/allocator_loader.hpp"

#include <dlfcn.h>

#include <array>
#include <stdexcept>

namespace r2 {
namespace {

struct AllocatorSpec {
    const char* name;
    const char* library_file;
    const char* allocate_symbol;
    const char* release_symbol;
};

constexpr std::array<AllocatorSpec, 5> ALLOCATOR_SPECS = {{
    {"libmalloc", nullptr, "malloc", "free"},
    {"mimalloc", "libmimalloc.dylib", "mi_malloc", "mi_free"},
    {"jemalloc", "libjemalloc.dylib", "malloc", "free"},
    {"tcmalloc", "libtcmalloc.dylib", "tc_malloc", "tc_free"},
    {"snmalloc", "libsnmallocshim.dylib", "malloc", "free"},
}};

const AllocatorSpec& find_spec(const std::string& name) {
    for (const AllocatorSpec& spec : ALLOCATOR_SPECS) {
        if (name == spec.name) {
            return spec;
        }
    }
    throw std::runtime_error("unknown allocator: " + name);
}

void* open_handle(const AllocatorSpec& spec, const std::string& lib_dir) {
    if (spec.library_file == nullptr) {
        return RTLD_DEFAULT;
    }
    const std::string path = lib_dir + "/" + spec.library_file;
    void* handle = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr) {
        throw std::runtime_error("dlopen failed for " + path + ": " + dlerror());
    }
    return handle;
}

void* resolve_symbol(void* handle, const char* symbol) {
    void* address = dlsym(handle, symbol);
    if (address == nullptr) {
        throw std::runtime_error(std::string("dlsym failed for ") + symbol + ": " + dlerror());
    }
    return address;
}

std::string image_of(const void* address) {
    Dl_info info{};
    if (dladdr(address, &info) == 0 || info.dli_fname == nullptr) {
        return "unknown";
    }
    return info.dli_fname;
}

}  // namespace

AllocatorApi load_allocator(const std::string& name, const std::string& lib_dir) {
    const AllocatorSpec& spec = find_spec(name);
    void* handle = open_handle(spec, lib_dir);
    void* allocate_address = resolve_symbol(handle, spec.allocate_symbol);
    void* release_address = resolve_symbol(handle, spec.release_symbol);

    AllocatorApi api;
    api.name = name;
    api.image_path = image_of(allocate_address);
    api.allocate = reinterpret_cast<AllocateFn>(allocate_address);
    api.release = reinterpret_cast<ReleaseFn>(release_address);
    return api;
}

}  // namespace r2
