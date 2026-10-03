# Phase 0 rerun — Gate A PASS; stop before implementation

Date: 2026-10-01. Scope: repair local build prerequisites and execute only Phase0 measurement. User explicitly requested stopping after Gate A. No production coordinator, implementation worktree, commit, or push.

This report supersedes the blocked execution status in `report.md`. Earlier failed evidence remains unchanged.

## 1. Build prerequisite diagnosis and repair

**Observed:** the fresh worktree lacked `cmsis-wasm/public`, CMSIS Third_Party headers, lwIP Third_Party sources/headers and `lwip-wasm/public`. The earlier isolated root configure failed at `find_package(cmsis REQUIRED)`.

**Code-confirmed cause:** `cmsis-wasm/CMakeLists.txt` installs `cmsis-config.cmake` into `<source>/public`; root `CMakeLists.txt:59-62` adds the source subdirectory but immediately loads the installed package. Adding the subdirectory does not run install. `build.bash all` downloads Third_Party inputs and builds/installs CMSIS and lwIP before root configure; the copied isolated recipe omitted that bootstrap because its original worktree already had those packages. No generated-path mismatch was found.

**Repair:** `bash experiments/eintr-ip-refresh-phase0/setup-dependencies.sh` ran the existing download/build/install sequence inside this worktree. CMSIS and lwIP install succeeded; configure and instrumented `MODULE_echoback_string` build then succeeded. No root/submodule build-system source edits were needed. The downloaded `cc.h` compatibility adjustment matches existing `build.bash`. Generated topic templates are unchanged; all three existing service-template headers have unchanged SHA-256 values. The new successful app builds use the normal optional service include, not the historical empty shim.

Setup evidence: `setup-retry-01/console.log`, package/download hashes and build directories. Successful app command, logs, source diff and compile commands: `builds/build-04/provenance/`. Reproduction after bootstrap: `bash experiments/eintr-ip-refresh-phase0/build-app-retry.sh <fresh-index>`.

### Instrumentation issues found before the successful trials

- `smoke/same/run-01`: failed before checkpoint because the previous temporary instrumentation called unimplemented `osThreadGetId()`. Replaced ONLY measurement identity with guest `pthread_self()`, already used in CMSIS baseline. The runtime was not changed.
- `smoke/same/run-02`: pre-gate and checkpoint succeeded, but host-side image cross-check failed parsing an interleaved/truncated printf line before restore. No restore trial occurred. Its checkpoint images are retained under `runtime-build/state/experimental-run-02/` (approximately 1 GiB). Do not count it as a successful C/R or as a state-preservation failure.
- Final instrumentation formats each measurement into a bounded local buffer and emits one `write(STDERR_FILENO, ...)`, preserving errno. It logs canary/default/IP guest addresses for dump cross-check. No refresh is triggered by measurement. The host parser requires complete measurement fields. Older application/native-runtime printf lines may still interleave; complete-ID gates remain conservative and the new measurement records are complete.

The inherited mixed-line-ending normalization in `udp.c` remains a temporary diff; ignoring EOL whitespace shows only measurement additions. Nothing is carried to production.

## 2. Procedure and exact artifacts

Reused removal campaign procedure and existing isolated `mros2-cr-net` bridge (`172.18.0.0/16`): Wasm source `.3`, native echo peer `.5`; same-IP restore in source container, changed-IP restore in destination `.6` after source iwasm exited. Existing Docker image/network IDs and pinned artifact hashes were checked before each trial. Native peer remained running across each successful C/R.

Both trials used the SAME instrumented app and unchanged validated runtime:

| Artifact | SHA-256 |
| --- | --- |
| iwasm | `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60` |
| echoback_string.wasm | `c77a9ac9b0eb343e34669a4655888512981ec34e384ea277a02a53baf63911d5` |
| native peer | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |

Commands:

```sh
PHASE0_MIN_FREE_BYTES=3221225472 python3 experiments/eintr-ip-refresh-phase0/campaign.py run same experimental 3
PHASE0_MIN_FREE_BYTES=3221225472 python3 experiments/eintr-ip-refresh-phase0/campaign.py run changed experimental 3
python3 experiments/eintr-ip-refresh-phase0/analyze-gate-a.py
```

Procedure difference: available space was about 5.5 GB before retained run-02 state. The original conservative 6 GiB preflight limit was explicitly overridden to 3 GiB for sequential single-trial operation. Existing manifests show a fixed 1 GiB memory image plus <32 KiB thread/socket data. PASS state is hashed, image values extracted, then only that trial's newly created state is removed. Existing artifacts and the failed run-02 checkpoint remain. Disk preflight and effective threshold are recorded per trial. No old artifacts were deleted to make space.

