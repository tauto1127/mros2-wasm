# Startup/publication repair — final repair round 2

**Disposition:** startup seam repaired and checked; ready for independent review. This is not production adoption, application-campaign acceptance, or permission to publish. No new C/R campaign was run; previous C/R evidence remains for the unchanged post-startup seam and is not represented as testing this revised startup source.

## Change

- `Participant::hasBuiltInEndpoints()` is a brief mutex-protected snapshot of the existing successful six-builtin publication flag.
- `Domain::completeInit()` starts SPDP only for participants with that publication flag. It reports false when the thread pool started but no participant was successfully published, avoiding false readiness after all slots failed.
- `SPDPAgent::start()` independently refuses calls before SPDP initialization, without a participant, or before successful builtin publication.
- Actual linked projection fixture coverage now takes all six concrete builtin mutex-init failures through `completeInit()`, tests direct incomplete `SPDP.start()`, verifies no builtin publication/SPDP running/false readiness, covers later SEDP mutex init failure after SPDP init, and verifies a healthy publication still starts.
- `run-task.sh` accepts optional `RTPS_RUNTIME` and `RTPS_RUNTIME_SHA256` for explicit immutable runtime selection; defaults retain the prior pin.

Only the startup/publication seam and its linked fixture/runner were edited. Existing surrounding implementation diffs remain unadopted and were not rewritten as part of this repair.

## Red/green and validation

- **RED:** before production fix, actual linked fixture `T10c6` failed at `projection-fixture.cpp:830` because `!spdpRunning(failed-slot)` was false after `completeInit()`. Retained at `validation/rtps/runs/20261003T002300-T10c6-2330300/run.log`; its nonzero run is intentionally preserved.
- **GREEN:** final `bash validation/rtps/run-task.sh all` passed on final sources using `/tmp/wamr-parent-restore-park-fix-20261002/build-fixed/iwasm`, SHA-256 `70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3`. Aggregate coverage: `validation/rtps/runs/20261003T003252-all-2332558/coverage.manifest` (T01, T10a, T10b1/2/3, T10c6, T10c1, T10c, T10c2a, T10c2b). T10a healthy-start assertion passed; T10c6 log records six failed builtin cases through completion and `T10c_LATE_AGENT_FAILURE_PASS`.
- The explicit runtime support was also exercised by standalone T10c6 RED and GREEN runs.
- **Three final-source clean normal builds passed** with SDK21 pthread, T11 CMake flags/dependency inputs, in new directories `validation/rtps/runs/20261003T-startup-repair2-T11-final/build-{echoback_string,service_test_add_two_int,service_server_add_two_int}`. Existing `/tmp/locks-native-T11-20261002` builds were not overwritten.
  - `echoback_string.wasm`: `b66ded95023a51022e4ebe19cca65663f83c173590dc9bef6d5cba5b27d326fc` (28 warning lines)
  - `service_test_add_two_int.wasm`: `aa10daa68fb8e058eed3d507ce7b2471a7f952c85b84354c0e319fb15926ab98` (36 warning lines)
  - `service_server_add_two_int.wasm`: `5546c2677b36f2272cf1f526b66e4a1e4c927c830246c0e92802fb3e91c5d52f` (35 warning lines)
  All three linked successfully. Warnings include existing `udp_multicast.c` format/unused-variable and `PARTICIPANT_VERBOSE` macro redefinition; logs are retained per build. Service template before/after hash manifests are identical (both manifest SHA-256 `04e500f5ce805f4d4859bbce1f0652a3bcb113b36bcfbec9a920d889582b47fd`).

## Provenance and retained evidence

- Final exact diff snapshots for root, mros2, embeddedRTPS, lwIP and WAMR plus status/HEAD and cached-diff snapshots: `validation/rtps/runs/20261003T-startup-repair2-evidence/`. Hash manifest:
  - root diff: `f76ce6c4f0cb614ccad9a623a16da670844a22a78618075dbf1d24c8d87fa0a7`
  - mros2 diff: `df36992bfcc1f3db050cbc0327ccca8010e5c37128a3ea73ca31b0114d572cbe`
  - embeddedRTPS diff: `ef8a59ed007b966e9a3cd1eaa87cac9026421c20465f3649ff326b7c2ef18e9f`
  - lwIP diff: `588c97bc4496ba803c53747a60dcab1c93678498e9a6fa0a7ace3589ad4b1fcc`
  - WAMR diff: `c747dc9f9a66b105480909bdcb807b8fc4ae004da0739fdbd888c857a51166da`
  - untracked `mros2/embeddedRTPS/include/rtps/discovery/PreparedDiscovery.h`: `09811065af93c1d84ef24face33ac05f5fa2d3ceaa5ffedafdb5fdf723b4ffd7`; copied byte-for-byte into the evidence folder. Actual include selection is recorded there.
- Runtime/compiler/dependency hashes, T11 source/config/dependency/artifact hashes, final validation hashes and service-header manifests are retained alongside those diffs and under the T11 directory. Compiler is `/opt/wasi-sdk-21`; `clang`/`clang++` SHA-256 `5aa2f1612ebc041f175cbf8cd666c9565364134d222b8170443399577548edac`; pthread toolchain file SHA-256 `a575a7bf235b349309f098ff1fe9da1ee7648bb65dc2fcc438e2a117e34ac275`.
- No files are staged in root or nested repositories. No cleanup, commit, push, Docker/network operation, adoption, or publication was performed.

## Review notes / residual limits

- Startup regression is actual linked code, not a synthetic lock/owner test. The all-failed case returns false; thread-pool lifecycle remains governed by existing Domain stop/destructor behavior.
- The application campaigns were intentionally not repeated and none are claimed against this revised startup source. No additional socket restart/recovery or container/network evidence is claimed.
- The root still contains pre-existing unrelated dirty work. See exact snapshots/status files; do not stage or treat those diffs as part of this startup repair.

## Changed files in this repair

- `mros2/embeddedRTPS/include/rtps/entities/Participant.h`
- `mros2/embeddedRTPS/src/entities/Participant.cpp`
- `mros2/embeddedRTPS/src/entities/Domain.cpp`
- `mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp`
- `validation/rtps/projection-fixture.cpp`
- `validation/rtps/run-task.sh`
