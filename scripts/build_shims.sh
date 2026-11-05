#!/bin/sh
# Builds the two allocator shims that the harness loads from lib/.
#
#   libsnmallocshim.dylib   snmalloc 0.6.2 shim target
#
# Usage: scripts/build_shims.sh <snmalloc-0.6.2-source-dir> [lib-dir]
set -eu

SNMALLOC_SRC="${1:?usage: build_shims.sh <snmalloc-0.6.2-source-dir> [lib-dir]}"
WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
LIB_DIR="${2:-$WORKSPACE/lib}"
BUILD_DIR="$WORKSPACE/build/shims"

mkdir -p "$BUILD_DIR" "$LIB_DIR"

cmake -S "$SNMALLOC_SRC" -B "$BUILD_DIR/snmalloc" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-Wno-missing-template-arg-list-after-template-kw" > "$BUILD_DIR/snmalloc-configure.log" 2>&1
cmake --build "$BUILD_DIR/snmalloc" --target snmallocshim > "$BUILD_DIR/snmalloc-build.log" 2>&1
cp "$BUILD_DIR/snmalloc/libsnmallocshim.dylib" "$LIB_DIR/libsnmallocshim.dylib"

for shim in libsnmallocshim.dylib; do
  for symbol in malloc free; do
    nm -gU "$LIB_DIR/$shim" | grep -q " _$symbol\$" || { echo "missing $symbol in $shim" >&2; exit 1; }
  done
done
echo "built $LIB_DIR/libsnmallocshim.dylib"
