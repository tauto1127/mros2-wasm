# T10b implementation result — NOT READY

Implemented a narrow actual-source T10b runner mode and exercised three failure-injection assertions against the production projection path. The requested full T10b matrix is **not complete**; this report does not claim T10b passed.

## Changed files

- `validation/rtps/projection-fixture.cpp`: test-only linker wrappers for real `pbuf_alloc`, `pbuf_take_at`, and `ucdr_serialize_array_uint8_t` that delegate except at the injected call; snapshots SPDP output bytes, latest history payload bytes/sequence, and applied IP; adds failure checks and retry/equal-IP checks.
- `validation/rtps/run-task.sh`: recognizes T10b, links the three wrappers, and checks the emitted assertions.

No production source was edited, and no files are staged. Existing worktree changes were preserved.

## Commands and raw evidence

Command: `bash validation/rtps/run-task.sh T10b`

Result: exit 0, `PASS T10b artifacts=/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl/validation/rtps/runs/20261002T060418-T10b-2254653`

Raw assertion output from `validation/rtps/runs/20261002T060418-T10b-2254653/run.log`:

```text
T10b_PREP_FAIL_PASS stage=ucdr_serialize applied_unchanged=1 spdp_history_unchanged=1 output_unchanged=1\n
T10b_PREP_FAIL_PASS stage=pbuf_alloc applied_unchanged=1 spdp_history_unchanged=1 output_unchanged=1\n
T10b_PREP_FAIL_PASS stage=pbuf_take_at applied_unchanged=1 spdp_history_unchanged=1 output_unchanged=1\n
T10b_BASELINE_PASS appliedA_to_B_retry=1 equal_noop=1
```

The `\\n` shown in three failure lines is literally present in this run's output because the test printf uses an escaped backslash-n.

Artifact SHA-256:

```text
projection-fixture.cpp 39e4316a210303990a48b5d4e0a0b9be320e525414725d1daf1db47bfe18caed
run-task.sh            51031c73f22ff12b3e548bc782fda2a2312ef204c7ae08c035fdb2b52fd3daf4
run.log                9aa613993d1e876e682b3acef4965d41a17d78cce840f92006edb416d8d9db59
fixture.wasm           86078fad4759fad94c9eff11ce2fb76d3a98e4c8e3f34fca44b80a1e6f665933
```

One earlier T10b attempt failed an assertion because the injected Micro-CDR failure did not set its sticky error bit; its source checkpoint, binary, and raw log remain preserved at `validation/rtps/runs/20261002T060237-T10b-2254531/`. No test run artifacts were overwritten.

## Not yet covered (therefore not accepted as passed)

- Failure injection at every individual prepare-call position (only first call per three API classes).
- Initial-zero failure and subsequent successful A; B-failure from initial-zero then A; unchanged-coordinator retry semantics in the full requested states.
- User endpoint locator/history/cursor snapshots, SEDP payload immutability and normal ring-full behavior, SPDP latest-only resend/cursor checks, >history2 rejection.
- Proof of zero pbuf/new allocations after preparation during commit and explicit temporary-allocation release assertions.

The executed harness uses a real Participant and production projection, but has zero user endpoints, so it cannot establish the SEDP/history cases above. No production bug was diagnosed. No `git add`, commit, push, Docker, or full-suite command was run.
