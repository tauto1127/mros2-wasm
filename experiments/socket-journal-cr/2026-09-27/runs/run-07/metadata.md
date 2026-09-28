# run-07 metadata

## Execution

- Date: 2026-09-28 (UTC).
- Method: manual, phase-by-phase rerun using the acceptance gates from [`run-04/plan.md`](../run-04/plan.md).
- Wasm container: `mros2-cr-manual-20260928-01-wamr`, `172.18.0.3`.
- Native peer container: `mros2-cr-manual-20260928-01-peer`, `172.18.0.5`.
- Wire observer: `mros2-cr-manual-20260928-01-wiretap`, sharing the peer network namespace with `CAP_NET_RAW`.
- All three containers were stopped and removed after the run. The existing network was not changed.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| `iwasm` | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| `echoback_string.wasm` | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| Native peer executable | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |
| `main-socket.img` | `9c4835afe110f24d00037522f355593ce0fd79a31bd53ace1a9bd755f5c065aa` |

The runtime and Wasm were mounted read-only from `/tmp/mros2-wasm-cr-rerun-20260927/{runtime,app}`. The peer executable was mounted read-only from `/tmp/mros2-posix-run04-final-build/mros2-posix`.

## Commands and state

- Checkpoint and restore argv: `/runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 [--restore] /artifact/echoback_string.wasm`.
- Checkpoint signal: `SIGUSR2` to verified container PID 14. Restore ran with PID 59 and was stopped with `SIGTERM` after the post-restore gate passed; its collector exit status 143 is the expected result of that explicit stop.
- Checkpoint state: `/tmp/mros2-wasm-cr-manual-20260928-01/state/` (about 1.1 GiB). The state body is not in Git.
- Raw execution logs were first captured under `/tmp/mros2-wasm-cr-manual-20260928-01/raw/` and copied unchanged to this run's `raw/` directory. The temporary run directory remains available for inspection.
