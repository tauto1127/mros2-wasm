# Runner adjustments from run-04 and run-06

Recorded before the trials. The life-wiki file `llm-context/working/mros2-wasm-cr-validation-planning.md` was absent on 2026-09-28 and was not recreated. Current position was taken from `llm-context/working/mros2-wasm-network-migration.md` and `llm-context/wiki/pages/mros2-wasm-migration.md`. life-wiki was read only.

## Worktree

- New worktree: `/home/osslab/mros2-wasm-cr-validation-182dcaf`
- New branch: `validate/cmsis-timeout-cr-20260928`
- Parent commit: `7b632868ed9859dc152bc87a23c98d4afff43837`
- The existing `debug/recvfrom-observability` worktree was not reset, cleaned, or built.
- `cmsis-wasm` `182dcaf` is not on the GitHub remote this machine fetched (`upload-pack: not our ref`). Submodules were checked out from local objects already present in the existing submodule git directories. Those working trees were left at their previous commits.

Recorded submodule commits:

| path | commit |
|---|---|
| cmsis-wasm | `182dcaff50a0e9c626c84db365b1d762747a806b` |
| lwip-wasm | `78ef9fc33842bece9ad9a83c1cd0a448b779d64e` |
| mros2 | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` |
| mros2/embeddedRTPS | `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` |
| third_party/wamr | `db2054224dcff9686f3f98850a29c554974096bc` |

## Build deviations required to compile the recorded tree

- `third_party/wamr/core/iwasm/migration/migration.cmake`: `add_subdirectory` now passes `${wasmig_BINARY_DIR}`. FetchContent's wasmig source is outside the WAMR source tree, and CMake rejects `add_subdirectory` without a binary directory in that case. This does not change checkpoint, restore, timeout, or communication behavior.
- wasmig is the existing local checkout `c5015ee06acd3992ce826655825e1911da8c5945` via `FETCHCONTENT_SOURCE_DIR_WASMIG`, not a new fetch of floating `main`.
- `mros2/src/mros2.cpp` includes `templates-service.hpp`. echoback has no services, so an empty header is placed only in the isolated build include directory.
- lwIP's downloaded `cc.h` gets the same `LWIP_PROVIDE_ERRNO` comment-out that `build.bash` applies, so errno comes from the WASI sysroot.
- Cartographer and zlib are not checked out. The app target does not compile them.
- Native peer binary is the existing run-04 executable `/tmp/mros2-posix-run04-final-build/mros2-posix`, SHA-256 `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`. It is mounted read-only. Wasm and iwasm are new isolated builds and are not the run-04/run-06 artifacts.
- Nested `lwip` commit recorded by lwip-wasm is `e6a8415df332ee34d7af02255b2aa1e8ee74348f` (lwIP 2.1.0). It was checked out from local objects.
- System Cargo 1.75 cannot parse wasmig's Cargo.lock version 4. The build used Cargo 1.97.1 from `~/.cargo/bin`. wasmig `c5015ee` was copied into the isolated build directory so the shared checkout was not modified.
- A no-checkpoint log probe on 172.18.0.3 saw `mros2-posix start!` in the first output lines, and the netif log showed `172.18.0.3`. No `app.cpp` flush change was added. Probe containers were removed.

## Gate and timing changes

Copied behavior that is kept:

- Docker network `mros2-cr-net` (`609362e37c7a…`, `172.18.0.0/16`) is reused and never deleted.
- Image `ros:humble` ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`.
- same-IP restores in the same `172.18.0.3` container. changed-IP checkpoints on `.3` and restores in a new `.6` container with the same state mount. Peer stays on `.5`.
- iwasm argv: `--addr-pool=0.0.0.0/0 --max-threads=32 -v=5` plus `--restore` only on restore. Working directory is the trial state directory.
- Checkpoint signal is `SIGUSR2` to the verified iwasm PID.
- Each trial has its own container names, Docker label, log directory, and state directory. Trials are sequential.
- Cleanup removes only that trial's labeled containers. Checkpoint state is not committed.

Changes from run-04/run-06:

- No 30-second no-C/R baseline.
- The 60-second pre-C/R gate and 90-second post-C/R gate are not success deadlines.
- Pre-checkpoint success is the first moment when 10 consecutive publish IDs each have a full round trip: Wasm publish, native peer receive, peer echo return, Wasm subscriber callback, same ID and body `Hello from mros2-posix onto Linux: <id>`. Cumulative distinct IDs are not enough. `SIGUSR2` is sent immediately after that observation.
- `N` is the maximum Wasm publish ID observed in the checkpoint process, including publishes between the 10th callback and process exit. Post-restore PASS requires 10 new consecutive IDs all greater than `N`. Callbacks for IDs `<= N` do not count.
- IDs are parsed from the clean-line message text (`publishing msg` / `subscribed msg`). Peer lines stay in the run-04 native-peer format.
- Host `time.monotonic_ns()` is the primary clock. UTC is stored on the same lines for cross-check.
- Checkpoint interval ends at normal process exit when `main-memory.img` and `main-socket.img` are present. SHA-256 of the state is timed separately and is not part of that interval.
- Restore-stage completion is estimated only from `Finish to restore stack` lines that occur before the first application line. `SOCKET_JOURNAL restore_end` is not required. If that point cannot be separated from resumed execution, the interval is recorded as missing. Stopping iwasm later is not the restore completion time.
- Recovery interval is restore command start to the Wasm callback of the first new fully completed ID.
- Operator stall rule, not a pass/fail timeout: if the consecutive complete run does not grow for 300 seconds, the trial is `UNRESOLVED` with the elapsed time and is not a PASS. There is no automatic retry. Process death, a non-zero checkpoint exit, or a missing memory/socket image is `FAIL`. A pre-checkpoint stall or an environment/hash/network conflict is `STOP` and does not send `SIGUSR2`.
- One same-IP non-PASS stops the campaign before changed-IP.
- Successful trials do not start a packet capture. Failed trials keep their state. After a PASS, the manifest and hashes are checked, the state path is checked to be exactly `/tmp/mros2-wasm-cr-validation-182dcaf/state/<trial-id>`, and only then is that directory removed. A trial is not started when `/tmp` has less than 6 GiB free, so the about-1 GiB image still leaves the historical 4 GiB floor.

## Scripts

`campaign.py` is the adapted runner. It absorbs the container, signal, log, and gate roles of `run06_setup.py`, `run06_wasm.py`, `run06_peer.py`, `run-04/roundtrip_gate.py`, `run-04/postcr_gate.py`, and `run-04/send_checkpoint_signal.py`. Those files were read and not modified.
