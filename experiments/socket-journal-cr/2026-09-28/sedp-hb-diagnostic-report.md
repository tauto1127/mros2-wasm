# SEDP heartbeat / ACKNACK diagnostic report

## Classification

**Narrowed.** The first difference between a passing cold start and a run-38-style timeout is the absolute deadline computed for the first SEDP `vTaskDelay(4000)`. Thread creation, the first loop tick, the empty-proxy skip, writer lookup, and the later unmatched `010f0641...` ACKNACK are common to both outcomes. No send decision, heartbeat period, ReaderProxy rule, or application behavior was changed to repair this. No checkpoint or restore was run.

## What was run

Four independent cold starts, run-46 through run-49, on `mros2-cr-net`. Wasm stayed at `172.18.0.3` and the native peer at `172.18.0.5`. All four used one instrumented Wasm artifact, `e1ef90ff5ece66769e3ec40b4e454b92cecfc4457b1db6a1861fcd83dc609a40`, the same `iwasm`, and the same native peer as run-31 through run-40. The 60-second pre-C/R gate was unchanged.

The committed `sendHeartBeatLoop()` slept SEDP writers with `nanosleep`. run-31 through run-40, including the run-38 timeout, called `vTaskDelay`, which is `osDelay` and then `WasmThreadSyncSleep`. This series put that call back and added `[SEDP-HB]` logs around it. `SF_WRITER_HB_PERIOD_MS` stayed 4000.

| Run | Gate | Complete round trips | Wasm -> peer SEDP DATA | Wasm -> peer SEDP HEARTBEAT | Peer -> Wasm user DATA |
|---|---|---:|---:|---:|---:|
| 46 | timeout | 0 | 0 | 0 | 0 |
| 47 | timeout | 0 | 0 | 0 | 0 |
| 48 | pass | 10 | 7 | 2229 | 14 |
| 49 | pass | 10 | 8 | 3259 | 15 |

DATA and HEARTBEAT counts are passive-observer submessages on metatraffic port 7410 inside the gate window. The two timeouts also captured 56 Wasm -> peer user DATA frames, 30 peer -> Wasm SEDP HEARTBEAT frames, and 30 Wasm -> peer SEDP ACKNACK frames. That is the run-38 wire signature.

## Where the traces still agree

On every trial, both SEDP writers do all of the following before any send:

1. `heartbeat_thread_create` with `created=1`.
2. `heartbeat_loop_start` with `running=1`.
3. `heartbeat_loop_tick` tick 1, `proxies_empty=1`, history `-1:0`..`-1:0`.
4. `heartbeat_enter` call 1 and `heartbeat_skip reason=no_proxies`.
5. `heartbeat_delay_enter` tick 1, `delay_ms=4000`, `backend=vTaskDelay`.

The real peer proxy is then added with `add_success=1`, history `0:1`..`0:1`, and `next=0:2`. That registration does not wake the heartbeat thread. The empty-proxy `progress()` order from run-31 through run-40 is still present and still does not separate pass from timeout.

## First divergence

`add_timespec()` in `cmsis-wasm/src/core/cmsis_wasm_thread_sync.c` adds `4000 * 1000 * 1000` nanoseconds to a 32-bit `tv_nsec`. `CLOCK_REALTIME` seconds are a plausible 2026 timestamp in every trial. The nanosecond field decides the branch.

`2^32 - 4000000000 = 294967296`.

- If `clock_nsec >= 294967296`, the wrapped nanosecond stays below one second and the code does not carry into `tv_sec`. The stored deadline is the same second and exactly 294967296 ns earlier than the clock, so it is already in the past. `pthread_cond_timedwait` returns at once (`err=73`). The heartbeat loop keeps ticking, `sendHeartBeat()` reaches transport, and SEDP HEARTBEAT / DATA appear on the wire.
- If `clock_nsec < 294967296`, the wrapped nanosecond is negative. The comparison against unsigned `TIMESPEC_NANOSEC` promotes that negative value, and the carry adds 18446744073 seconds. The deadline is about 584 years ahead. `sleep_return` and `heartbeat_delay_return` are absent for the whole 60-second gate. There is no SEDP transport send and no Wasm -> peer SEDP HEARTBEAT or DATA.

| Run | Gate | First `clock_nsec` | Deadline second minus clock second | Nanosecond change |
|---|---|---:|---:|---:|
| 46 | timeout | 30555024 | 18446744073 | +414584320 |
| 47 | timeout | 28572480 | 18446744073 | +414584320 |
| 48 | pass | 630305763 | 0 | -294967296 |
| 49 | pass | 512967043 | 0 | -294967296 |

run-46 deadline log: clock `1790593469.030555024`, deadline `20237337542.445139344`. run-48 deadline log: clock `1790593679.630305763`, deadline `1790593679.335338467`, then `sleep_return idx=0 err=73` in the same host millisecond.

## Success path after the sleep returns

run-48 publications writer, same host second `2026-09-28T11:07:59`:

- `11:07:59.661` `[SEDP-HB] heartbeat_transport_before` `first=0:1 last=0:1 count=1`.
- `11:07:59.661` passive HEARTBEAT `writer_id=000003c2` `first_sn=0:1` `last_sn=0:1` `count=1` from `172.18.0.3:7410` to `172.18.0.5:7410`.
- `11:07:59.662` passive ACKNACK `base_sn=0:1` `num_bits=1` `bitmap=0x80000000` `count=1` from the peer.
- `11:07:59.665` `acknack_action action=send_data sequence=0:1` after `acknack_dispatch writer_found=1` and `acknack_proxy_matched`.
- `11:07:59.667` `sedp_senddata_transport_before sequence=0:1`, and the passive SEDP DATA sequence `0:1` at the same timestamp.

run-49 repeats that chain at `11:08:26.540` through `11:08:26.546`. The fast loop then emits thousands of HEARTBEAT frames because the broken deadline is in the past, not because the configured period elapsed.

## What the timeout ACKNACKs do

On run-46 and run-47 the peer's real reader prefix never appears in an ACKNACK. The ACKNACKs that do arrive use source prefix `010f06411e00ffff00000000`, base `0:0`, `num_bits=0`. `MessageReceiver` finds the local SEDP writer (`writer_found=1`) and `onNewAckNack()` drops them with `reason=no_matching_reader_proxy` even though `proxies_empty=0`. The registered real peer prefix is different (`8fee198f...` on run-46). The same unmatched `010f0641...` drop also occurs late on both passes, after the real peer has already matched and resent sequence `0:1`. It is not the first split.

## Judgment

This is branch A of the plan, narrowed to the sleep implementation. The heartbeat thread is created and the first tick runs. The thread does not reach a second tick on a timeout because `vTaskDelay(4000)` does not return. The next place to inspect is `add_timespec()` in `cmsis-wasm/src/core/cmsis_wasm_thread_sync.c`, specifically the 32-bit `tv_nsec` addition and the unsigned comparison that follows. A fix stays in a separate reviewed plan.

## What was not done

No behavior fix. No change to heartbeat period, resend rules, sequence numbers, ReaderProxy registration, QoS, Docker network, or the application. run-31 through run-40 were not edited. These four trials were not committed or pushed.
