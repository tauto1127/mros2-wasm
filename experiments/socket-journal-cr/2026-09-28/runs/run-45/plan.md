# run-45 plan

Instrumentation sanity check for the SEDP HEARTBEAT / ACKNACK diagnostic plan. No checkpoint/restore and no behavior fix. Confirm that `[SEDP-HB]` traces cover heartbeat thread/loop, `sendHeartBeat()`, ACKNACK dispatch, ACKNACK-driven `sendData()`, and that transport-send traces correlate with passive RTPS frames.
