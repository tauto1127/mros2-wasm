# Parent-owned focused real-refresh C/R evidence

## Result and scope

**run-09 PASS — experiment-confirmed, same-host Docker only.** This is coordinator/probe evidence, not final Gate B or production/application acceptance. No production worktree/branch or approved-design file was created. D's original report remains correctly incomplete; this report is a separately identified parent takeover after two unsuccessful delegated attempts.

- Exact pinned netif source `fbac6d22:src/netif/netif_wasm.c` is included unchanged by `fixture-v3.c` (with syscall logging/cut macros only). Legacy pending in that extracted fixture is NOT the adopted production design.
- Same-TU exact pinned core uses its actual private `tcpip_core_mutex`, with documented candidate delta: static `PTHREAD_MUTEX_INITIALIZER`, remove redundant MX initialization, add `pthread_mutex_trylock` wrapper. No synthetic substitute guard or blind reset.
- C11 atomic test control; first contender attempt cannot precede restored owner continuation. Fixture setup is single-threaded; it does not attest future production reader migration or C++ projection transaction.
- Fixed shared 1 GiB target memory, SDK21/sysroot, pinned runtime `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e578587b60`, Docker same network/IP `.3`.

## Measured ordered facts

1. Precheckpoint initial real socket/connect/getname/close succeeds with `0x030012ac` (`172.18.0.3`). Owner next opens fd7 and connects successfully.
2. Cut is **after real connect, before getsockname**, while the exact core mutex is held: guest mutex `0x15a4`, size24; post-stage `0x165c`, ack `0x1660`.
3. Checkpoint log has NO owner continuation or contender BUSY. Full checkpoint memory/socket/thread manifests recorded before restore.
4. Restore owner guest pthread `0x404` resumes checkpoint hook receive with `rc=-1, errno=27` (EINTR).
5. Restored contender guest pthread `0xc81ce4` FIRST try returns BUSY; does not unlock or wait for owner. Owner waits only in test-control hook for evidence acknowledgment, NOT proposed receive loser logic.
6. Real restored getsockname fd7 returns success but address `0x00000000`; unchanged baseline rejects wildcard. **No injected error** (`injected_getname_error:false`).
7. Baseline closes fd7 with rc0; common coordinator releases on failure. Then subsequent actual socket/connect/getname/close succeeds at `.3`, coordinator releases, fixture exits0.
8. Script asserts exact event order/counts, no precheckpoint continuation, first BUSY once, both closes rc0, natural replay wildcard/error, subsequent actual success, and exit0. PASS is not merely a cleanup label.

## Raw authority

Under this directory:

- `run-09/{checkpoint.log,restore.log,restore-final.log,result.json,build-command.json,build.log,preflight.json,checkpoint-manifest.json,artifact-hashes.json,docker-commands.log,network-after.json,checkpoint-owner-identity.txt}`.
- Fixture Wasm SHA256 `fcd2cdb46bc93331d9d083740f9533ddcaf48dc24e2667d92f60a2d57b8ee24c`.
- `main-memory.img` is exactly1073741824 bytes, SHA256 `73db8fca35389519d1d08d0152d6f9cc01a2fc7a18aa1d9b2cfcbb28084d4b11`.
- `fixture-v3.c`, `run-v3.py`, `lwip-core-v2.c`, pinned-v2 source, v2 originals and parent patches preserved. Build09 uses complete project raw lwIP/system include recipe, GNU C11 plus limits header for SDK ssize_t, unchanged baseline `sys_utils.c` for byte order. Unused core initialization dropped by linker GC; kernel allocator initialization is not exercised by this fixture.
- Free preflight4738428928 bytes, required3221225472. Own unique v3-labeled container stopped/removed; preexisting unrelated container/network untouched.

## Failure preservation and limits

- Worker v2 run06 missing raw header include; parent run07 missing arch include; run08 strict-C11 ssize_t header error. All are retained build-only failures, no Docker/C-R. run09 is the only new parent C/R trial.
- D-owned run03/run05 payloads remain losslessly archived with verified decompressed SHA/membership; old Phase0/atomic states untouched. run09 PASS payload is currently retained pending independent evidence inspection and authorized own-PASS cleanup.
- **Code-confirmed/inference:** other normal socket/invalid-address/connect/getname return paths close owned fd or own none; common wrapper releases irrespective of baseline result. Only the after-connect/wildcard-getname C/R path is measured here; not arbitrary syscall traps/process death, cross-host, or multi-NIC proof.
- C++ endpoint synchronization, prepared projection admission/commit, zero-endpoint/startup/ABA tests and all three normal app builds/application campaigns still require clean implementation and final independent diff review after explicit parent Gate B approval.
