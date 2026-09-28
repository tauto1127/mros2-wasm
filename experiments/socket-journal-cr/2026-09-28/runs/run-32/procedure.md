# run-32 procedure

Phase A startup-only cold-start trial under the SEDP diagnostic plan.

- Start the existing native peer at `172.18.0.5` and Wasm participant at `172.18.0.3` on the existing `mros2-cr-net` network.
- Start the existing peer-side passive RTPS observer in the native peer's network namespace.
- Launch the Wasm application with the unchanged run-31 instrumented artifact and the same iwasm runtime used for runs 08/09.
- Apply the copied 60-second `pre` round-trip evidence gate unchanged: pass requires 10 distinct ordered ID/body round trips across Wasm publish, native receive, native echo publish-return, and Wasm callback.
- Stop this trial's processes and its three named containers after the gate. Do not checkpoint or restore.
- Record `[SEDP-RACE]` rows from the Wasm log and direction-specific RTPS packet counts from `peer-wire.jsonl`.

This directory is the second independent instrumented trial. Later trials, if needed, use new `run-NN` directories and unique `/tmp` state directories with the same artifact and conditions.
