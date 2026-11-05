#!/usr/bin/env bash
# Builds gperftools 2.19.1 tcmalloc from source, unmodified (default) and with the
# transfer-batch cap patch applied (mod). Writes libtcmalloc.dylib into WORK/libs-default and WORK/libs-mod.
set -euo pipefail
WORK="${1:-$(mktemp -d)}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
git clone --depth 1 --branch gperftools-2.19.1 https://github.com/gperftools/gperftools.git "$WORK/gperf-src"
cp -R "$WORK/gperf-src" "$WORK/gperf-mod"
(cd "$WORK/gperf-mod" && patch -p1 < "$DIR/transfer_batch_cap.patch")
for variant in default mod; do
  src="$WORK/gperf-src"; [ "$variant" = mod ] && src="$WORK/gperf-mod"
  cmake -S "$src" -B "$src/build-$variant" -DCMAKE_BUILD_TYPE=Release -Dgperftools_build_benchmark=OFF
  cmake --build "$src/build-$variant" -j8 --target tcmalloc
  mkdir -p "$WORK/libs-$variant"
  ln -sf "$src/build-$variant/libtcmalloc.dylib" "$WORK/libs-$variant/libtcmalloc.dylib"
done
echo "built: $WORK/libs-default and $WORK/libs-mod"
