# 実験metadata

実行前後の値を推測せず記録する。未確認欄は空欄のままにし、開始ゲートへ進まない。

## 計画・レビュー

- 計画: [`../../plan.md`](../../plan.md)
- Sol review: **APPROVE**（2026-09-27、build再開条件・collector・lwIP build方式・compile-only header・最終pre-runtime確認）
- Run ID: `run-01`
- Run tag: `[CR-RERUN-20260927]`

## 固定条件と実測値

| 項目 | 実測値 |
|---|---|
| 準備開始UTC | `2026-09-27T03:55:49.641Z`（初回peer helper起動。API不一致で停止し、計測には含めない） |
| C/R計測開始UTC（Wasm起動試行） | `2026-09-27T04:04:35.892Z` |
| 実験終了UTC（Wasm process exit） | `2026-09-27T04:07:44.428Z` |
| root repo branch / HEAD | `debug/recvfrom-observability` / `0842ac9782cf51c5806619c2c3af9e1467435727` |
| mROS 2 / embeddedRTPS commit | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` / `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` |
| lwip-wasm commit | `5acfdb028b8d1b8ddf158671eeb7e539901ac11a` |
| WAMR commit | `2dd4eae0f301dd100e651c037ce6a3a8f56cce5e` |
| pre-instrumentation iwasm SHA-256 | `fa91868a8450b3e56e15cc5514b35d50a25d3b72650cb9d6ccba9ddc5f1f845e` |
| pre-instrumentation Wasm SHA-256 | `237a115984c21bccf6dcfe7ad8013d53bdde2bc6ab1533759f9b89ea394d01d0` |
| instrumented iwasm SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| instrumented Wasm SHA-256 | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| temporary build root | `/tmp/mros2-wasm-cr-rerun-20260927` |
| temporary WAMR build dir / Wasmig source copy revision | `/tmp/mros2-wasm-cr-rerun-20260927/wamr-build`; source copy `/tmp/mros2-wasm-cr-rerun-20260927/wasmig-src` at `c5015ee06acd3992ce826655825e1911da8c5945` |
| runtime artifact directory | `/tmp/mros2-wasm-cr-rerun-20260927/runtime` |
| Wasm artifact directory | `/tmp/mros2-wasm-cr-rerun-20260927/app` |
| WAMR CMake command / cache options | Plan A0; Release, X86_64/linux, interpreter=ON, AOT/fast-interp=OFF, libc builtin/WASI=ON, WAMR pthread=OFF, WASI threads/ref-types/shared-memory/thread-manager=ON, tests=OFF; out-of-source configure and `iwasm` build succeeded |
| modified lwIP source build path | `/tmp/mros2-wasm-cr-rerun-20260927/wasm-build/lwip-wasm/CMakeFiles/lwip.dir/src/core/udp.c.obj`; no standalone install |
| Wasm CMake command / target | Plan A0; `/tmp/mros2-wasm-cr-rerun-20260927/wasm-build`, `echoback_string`, WASI SDK 21, sysroot `/home/osslab/wasi-sysroot`, `CMAKE_CXX_FLAGS=-I/tmp/mros2-wasm-cr-rerun-20260927/wasm-build/experiment-includes`; `MODULE_echoback_string` succeeded |
| temporary empty `templates-service.hpp` path / SHA-256 | `/tmp/mros2-wasm-cr-rerun-20260927/wasm-build/experiment-includes/templates-service.hpp` / `ea8c1707a0ed2cb7a5b7eecd3a7e9b38b5e6392b098762b6e3d64d6ea03163ef` |
| `ros:humble` image ID | `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| Docker network ID / options | `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, bridge `172.18.0.0/16`, gateway `172.18.0.1`, `Internal=false`; active run containers at `.3` and `.5`, see `raw/network-pre-wasm.json` |
| peer container ID / IP / PID | `81457edde284e5d6067c6cbb263554b717e0ef8fd1249c648a896a752673367a` / `172.18.0.5` / container PID 1, host PID `1536893`; restarted with corrected helper at `2026-09-27T03:59:06Z` |
| WAMR runner container ID / IP / PID | `8b1fd029f81aa13d7de279779e0a669466620067e7fa2d3fabf4ea0000068f91` / `172.18.0.3` / container PID 1 `sleep infinity`, host PID `1534329` |
| Wasm netif IP / netmask / route | netif runtime log: `172.18.0.3` / `255.255.255.0` (`mask=0x00ffffff`); Docker bridge/container route: `172.18.0.0/16` via `172.18.0.1`（差異あり。原因とは未断定） |
| host run directory | `/home/osslab/mros2-wasm-service-communication-socket-journal/experiments/socket-journal-cr/2026-09-27/runs/run-01` |
| host checkpoint image directory | `/tmp/mros2-wasm-cr-rerun-20260927/state` (confirmed absent, then created empty before container startup) |
| iwasm build command and CMake options | `rtk cmake --build /tmp/mros2-wasm-cr-rerun-20260927/wamr-build --target iwasm --parallel 4`; Release; details above and in plan A0 |
| Wasm build command and CMake options | `rtk cmake --build /tmp/mros2-wasm-cr-rerun-20260927/wasm-build --target MODULE_echoback_string --parallel 4`; WASI SDK 21; debug (`-g -O0`); details in plan A0 |
| modified source paths and diff hash | root app `5bb86392791752710be24e54cbda5c3dcf111bb936c9432f564d5df82bc6a782`; lwIP `be8bd3459173668d9efd09ff6347814d1f40369d1f5a18eb4410bdc04c0f7f74`; embeddedRTPS `6f28b3678d86a8e4f3082ecc861ca4d4e7351947287c0181861e0bb72f34c84f`; WAMR `d0be261799f33ef0b110660e590209b6f28b4c0ea6fdf6823c455c6f91760081` |
| checkpoint argv | `/runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 /artifact/echoback_string.wasm` |
| restore argv | `/runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 --restore /artifact/echoback_string.wasm` |
| checkpoint起動試行 PID / start / exit / status | container PID `56`; `04:04:35.892Z`開始、`04:07:44.428Z`終了、SIGTERM、exit status `143`。`SIGUSR2`は未送信のためcheckpoint／journal dumpなし。`raw/wasm-checkpoint.status` |
| restore PID / start / cleanup / exit / status | 未実行。`--restore`起動・journal replayなし |

## Build observations

- Full configure/build output is appended to [`raw/build.log`](raw/build.log). The failed configure/build attempts are retained before the successful retry.
- WAMR's first configure failed because its external WASMIG source had no explicit CMake binary directory. The build-only source fix is in `third_party/wamr/core/iwasm/migration/migration.cmake`; its output remains under the temporary WAMR build directory.
- The first Wasm compile found `inet_ntoa()` unavailable in the WASI SDK. The UDP destination log now formats the IPv4 octets directly; the second compile found mROS 2's unconditional `templates-service.hpp` include, satisfied by the hashed empty compile-only header listed above. The final app build succeeded.
- The app out-of-source build compiled the modified `lwip-wasm/src/core/udp.c` directly. Existing `lwip-wasm/cmake_build`, `lwip-wasm/public`, root `cmake_build`, and the 880 MB WAMR `build_socket_journal` were not rebuilt or installed into.
- The first peer process exited on its initial graph snapshot because rclpy Humble exposes `count_publishers()` / `count_subscribers()`, not the initially used `get_publisher_count()` / `get_subscription_count()`. The complete failed-attempt stderr/stdout is preserved in [`raw/ros-peer-first-attempt.log`](raw/ros-peer-first-attempt.log); the helper method names were corrected before starting Wasm. A no-network ROS image introspection confirmed the rclpy API.
- Restarted peer PID 1 remains alive and reports only its own `/to_linux` subscription and `/to_stm` publisher before Wasm starts; snapshots are in `raw/ros-peer-pre-wasm.log`. Both assigned addresses `.3` and `.5` joined the expected `/16` network. The image has no `ip` executable, so exact route table text is captured from `/proc/net/route` in `raw/*-pre-wasm-route.txt`; Docker inspect supplies each interface IP/prefix.

## C/R前ゲートと境界値

| 項目 | 値 / raw log参照 |
|---|---|
| endpoint match成立時刻 | 成立せず。peerの全558 graph snapshotsにWasm endpointなし |
| `/to_linux` peer graph endpoint count / GIDs | publisher `0`、subscription `1`（peer自身のGID `010f06410100ffff00000000000012040000000000000000`）。Wasm publisherなし |
| `/to_stm` peer graph endpoint count / GIDs | publisher `1`（peer自身のGID `010f06410100ffff00000000000011030000000000000000`）、subscription `0`。Wasm subscriberなし |
| 60秒ゲート内 Wasm `/to_linux` publish_return数 | `59` |
| 60秒ゲート内 peer receive / echo数 | `0` / `0` |
| 60秒ゲート内 Wasm `/to_stm` callback数 | `0` |
| 60秒ゲート内RTPS DATA parse／Reader配送ログ数 | `42`（アプリmessage往復数には算入しない） |
| 実際のWasm終了時刻 / 起動からの経過 | `04:07:44.428Z` / 約`188.5秒`。計画上の60秒期限を超過。期限後の延長観測をゲート判定に使わない |
| 30秒無C/R観測の開始・終了時刻 | 未実施（C/R前ゲート不通過） |
| 無C/R区間の往復ID数 | 未実施 |
| SIGUSR2時刻 / iwasm PID | 未送信 / PID `56`はSIGTERM終了 |
| `N`（signal直前までの最大publish開始ID） | 該当なし（SIGUSR2未送信） |
| checkpoint journal path / size / SHA-256 | 未作成。host state directoryは空 |
| dump operation数 / overflow | 該当なし |

## restore後の結果

| 項目 | 値 / raw log参照 |
|---|---|
| restore完了時刻 | 未実行 |
| journal replay数 / 成功 / fallback / failure | 未実行 |
| restore後endpoint match時刻 | 未実行 |
| restore後にpeer受信した`ID > N`の数 | 未実行 |
| restore後にWasm callbackまで戻った`ID > N`の数 | 未実行 |
| 重複・遅着・欠番 | 未実行 |
| 最後に通った境界 | RTPS DATA parse／internal Readerの`newChange`ログまで。app callback、peer receive／echoは0 |
| 判定（成功 / C/R失敗 / gate stop） | **gate stop**。C/Rを開始していない |
