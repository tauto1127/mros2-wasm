# run-10 procedure

- Native peer: existing run-04 binary, container `mros2-cr-run10-native-peer`, `172.18.0.5`.
- Wasm: instrumented `echoback_string.wasm`, container `mros2-cr-run10-wamr`, `172.18.0.3`.
- iwasm: same binary as run-09.
- Observer: passive wiretap in peer namespace.
- Gate logic: copied from run-09 unchanged except run identity.
- No commit/push. Shared Docker network is not modified.
