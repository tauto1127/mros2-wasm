# run-49 metadata

## Scope

Cold-start SEDP heartbeat/ACKNACK observation. No checkpoint or restore.

## Artifact

- Wasm: `/tmp/mros2-wasm-sedp-hb-vtask-20260928/app/echoback_string.wasm`
- Wasm SHA-256: `e1ef90ff5ece66769e3ec40b4e454b92cecfc4457b1db6a1861fcd83dc609a40`
- Build tree: `/tmp/mros2-wasm-delaydiag-20260928-build`
- Runtime SHA-256: `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a`
- Native peer SHA-256: `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`

## Fixed conditions

- Docker network: `mros2-cr-net`
- Wasm: `172.18.0.3`
- Native peer: `172.18.0.5`
- State path: `/tmp/mros2-wasm-sedp-hb-vtask-20260928-run49/state`
- Heartbeat delay for every stateful writer: `vTaskDelay(SF_WRITER_HB_PERIOD_MS)` with period 4000
- Checkpoint/restore: not run
