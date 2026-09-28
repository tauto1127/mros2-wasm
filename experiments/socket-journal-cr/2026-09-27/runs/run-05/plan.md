# run-05 plan: SIGUSR1 no-op control for blocked socket receives

## Question

Does receiving a process signal by itself interrupt the WAMR/WASI socket receive path, or does the checkpoint routine's explicit wake-up of blocked WAMR operations produce the `EINTR` observed in run-04?

## Design

- Reuse the exact run-04 `iwasm`, Wasm app, native mROS 2 peer binary, `ros:humble` image, Docker bridge, and addresses. Expected hashes are checked by the runner before launch.
- Start a fresh native peer at `172.18.0.5` and Wasm runner at `172.18.0.3` on the existing `mros2-cr-net`. Refuse to start if the network is occupied or the run-05 container names already exist.
- Wait for ten distinct same-ID app round trips before sending a signal.
- Send `SIGUSR1` to the verified iwasm PID. In this WAMR build, the signal-control thread consumes SIGUSR1 and logs it without calling the checkpoint routine or waking blocked socket calls.
- For eight seconds after that handler is observed, require at least five additional full round trips and no WASI `errno=27`, no SIGUSR2 handler, and no checkpoint completion.
- Stop only the run-05 processes/containers. Do not modify or remove the shared Docker network or prior checkpoint state.

## Comparison and limits

The treatment reference is run-04: SIGUSR2 entered the checkpoint routine, which explicitly wakes threads blocked in socket syscalls; four `sock_recv_from` calls then returned WASI errno 27. Run-05 tests whether a different signal that is merely consumed by `sigwait` has the same effect. This is a signal-mechanism control, not a C/R run and not a reproduction of the 9/17 callback-loss failure.

## Pass/fail

Pass only if ten full round trips occur before SIGUSR1, the SIGUSR1 handler is logged, at least five new full round trips occur afterward, and no WASI errno 27 or checkpoint event occurs. The runner exits nonzero on a failed gate and saves the evidence under this run directory.
