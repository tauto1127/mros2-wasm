# Task 5 build review

Date: 2026-10-04 (Asia/Tokyo)

The original build helper pointed at `/tmp/mros2-wasm-cr-rerun-20260927/wasmig-src`, which is absent. The recorded `runtime-configure-command.txt` also described `WAMR_BUILD_FAST_INTERP=1`, while the plan requires the classic interpreter with fast interpreter disabled. The actual previously used runtime binary hash matched the existing `build-cr-state-boundary-classic/iwasm`, whose CMake cache records `WAMR_BUILD_INTERP=1` and `WAMR_BUILD_FAST_INTERP=0`; that fact alone did not make the stale command record reliable.

`build.sh` now uses the pinned WASMIG source already present under the experiment's WAMR build tree and checks its commit (`c5015ee06acd3992ce826655825e1911da8c5945`). Build, runtime build, output, and provenance directories can be overridden with task-specific environment variables so verification does not overwrite existing artifacts. The fresh build used separate directories ending in `verified-20261004` and completed successfully.

The fresh runtime configure command records the planned feature family: interpreter on, fast interpreter off, AOT/JIT/fast JIT off, libc-wasi on, WASI threads on, legacy pthread off, thread manager on, and shared memory on. `compile_commands.json` confirms `netif_wasm.c` used `--target=wasm32-wasi-threads`; its object has `netif_default`, `netif_wasm`, and `ip_changed_pending`. The fresh module imports `cr_host_probe_get` and `cr_host_probe_set` from `env`.

Artifact comparison:

| Artifact | Existing trial build | Fresh verified build | Result |
|---|---|---|---|
| `iwasm` | `fa63c40c2a17f8df6461d687a95cb01bf544e0b7788377d41c317dcec6d46822` | same | byte-identical |
| native probe | `b91cdb900b478292d78a8dbfab24906bbdd3252be93b688f9c03e96c0b9121ca` | same | byte-identical |
| native peer | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` | same | byte-identical |
| Wasm module | `52ecd6ffde313c25cc6c20298769f7c9ad816419b0ddce80555c5bc2417520e0` | `2da5a6419d5741602cb50c44b8cfe7ea413383b8414462ebd81b0ef3934c48c9` | not byte-identical |

`wasm-objdump -h` reports the same Type, Import, Function, Table, Global, Export, Start, Element, DataCount, Code, and Data section offsets and sizes in both modules. The observed size difference is in `.debug_str` (+54 bytes), with later custom debug sections shifted accordingly. This supports a debug-metadata/build-path difference but does not establish whole-module byte identity. The original trial artifacts remain untouched and the trial evidence continues to refer to their recorded original hashes.

The fresh build emitted existing compiler warnings in lwIP/mROS2/WAMR sources; both Wasm and runtime builds completed successfully. Full configure/build commands, compiler version, SDK directory version, logs, object symbols, import listing, and SHA-256 values are saved beside this note.
