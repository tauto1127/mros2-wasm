# run-40 report

## Result

Phase A pre-C/R gate **passed**. It recorded 10 complete ID/body round trips in 44.4 seconds of the 60-second window. Checkpoint and restore were not run. This is success number 9 in the instrumented series (successes=9, failures=1). The trial reused the run-31 Wasm artifact, runtime, and native peer without rebuilding.

## SEDP order observed

The Wasm log contains 13 parseable `[SEDP-RACE]` events.

Application SEDP changes and the following empty-proxy progress observations:

- `rt/to_linux` (publication), sequence `0:1`: consumed_without_proxy=True, next_after=`0:2`, proxy_added_later=True.
- `rt/to_stm` (subscription), sequence `0:1`: consumed_without_proxy=True, next_after=`0:2`, proxy_added_later=True.

Passive wire counts in the pre-gate window:

- Wasm -> peer SEDP DATA submessages: 16
- Wasm -> peer SEDP HEARTBEAT frames: 732
- peer -> Wasm SEDP DATA submessages: 2
- peer -> Wasm SEDP HEARTBEAT frames: 22
- Wasm -> peer user DATA submessages: 41
- peer -> Wasm user DATA submessages: 41

The passive observer records DATA writer and reader entity IDs and does not record DATA sequence numbers. SEDP DATA submessages in this window therefore cannot be tied to a specific sequence-1 change.

## Evidence limits

At least one trace row was interleaved with an existing WAMR receive log on the captured stdout line. The `[SEDP-RACE]` payload was extracted into `raw/sedp-race-trace.jsonl`; the raw log is retained.

Cleanup removed this trial's three containers. `raw/staged-compare.txt` is `unchanged`, and the shared network was retained.

Series position prepared by the continuation driver: tenth instrumented trial.

## Series classification

The same empty-proxy progress order appears on the nine passes and on the run-38 timeout. Classification across run-31 through run-40: **weakened**. See `../../sedp-race-phase-a-report.md`. Phase B was not run.
