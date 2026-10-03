# EINTR IP-refresh Phase 0 checkpoint — BLOCKED (historical)

**Superseded execution status:** the authorized Phase0-only rerun repaired setup and passed Gate A. See [gate-a-report.md](gate-a-report.md) and `gate-a-summary.json`. The failure evidence and preliminary design notes below are retained; Gate Review/Phase1 remain unapproved.

Date: 2026-10-01. No production implementation, staging, commits, or pushes.

## Execution and source provenance

Worktree: `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh`.
Root `experiment/eintr-ip-refresh` at `c88b569a567529c5c49cb64e698c8cbdea987206`.
lwip `experiment/eintr-ip-refresh` at `fbac6d22cd08d12fccfc27c4efa383a8be32335f`, with temporary uncommitted instrumentation.
Pins confirmed: cmsis `182dcaff`, mros2 `912cfbdd`, embeddedRTPS `81a6a4fe`, WAMR `db205422`.

The requested `/home/takuto1127/life-wiki` is absent on this host. `/tmp/life-wiki` is outdated and lacks the required plan/index. Mandatory current documents were fetched read-only from `tauto1127/life-wiki` at `50efbc27980027d68ec824891abfd2f1b9a72be5` into `context/life-wiki/` here; no canonical wiki was modified. The remote research SSH host's ED25519 fingerprint matches this machine's host key; no SSH trust configuration was changed.

## Direct execution evidence

- Attempt: `bash experiments/eintr-ip-refresh-phase0/build-isolated.sh 01`.
- CMake configuration failed before application compilation: `cmsisConfig.cmake` / `cmsis-config.cmake` missing; `cmsis-wasm/public` does not exist. See `build-console.log` and `builds/build-01/provenance/configure.log`.
- The copied isolated recipe assumes preinstalled submodule packages. Ordinary `build.bash all` has dependency download/build/install steps preceding root configuration; those steps were not executed in this attempt. This is a missing setup prerequisite, not evidence of a source regression. The copied recipe also retains a historical no-service include shim; the baseline now has the optional service-template include fix. No source service headers were changed.
- No same-IP or changed-IP C/R trial ran. No application/runtime artifact was produced by this attempt; no trial hashes, round trips, canary survival, pointers, fallback entry behavior, EINTR fan-out or refresh/skip counts were measured. Do not report these as zero, PASS, or disproved.
- Native child infrastructure also failed with `model_verification_failed`: launch candidate `openai-codex/gpt-6-luna:low`, observed response model `gpt-6.1-sol`. Workflow `80674e5e-68cd-4c2e-9068-69ad0a1e86b8`, Phase0 child `de7d06f9-9c77-494b-bc26-35b45872e04d`. Workflow is terminal, with one failed experiment child and one completed source-analysis child. No model alias configuration was changed and no execution-mode fallback was taken.

## Gate A

**BLOCKED / not adjudicated.** There is no experimental evidence with which to accept or reject guest-state survival, restore-side netif pointers/IP, fallback behavior, or EINTR fan-out. An atomic coordinator is not authorized by this Gate.

## Code-confirmed facts (not experimental observations)

Baseline source locations below refer to pinned source before temporary instrumentation.

1. `lwip-wasm/src/netif/netif_wasm.c:14-16` defines guest C static/global state. `netif_wasm_refresh()` probes first, then updates netif state and sets a plain `ip_changed_pending` integer. `netif_wasm_take_ip_changed():120-124` uses a non-atomic read/clear.
2. `SPDPAgent.cpp:79-101` calls refresh under `TcpipCoreLock`, but takes pending outside that lock and before checking refresh failure. `runBroadcast():108-126` calls this periodically. The current UDP EINTR branch retries receive without refresh. A new recv-only atomic guard would not serialize SPDP against recv refresh calls.
3. WAMR classic dump writes linear-memory bytes (`wasm_dump_classic.c:275-287`) separately from explicit Wasm globals (`:291-321`). Classic restore copies linear memory (`wasm_restore_classic.c:356-368`); only main restores shared memory, followed by per-thread global/stack/PC restoration and a post-restore barrier (`wasm_restore_classic.c:442-455`, `wasm_interp_classic.c:1625-1684`). This does not support the netif comment's blanket assertion that guest C globals are reset on restore.
4. Checkpoint code signals and wakes blocked syscall threads (`wasm_thread_migration.c:27-33`, `thread_manager.c:965-999`). The source explicitly describes syscall EINTR returning execution to interpreter checkpoint handling. Which UDP threads/fds actually do this in these requested trials is unmeasured.
5. The selected `/opt/wasi-sdk-21/share/cmake/wasi-sdk-pthread.cmake` sets target `wasm32-wasi-threads`, `-pthread`, and imported/exported memory. WAMR classic interpreter has an atomic-opcode path gated on `WASM_ENABLE_SHARED_MEMORY` (`wasm_interp_classic.c:3987` and following). Exact C11 atomic lowering, actual runtime configuration and execution remain unvalidated; absence of flags in root CMake alone is not proof of missing atomic support.

