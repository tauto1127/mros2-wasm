# run-41 SEDP recovery-path diagnostic

- No checkpoint/restore.
- Same network/IP/native peer/runtime as run-31 through run-40.
- Wasm artifact is rebuilt from the run-31 temporary source snapshot.
- Behavior remains on the original vTaskDelay heartbeat path.
- Added observation only for SEDP heartbeat thread lifecycle, sampled heartbeat sends,
  ACKNACK receipt/replay, and actual SEDP DATA send.
- Passive wire tap additionally decodes DATA sequence numbers, HEARTBEAT first/last,
  and ACKNACK base/bitmap/count.
