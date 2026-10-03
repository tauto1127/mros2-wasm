#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TASK=${1:?Usage: run-task.sh T01|T10a|T10b1|T10b2|T10b3|T10c|T10c1|T10c2a|T10c2b|T10c6|all}
if [[ "$TASK" == all ]]; then
  AGGREGATE="$ROOT/validation/rtps/runs/$(date -u +%Y%m%dT%H%M%S)-all-$$"
  mkdir -p "$AGGREGATE"
  : > "$AGGREGATE/coverage.manifest"
  for CASE in T01 T10a T10b1 T10b2 T10b3 T10c6 T10c1 T10c T10c2a T10c2b; do
    RESULT=$(bash "$(dirname "$0")/run-task.sh" "$CASE" 2>&1) || { printf '%s\n' "$RESULT" | tee -a "$AGGREGATE/aggregate.log"; exit 1; }
    printf '%s\n' "$RESULT" | tee -a "$AGGREGATE/aggregate.log"
    CASE_OUT=$(printf '%s\n' "$RESULT" | sed -n 's/^PASS .* artifacts=//p' | tail -1)
    printf '%s %s\n' "$CASE" "$CASE_OUT" >> "$AGGREGATE/coverage.manifest"
  done
  sha256sum "$AGGREGATE/coverage.manifest" > "$AGGREGATE/coverage.sha256"
  echo "PASS all coverage=$AGGREGATE/coverage.manifest"
  exit
fi
[[ "$TASK" == T01 || "$TASK" == T10a || "$TASK" == T10b || "$TASK" == T10b1 || "$TASK" == T10b2 || "$TASK" == T10b3 || "$TASK" == T10c || "$TASK" == T10c1 || "$TASK" == T10c2a || "$TASK" == T10c2b || "$TASK" == T10c6 ]] || { echo "Task not implemented: $TASK" >&2; exit 2; }
OUT="$ROOT/validation/rtps/runs/$(date -u +%Y%m%dT%H%M%S)-$TASK-$$"
mkdir -p "$OUT"
exec > >(tee "$OUT/commands.log") 2>&1
set -x
if [[ "$TASK" == T10c2b ]]; then
  NATIVE_FLAGS=(-std=c++17 -O0 -ffunction-sections -fdata-sections
    -I"$ROOT/include" -I"$ROOT/mros2/include" -I"$ROOT/mros2/embeddedRTPS/include"
    -I"$ROOT/lwip-wasm/lwip/src/include" -I"$ROOT/lwip-wasm/src/include"
    -I"$ROOT/lwip-wasm/public/include/system" -I"$ROOT/cmsis-wasm/public/include")
  g++ "${NATIVE_FLAGS[@]}" "$ROOT/mros2/embeddedRTPS/src/communication/UdpDriver.cpp" \
    "$ROOT/validation/rtps/native-ip-mapping.cpp" -Wl,--gc-sections \
    -o "$OUT/native-ip-mapping" > "$OUT/native-build.log" 2>&1
  sha256sum "$ROOT/validation/rtps/native-ip-mapping.cpp" \
    "$ROOT/mros2/embeddedRTPS/src/communication/UdpDriver.cpp" \
    "$ROOT/mros2/embeddedRTPS/include/rtps/communication/UdpDriver.h" \
    "$ROOT/lwip-wasm/lwip/src/include/lwip/netif.h" "$ROOT/include/rtps/config.h" \
    "$ROOT/lwip-wasm/src/include/lwipopts.h" "$OUT/native-ip-mapping" > "$OUT/artifacts.sha256"
  git -C "$ROOT/mros2/embeddedRTPS" diff --binary | sha256sum > "$OUT/embedded-diff.sha256"
  timeout 15s "$OUT/native-ip-mapping" > "$OUT/run.log" 2>&1
  grep -q 'T10c2b_NATIVE_IP_MAPPING_PASS' "$OUT/run.log"
  echo "PASS $TASK artifacts=$OUT"
  exit
fi
SDK=/opt/wasi-sdk-21
RUNTIME=${RTPS_RUNTIME:-/tmp/mros2-wasm-no-udp-recover-experiment-build-03/runtime/iwasm}
EXPECTED=${RTPS_RUNTIME_SHA256:-77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60}
[[ $(sha256sum "$RUNTIME" | cut -d' ' -f1) == "$EXPECTED" ]]
LW="$ROOT/lwip-wasm"
CMS="$ROOT/cmsis-wasm"
RTPS="$ROOT/mros2/embeddedRTPS"
FLAGS=(--target=wasm32-wasi-threads --sysroot=/home/osslab/wasi-sysroot -pthread -fno-exceptions -O0 -g -ffunction-sections -fdata-sections
  -I"$ROOT/include" -I"$ROOT/mros2/include" -I"$RTPS/include" -I"$RTPS/thirdparty/Micro-CDR/include"
  -I"$LW/public/include/lwip" -I"$LW/public/include/posix" -I"$LW/public/include/system"
  -I"$LW/src/include" -I"$CMS/public/include")
OBJECTS=()
WRAPS=()
if [[ "$TASK" != T01 ]]; then
  WRAPS=(-Wl,--wrap=connect,--wrap=getsockname,--wrap=netif_wasm_get_ip_snapshot,--wrap=sys_mutex_new,--wrap=pbuf_alloc,--wrap=pbuf_take_at,--wrap=pbuf_free,--wrap=pbuf_ref
    -Wl,--wrap=ucdr_serialize_array_uint8_t,--wrap=ucdr_serialize_uint16_t,--wrap=ucdr_serialize_uint32_t,--wrap=ucdr_serialize_int32_t
    -Wl,--wrap=ucdr_serialize_uint8_t,--wrap=ucdr_serialize_array_char,--wrap=_Znwm)
