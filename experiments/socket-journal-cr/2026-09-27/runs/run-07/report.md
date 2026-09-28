# Socket Journal C/R experiment report — run-07

## Conclusion

**The same-IP rerun succeeded once.** The native POSIX mROS 2 peer received and echoed Wasm app data before checkpoint. After restoring the Wasm process in the same container at `172.18.0.3`, ten new message IDs completed the full application round trip.

The result applies to this run on one physical host, using the existing Docker bridge, the same IP, and the recorded runtime and app artifacts. It does not establish migration to another IP or another host.

## Setup

- Wasm mROS 2: WAMR `iwasm` and `echoback_string.wasm`, container IP `172.18.0.3`.
- Peer: native POSIX mROS 2 executable, container IP `172.18.0.5`; subscribes to `/to_linux` and echoes to `/to_stm`.
- Network: existing `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, subnet `172.18.0.0/16`.
- Image: `ros:humble`, image ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`. The peer was the native mROS 2 executable, not an `rclpy` node.
- The runtime, Wasm, and peer executable hashes matched the successful run-04 artifacts; see `raw/artifact-hashes.txt`.

## Results

| Gate or stage | Result |
|---|---|
| Pre-checkpoint full-round-trip gate | Pass: 31 matching IDs observed across Wasm publish, peer receive, peer echo, and Wasm callback. |
| No-checkpoint baseline | Pass: 30.069 seconds, 27 new full round trips. |
| Checkpoint | PID 14 was verified against the expected `iwasm` command before `SIGUSR2`. Maximum publish ID at signal time was `N=102`; checkpoint exited 0. |
| Socket Journal dump | `main-socket.img`: 222 operations, `overflow=0`, `result=0`. |
| Restore and replay | PID 59 restored at `.3`; 222/222 operations succeeded, with 0 failures, fallbacks, skipped operations, or unknown operations. |
| UDP receive recovery | All four local ports (7400, 7401, 7410, 7411) reported `result=ok`. |
| Post-restore full-round-trip gate | Pass: 10 distinct IDs greater than 102: `103, 104, 105, 106, 108, 109, 110, 111, 112, 113`. |

The post-restore gate saw 12 publish IDs, 12 peer receives, 12 peer echo returns, and 11 Wasm callbacks; ten IDs appeared in all four sets. The skipped ID 107 was not counted as a complete round trip.

The passive capture recorded 142 RTPS DATA frames to UDP port 7411 in each direction over the full capture interval. Application IDs were matched from the Wasm and native peer logs; the wire capture does not decode application payloads.

## Interpretation and limits

This run independently reproduced the run-04 same-IP outcome once. The Socket Journal dump/replay, four receive-socket recoveries, and new bidirectional app traffic all completed in this run. It does not prove cross-host or changed-IP migration, nor establish a general success rate. The observed `errno=27` during restore is recorded in the raw log; this run does not establish its cause.

The experiment containers were stopped and removed. The shared Docker network retained its original ID and was empty after cleanup. No project files were committed.

## Evidence

- `raw/roundtrip-gate.status`, `raw/no-cr-baseline.status`, `raw/postcr-gate.status`: gate decisions and matched IDs.
- `raw/checkpoint-signal.log`, `raw/wasm-checkpoint.log`, `raw/wasm-checkpoint.status`: verified signal, checkpoint, and journal dump.
- `raw/wasm-restore.log`, `raw/wasm-restore.status`: replay, receive recovery, and controlled process stop.
- `raw/peer-native.log`: native peer callback receives and echo calls.
- `raw/peer-wire.jsonl`: passive RTPS/UDP observation.
- `raw/checkpoint-state-files.txt`, `raw/checkpoint-state-files.sha256`: state inventory and hashes; state files remain in `/tmp`.
