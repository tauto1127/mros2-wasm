# Restore park/resume race repair (2026-10-02)

Operator requested the repair after parent direct inspection. Parent only; no subagent used. This repair is in WAMR, not the approved lwIP/RTPS projection transaction.

## Change

- `third_party/wamr/core/iwasm/libraries/thread-mgr/thread_manager.{c,h}` adds `wasm_cluster_thread_continue_if_stopped`: under the existing exec-env wait lock, check STOP, clear signal, set RUNNING and signal. A not-yet-parked thread returns false without touching status or signal.
- `third_party/wamr/core/iwasm/interpreter/wasm_interp_classic.c` retries that conditional continuation for each saved waiter before waiting for atomic.wait reconstruction. It no longer sends a continuation that a later initial STOP could overwrite.
- Existing unconditional continuation and final nonwaiter release semantics are unchanged. No new lock/event, RTPS socket changes, instrumentation or live-process edits.

## Regression

`validation/runtime/test_restore_park.py` compiles exact extracted production wait/continue functions against real POSIX mutexes/condition variables and minimal type/debug shims. It delays a child until after the first continuation attempt; thus the old sequence deterministically loses the notification. It verifies that early conditional continuation preserves status/signal, parked continuation clears the signal and resumes the child, and a second continuation is rejected. The interpreter call site is also checked. This is an isolated function-level race regression, not a fully linked runtime or application C/R acceptance test.

```sh
python3 validation/runtime/test_restore_park.py --legacy
# RED: early resume lost; restored child stays STOP (exit 1)
python3 validation/runtime/test_restore_park.py
# GREEN: 50 delayed restore parks resumed without lost wakeups (exit 0)
```

## Build and preserved evidence

New runtime: `/tmp/wamr-parent-restore-park-fix-20261002/build-fixed/iwasm`.
SHA256: `70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3`.
WAMR base remains `db2054224dcff9686f3f98850a29c554974096bc`; three-file uncommitted diff. Build manifest and red/green/raw build logs are under `/tmp/wamr-parent-restore-park-fix-20261002/`.

A private source mirror reproduces the old runtime build's CMake out-of-tree `add_subdirectory` binary-directory workaround. Repository migration.cmake unchanged. The old build's clean wasmig source commit `c5015ee06acd3992ce826655825e1911da8c5945` was reused. System cargo 1.75 could not parse lockfile v4; installed cargo 1.97.1 was selected through build-local PATH only. Both initial build failures are preserved. Release/classic-interpreter/WASI-threads build completed successfully; the three changed compiled source files hash-match the repository.

Old runtime, failed checkpoint image, failed restored app and continuous peer remain untouched. No commit or push. New runtime has not replaced campaign pins.

## Remaining acceptance

Actual restored application communication has NOT been retested with this runtime. SAME remains NOT PASS, and changed/repeated campaigns remain unaccepted. The existing diagnostic is non-invasive; its failure may have further causes beyond this isolated lost-resume race. Final independent review/parent adoption/publication gates remain pending.
