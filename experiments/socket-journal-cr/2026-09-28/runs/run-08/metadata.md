---
sources:
  - "plan.md"
  - "../../../2026-09-27/runs/run-04/metadata.md"
  - "../../../2026-09-27/runs/run-07/report.md"
  - "raw/artifact-hashes-preflight.txt"
  - "raw/roundtrip-gate.status"
  - "raw/roundtrip-id-analysis.md"
  - "raw/wasm-checkpoint.log"
  - "raw/peer-native.log"
  - "raw/network-post-cleanup.json"
---
# run-08 metadata

## Result

The pre-checkpoint application gate timed out. Fifty-six distinct IDs had matching bodies in the Wasm publish, native receive, and native echo-publish-return logs, but no Wasm `/to_stm` subscriber callback was recorded. The pre-checkpoint gate therefore had zero complete round trips. The 30-second baseline, checkpoint, and restore were not run.

## Fixed conditions

| Item | Measured condition |
|---|---|
| Experiment ID | `run-08` |
| Host time | All timestamps below are UTC; host timezone is Asia/Tokyo. |
| Root repository | `debug/recvfrom-observability`, HEAD `0842ac9782cf51c5806619c2c3af9e1467435727`. |
| Network | Existing `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, bridge subnet `172.18.0.0/16`, gateway `172.18.0.1`. |
| Network use | Zero attached containers at preflight and after cleanup. The network ID and subnet were unchanged. |
| Image | `ros:humble`, image ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`. |
| Wasm | `mros2-cr-run08-wamr`, IP `172.18.0.3`, container ID `2bd3d6be6610d0425e71f7cd97548ff43f826a11c345fbc1795a468be8ac5fd8`. |
| Native peer | `mros2-cr-run08-native-peer`, IP `172.18.0.5`, container ID `bd85158ee23370f25e03a62cf94c7a415f6b56e4e45f397c86241c048ce54332`. |
| Wire observer | `mros2-cr-run08-wiretap`, sharing the native peer network namespace with `CAP_NET_RAW`, container ID `59c55045ab09d10b1db4ff06bb6753d030d716c3e40f9d1e4c23b42598feacf4`. |
| Topics and message | Wasm publishes `/to_linux` and subscribes `/to_stm`; native mROS 2 does the reverse. `std_msgs/msg/String`, Domain 0; the peer echoes the same body. |
| State path | `/tmp/mros2-wasm-cr-rerun-20260928-run08/state/`; no checkpoint files were created. |

Container inspection is in `raw/*container-inspect.json`; commands are in `raw/*container.command.txt`. Preflight and final Docker state are in `raw/network-preflight.json`, `raw/network-post-cleanup.json`, and the container inventories.

## Executables and source provenance

The three executable files were measured before launch and match run-04 metadata and run-07:

| Artifact | Path | SHA-256 |
|---|---|---|
| `iwasm` | `/tmp/mros2-wasm-cr-rerun-20260927/runtime/iwasm` | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| Wasm app | `/tmp/mros2-wasm-cr-rerun-20260927/app/echoback_string.wasm` | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| Native app | `/tmp/mros2-posix-run04-final-build/mros2-posix` | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |

Run-04 source revisions recorded for those artifacts: root `0842ac9782cf51c5806619c2c3af9e1467435727`; Wasm mROS 2 `a8d4481c4531f77b143d5e78ac32b333c338b0a2`; Wasm lwIP `5acfdb028b8d1b8ddf158671eeb7e539901ac11a`; WAMR `2dd4eae0f301dd100e651c037ce6a3a8f56cce5e`; native POSIX source `d267988c279411a685d63956e42e05d9bfc32b56`; native mROS 2 `24a4a233672ff823429d11dfc30112c3f298c374`; native lwIP POSIX `f1d576bde977f20a452654ab283fa11c03a2ffc1`.

No source was built or modified for this trial. The known run-04 native build changes and the limit on reconstructing its dirty source snapshot are recorded in [`raw/build-provenance-limit.md`](raw/build-provenance-limit.md). The current repository snapshot is in `raw/git-status-preflight.txt`; all 310 staged entries had the same status and paths in the preflight and post-run snapshots. No commit or push was made.

## Timeline and gate

| Stage | UTC and outcome |
|---|---|
| Native peer process collector started / peer ready | `03:29:03.267` / `03:29:03.510` |
| Passive wire observer ready | `03:29:03.338` |
| Wasm runner launched / process verified | `03:29:09.648` / `03:29:09.822`, container PID 14, argv recorded in `raw/wasm-checkpoint.command.txt` |
| Pre-checkpoint window | Verified-process time `03:29:09.822` through the 60-second deadline `03:30:09.822`; gate completed at `03:30:09.857` with `result=timeout`. In `roundtrip-gate.status`, `start_utc` is the gate script invocation time, while `start_mono_ns` and the deadline use the earlier verified-process monotonic time. |
| Pre-checkpoint evidence | 58 distinct publish IDs and 58 native receive IDs were present in the window. Fifty-six ID/body pairs matched across Wasm publish, native receive, and native echo-return records. Wasm callback count was 0; complete ordered round trips were 0. See `raw/roundtrip-gate.status` and `raw/roundtrip-id-analysis.md`. |
| 30-second no-checkpoint baseline | Not run because the first gate failed. |
| Checkpoint and restore | Not run. No `SIGUSR2`, Socket Journal dump, restore process, or post-restore window occurred. |
| Wasm process stopped | `03:36:29.263`, explicit `SIGTERM`, collector exit status 143. Traffic logged after the 60-second deadline is outside the acceptance window and was not counted. |
| Native peer stopped / wire capture closed | `03:37:12.915` / `03:37:12.898`; native collector exit 143 after explicit stop, passive observer exit 0 after its signal handler wrote `capture_stop`. |
| Containers removed / final network inspection | `docker stop` and `docker rm` succeeded for all three run-08 containers. Final network inspection recorded zero attachments and the original network ID. |

`raw/topic-list.log` captured `/parameter_events`, `/rosout`, `/to_linux`, and `/to_stm` as ancillary graph information. It does not establish delivery. `raw/peer-wire.jsonl` is passive packet metadata and does not decode application payloads.

## Cleanup and state

The three run-08 containers and their application processes were stopped and removed. The shared network was retained. The run-specific state directory remains in `/tmp` and is empty; `raw/checkpoint-state-files.txt` records that no checkpoint state was produced, and `raw/checkpoint-state-files.sha256` is empty. Cleanup commands and results are in `raw/cleanup-commands.txt`, `raw/docker-stop.txt`, and `raw/docker-rm.txt`.
