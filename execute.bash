#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WAMR_BIN="${WAMR_BIN:-${SCRIPT_DIR}/third_party/wamr/product-mini/platforms/linux/build_socket_journal/iwasm}"
WASM_APP="${WASM_APP:-${SCRIPT_DIR}/cmake_build/service_test_add_two_int.wasm}"

exec "${WAMR_BIN}" \
  --addr-pool=0.0.0.0/0 \
  --max-threads=32 \
  -v=5 \
  "${WASM_APP}"