Root stays `experiment/eintr-ip-refresh` at `c88b569a`; lwIP stays `experiment/eintr-ip-refresh` at `fbac6d22` with uncommitted temporary measurement. Pins remain CMSIS `182dcaff`, mros2 `912cfbdd`, embeddedRTPS `81a6a4fe`, WAMR `db205422`.

## 3. Directly observed successful C/R results

| Trial | Pre 10-consecutive-ID gate | Checkpoint max publish ID N | Post 10-consecutive-ID gate | First complete new ID | Restore command to first complete callback* |
| --- | --- | --- | --- | --- | --- |
| same-IP `smoke/same/run-03` | 35–44 PASS | 49 | 63–72 PASS | 50 | 6.179 s |
| changed-IP `smoke/changed/run-03` | 35–44 PASS | 49 | 51–60 PASS | 51 | 5.785 s |

Each complete ID requires Wasm publish, native subscription callback, native echo publish-return, and Wasm callback, with matching message body and phase/source. The first complete new ID need not begin the first ten-consecutive-ID window. *Timing is host log-collection timing, not an exact guest execution or internal convergence duration: baseline stdout buffering remains. The runner's "last stack restore log" estimate is NOT a full restore-completion timestamp; shared-memory restoration finishes later, as visible in raw logs.

### Guest state across C/R

In BOTH successful trials:

- Runtime canary starts from initializer 0 and is set during `netif_wasm_add()` to `addr ^ 0x5a17c0de = 0x5917d272` before checkpoint.
- Canary at guest address `0x9bf3c` is present in `main-memory.img` with that noninitial value and remains `0x5917d272` in all four restored receive threads and the periodic refresh thread.
- `netif_default == &netif_wasm == 0x9beb8` before checkpoint, in dumped state, and after restore. These are **guest linear-memory offsets**, not host native pointers.
- The pointer variable is at guest address `0x9beb4`; the IP field at `0x9bebc`. Dump bytes at logged guest addresses independently match canary, pointer value, and source IP. See each trial's `guest-checkpoint-state.json`.
- Same-IP: IP stays `0x030012ac` (`172.18.0.3`).
- Changed-IP: the first four restored EINTR snapshots still show source IP `.3`; the existing periodic refresh then updates to `0x060012ac` (`172.18.0.6`) while pointer/object/canary remain unchanged.
- `fallback_entries=0` throughout; no `fallback-entry` record or restore-initialization log. Thus the `netif_default == NULL` fallback did **not** execute in either successful trial. This does not establish that it can never execute in other paths.
- No restored `add-mutated`/`recv-start` records: these threads continued restored execution rather than re-running initialization.

### Guest EINTR fan-out

Exactly four receive threads/four guest fd handles reported EINTR once each per successful checkpoint. The same thread/fd pairs existed at receive startup with count 0. No guest receive EINTR was logged on the source before checkpoint; the preserved interrupted receive continuation reached its guest handler after restore. These guest `pthread_self()` descriptor addresses are **not host OS tids**.

| Guest pthread identity | same-IP guest fd/count | changed-IP guest fd/count |
| --- | --- | --- |
| `0x13fe194` | 4 / 1 | 6 / 1 |
| `0x1a4e434` | 7 / 1 | 7 / 1 |
| `0x209e7d4` | 14 / 1 | 3 / 1 |
| `0x26eea74` | 12 / 1 | 10 / 1 |
| **Total** | **4 EINTRs** | **4 EINTRs** |

Restore log lines 548–551 contain the four complete EINTR/state snapshots in each successful trial; lines 552–553 show the first periodic refresh entry/exit. Total across these TWO successful C/R trials: 8 guest receive EINTRs. Do not generalize four to every application/checkpoint: only receives blocked at checkpoint are expected to fan out this way.

### Existing periodic refresh, not a coordinator

No EINTR-triggered refresh was implemented. All measured refreshes are from existing thread `0x4c7fd64`, distinct from all recv threads.

| Observation interval | same-IP | changed-IP |
| --- | --- | --- |
| Periodic refresh before checkpoint | 49 entry/exit pairs, same IP | 49 entry/exit pairs, same IP |
| Restore through cleanup | 28 entry/exit pairs: 28 same | 14 entry/exit pairs: 1 changed, 13 same |
| EINTR-triggered refresh | 0 | 0 |
| Atomic overlap skip | N/A: no coordinator | N/A: no coordinator |

