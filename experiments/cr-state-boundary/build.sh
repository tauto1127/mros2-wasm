#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BUILD_ROOT=${CR_STATE_BOUNDARY_BUILD_ROOT:-/tmp/mros2-wasm-cr-state-boundary-build}
WASM_BUILD="$BUILD_ROOT/wasm-build"
RUNTIME_BUILD=${CR_STATE_BOUNDARY_RUNTIME_BUILD:-$ROOT/third_party/wamr/product-mini/platforms/linux/build-cr-state-boundary-repro}
WASMIG_CACHE="$ROOT/third_party/wamr/product-mini/platforms/linux/build-cr-state-boundary/_deps/wasmig-src"
WASMIG_SOURCE="$WASMIG_CACHE"
INCLUDE_DIR="$WASM_BUILD/experiment-includes"
RUN=${CR_STATE_BOUNDARY_RUN_DIR:-$ROOT/experiments/cr-state-boundary/runtime-build}
PROV=${CR_STATE_BOUNDARY_PROV_DIR:-$ROOT/experiments/cr-state-boundary/build-provenance}
CMAKE_BIN=/home/osslab/.local/bin/cmake
WASI_SDK=/opt/wasi-sdk-21
SYSROOT=/home/osslab/wasi-sysroot
ZLIB_LIBRARY=/tmp/mros2-wasm-eintr-integration-build/zlib-wasi/libz.a
PEER=/tmp/mros2-posix-run04-final-build/mros2-posix

if [[ -e "$BUILD_ROOT" ]]; then
  echo "refusing to reuse build root: $BUILD_ROOT" >&2
  exit 2
fi
if [[ -e "$RUNTIME_BUILD" ]]; then
  echo "refusing to reuse runtime build root: $RUNTIME_BUILD" >&2
  exit 2
fi
mkdir -p "$BUILD_ROOT" "$INCLUDE_DIR" "$RUN/app" "$RUN/runtime" "$PROV"
printf "%s\n" "// Intentionally empty: echoback_string defines no service endpoints." > "$INCLUDE_DIR/templates-service.hpp"
"$WASI_SDK/bin/clang" --version > "$PROV/compiler-version.txt"
printf 'wasi_sdk=%s\n' "$(basename "$WASI_SDK")" > "$PROV/wasi-sdk-version.txt"

{
  echo "root $(git -C "$ROOT" rev-parse HEAD)"
  for p in cmsis-wasm lwip-wasm mros2 mros2/embeddedRTPS third_party/wamr; do
    echo "$p $(git -C "$ROOT/$p" rev-parse HEAD)"
  done
} > "$PROV/revisions-before-build.txt"

CONFIGURE_ARGS=(
  -S "$ROOT"
  -B "$WASM_BUILD"
  -DCMAKE_APPNAME=echoback_string
  "-DWASI_SDK_PREFIX=$WASI_SDK"
  "-DCMAKE_TOOLCHAIN_FILE=$WASI_SDK/share/cmake/wasi-sdk-pthread.cmake"
  "-DCMAKE_SYSROOT=$SYSROOT"
  "-DWAMR_ROOT=$ROOT/third_party/wamr"
  "-DCARTOGRAPHER_ROOT=$ROOT/third_party/cartographer"
  "-DCARTOGRAPHER_LIBRARY_ROOT=$ROOT/third_party/cartographer-library"
  "-DZLIB_LIBRARY=$ZLIB_LIBRARY"
  "-DCMAKE_CXX_FLAGS=-I$INCLUDE_DIR"
  -DCMAKE_EXPORT_COMPILE_COMMANDS=1
)
BUILD_ARGS=(--build "$WASM_BUILD" --target MODULE_echoback_string --parallel 8)
printf "%s" "$CMAKE_BIN" > "$PROV/configure-command.txt"; printf " %q" "${CONFIGURE_ARGS[@]}" >> "$PROV/configure-command.txt"; printf "\n" >> "$PROV/configure-command.txt"
printf "%s" "$CMAKE_BIN" > "$PROV/build-command.txt"; printf " %q" "${BUILD_ARGS[@]}" >> "$PROV/build-command.txt"; printf "\n" >> "$PROV/build-command.txt"
"$CMAKE_BIN" "${CONFIGURE_ARGS[@]}" 2>&1 | tee "$PROV/configure.log"
"$CMAKE_BIN" "${BUILD_ARGS[@]}" 2>&1 | tee "$PROV/build.log"
cp "$WASM_BUILD/compile_commands.json" "$PROV/compile_commands.json"
cp "$WASM_BUILD/echoback_string.wasm" "$RUN/app/echoback_string.wasm"

