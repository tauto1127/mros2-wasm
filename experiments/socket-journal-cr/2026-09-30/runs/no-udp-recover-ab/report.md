# Same-IP checkpoint/restore: EINTR recovery A/B

Date: 2026-09-30  
Network: `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, subnet `172.18.0.0/16`  
Wasm: `172.18.0.3`  
Native peer: `172.18.0.5`

## Revisions

| Component | Control | Experimental |
|---|---|---|
| Parent during trials | `7b632868ed9859dc152bc87a23c98d4afff43837` | `7b632868ed9859dc152bc87a23c98d4afff43837` |
| `cmsis-wasm` | `182dcaff50a0e9c626c84db365b1d762747a806b` | same |
| `lwip-wasm` | `78ef9fc33842bece9ad9a83c1cd0a448b779d64e` + common logging instrumentation | `02654e0602cb4b80e83b1f8faae7687aad24cf55` |
| `mros2` | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` | same |
| `embeddedRTPS` | `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` | same |
| WAMR | `db2054224dcff9686f3f98850a29c554974096bc` | same |

The parent experiment branch now points at local commit `924be79065fb581c63e0d79f3b74be387608075c`, which records the experimental `lwip-wasm` gitlink. The `lwip-wasm` behavior change is local commit `02654e0`; nothing was pushed. The WAMR submodule has the same one-line, build-only `add_subdirectory(..., ${wasmig_BINARY_DIR})` compatibility adjustment used for the 2026-09-28 build. It does not change runtime behavior.

`iwasm` SHA-256 was `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60` in both arms. The Control Wasm SHA-256 was `022844cc6f0e093e6ed9865331c1c640b0c615db7785bec75cccc5e816a443de`; Experimental was `d4021793713b0181a6dbfae44b81a696b8d597fcdb92e6d0ed80113819e35656`. The native peer SHA-256 was `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`.

The full build succeeded with WASI SDK 21 and Cargo 1.97.1. Two failed setup attempts are retained in the build logs: the first used system Cargo 1.75, which cannot read wasmig's lockfile version 4; the second exposed an over-broad `cc.h` text replacement in the copied 9/28 setup. The setup now leaves an already-commented `LWIP_PROVIDE_ERRNO` guard intact. The final Experimental Wasm was rebuilt from the same CMake build tree after the `udp.c` change. Build provenance and hashes are in `build-provenance/`.

## Experimental diff

File: `lwip-wasm/src/core/udp.c` (lwip-wasm commit `02654e0`). The common instrumentation saves `errno` immediately after `recvfrom`, logs the error, and logs recovery start/result and old/new fd. The only behavior change is the `EINTR` branch: log skip, retain the existing one-second delay, then retry using the restored fd. All non-`EINTR` errors still call `udp_mc_recover()` and use the prior delay.

```diff
@@ recvfrom error path
     int saved_errno = errno;
     int old_fd = mcp->sd;
+    if (saved_errno == EINTR) {
+      CMSIS_IMPL_ERROR("UDP_RECV_RECOVERY action=skip reason=EINTR fd=%d", old_fd);
+      osDelay(1000);
+      continue;
+    }
     int recovery_result = udp_mc_recover(mcp);
```

The full diff is recorded by the `lwip-wasm` commit and visible in the source worktree.

## Control

| Run | EINTR | `udp_mc_recover()` | Topic round-trip | Result |
|---|---|---|---|---|
| 01 | observed (`errno=27`) | executed, `rc=0` | pre `4–13`; post `16–25` | PASS |
| 02 | observed (`errno=27`) | executed, `rc=0` | pre `4–13`; post `16–25` | PASS |
| 03 | observed (`errno=27`) | executed, `rc=0` | pre `4–13`; post `16–25` | PASS |

## Experimental

| Run | EINTR | Recovery action | Topic round-trip | Result |
|---|---|---|---|---|
| 01 | observed (`errno=27`) | skipped; no recovery start/result after EINTR | pre `4–13`; post `16–25` | PASS |
| 02 | observed (`errno=27`) | skipped; no recovery start/result after EINTR | pre `4–13`; post `16–25` | PASS |
| 03 | observed (`errno=27`) | skipped; no recovery start/result after EINTR | pre `4–13`; post `16–25` | PASS |

