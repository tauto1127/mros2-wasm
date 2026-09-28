# run-29 nanosleep control

Startup-only control. Same discovery probe and pre-checkpoint gate, but only the two SEDP builtin writer heartbeat loops use POSIX `nanosleep(4s)` instead of `vTaskDelay -> osDelay -> WasmThreadSyncSleep`. No checkpoint/restore is run.
