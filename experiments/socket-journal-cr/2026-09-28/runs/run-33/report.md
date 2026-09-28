# run-33 report

## Result

Phase A pre-C/R gate **passed**. It recorded 10 complete ID/body round trips in 29.5 seconds of the 60-second window. Checkpoint and restore were not run. This is success number 3 in the instrumented series (successes=3, failures=0). The trial reused the run-31 Wasm artifact, runtime, and native peer without rebuilding.

## SEDP order observed

The Wasm log contains 12 parseable `[SEDP-RACE]` events. The publications `change_created` line is present in `wasm-checkpoint.log` but lost its `[SEDP-RACE] seq=` prefix, so it is absent from the structured trace. That raw line still records `role=publication`, `topic=rt/to_linux`, and `sequence=0:1`. The publications writer then progressed `0:1` to `0:2` with an empty proxy list.

Application SEDP changes and the following empty-proxy progress observations:

- `rt/to_stm` (subscription), sequence `0:1`: consumed_without_proxy=True, next_after=`0:2`, proxy_added_later=True.

Passive wire counts in the pre-gate window:

- Wasm -> peer SEDP DATA submessages: 7
- Wasm -> peer SEDP HEARTBEAT frames: 2148
- peer -> Wasm SEDP DATA submessages: 2
- peer -> Wasm SEDP HEARTBEAT frames: 14
- Wasm -> peer user DATA submessages: 26
- peer -> Wasm user DATA submessages: 26

The passive observer records DATA writer and reader entity IDs and does not record DATA sequence numbers. SEDP DATA submessages in this window therefore cannot be tied to a specific sequence-1 change.

## Evidence limits

At least one trace row was interleaved with an existing WAMR receive log on the captured stdout line. The `[SEDP-RACE]` payload was extracted into `raw/sedp-race-trace.jsonl`; the raw log is retained.

Cleanup removed this trial's three containers. `raw/staged-compare.txt` is `unchanged`, and the shared network was retained.

Series position prepared by the continuation driver: third instrumented trial.
