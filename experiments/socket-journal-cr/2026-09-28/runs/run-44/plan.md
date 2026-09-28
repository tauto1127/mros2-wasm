# run-44 osDelay deadline diagnostic

Same no-C/R cold-start test as run-42/43. The artifact adds only diagnostic
prints around cmsis-wasm WasmThreadSyncSleep for timeout=4000:
CLOCK_REALTIME result, computed absolute deadline, and pthread_cond_timedwait return.
