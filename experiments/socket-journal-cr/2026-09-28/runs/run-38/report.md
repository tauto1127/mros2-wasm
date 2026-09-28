# run-38 report

## Result

Phase A pre-C/R gate **timed out**. It recorded 0 complete ID/body round trips in 60.0 seconds of the 60-second window. Checkpoint and restore were not run. This is failure number 1 in the instrumented series (successes=7, failures=1). The trial reused the run-31 Wasm artifact, runtime, and native peer without rebuilding.

## SEDP order observed

The Wasm log contains 13 parseable `[SEDP-RACE]` events.

Application SEDP changes and the following empty-proxy progress observations:

- `rt/to_linux` (publication), sequence `0:1`: consumed_without_proxy=True, next_after=`0:2`, proxy_added_later=True.
- `rt/to_stm` (subscription), sequence `0:1`: consumed_without_proxy=True, next_after=`0:2`, proxy_added_later=True.

Passive wire counts in the pre-gate window:

- Wasm -> peer SEDP DATA submessages: 0
- Wasm -> peer SEDP HEARTBEAT frames: 0
- peer -> Wasm SEDP DATA submessages: 2
- peer -> Wasm SEDP HEARTBEAT frames: 30
- Wasm -> peer user DATA submessages: 56
- peer -> Wasm user DATA submessages: 0

The passive observer records DATA writer and reader entity IDs and does not record DATA sequence numbers. SEDP DATA submessages in this window therefore cannot be tied to a specific sequence-1 change.

## Evidence limits

Parsed `[SEDP-RACE]` rows had no WAMR receive-log prefix before the event marker. `wire-counts.md` does not count ACKNACK. In the same pre-gate window, `peer-wire.jsonl` also contains 30 Wasm -> peer frames on port 7410 whose only submessage id is `0x06` (ACKNACK), 61 SPDP DATA frames in each multicast direction on port 7400, and no peer -> Wasm ACKNACK on port 7410.

The application log records 60 Wasm publishes, 56 native receives, 56 native echo-publish returns, and 0 Wasm callbacks. Those 56 native echo-publish returns have no matching peer -> Wasm user DATA frame.

Cleanup removed this trial's three containers. `raw/staged-compare.txt` is `unchanged`, and the shared network was retained.

## Hypothesis

From this trial alone the race order is present and the sequence-`0:1` advertisements have no Wasm -> peer SEDP DATA. The series comparison weakens that order as a sufficient cause: the same order occurs on the passes. Series classification: **weakened**. See `../../sedp-race-phase-a-report.md`. Phase B was not run from this timeout.
