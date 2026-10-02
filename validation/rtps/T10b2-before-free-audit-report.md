# T10b2 fixture result — subset only

Implemented test-only Nth-call failure wrappers and a T10b2 runner dispatch. Baseline valid projection counted all invoked prepare positions, then each position was failed individually with a prepared A state and compared against A's user locator address, SPDP output/history bytes+sequence, pub/sub/SPDP latest retained payload/history bounds and cursors, and applied IP. Actual primitive implementations are delegated to except on injected failure; UCDR sets sticky error. No production source was changed.

Run: `bash validation/rtps/run-task.sh T10b2` — PASS. Raw output: `validation/rtps/runs/20261002T062325-T10b2-2256308/run.log`:

```text
T10b2_MATRIX_PASS cases=106 pbuf_alloc=3 pbuf_take_at=3 ucdr_u16=55 ucdr_u32=14 ucdr_i32=1 ucdr_u8=7 ucdr_array_u8=19 ucdr_array_char=4 user_endpoints=1 atomic_state=1\n
```

Changed files: `validation/rtps/projection-fixture.cpp`, `validation/rtps/run-task.sh`. `git diff --check` passed; no staged files. Previous failed raw logs were preserved.

Residual: the matrix does not currently assert pbuf allocation/reference/free counts return to baseline after temporary preparation objects destruct; therefore it is not complete evidence for that explicit T10b2 requirement and must not be represented as a fully accepted T10b2. Locator snapshot compares the locator address field (the fixture additionally checks publication retains history state), not every locator field. Production code untouched; no production bug identified. Parent owns final aggregate/adoption.