## Preliminary plan review and minimal revised plan proposal

This is source-based pre-review, NOT the requested post-Gate-A experimental design acceptance. **BLOCK original recv-only placement.** Do not start Phase1 without completing Phase0 and reviewing this revision.

- Put the one-at-a-time refresh guard in the common `netif_wasm_refresh()` primitive, private to `netif_wasm.c`, so periodic SPDP and recv EINTR both participate. Protect the whole probe/update interval and release on every claimed path, including failure and fallback. Keep initialization's startup-only assumption explicit; if runtime `netif_wasm_add()` remains callable, it must not bypass the exclusion invariant.
- Define a nonblocking skipped outcome distinguishable for logging from an executed same-IP result; audit the existing integer return contract and every caller before changing it. Losers continue receiving without a wait/barrier. Strict one-refresh-per-checkpoint is not an initial invariant.
- Make pending production/consumption race-safe, e.g. an atomic store/exchange with defined ordering, not the current plain load/clear. Do not clear pending on a failed periodic probe: `refreshLocalIp()` must check failure before consuming, or use another explicitly justified contract. A shared refresh guard does not itself protect the consumer outside it. Preserve eventual locator/participant refresh when a receive-side probe changes IP.
- Audit netif readers and existing core-lock coverage separately: writer/probe exclusion alone is not a proof of whole-netif read/write synchronization. The current stale-IP window is not generally safe by assertion; any accepted limitation must name the tested same-host scope and validation evidence.
- Verify C11 CAS/release and pending exchange using the exact WASI toolchain, shared module and runtime. Avoid changing the toolchain merely to make the experiment pass.
- Do not reset an in-progress guard on restore without justification. Restored linear memory may contain true, but the owner thread's stack/PC is also restored. Code inspection does NOT establish that the owner is lost or that the flag necessarily becomes stuck. Check owner continuation, native probe error cleanup and release semantics, ideally with a separately labeled checkpoint-during-owner experiment after the Phase0 prerequisites. A generation/owner-repair mechanism is not yet established necessary.
- Leave generation-based sequential duplicate suppression and SPDP immediate wake deferred. Measure refreshes per checkpoint and time until locator convergence. Reuse existing periodic propagation; do not switch to a request/consumer architecture without an approved design change.

Source-analysis child suggestions that treated flag=true as necessarily losing the owner, or required generation/coalesced requests immediately, were not accepted as established findings. They lack a demonstrated failure in this restore path.

## Remaining work / safe resumption

1. Resolve the native model verification problem through an explicitly verified mapping or an owner-approved same-protocol launch. Do not invent an alias or silently change execution mode.
2. Prepare dependency packages using the validated worktree-local normal setup sequence; no other checkout should be modified. Review the current script before rerunning.
3. Review instrumentation first. `udp.c` was unintentionally normalized from mixed line endings: raw diff is 382 insertions/373 deletions; ignoring end-of-line whitespace reveals nine intended inserted lines. `netif_wasm.c` has 21 intended insertions. The partial diff is preserved in `evidence/instrumentation.patch` and build provenance; do not carry it into production. Instrumentation is not compile-validated.
4. Execute same-IP and changed-IP .3->.6 with raw state/EINTR and application pre/post evidence, decide Gate A, then review the revised common-primitive design. Only after both Gates pass create the clean Phase1 worktree from the specified baseline.
5. If Phase1 is reached, perform same/changed/repeated/no-C/R and normal builds for all three requested apps; retain service-header hashes and per-checkpoint refresh/skip metrics.

## Final requested status summary

- Phase0 experiments: not run; configuration and native-run infrastructure blocked.
- Gate A: BLOCKED, no empirical verdict.
- Plan review: preliminary source-only BLOCK of recv-only guard; completed experimental review deferred.
- Plan change: common refresh primitive and race-safe pending/failure semantics proposed; canonical plan unchanged.
- Phase1: not entered; no implementation worktree/branch/commit created.
- Validation: same-IP, changed-IP, repeated, no-C/R and three normal target builds not completed.
- EINTR/refresh/skip counts: unmeasured.
- Future TODO: duplicate suppression, SPDP wake, cross-host scope; resolve prerequisite evidence before deciding generation.
- Pushes: none. Existing untracked artifacts not staged/committed.
