#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TASK=${1:?Usage: run-task.sh T01|T10a|T10b|all}
if [[ "$TASK" == all ]]; then
  "$(dirname "$0")/run-task.sh" T01
  "$(dirname "$0")/run-task.sh" T10a
  exit
fi
[[ "$TASK" == T01 || "$TASK" == T10a || "$TASK" == T10b ]] || { echo "Task not implemented: $TASK" >&2; exit 2; }
OUT="$ROOT/validation/rtps/runs/$(date -u +%Y%m%dT%H%M%S)-$TASK-$$"
mkdir -p "$OUT"
exec > >(tee "$OUT/commands.log") 2>&1
set -x
SDK=/opt/wasi-sdk-21
RUNTIME=/tmp/mros2-wasm-no-udp-recover-experiment-build-03/runtime/iwasm
EXPECTED=77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60
[[ $(sha256sum "$RUNTIME" | cut -d' ' -f1) == "$EXPECTED" ]]
LW="$ROOT/lwip-wasm"
CMS="$ROOT/cmsis-wasm"
RTPS="$ROOT/mros2/embeddedRTPS"
FLAGS=(--target=wasm32-wasi-threads --sysroot=/home/osslab/wasi-sysroot -pthread -fno-exceptions -O0 -g -ffunction-sections -fdata-sections
  -I"$ROOT/include" -I"$ROOT/mros2/include" -I"$RTPS/include" -I"$RTPS/thirdparty/Micro-CDR/include"
  -I"$LW/public/include/lwip" -I"$LW/public/include/posix" -I"$LW/public/include/system"
  -I"$LW/src/include" -I"$CMS/public/include")
OBJECTS=()
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
  -Wl,--wrap=connect,--wrap=getsockname,--wrap=pbuf_alloc,--wrap=pbuf_take_at,--wrap=ucdr_serialize_array_uint8_t \
  -Wl,-Map,"$OUT/link.map" -o "$OUT/fixture.wasm" > "$OUT/link.log" 2>&1
sha256sum "$ROOT/validation/rtps/fixture.cpp" "$ROOT/validation/rtps/projection-fixture.cpp" "$ROOT/validation/rtps/run-task.sh" \
  "$ROOT/mros2/CMakeLists.txt" "$ROOT/include/rtps/config.h" "$LW/src/include/lwipopts.h" "$RTPS/src/storages/PBufWrapper.cpp" \
  "$LW/public/liblwip.a" "$CMS/public/libcmsis.a" "$LW/public/libsocket_wasi_ext.a" "$RUNTIME" "$OUT/fixture.wasm" > "$OUT/artifacts.sha256"
git -C "$ROOT/mros2/embeddedRTPS" diff --binary | sha256sum > "$OUT/embedded-diff.sha256"
"$RUNTIME" "$OUT/fixture.wasm" "$TASK" > "$OUT/run.log" 2>&1
if [[ "$TASK" == T10a ]]; then
  grep -q 'T10a_SMOKE_PASS' "$OUT/run.log"
elif [[ "$TASK" == T10b ]]; then
  grep -q 'T10b_PREP_FAIL_PASS stage=ucdr_serialize' "$OUT/run.log"
  grep -q 'T10b_PREP_FAIL_PASS stage=pbuf_alloc' "$OUT/run.log"
  grep -q 'T10b_PREP_FAIL_PASS stage=pbuf_take_at' "$OUT/run.log"
  grep -q 'T10b_BASELINE_PASS' "$OUT/run.log"
else
  grep -q "${TASK}_PASS" "$OUT/run.log"
fi
echo "PASS $TASK artifacts=$OUT"
