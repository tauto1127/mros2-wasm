# run-32 metadata

## Scope

Phase A only; no checkpoint or restore. This is the second trial in the new `[SEDP-RACE]` series. The source instrumentation adds logs at SEDP change creation, SEDP writer progress, matched-reader registration, and SPDP builtin-proxy planning. It does not alter discovery or recovery decisions.

## Source and build provenance

| Item | Value |
|---|---|
| Root repository | `debug/recvfrom-observability`, `0842ac9782cf51c5806619c2c3af9e1467435727` |
| CMSIS-Wasm | `e5bae0901170296908996a927753a7a07a245434` |
| lwip-wasm | `5acfdb028b8d1b8ddf158671eeb7e539901ac11a` |
| nested lwIP | `e6a8415df332ee34d7af02255b2aa1e8ee74348f` |
| mROS 2 | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` |
| embeddedRTPS | `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` |
| WAMR | `2dd4eae0f301dd100e651c037ce6a3a8f56cce5e` |
| temporary source tree | `/tmp/mros2-wasm-sedp-race-20260928-run31/source` |
| temporary CMake output | `/tmp/mros2-wasm-sedp-race-20260928-run31/build` |
| Wasm app artifact | `/tmp/mros2-wasm-sedp-race-20260928-run31/app/echoback_string.wasm` |
| Wasm app SHA-256 | `9e926d0f13c9fbfcd003710c0ff01cd7c0229352a05b1efba9d0a97b2d378d46` |
| iwasm runtime SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| native peer SHA-256 | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |
| app source SHA-256 | `6c4b2e11c393abefeeb6e6649266dce00e9e6f4072c79fcd959cc33ea3433ba4` (staged app source copied as-is) |

The source diff for the diagnostic code is in `raw/SEDPAgent.patch`, `raw/SPDPAgent.patch`, `raw/StatefulWriter.patch`, and `raw/SEDPRaceTrace.h.patch`. The staged application source diff and pinned submodule list are in `raw/app-staged.diff` and `raw/submodules-commits.txt`.

The fresh archive omitted generated/untracked build inputs. In the temporary source only, the project download scripts fetched CMSIS OS headers from the `mROS-base/STM32CubeF7` `mros2` branch and lwIP OS files from `STMicroelectronics/STM32CubeF7` `v1.17.3`. The root `build.bash` also comments out `LWIP_PROVIDE_ERRNO` in the downloaded lwIP `cc.h`; this was applied only to avoid defining a non-TLS `errno` alongside WASI libc. Existing `cmsis-wasm/public` and `lwip-wasm/public` package inputs were copied into the isolated source tree; their generated import paths were redirected to that tree. These build-support inputs do not change the runtime application logic. Their hashes and the exact command lines are recorded in the raw artifacts.

The first two CMake configuration attempts and two build failures are retained in `raw/cmake-configure.log`, `raw/cmake-configure-retry.log`, `raw/build.log`, and `raw/build-retry1.log`. The final configure and build succeeded; `raw/cmake-configure-final.log` and `raw/build-retry2.log` are the successful outputs. The empty compile-only `templates-service.hpp` is recorded by hash. No existing source checkout, reference binary, or earlier run directory was changed.

## Fixed runtime conditions

| Item | Value |
|---|---|
| Docker image | `ros:humble`, `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| Docker network | `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408` |
| Wasm participant | `172.18.0.3` |
| Native peer | `172.18.0.5` |
| Run-specific state path | `/tmp/mros2-wasm-sedp-race-20260928-run32/state` |
| Checkpoint/restore | Not run |

Gate, container, artifact, network, packet, trace, and cleanup details are in `raw/`.


The instrumented source diff, source revision manifest, build inputs, and build command are reused unchanged from [run-31](../run-31/metadata.md). Their exact raw paths are listed in `raw/static-evidence-links.md`. The Wasm application, runtime, and native peer binaries are reused from run-31; this trial does not rebuild them.
