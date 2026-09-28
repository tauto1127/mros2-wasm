# run-45 metadata

## Scope

Instrumentation sanity check only; no checkpoint or restore.

## Artifact

- Wasm: `/tmp/mros2-wasm-sedp-hb-20260928/app/echoback_string.wasm`
- Wasm SHA-256: `6cddd4b77fe1a5eaccf8de85af351272de6d228ce49ef1dfeafb6e4480195c81`
- Runtime and native peer are unchanged from run-31--40.
- Source instrumentation is limited to SEDP heartbeat/ACKNACK observation; send decisions are unchanged.

## Fixed conditions

- Docker network: `mros2-cr-net`
- Wasm: `172.18.0.3`
- Native peer: `172.18.0.5`
- State path: `/tmp/mros2-wasm-sedp-hb-20260928-run45/state`
- Checkpoint/restore: not run
