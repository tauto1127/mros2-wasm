# run-37 passive wire counts

Window: Wasm process verification through pre-gate completion (`2026-09-28T09:05:54.613000+00:00` to `2026-09-28T09:06:24.129000+00:00` UTC).
Counts are captured DATA submessages or frames containing a HEARTBEAT submessage; DATA is identified by the RTPS builtin SEDP writer entity IDs on metatraffic port 7410, and non-builtin writer IDs on user port 7411.

- `wasm_to_peer_sedp_data_frames`: 7
- `wasm_to_peer_sedp_data_submessages`: 7
- `wasm_to_peer_sedp_heartbeat_frames`: 892
- `peer_to_wasm_sedp_data_frames`: 2
- `peer_to_wasm_sedp_data_submessages`: 2
- `peer_to_wasm_sedp_heartbeat_frames`: 14
- `wasm_to_peer_user_data_frames`: 26
- `wasm_to_peer_user_data_submessages`: 26
- `peer_to_wasm_user_data_frames`: 26
- `peer_to_wasm_user_data_submessages`: 26
- `rtps_frames_in_gate_window`: 1873
