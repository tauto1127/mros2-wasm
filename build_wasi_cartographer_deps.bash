#!/bin/bash
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WASI_SDK_ROOT=${WASI_SDK_ROOT:-/opt/wasi-sdk-21}
CARTOGRAPHER_LIBRARY_ROOT=${CARTOGRAPHER_LIBRARY_ROOT:-${SCRIPT_DIR}/third_party/cartographer-library}
LOCAL_SYSROOT=${LOCAL_SYSROOT:-${HOME}/wasi-sysroot}
ZLIB_BUILD_DIR=${ZLIB_BUILD_DIR:-${SCRIPT_DIR}/cmake_build/zlib-wasi}

if [ ! -d "${LOCAL_SYSROOT}" ]; then
  echo "Creating local WASI sysroot at ${LOCAL_SYSROOT}..."
  cp -r "${WASI_SDK_ROOT}/share/wasi-sysroot" "${LOCAL_SYSROOT}"
  "${WASI_SDK_ROOT}/bin/llvm-ar" -d \
    "${LOCAL_SYSROOT}/lib/wasm32-wasi/libc.a" dlmalloc.o
fi

ZLIB_SOURCE_DIR=$(cd "${CARTOGRAPHER_LIBRARY_ROOT}/wasi/zlib" && pwd)
if [ -f "${ZLIB_BUILD_DIR}/CMakeCache.txt" ]; then
  CACHED_SOURCE_DIR=$(sed -n \
    's/^CMAKE_HOME_DIRECTORY:INTERNAL=//p' \
    "${ZLIB_BUILD_DIR}/CMakeCache.txt")
  if [ "${CACHED_SOURCE_DIR}" != "${ZLIB_SOURCE_DIR}" ]; then
    cmake -E remove_directory "${ZLIB_BUILD_DIR}"
  fi
fi

cmake -S "${ZLIB_SOURCE_DIR}" \
  -B "${ZLIB_BUILD_DIR}" \
  -DCMAKE_TOOLCHAIN_FILE="${WASI_SDK_ROOT}/share/cmake/wasi-sdk-pthread.cmake" \
  -DCMAKE_SYSROOT="${LOCAL_SYSROOT}" \
  -DBUILD_SHARED_LIBS=OFF
cmake --build "${ZLIB_BUILD_DIR}" --target zlibstatic

echo "WASI zlib: ${ZLIB_BUILD_DIR}/libz.a"
