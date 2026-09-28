# run-48 report

Gate `pass`, 10 complete round trips. Wasm -> peer SEDP DATA 7, Wasm -> peer SEDP HEARTBEAT 2229, peer -> Wasm user DATA 14.

The first SEDP sleep saw `clock_nsec=630305763`. The sleep result was `immediate return`. Thread create, loop start, tick 1, and `heartbeat_skip reason=no_proxies` happened before that sleep on this run, as on the other three trials.

Shared artifact `e1ef90ff5ece66769e3ec40b4e454b92cecfc4457b1db6a1861fcd83dc609a40`. No checkpoint or restore. The comparison and the deadline arithmetic are in `/home/osslab/mros2-wasm-service-communication-socket-journal/experiments/socket-journal-cr/2026-09-28/sedp-hb-diagnostic-report.md`.

Cleanup removed this trial's containers. `raw/orchestrator-result.json` records the cleanup result. Source diffs are `raw/instrumentation-statefulwriter.diff`, `raw/instrumentation-messagereceiver.diff`, and `raw/instrumentation-cmsis-sleep.diff`.
