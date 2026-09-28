# run-32 report

## Result

Phase A pre-C/R gate **passed**. It recorded 10 complete ID/body round trips in 32.5 seconds of the 60-second window. Checkpoint and restore were not run. This is success 2 in the instrumented series. The trial reused the run-31 Wasm artifact, runtime, and native peer without rebuilding.

## SEDP order observed

The Wasm log contains 13 parseable `[SEDP-RACE]` events. For both the `/to_linux` publication and `/to_stm` subscription, `change_created` sequence `0:1` was followed by `progress_enter` with an empty proxy list and `progress_exit` with `next_after=0:2` and `send_attempted=0`. The matching builtin reader proxy was added later with `add_success=1`.

This is the same empty-proxy progress order seen in run-31, again during a successful startup. Passive wire capture in the pre-gate window saw 8 Wasm-to-peer SEDP DATA submessages, 2931 Wasm-to-peer HEARTBEAT frames, 2 peer-to-Wasm SEDP DATA submessages, and 16 peer-to-Wasm HEARTBEAT frames. User DATA was seen in both directions, 29 submessages each. The gate confirms 10 full application round trips (IDs 4, 9, 14, 15, 19, 20, 21, 25, 30, 31).

The existing passive observer records DATA writer/reader entity IDs but not DATA sequence numbers. Therefore the 8 SEDP DATA submessages cannot yet be tied directly to the two initial sequence-1 changes. This second success shows that the early empty-proxy progress does not by itself prevent later communication. Whether a later SEDP resend accounts for those DATA submessages remains unresolved.

## Evidence limits and next step

Three trace rows were interleaved with an existing WAMR receive log in the captured stdout line. The `[SEDP-RACE]` payloads and sequence numbers are intact and have been extracted into `raw/sedp-race-trace.jsonl`; the raw log is retained.

Cleanup removed this trial's three containers. `raw/staged-compare.txt` is `unchanged`, and the shared network was retained.

Series result after run-40: the same empty-proxy progress order appears on nine passes and on the run-38 timeout. Classification: **weakened**. See `../../sedp-race-phase-a-report.md`. Phase B was not run.