fi
if [[ "$TASK" == T01 ]]; then
  "$SDK/bin/clang++" "${FLAGS[@]}" -std=gnu++17 -c "$ROOT/validation/rtps/fixture.cpp" -o "$OUT/fixture.o" > "$OUT/compile-fixture.log" 2>&1
  OBJECTS+=("$OUT/fixture.o")
else
  TEST_FLAGS=(-DRTPS_T10_TEST_ACCESS)
  SOURCES=(
    "$ROOT/validation/rtps/projection-fixture.cpp"
    "$RTPS/src/communication/UdpDriver.cpp"
    "$RTPS/src/messages/MessageTypes.cpp"
    "$RTPS/src/messages/MessageReceiver.cpp"
    "$RTPS/src/discovery/TopicData.cpp"
    "$RTPS/src/discovery/ParticipantProxyData.cpp"
    "$RTPS/src/discovery/SEDPAgent.cpp"
    "$RTPS/src/discovery/SPDPAgent.cpp"
    "$RTPS/src/ThreadPool.cpp"
    "$RTPS/src/entities/Participant.cpp"
    "$RTPS/src/entities/Domain.cpp"
    "$RTPS/src/entities/StatelessReader.cpp"
  )
  for SOURCE in "${SOURCES[@]}"; do
    NAME=$(basename "${SOURCE%.*}")
    OBJECT="$OUT/$NAME.o"
    "$SDK/bin/clang++" "${FLAGS[@]}" "${TEST_FLAGS[@]}" -std=gnu++17 -c "$SOURCE" -o "$OBJECT" > "$OUT/compile-$NAME.log" 2>&1
    OBJECTS+=("$OBJECT")
  done
fi
"$SDK/bin/clang++" "${FLAGS[@]}" -std=gnu++17 -c "$RTPS/src/storages/PBufWrapper.cpp" -o "$OUT/PBufWrapper.o" > "$OUT/compile-pbuf.log" 2>&1
OBJECTS+=("$OUT/PBufWrapper.o")
for SOURCE in common types/basic types/string types/array types/sequence; do
  OBJECT="$OUT/ucdr-${SOURCE//\//-}.o"
  "$SDK/bin/clang" "${FLAGS[@]}" -std=gnu11 -c "$RTPS/thirdparty/Micro-CDR/src/c/$SOURCE.c" -o "$OBJECT" > "$OUT/compile-ucdr-${SOURCE//\//-}.log" 2>&1
  OBJECTS+=("$OBJECT")
done
"$SDK/bin/clang++" "${FLAGS[@]}" "${OBJECTS[@]}" "$LW/public/liblwip.a" "$CMS/public/libcmsis.a" "$LW/public/libsocket_wasi_ext.a" \
  -Wl,--gc-sections,--shared-memory,--initial-memory=134217728,--max-memory=134217728,-zstack-size=6553600 \
  "${WRAPS[@]}" -Wl,-Map,"$OUT/link.map" -o "$OUT/fixture.wasm" > "$OUT/link.log" 2>&1
sha256sum "$ROOT/validation/rtps/fixture.cpp" "$ROOT/validation/rtps/projection-fixture.cpp" \
  "$ROOT/validation/rtps/native-ip-mapping.cpp" "$ROOT/validation/rtps/run-task.sh" \
  "$ROOT/mros2/CMakeLists.txt" "$ROOT/include/rtps/config.h" "$LW/src/include/lwipopts.h" \
  "$RTPS/src/communication/UdpDriver.cpp" "$RTPS/src/storages/PBufWrapper.cpp" \
  "$LW/public/liblwip.a" "$CMS/public/libcmsis.a" "$LW/public/libsocket_wasi_ext.a" "$RUNTIME" "$OUT/fixture.wasm" > "$OUT/artifacts.sha256"
git -C "$ROOT/mros2/embeddedRTPS" diff --binary | sha256sum > "$OUT/embedded-diff.sha256"
if [[ "$TASK" == T10c || "$TASK" == T10c2a ]]; then
  timeout 180s "$RUNTIME" --max-threads=16 "$OUT/fixture.wasm" "$TASK" > "$OUT/run.log" 2>&1
else
  timeout 180s "$RUNTIME" "$OUT/fixture.wasm" "$TASK" > "$OUT/run.log" 2>&1
fi
if [[ "$TASK" == T10a ]]; then
  grep -q 'T10a_SMOKE_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10b1 ]]; then
  grep -q 'T10b1_USERS_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10b2 ]]; then
  grep -q 'T10b2_MATRIX_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10b3 ]]; then
  grep -q 'T10b3_DISPATCH_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10b ]]; then
  grep -q 'T10b2_MATRIX_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10c ]]; then
  grep -q 'T10c_STARTUP_BIRTH_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10c1 ]]; then
  grep -q 'T10c1_RUNTIME_BIRTH_FAILURES_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10c6 ]]; then
  grep -q 'T10c_TYPED_INIT_FAILURES_PASS cases=6' "$OUT/run.log"
  grep -q 'T10c_LATE_AGENT_FAILURE_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10c2a ]]; then
  grep -q 'T10c2a_ACCESSOR_CONTENTION_PASS' "$OUT/run.log"
  grep -q 'T10c2a_EXPIRED_PREFIX_PASS' "$OUT/run.log"
else
  grep -q "${TASK}_PASS" "$OUT/run.log"
fi
echo "PASS $TASK artifacts=$OUT"
