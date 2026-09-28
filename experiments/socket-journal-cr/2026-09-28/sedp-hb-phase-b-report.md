# SEDP HEARTBEAT / ACKNACK diagnostic report

## Conclusion

**Failure cause remains unresolved because the run-38-type failure was not reproduced under the new instrumentation.** The new evidence does, however, identify the recovery mechanism used by successful starts much more clearly.

On every successful instrumented start, both SEDP builtin writers started their heartbeat loops. After the initial no-proxy heartbeat skip, each writer later emitted a HEARTBEAT advertising retained sequence `0:1`. The peer then sent an ACKNACK requesting sequence `0:1`; the Wasm SEDP writer matched the ReaderProxy, entered the ACKNACK-driven `sendData()` path, and sent DATA sequence `0:1`. The passive capture independently observed those two `0:1` SEDP DATA submessages on the wire. This explains how successful starts recover the endpoint advertisement even though the earlier `progress()` path had advanced past `0:1`.

The old run-38 failure remains different in the key place: its 60-second window had no Wasm -> peer SEDP HEARTBEAT and no Wasm -> peer SEDP DATA at all. Therefore a failure of the HEARTBEAT / ACKNACK recovery path remains a plausible explanation for run-38, but this series cannot locate the failing step because all ten Phase B trials passed.

## Instrumentation sanity check: run-45

- Gate: pass; 10 complete application round trips.
- Both SEDP publications/subscriptions heartbeat threads were created and both loops started.
- Internal `heartbeat_transport_before`: 8; passive Wasm -> peer SEDP HEARTBEAT: 8.
- Internal ACKNACK receive/dispatch traces: 14 each.
- ACKNACK-driven SEDP `sendData()` entries: 2.
- Passive Wasm -> peer SEDP DATA: 2, with writer sequence `0:1` for publications and `0:1` for subscriptions.
- This correspondence was sufficient to validate the new observation path before repeated trials.

## Phase B repeated cold starts

The validated Wasm artifact was fixed for all Phase B trials: `6cddd4b77fe1a5eaccf8de85af351272de6d228ce49ef1dfeafb6e4480195c81`. Runtime, native peer, Docker network, IPs, QoS, application behavior, startup procedure, and the 60-second pre-C/R gate were held fixed. Checkpoint/restore was not run.

| Run | Gate | Gate duration (s) | Wasm -> peer SEDP HB | Wasm -> peer SEDP DATA | ACKNACK receive traces | ACKNACK-driven sendData | DATA SNs |
|---|---|---:|---:|---:|---:|---:|---|
| 61 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 62 | pass | 18.3 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 63 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 64 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 65 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 66 | pass | 19.3 | 10 | 2 | 16 | 2 | 0:1,0:1 |
| 67 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 68 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |
| 69 | pass | 14.4 | 6 | 2 | 12 | 2 | 0:1,0:1 |
| 70 | pass | 18.4 | 8 | 2 | 14 | 2 | 0:1,0:1 |

Phase B stopped at the configured 10-trial cap: **10 passes, 0 failures**. The cap is a search bound, not a statistical estimate of failure probability.

Every pass had exactly two Wasm -> peer SEDP DATA submessages, one `0:1` advertisement from each SEDP writer. HEARTBEAT count varied from 6 to 10 according to how long the application gate remained open, while the same recovery sequence remained visible.

## Successful-start recovery sequence

A representative run (run-61) shows the following order for each SEDP writer:

1. heartbeat loop reaches a send with retained history `first=0:1`, `last=0:1`;
2. `heartbeat_transport_before` / `after` completes to peer metatraffic port 7410;
3. peer ACKNACK arrives with `base=0:1`, `num_bits=1`, requesting the missing advertisement;
4. `MessageReceiver` finds the local writer and dispatches the ACKNACK;
5. `onNewAckNack()` finds the matching ReaderProxy;
6. `acknack_action action=send_data sequence=0:1`;
7. `sendData()` reaches transport;
8. passive capture sees SEDP DATA sequence `0:1`.

This sequence is direct evidence that the RTPS reliable-writer recovery path is what rescues the initially untransmitted sequence-`0:1` SEDP advertisement in successful starts.

## What this says about the current hypothesis

- **Previous ordering hypothesis:** further weakened as a sufficient cause. A successful start can have the same early empty-proxy ordering and then recover `0:1` through HEARTBEAT -> ACKNACK -> `sendData()`.
- **HEARTBEAT / recovery hypothesis:** supported as the mechanism that makes successful starts work, but **unresolved as the cause of the intermittent failure**. The only captured failure with the relevant signature is still old run-38, where both outgoing SEDP HEARTBEAT and DATA were absent.
- The exact run-38 failure point could still be heartbeat-thread scheduling, `sendHeartBeat()` state/early return, transport, or another condition that prevents this recovery exchange. The new instrumentation did not observe a failure to distinguish those cases.

## Reproduction limitation

The new instrumentation adds logging on the heartbeat and ACKNACK hot paths. Phase A previously reproduced one timeout in ten starts; this new series reproduced zero in ten. That difference is not enough to conclude that instrumentation suppressed the race, but logging-induced scheduling perturbation remains a relevant possibility. More trials with lower-overhead tracing would be the next diagnostic step if reproducing the failure is necessary.

## Isolation and cleanup

- run-60 was aborted at preflight because another experiment temporarily occupied `mros2-cr-net`; it is not counted as a trial.
- Concurrent run-46 and nearby runs used different Wasm artifacts and are not included in this fixed-artifact series.
- All counted Phase B runs report `staged-compare.txt = unchanged`.
- After completion, `mros2-cr-net` had zero attached containers and no run-45/run-61--70 containers remained.
- No checkpoint/restore was run. No behavior fix was applied. No commit or push was performed.

## Evidence paths

- Series machine-readable summary: `experiments/socket-journal-cr/2026-09-28/sedp-hb-phase-b-summary.json`
- Sanity check: `experiments/socket-journal-cr/2026-09-28/runs/run-45/`
- Phase B trials: `experiments/socket-journal-cr/2026-09-28/runs/run-61/` through `run-70/`
- Per-run structured comparison: each `raw/hb-analysis.json`
- Passive packet evidence: each `raw/peer-wire.jsonl`
- Internal trace: each `raw/wasm-checkpoint.log` (`[SEDP-HB]`)
- Instrumentation/build evidence: `run-45/raw/instrumentation-tracked.diff`, `run-45/raw/instrumentation-new-header.diff`, `run-45/raw/cmake-configure.log`, and `run-45/raw/build.log`.

## Next boundary

Do not implement a behavior fix yet. If this investigation continues, prefer a lower-perturbation trace (for example, compact preallocated in-memory events flushed after the gate) and repeat the cold-start search. The decisive evidence would be a new timeout showing the first divergence between heartbeat-loop wakeup, `sendHeartBeat()` decision, transport submission, wire HEARTBEAT, ACKNACK dispatch, and `sendData()` resend.
