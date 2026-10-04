#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$ROOT/experiments/cr-state-boundary/build/libcr_state_probe.so"
mkdir -p "$(dirname "$OUT")"
cc -shared -fPIC \
  -I "$ROOT/third_party/wamr/core/iwasm/include" \
  "$ROOT/experiments/cr-state-boundary/native_probe.c" \
  -o "$OUT"
nm -D "$OUT" | grep " get_native_lib$"
sha256sum "$OUT"
