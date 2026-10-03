# RTPS socket `getsockname()` comparison

## Baseline

- Parent repository: `e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0`, branch `integration/network-migration`.
- `lwip-wasm`: `160d01d0a088fad9b20ce334bad1e3a110576500`. The live checkout was on branch `fix/eintr-no-udp-recover`, not the branch named in the request; the commit matched. The experiment worktree used this exact commit.
- `cmsis-wasm`: `182dcaff50a0e9c626c84db365b1d762747a806b`.
- The parent live checkout already had untracked `experiments/`; it was left untouched. All source instrumentation and artifacts are in the separate worktree `/home/osslab/20261003-rtps-socket-getsockname`, branch `experiment/rtps-socket-getsockname`.

## Socket topology observed in source

embeddedRTPS creates a raw lwIP `udp_pcb` per receiving RTPS port. lwip-wasm associates each PCB with a BSD/WASI UDP socket; `mcp->sd` is that socket fd and is passed to `sendto()` and `recvfrom()`.

The normal one-participant runtime used four sockets:

| Role | RTPS port | Initial `mcp->sd` (same run) | Bind address |
|---|---:|---:|---|
| SPDP/SEDP built-in multicast discovery | 7400 | 14 | `0.0.0.0` |
| User multicast | 7401 | 3 | `0.0.0.0` |
| Built-in unicast, participant 0 | 7410 | 10 | `0.0.0.0` |
| User unicast, participant 0 | 7411 | 9 | `0.0.0.0` |

`UdpDriver::createUdpConnection()` binds PCBs with `IP_ADDR_ANY`; the BSD socket adapter binds `INADDR_ANY` and the PCB's local port. Multicast membership is applied through `IP_ADD_MEMBERSHIP`, separately from bind. The observed ports match Domain 0 / participant 0. Additional participants or user multicast locators can create additional sockets.

Socket Journal source inspection shows it records successful socket OPEN, BIND, relevant `setsockopt()` operations including multicast membership, and socket CLOSE. Restore creates a new host socket and inserts it into the WASI fd table using the recorded fd, then replays BIND and socket options. Membership replay can retry with `INADDR_ANY` if the saved interface address is unavailable on the destination. It restores the guest fd mapping, not the original kernel socket object.

## Instrumentation

- Changed in the experiment worktree's `lwip-wasm`: `src/core/udp.c`, `src/netif/netif_wasm.c`.
- Added diagnostics at RTPS bind and after EINTR handling, plus the address/ephemeral port returned by the existing `probe_local_ip()`.
- Diagnostic fields: phase, `mcp->sd`, role inferred from port, bound port, `getsockname()` result/address/port, and current probe/netif address.
- No socket lifecycle, bind, membership, `connect()`, WAMR, or production behavior changes. No RTPS socket received `connect()`.
- Built `echoback_string.wasm` with WASI SDK 21. Existing pinned `iwasm` and native peer artifact were reused. To fit the available environment without deleting files, the copied test runner stored checkpoint state in `/dev/shm`; it reused the already-running `.5` native peer and only tailed its log. The pre-existing container was not modified.

## Comparison

`socket_addr` below is the direct `getsockname(mcp->sd)` result. `probe_addr` is the route-selected address from the existing temporary-socket probe, or the netif address it just refreshed.

| Phase | Probe address | Role / port | `mcp->sd` | Socket address / port |
|---|---|---|---:|---|
| Pre-checkpoint, same run | `172.18.0.3` | User multicast / 7401 | 3 | `0.0.0.0:7401` |
| Pre-checkpoint, same run | `172.18.0.3` | Built-in multicast / 7400 | 14 | `0.0.0.0:7400` |
| Pre-checkpoint, same run | `172.18.0.3` | User unicast / 7411 | 9 | `0.0.0.0:7411` |
| Pre-checkpoint, same run | `172.18.0.3` | Built-in unicast / 7410 | 10 | `0.0.0.0:7410` |
| Same-IP restore, EINTR window | `172.18.0.3` | User multicast / 7401 | 7 | `0.0.0.0:7401` |
| Same-IP restore, EINTR window | `172.18.0.3` | Built-in multicast / 7400 | 10 | `0.0.0.0:7400` |
| Same-IP restore, EINTR window | `172.18.0.3` | User unicast / 7411 | 15 | `0.0.0.0:7411` |
| Same-IP restore, EINTR window | `172.18.0.3` | Built-in unicast / 7410 | 3 | `0.0.0.0:7410` |
| Changed-IP restore, EINTR window | `172.18.0.6` | User multicast / 7401 | 3 | `0.0.0.0:7401` |
| Changed-IP restore, EINTR window | `172.18.0.6` | Built-in multicast / 7400 | 12 | `0.0.0.0:7400` |
| Changed-IP restore, EINTR window | `172.18.0.6` | User unicast / 7411 | 9 | `0.0.0.0:7411` |
| Changed-IP restore, EINTR window | `172.18.0.6` | Built-in unicast / 7410 | 6 | `0.0.0.0:7410` |

At restore, the observed fd numbers were the `mcp->sd` values printed by the resumed receive threads. Same-IP's role-to-fd values differed from its initial bind sample; changed-IP's values matched its initial bind sample. In both trials the resumed sockets remained usable and their reported local endpoints remained `0.0.0.0:<bound port>`.

## C/R application round trips

- Same-IP `.3 → .3`: PASS. The runner verified the complete publish → native receive → native echo → Wasm callback chain for post-restore IDs 48–57.
- Changed-IP `.3 → .6`: PASS. The runner verified that complete chain for IDs 98–107 after restore; the first resumed probe returned `.6`. A later `netif_wasm` log reported the local IP changed to `.6`.
- Raw logs and `result.json` are under `smoke/same/run-02/` and `smoke/changed/run-02/`.

## Conclusion

**Can `getsockname(existing RTPS socket)` replace `probe_local_ip()`? NO.**

For every tested RTPS socket, `getsockname()` returned the wildcard bind address `0.0.0.0` and its bound port. It did not return the route-selected source IP, either before checkpoint or after same-IP / changed-IP restore. The existing temporary UDP socket's `connect(discovery multicast)` and `getsockname()` returned `.3` or `.6` as applicable. The experiment therefore supports keeping the temporary probe for the current `INADDR_ANY`-bound socket design. No production change was made.

## Remaining uncertainty

- This is one normal startup plus one same-IP and one changed-IP run in the existing Docker network; other network stacks, multiple participants, and extra user multicast locators were not sampled.
- Restore fd numbers were observed per role, and they were not consistent between the initial and restored samples in both runs. The Socket Journal source replays each recorded WASI fd mapping, but the diagnostic comparison alone does not explain the same-IP run's role-to-fd differences.
- No test was made of sockets explicitly bound to a concrete local address; that is a different bind configuration from the production path observed here.
