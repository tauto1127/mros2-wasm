# Handoff: continue SEDP race diagnosis

Continue the plan at `/tmp/life-wiki/llm-context/working/mros2-wasm-sedp-race-diagnostic-plan.md`. Follow the repository `AGENTS.md` and `/home/osslab/.codex/RTK.md`; shell commands must use `rtk`. Do not commit or push.

## State

- run31 is the first trial in this new `[SEDP-RACE]` series. It completed Phase A only; no checkpoint or restore was attempted.
- The 60-second pre-C/R gate passed with 10 complete ID/body round trips. Cleanup stopped and removed this trial's three containers. The shared network was retained, its post-cleanup inspection is in `raw/network-post-cleanup.json`, and `raw/staged-compare.txt` says `unchanged`.
- Run31 is success 1, failure 0. Continue Phase A until there are two successes and two failures, or 10 trials total. Do not count runs 08–30 as trials in this newly instrumented series; they used different instrumentation or controls.
- No trial after run31 has been created or started. The next trial is run32.

## run31 evidence

See `report.md`, `raw/run-analysis.json`, `raw/sedp-race-trace.jsonl`, `raw/wire-counts.md`, `raw/roundtrip-id-analysis.md`, `raw/roundtrip-gate.status`, and `raw/orchestrator-result.json`.

Both app SEDP changes (`/to_linux` publication and `/to_stm` subscription, sequence `0:1`) were progressed while the proxy list was empty. Each progress exit advanced to `0:2` with `send_attempted=0`; the corresponding builtin reader proxy was added later. Despite that ordering, the gate passed. The pre-gate passive capture recorded 15 Wasm-to-peer SEDP DATA submessages, 2 peer-to-Wasm SEDP DATA submessages, bidirectional SEDP HEARTBEAT traffic, and 23 user DATA submessages in each direction. The existing observer does not capture DATA sequence numbers, so these packets cannot yet be attributed to the two sequence-1 changes.

There are 13 structured trace events. Two raw stdout lines include an existing WAMR receive-log prefix before a complete `[SEDP-RACE]` event; the event payloads and sequence numbers were extracted into the structured trace. Preserve this as an evidence limitation.

## Reuse these artifacts

The instrumented Wasm application was built once in a separate temporary source/build tree. Reuse this exact artifact for subsequent trials; do not overwrite it:

| Artifact | Path | SHA-256 |
|---|---|---|
| Wasm app | `/tmp/mros2-wasm-sedp-race-20260928-run31/app/echoback_string.wasm` | `9e926d0f13c9fbfcd003710c0ff01cd7c0229352a05b1efba9d0a97b2d378d46` |
| iwasm runtime | `/tmp/mros2-wasm-cr-rerun-20260927/runtime/iwasm` | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| Native peer | `/tmp/mros2-posix-run04-final-build/mros2-posix` | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |

Build/source details and hashes are in `metadata.md`, `raw/build-commands.md`, `raw/build-input-hashes.txt`, `raw/submodules-commits.txt`, `raw/app-staged.diff`, and the `raw/*.patch` files. Successful build output is `raw/cmake-configure-final.log` and `raw/build-retry2.log`. Earlier failed configure/build attempts are also retained and explain the generated CMSIS/lwIP inputs and temporary `LWIP_PROVIDE_ERRNO` adjustment.

The run31 Wasm artifact is a fresh instrumented build from the pinned source snapshots plus the staged app source; it is not byte-for-byte the run08/09 Wasm artifact. Run09's `raw/build-provenance-limit.md` records that the original dirty source snapshot cannot be reconstructed completely. Keep that comparability limit explicit in any series-level conclusion.

## Next trial checklist

1. Create `runs/run-32/` with a fresh empty `raw/` directory. Copy the trial scripts and `plan.md`, `procedure.md`, and `metadata.md` from run31. Copy the static source/revision/hash evidence or link it clearly to run31.
2. Change only trial identity fields in the copied orchestration: `run-32`, container names ending in `run32`, tag `[SEDP-RACE-RUN32]`, and the unique state path `/tmp/mros2-wasm-sedp-race-20260928-run32/state`. Keep the Wasm artifact path and expected hash at the run31 artifact above.
3. Preserve the existing Docker image/network checks, addresses (`172.18.0.3` Wasm, `172.18.0.5` peer), peer-side passive capture, and copied 60-second `pre` gate. Do not checkpoint or restore in Phase A.
4. Run with `rtk python3 orchestrate.py`, analyze the new raw logs with the copied `analyze_run.py`, and verify cleanup and staged-path comparison before starting another trial.
5. Update a series-level summary with one classification per trial. Stop Phase A at two passes and two timeouts, or after 10 trials. Only then decide whether Phase B is justified. Do not add a behavior fix to this diagnosis.

The exact reusable scripts are `orchestrate.py`, `peer_collector.py`, `wiretap_collector.py`, `rtps_wire_tap.py`, `run_wasm_phase.py`, `roundtrip_evidence_gate.py`, and `analyze_run.py` in this directory.
