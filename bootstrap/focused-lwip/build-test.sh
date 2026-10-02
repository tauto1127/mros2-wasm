#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl
SDK=/opt/wasi-sdk-21
WASI=/home/osslab/wasi-sysroot
LW=$ROOT/lwip-wasm
CMS=$ROOT/cmsis-wasm
WAMR=$ROOT/third_party/wamr
OUT=$ROOT/bootstrap/focused-lwip
"$SDK/bin/clang" --target=wasm32-wasi-threads --sysroot="$WASI" -pthread -std=gnu11 -O0 -g -ffunction-sections -fdata-sections \
  -I"$LW/Third_Party/STM32CubeF7/Middlewares/Third_Party/LwIP/system" \
  -I"$LW/src/include" -I"$LW/src/core" -I"$LW/src/netif" \
  -I"$LW/lwip/src/include" -I"$CMS/public/include" \
  -I"$CMS/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2" \
  -I"$WAMR/core/iwasm/libraries/lib-socket/inc" \
  -include "$OUT/hooks.h" \
  -DLWIP_NETIF_SOCKET=test_netif_socket -DLWIP_NETIF_CONNECT=test_netif_connect \
  -DLWIP_NETIF_GETSOCKNAME=test_netif_getsockname -DLWIP_NETIF_CLOSE=test_netif_close \
  -DLWIP_CORE_MUTEX_TRYLOCK=test_core_trylock -DLWIP_UDP_RECVFROM=test_udp_recvfrom \
  -DLWIP_UDP_TEST -DCMSIS_LOG_DISABLE_INFO \
  "$OUT/focused_lwip_test.c" "$LW/src/netif/netif_wasm.c" "$LW/src/core/lwip.c" "$LW/src/core/udp.c" "$LW/src/core/sys_utils.c" \
  -Wl,--gc-sections,--import-memory,--export-memory,--shared-memory,--initial-memory=134217728,--max-memory=134217728,-zstack-size=6553600 \
  -o "$OUT/focused_lwip_test.wasm"
