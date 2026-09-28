# run-08 procedure

This is one fixed-condition same-IP trial using the run-04 artifacts. It uses only the existing local Docker network `mros2-cr-net` and does not rebuild binaries or modify network settings.

## Fixed identities

- Experiment ID: `run-08`.
- Docker network: `mros2-cr-net` (`609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`).
- Wasm runner: `mros2-cr-run08-wamr`, `172.18.0.3`.
- Native mROS 2 peer: `mros2-cr-run08-native-peer`, `172.18.0.5`.
- Passive observer: `mros2-cr-run08-wiretap`, sharing the peer network namespace with `CAP_NET_RAW`.
- Image: `ros:humble`, expected ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`.
- Runtime/app/native peer are mounted read-only from their run-04 paths; hashes are recorded in `raw/artifact-hashes-preflight.txt`.
- Checkpoint state is stored only under `/tmp/mros2-wasm-cr-rerun-20260928-run08/state/`.

## Sequence and gates

1. Confirm the three binary hashes, image ID, empty network attachments, free container names, and unused experiment/temp directories. If a precondition differs, stop before launching anything.
2. Start the native peer at `.5`, then the passive wire observer. Start `iwasm` in checkpoint mode at `.3` with the run-04 argv.
3. `roundtrip_evidence_gate.py pre` allows 60 seconds from the verified WAMR process and requires ten distinct messages with equal bodies and ordered events: Wasm publish, native receive, native echo publish return, Wasm callback.
4. `roundtrip_evidence_gate.py baseline` requires ten further complete messages during a 30-second no-checkpoint interval. Checkpoint is forbidden unless both gates pass.
5. Record the greatest pre-signal publish ID `N`, send `SIGUSR2` to the verified checkpoint `iwasm` PID, and preserve the native peer and wire observer while saving state.
6. Restore the same runtime and app in the same `.3` container. The post gate starts its 90-second limit at the verified restore process and requires ten distinct IDs greater than `N`, with identical payloads across both subscriber callbacks and ordered events.
7. Stop only the new app processes and containers. Leave `mros2-cr-net` unchanged. Save the state file list and SHA-256 manifest, but keep the state body in `/tmp`.

All command lines, process IDs, UTC and monotonic times, raw application logs, gate evidence, Docker inspection, and cleanup results are recorded under `raw/`.