Each trial used root SHA `7b632868…`, the expected `cmsis-wasm`, `mros2`, `embeddedRTPS`, and WAMR revisions above, the exact Docker network ID/subnet, and the same `.3` Wasm / `.5` peer addresses. Every pre-gate was 10 consecutive complete round-trips for IDs 4–13. Every checkpoint succeeded and produced both memory and socket images. The observed boundary was `N=14` in all six trials. Every restore completed and each post-gate counted ten consecutive complete round-trips using IDs 16–25, all greater than `N`.

| Arm / run | First complete post-R ID | Restore command to first complete callback |
|---|---:|---:|
| Control 01 | 16 | 7.335 s |
| Control 02 | 16 | 6.243 s |
| Control 03 | 16 | 6.088 s |
| Experimental 01 | 16 | 3.062 s |
| Experimental 02 | 16 | 3.223 s |
| Experimental 03 | 16 | 3.119 s |

## Representative evidence

Evidence below uses run 01 from each arm. Host monotonic and UTC timestamps are in the raw log lines.

**Control**

1. `checkpoint-signal.log` records the pre-checkpoint 10-ID window `[4, …, 13]`; the checkpoint collector exited with status 0. The checkpoint state manifest lists `main-socket.img` (3,460 bytes) and `main-memory.img`.
2. Restore output reports `Finish to restore stack` before resumed application output.
3. At `08:03:36.287`, restore logs show `UDP_RECV result=error errno=27` and `UDP_RECV_RECOVERY action=start`. The recover result is `ok rc=0`; for fd 6, the log records old fd 6 and new fd 9.
4. For ID 16 and body `Hello from mros2-posix onto Linux: 16`, the peer log records `/to_linux` receive and `/to_stm` echo publish. The Wasm log records publish and subscriber callback for the same ID/body. `result.json` records the post-R gate `[16, …, 25]`.

**Experimental**

1. `checkpoint-signal.log` records `[4, …, 13]`; the checkpoint collector exited with status 0. Its state manifest lists `main-socket.img` and `main-memory.img`.
2. Restore output reports `Finish to restore stack` before resumed application output.
3. At `08:08:47.317`, restore logs show `UDP_RECV result=error errno=27` followed by `UDP_RECV_RECOVERY action=skip reason=EINTR`. The restore log contains no recovery `action=start` or result line.
4. For the same ID 16 and body, the peer log records `/to_linux` receive and `/to_stm` echo publish; the Wasm log records publish and subscriber callback. `result.json` records the post-R gate `[16, …, 25]` and 3.062 s to the first new complete callback.

The raw logs do not contain a dedicated `SOCKET_JOURNAL` replay marker. The direct evidence for restore is the checkpoint manifest's socket image, successful restore-stack completion, and subsequent complete application-level round-trips.

## Observation

- All six same-IP trials passed the pre- and post-restore application-level gates.
- Every trial logged a guest-visible `errno=27` after restore. The WASI SDK defines `EINTR` as `__WASI_ERRNO_INTR`, whose value is 27; the guest branch compares the symbolic `EINTR`.
- Control ran `udp_mc_recover()` after those errors and logged successful returns.
- Experimental skipped `udp_mc_recover()` for those errors and completed ten consecutive new topic round-trips on the restored logical sockets in all three trials.

## Interpretation

For this same-IP checkpoint/restore path, the observations support that application-level `udp_mc_recover()` is not required solely because checkpoint wakeup interrupted `recvfrom()`: the restored logical sockets resumed complete topic communication without that recovery call in 3/3 trials.

This result does not establish that `udp_mc_recover()` is unnecessary for non-`EINTR` socket failures. Changed-IP behavior was not tested.

## Stop

Phase 1 ended after the 3/3 Experimental result. No changed-IP trials or follow-up behavior changes were run.
