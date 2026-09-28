# run-47 plan

SEDP HEARTBEAT / ACKNACK diagnostic trial. No checkpoint/restore and no behavior fix.

The committed tree slept SEDP writers with `nanosleep`. run-31 through run-40, which produced the run-38 timeout, called `vTaskDelay` (`osDelay`). This trial restores that `vTaskDelay` call and adds `[SEDP-HB]` logs only. Heartbeat period, resend decisions, sequence numbers, ReaderProxy registration, QoS, and the application are unchanged.

Logs cover heartbeat thread create, loop start, sampled ticks, delay enter/return, `sendHeartBeat()` enter/skip/history, transport send before/after, ACKNACK receive/dispatch/`onNewAckNack()`, ReaderProxy lookup, and `sendData()`. The first 24 `osDelay(4000)` calls also log the computed absolute deadline and `pthread_cond_timedwait` result. Passive capture keeps DATA sequence, HEARTBEAT first/last/count, and ACKNACK base/bitmap/count.
