# run-09 procedure

This file was written before the containers were started. It fixes how run-09 reads the plan. The binaries, image, network, and addresses stay at the run-04 values. Nothing is rebuilt, and the shared network is not edited.

## Identity

- Experiment ID: `run-09`. `run-08` already occupies `2026-09-28/runs/run-08/` and is left unchanged.
- Network: existing `mros2-cr-net` (`609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`), subnet `172.18.0.0/16`.
- Wasm: container `mros2-cr-run09-wamr` at `172.18.0.3`.
- Native mROS 2 peer: container `mros2-cr-run09-native-peer` at `172.18.0.5`. The peer process stays up across checkpoint and restore.
- Passive observer: container `mros2-cr-run09-wiretap`, joined to the peer network namespace with `CAP_NET_RAW` only. It does not inject packets and does not enable promiscuous mode.
- Image: `ros:humble`, image ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`.
- Executables, read-only: `/tmp/mros2-wasm-cr-rerun-20260927/runtime/iwasm`, `/tmp/mros2-wasm-cr-rerun-20260927/app/echoback_string.wasm`, `/tmp/mros2-posix-run04-final-build/mros2-posix`.
- Checkpoint body: `/tmp/mros2-wasm-cr-rerun-20260928-run09/state/` only. The Git directory receives the file list and SHA-256 manifest.

If any hash, image ID, network ID, container name, or address is already different or occupied, the run stops before `docker run`. A failed gate does not lead to a second attempt.

## Launch order

1. Native peer container, wiretap container, then Wasm container.
2. Native peer process, then the passive observer, then `iwasm` in checkpoint mode. The argv is the run-04 argv: `/runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 /artifact/echoback_string.wasm`, working directory `/state`. Restore adds `--restore` in the same container and at the same address.
3. The peer log must show `ip=172.18.0.5` before Wasm starts. `ros2 topic list` runs only after the timed gates, so it is not inside the acceptance windows.

## What counts as one round trip

All four raw-log lines must carry the same ID and the same quoted body:

`Wasm APP publish_begin` → `native peer_receive` → `native peer_echo_publish_return` → `Wasm APP callback`

Order is accepted only when every item below holds:

- The Wasm log line of `publish_begin` is earlier than the Wasm log line of `callback`.
- The native log line of `peer_receive` is earlier than `peer_echo_publish_return`, and the native `epoch` increases.
- The host monotonic time on the Wasm callback is later than the host monotonic time on the native echo return.
- The host monotonic time on native receive is later than Wasm publish, or earlier by less than 100 ms. A smaller inversion is recorded as `collector_skew`. The body is created at publish and can appear in the native callback only after that send; run-08 already saw about 0.5 ms of collector delay on this path. An inversion of 100 ms or more does not count.

`recvfrom` success, a send-call return, the topic list, and the packet capture do not count as a round trip. The pass count is the number of distinct IDs that meet the rule above. The status file also records how many of those IDs are strictly ordered by host monotonic time alone.

## Windows

- Pre-checkpoint: 60 seconds from `event=process_verified` on the checkpoint `iwasm`. At least 10 distinct IDs.
- No-checkpoint baseline: the next 30 seconds. At least 10 distinct IDs greater than the largest Wasm publish ID already present when the window opens. No signal is sent in this window.
- Checkpoint only if both windows pass. `N` is the largest Wasm publish ID in the checkpoint log immediately before `SIGUSR2` to the verified checkpoint PID.
- Post-restore: 90 seconds from `event=process_verified` on the restore `iwasm`. At least 10 distinct IDs greater than `N` whose `APP publish_begin` is in the restore log. Older buffered receives and lines after the deadline are not counted.

## Stop

After the last window, only the three run-09 containers and their experiment processes are stopped and removed. `mros2-cr-net` stays. No commit and no push.