Intervals differ because the first ten-consecutive post-ID window occurs at different times; these counts are not one-refresh-per-checkpoint metrics and are not sequential duplicate EINTR probes. No failed refresh was observed in these paired intervals. No socket recreation path was added; `udp_mc_recover` runtime source references remain zero.

**Important source-context correction:** the actual app config is root `include/rtps/config.h:77`, `SPDP_RESEND_PERIOD_MS = 1000`, not desktop config's 10000. `compile_commands.json` places root include before embeddedRTPS includes. The approximately one-second post-restore refresh records agree. The plan's desktop-ten-second statement must not be used to explain THIS tested configuration. No config was changed.

## 4. Code-confirmed WAMR behavior and interpretation

- Object symbol inspection (`build-provenance/netif-guest-symbols.txt`) identifies C guest data symbols `netif_wasm`, `netif_default`, canary and pending state. Main memory dump byte cross-check establishes the observed data's concrete guest-memory placement.
- Active reused runtime hash also matches `/tmp/mros2-wasm-no-udp-recover-experiment-build-03/{runtime,wamr-build}/iwasm`. Cached CMake/compile definitions show classic interpreter (`WASM_ENABLE_FAST_INTERP=0`), migration, shared memory, thread manager, libc-WASI and WASI-threads enabled; see `build-provenance/runtime/`.
- `wasm_dump_classic.c:275-287` dumps shared linear-memory bytes; `wasm_restore_classic.c:356-368` copies them back. `wasm_restore_classic.c:442-455` restores shared memory on main, then globals; `wasm_interp_classic.c:1625-1684` restores thread stack/PC and uses a post-restore barrier.
- `wasm_thread_migration.c:27-33` sets checkpoint signals and wakes blocking operations. `thread_manager.c:965-999` describes syscall EINTR returning execution to interpreter checkpoint handling.

**Inference supported by code + observations:** a shared coordinator's data can be guest static storage in `netif_wasm.c`, rather than a host native global. Runtime-mutated shared linear-memory state survives these C/Rs; an actual atomic object's stored bit would be expected to be restored, not automatically reset. The four restored EINTR handlers fit the interrupted-call continuation/checkpoint/barrier mechanism.

This is NOT proof of a production atomic critical section's correctness, C11 lowering/execution, failure-release behavior, or checkpoint-while-claimed owner liveness. No atomic coordinator existed in these trials. A set flag should not be blindly reset at restore; ownership/continuation semantics need review with the actual design. The existing comment asserting netif guest globals are recreated from scratch is contradicted for these tested paths; it was not edited during Phase0.

## 5. Gate A decision and explicit stopping point

**Gate A: PASS for Phase0 shared-state/fan-out prerequisites within the tested same-host scope.**

Rationale:

1. A concrete guest shared-state location is demonstrated by symbols, dumped bytes and observations in five distinct guest threads.
2. Noninitial runtime state, guest object identity and initialized default pointer survive both C/Rs.
3. Fan-out is measured: four recv threads/four guest fds, one EINTR each, in each successful trial.
4. Restore begins with `netif_default` non-NULL and source IP; NULL fallback is not needed/executed here. Changed IP is subsequently detected by the unchanged periodic path.
5. WAMR's current classic shared-memory/thread restoration mechanism agrees with these observations. Adding shared coordinator state is supported as a design candidate, not approved as an implementation.

**Stop here as requested.** No post-Gate design revision or implementation was performed in this request. The prior source-review blocker (recv-only guard does not serialize SPDP; pending read/clear and failure consumption need review) remains separate. Gate A PASS does not clear Gate Review. No generation, barrier, condition wait, SPDP wake, actual ROS socket probing, or recreation was added.

Evidence paths:

- `gate-a-summary.json`; derived per-trial `phase0-observations.json`.
- `analyze-gate-a.py` asserts canary/dump/pointer preservation, fd/thread sets, counts, fallback, IP transition and app gates.
- `smoke/{same,changed}/run-03/`: raw Wasm/peer logs, result, image-byte cross-check, state file/hash manifest, Docker identity/topology/commands, artifact hashes and cleanup records.
- `setup-retry-01/` and `builds/build-04/provenance/`: repair/build/source provenance.

Final safety: no staged changes, no commits/pushes; baseline pins unchanged. All experiment containers removed, original Docker network preserved with no attachments. Successful state payloads removed only after observation/hash/manifest; failed run-02 state retained. Service header hashes unchanged. Phase1 and its repeated/no-C/R/three-target validation were deliberately not started.
