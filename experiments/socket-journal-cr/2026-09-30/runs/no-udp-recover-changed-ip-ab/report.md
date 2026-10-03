# Changed-IP checkpoint/restore: UDP EINTR recovery A/B

Date: 2026-09-30  
Network: `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, subnet `172.18.0.0/16`  
Source Wasm: `172.18.0.3`; native peer: `172.18.0.5`; restore destination: `172.18.0.6`

## Revisions and artifacts

| Component | Control | Experimental |
|---|---|---|
| Parent | `7b632868ed9859dc152bc87a23c98d4afff43837` | `924be79065fb581c63e0d79f3b74be387608075c` |
| `cmsis-wasm` | `182dcaff50a0e9c626c84db365b1d762747a806b` | same |
| `lwip-wasm` | `78ef9fc33842bece9ad9a83c1cd0a448b779d64e` + Phase 1 common logging instrumentation | `02654e0602cb4b80e83b1f8faae7687aad24cf55` |
| `mros2` | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` | same |
| `embeddedRTPS` | `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` | same |
| WAMR | `db2054224dcff9686f3f98850a29c554974096bc` | same |

Control used the Phase 1 recover-enabled source shape: base `78ef9fc3` plus the same errno/recovery logging instrumentation. Its rebuilt Wasm SHA-256 was `022844cc6f0e093e6ed9865331c1c640b0c615db7785bec75cccc5e816a443de`, exactly matching the recorded Phase 1 Control artifact. Experimental reused Phase 1 commit `02654e0`; its Wasm SHA-256 was `d4021793713b0181a6dbfae44b81a696b8d597fcdb92e6d0ed80113819e35656`, also matching Phase 1. `iwasm` SHA-256 was `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60`; peer SHA-256 was `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`.

The only behavior difference remained the Phase 1 EINTR branch: Control calls `udp_mc_recover()`; Experimental logs `action=skip reason=EINTR`, delays as before, then retries on the restored fd. No new socket, multicast, or RTPS behavior change was made. The WAMR worktree retained the same build-only `add_subdirectory(${wasmig_SOURCE_DIR}, ${wasmig_BINARY_DIR})` compatibility adjustment documented in Phase 1. Nothing was pushed.

Build provenance, staged arm artifacts, and the reused runner are in this directory: `build-provenance/`, `artifacts/`, and `campaign.py`.

## Results

Every run passed the complete application gate before checkpoint for IDs 4–13, checkpoint exited successfully, and `N=14`. Every destination container was inspected at `.6`; each post gate uses only IDs greater than `N`.

| Arm | Run | `.3 → .6` | EINTR | Recovery | First complete post-R ID | Time to first callback | Post-R gate | Result |
|---|---:|---|---|---|---:|---:|---|---|
| Control | 1 | yes | observed (`errno=27`) | executed, 4 starts / 4 successful results | 17 | 7.039 s | 17–26 | PASS |
| Control | 2 | yes | observed (`errno=27`) | executed, 4 starts / 4 successful results | 17 | 7.017 s | 17–26 | PASS |
| Control | 3 | yes | observed (`errno=27`) | executed, 4 starts / 4 successful results | 17 | 7.009 s | 17–26 | PASS |
| Experimental | 1 | yes | observed (`errno=27`) | skipped, 4 skip markers / 0 recovery starts | 16 | 3.001 s | 16–25 | PASS |
| Experimental | 2 | yes | observed (`errno=27`) | skipped, 4 skip markers / 0 recovery starts | 17 | 8.020 s | 17–26 | PASS |
| Experimental | 3 | yes | observed (`errno=27`) | skipped, 4 skip markers / 0 recovery starts | 16 | 3.044 s | 16–25 | PASS |

These IDs are same-ID, same-body complete round trips across Wasm publish, peer `/to_linux` callback, peer `/to_stm` echo publish, and Wasm subscriber callback. The runner counted the ten-ID windows from those four observations, not socket activity alone.

## Changed-IP auxiliary evidence

| Evidence | Control | Experimental |
|---|---|---|
| Destination container IP | `.6` in all 3 runs | `.6` in all 3 runs |
| Wasm local-IP log | `netif_wasm: local ip changed to 0x060012ac` in all 3 | same in all 3; this is `.6` in the logged address representation |
| Membership replay | 2 `used destination default interface` lines per run | 2 per run |
| Old-interface replay failure | not directly observed | not directly observed |
| SPDP/SEDP locator adaptation | no matching direct marker in existing logs | no matching direct marker in existing logs |

The runner verified that the source iwasm checkpoint process exited successfully before creating the destination restore container. The historical lifecycle leaves the source holder container (`sleep infinity`) attached to `.3` until per-trial teardown; it has no Wasm process after checkpoint and therefore no active source Participant. The peer remains `.5`. This distinction is visible in the saved source/destination inspect and command logs.

## Representative trace

Experimental run 01:

1. `checkpoint-signal.log` records the pre-window 4–13. `wasm-checkpoint.log` records checkpoint collector exit status 0; `checkpoint-boundary.txt` records `N=14`.
2. The source iwasm process exits before the `.6` destination is created. `dest-inspect.json` records `172.18.0.6` on the expected Docker network.
3. `wasm-restore.log` reports `Finish to restore stack`, then two multicast `add_membership` destination-default-interface fallback messages.
4. The restore log records four `UDP_RECV result=error errno=27` events and four `action=skip reason=EINTR` markers. There is no `action=start` or recovery result in that log.
5. `netif_wasm` logs the local-IP change to `0x060012ac`. Peer and Wasm logs record all four stages for ID 16 and the subsequent IDs; the gate records 16–25.

Representative raw evidence: [Experimental run 01 result](experimental/run-01/result.json), [restore log](experimental/run-01/wasm-restore.log), [peer log](experimental/run-01/peer-native.log), [destination inspect](experimental/run-01/dest-inspect.json), and [checkpoint boundary](experimental/run-01/checkpoint-boundary.txt). Control equivalents are under `control/run-01/`.

## Observation

- Control and Experimental each passed 3/3 changed-IP trials on the specified network.
- All six runs observed checkpoint-restore `errno=27`; Control called recovery and Experimental skipped it.
- All six destination restores used `.6`; all six completed ten new application-level topic round trips with IDs greater than `N`.
- Existing logs directly show local-IP change and multicast membership fallback. They do not directly show SPDP/SEDP locator updates or old-interface replay failure.

## Interpretation

For the tested changed-IP C/R path, application-level `udp_mc_recover()` after checkpoint-induced `EINTR` was not required to resume topic communication in 3/3 Experimental trials. Together with Phase 1, the tested same-IP and changed-IP conditions show that recovery solely because of checkpoint-induced `EINTR` was not a communication-recovery requirement.

This does not establish that `udp_mc_recover()` is unnecessary for non-EINTR socket failures, that Socket Journal alone performs every recovery step, or that cross-host migration works without recovery.

## Stop

Phase 2 ended after Control 3/3 and Experimental 3/3. No further experiments, fixes, cleanup, or branch changes were performed.