python3 - "$WASM_BUILD/compile_commands.json" > "$PROV/netif-compile-command.txt" <<"PY"
import json, pathlib, sys
rows=json.load(open(sys.argv[1]))
hits=[r for r in rows if pathlib.Path(r["file"]).name=="netif_wasm.c"]
if len(hits)!=1: raise SystemExit(f"expected one netif_wasm.c command, got {len(hits)}")
cmd=hits[0]["command"]
print(cmd)
if "--target=wasm32-wasi-threads" not in cmd: raise SystemExit("netif_wasm.c is not wasm32-wasi-threads")
print("classification=wasm32-wasi-threads")
PY
OBJ=$(find "$WASM_BUILD" -type f -name "netif_wasm.c.obj" -print -quit)
test -n "$OBJ"
/opt/wasi-sdk-21/bin/llvm-nm "$OBJ" | grep -E "netif_default|netif_wasm|ip_changed_pending" > "$PROV/netif-symbols.txt"
wasm-objdump -x "$RUN/app/echoback_string.wasm" | grep -E "cr_host_probe_(get|set)" > "$PROV/guest-native-imports.txt"

"$ROOT/experiments/cr-state-boundary/build-native-probe.sh" > "$PROV/native-probe-build.txt"
cp "$ROOT/experiments/cr-state-boundary/build/libcr_state_probe.so" "$RUN/runtime/libcr_state_probe.so"

test "$(git -C "$WASMIG_CACHE" rev-parse HEAD)" = "c5015ee06acd3992ce826655825e1911da8c5945"
mkdir -p "$RUNTIME_BUILD"
{
  echo "wasmig_source=$WASMIG_CACHE"
  echo "wasmig_commit=$(git -C "$WASMIG_CACHE" rev-parse HEAD)"
  echo "cargo=$(/home/osslab/.cargo/bin/cargo --version)"
  "$CMAKE_BIN" --version | head -1
} > "$PROV/runtime-dependency-provenance.txt"

RUNTIME_CONFIGURE=(
  -S "$ROOT/third_party/wamr/product-mini/platforms/linux"
  -B "$RUNTIME_BUILD"
  -DCMAKE_BUILD_TYPE=Release
  "-DFETCHCONTENT_SOURCE_DIR_WASMIG=$WASMIG_SOURCE"
  -DWAMR_BUILD_INTERP=1
  -DWAMR_BUILD_FAST_INTERP=0
  -DWAMR_BUILD_AOT=0
  -DWAMR_BUILD_JIT=0
  -DWAMR_BUILD_FAST_JIT=0
  -DWAMR_BUILD_LIBC_WASI=1
  -DWAMR_BUILD_LIB_WASI_THREADS=1
  -DWAMR_BUILD_LIB_PTHREAD=0
  -DWAMR_BUILD_THREAD_MGR=1
  -DWAMR_BUILD_SHARED_MEMORY=1
)
printf "%s" "$CMAKE_BIN" > "$PROV/runtime-configure-command.txt"; printf " %q" "${RUNTIME_CONFIGURE[@]}" >> "$PROV/runtime-configure-command.txt"; printf "\n" >> "$PROV/runtime-configure-command.txt"
PATH=/home/osslab/.cargo/bin:/home/osslab/.local/bin:$PATH "$CMAKE_BIN" "${RUNTIME_CONFIGURE[@]}" 2>&1 | tee "$PROV/runtime-configure.log"
printf "%s --build %q --parallel 8\n" "$CMAKE_BIN" "$RUNTIME_BUILD" > "$PROV/runtime-build-command.txt"
PATH=/home/osslab/.cargo/bin:/home/osslab/.local/bin:$PATH "$CMAKE_BIN" --build "$RUNTIME_BUILD" --parallel 8 2>&1 | tee "$PROV/runtime-build.log"
cp "$RUNTIME_BUILD/iwasm" "$RUN/runtime/iwasm"
sha256sum "$RUN/runtime/iwasm" "$RUN/runtime/libcr_state_probe.so" "$RUN/app/echoback_string.wasm" "$PEER" > "$PROV/artifact-sha256.txt"
"$RUN/runtime/iwasm" --version > "$PROV/iwasm-version.txt" 2>&1 || true
cat "$PROV/artifact-sha256.txt"
