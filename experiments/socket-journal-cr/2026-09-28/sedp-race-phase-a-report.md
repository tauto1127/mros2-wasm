# SEDP race Phase A report

## Classification

**Weakened.** The empty-proxy `progress()` order in the hypothesis occurs on the failed startup and on every successful startup in this series. It does not by itself explain why one startup fails. Phase B was not run. No discovery or recovery code was changed.

## What was run

Ten independent cold starts, run-31 through run-40, on the existing `mros2-cr-net` network. Wasm stayed at `172.18.0.3` and the native peer at `172.18.0.5`. All ten used the same instrumented Wasm artifact, `9e926d0f13c9fbfcd003710c0ff01cd7c0229352a05b1efba9d0a97b2d378d46`, the same `iwasm`, and the same native peer. Nothing was rebuilt after run-31. No trial checkpointed or restored. Each trial's containers were removed afterward, `raw/staged-compare.txt` is `unchanged`, and the shared network was left with no containers attached.

The series stopped at the 10-trial cap: 9 pre-C/R gate passes and 1 timeout. That cap is a search limit, not a failure-rate estimate.

| Run | Gate | Complete round trips | Wasm -> peer SEDP DATA | Wasm -> peer SEDP HEARTBEAT | Peer -> Wasm user DATA |
|---|---|---:|---:|---:|---:|
| 31 | pass | 10 | 15 | 892 | 23 |
| 32 | pass | 10 | 8 | 2931 | 29 |
| 33 | pass | 10 | 7 | 2148 | 26 |
| 34 | pass | 10 | 13 | 1744 | 28 |
| 35 | pass | 10 | 13 | 1146 | 37 |
| 36 | pass | 10 | 15 | 318 | 26 |
| 37 | pass | 10 | 7 | 892 | 26 |
| 38 | timeout | 0 | 0 | 0 | 0 |
| 39 | pass | 10 | 12 | 1540 | 29 |
| 40 | pass | 10 | 16 | 732 | 41 |

DATA and HEARTBEAT counts are the passive-observer tallies in each `raw/wire-counts.md`. They count SEDP writer DATA and HEARTBEAT submessages on metatraffic port 7410. They do not count ACKNACK.

## What is common to all ten starts

For both SEDP writers, the captured order is:

1. `change_created` for sequence `0:1` (`/to_linux` on the publications writer, `/to_stm` on the subscriptions writer).
2. `progress_enter` with `proxies_empty=1` and `next_before=0:1`.
3. `progress_exit` with `next_after=0:2` and `send_attempted=0`.
4. `proxy_added` later, with `add_success=1` and `next=0:2`.

The first `builtin_proxy_plan` selects `172.18.0.5:7410` and sets both reader flags. No trial logs a second `progress()` after that proxy is added, and none logs `send_attempted=1`.

On run-33 the publications `change_created` line in `wasm-checkpoint.log` lost its `[SEDP-RACE] seq=` prefix, so the structured trace has 12 events instead of 13. The same line still records `role=publication`, `topic=rt/to_linux`, and `sequence=0:1`. The publications `progress_exit` for `0:1 -> 0:2` is present.

## What run-38 adds

The 60-second gate timed out with 0 complete round trips. The application log has 60 Wasm publishes, 56 native receives, 56 native echo-publish returns, and 0 Wasm callbacks.

Inside the pre-gate window (`2026-09-28T09:06:33.750000+00:00` to `2026-09-28T09:07:33.865000+00:00`), `peer-wire.jsonl` contains:

- 61 SPDP DATA frames, Wasm multicast `239.255.0.1:7400`
- 61 SPDP DATA frames, peer multicast `239.255.0.1:7400`
- 56 user DATA frames, `172.18.0.3:7411 -> 172.18.0.5:7411`
- 30 HEARTBEAT frames, `172.18.0.5:7410 -> 172.18.0.3:7410`
- 30 ACKNACK frames, `172.18.0.3:7410 -> 172.18.0.5:7410` (submessage id `0x06` only)
- 2 SEDP DATA frames, `172.18.0.5:7410 -> 172.18.0.3:7410`
- no Wasm -> peer SEDP DATA (`0x15`) and no Wasm -> peer SEDP HEARTBEAT (`0x07`)
- no peer -> Wasm user DATA on port 7411
- no peer -> Wasm ACKNACK on port 7410

The 30 ACKNACK frames are invisible to `wire-counts.md`, which only tallies SEDP DATA and HEARTBEAT. The raw JSONL is the source for that count. Unicast frames in this window total 118, matching `rtps_frames_in_gate_window`.

So participant discovery and the Wasm user writer were active. The Wasm SEDP reader answered the peer. The Wasm SEDP writers put no DATA and no HEARTBEAT on the path to `172.18.0.5:7410`. The peer's echo-publish call returned without a captured user packet back to Wasm.

## Why this weakens the hypothesis

The failure does show the predicted order, and the two sequence-`0:1` advertisements have no corresponding Wasm -> peer SEDP DATA in the window. That is the failure half of the strong-support pattern.

The success half is absent. Proxy registration is not earlier than `progress()` on the nine passes. Those passes also have no logged replay inside `progress()`. They still show Wasm -> peer SEDP DATA and hundreds or thousands of Wasm -> peer SEDP HEARTBEAT frames. Empty-proxy advancement of `m_nextSequenceNumberToSend` is therefore not sufficient to keep the advertisement off the wire.

`StatefulWriterT::progress()` is the only logged send attempt, and it records `send_attempted=0` in every trial. `StatefulWriterT::onNewAckNack()` can call `sendHeartBeat()` or `sendData()` without calling `progress()`. This series does not record those calls, so the success packets cannot be assigned to that function, and they cannot be assigned to sequence `0:1`. The observer does not store DATA sequence numbers.

The run-38 signature that the nine passes do not share is the total absence of Wasm SEDP DATA and Wasm SEDP HEARTBEAT for the whole minute, while SPDP, user DATA, and SEDP ACKNACK from Wasm are present. The configured heartbeat period in the instrumented tree is 4000 ms, so a running heartbeat loop with a non-empty proxy list and history `0:1` would have had many chances to emit a frame. This trace does not show whether `sendHeartBeat()` was entered.

## What was not done

Phase B was not started. One startup failure was reproduced, so this is not a series in which instrumentation removed the intermittent failure. The race account is not supported strongly enough, and it is not refuted, because the failure still has the predicted order and the predicted missing SEDP DATA. Checkpointing a later passing startup would not identify the silent writer path.

No behavior fix was applied.

## Next boundary

Instrument the two SEDP writers at `sendHeartBeat()` and at the ACKNACK `sendData()` path, still without changing send decisions. The question is why those sends produce DATA and HEARTBEAT on a pass and produce neither on a timeout, after `proxy_added` has already succeeded with history `0:1`. Keep the passive capture. A fix stays in a separate reviewed plan.
