# Final commit and evidence map

Worktree: `/home/osslab/20261004-mros2-wasm-cr-state-boundary`
Branch: `experiment/cr-state-boundary`
Report/manifest root commit before this map: `712b767b` (`test: document WAMR C/R state-boundary evidence`)
Merge-base: `e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0`

## Experiment source and evidence history

- `1a9d7a7a`: native probe library and build helper.
- `1b0b2b6e`: guest/native sentinel instrumentation in `workspace/echoback_string/app.cpp`.
- lwip-wasm submodule `50a6e414`: pre-mutation and initialization diagnostics; root pointer recorded by `6202b42e`.
- `1874fd84`: campaign/build scaffolding.
- `733f029c`: original build logs and raw control/same-IP/changed-IP trial evidence under `experiments/cr-state-boundary/smoke/`.
- `e062709b`, `ed296ca2`: original report and literal-format correction.
- `a48e643b`: Task 0 audit and Task 1 revision/status records.
- `506ca53d`: corrected reproducible build path and fresh Task 5 build provenance under `build-provenance/verified-20261004/`.
- `05559c49`: Task 6 fail-closed marker selection and parser/state-boundary cases. It was checked against existing raw logs; no runtime trial was rerun or rewritten.
- `712b767b`: report, Task 10 manifest, and integrity limitations.

The recorded original trial artifact hashes are `iwasm=fa63c40c2a17f8df6461d687a95cb01bf544e0b7788377d41c317dcec6d46822`, `wasm=52ecd6ffde313c25cc6c20298769f7c9ad816419b0ddce80555c5bc2417520e0`, `native_probe=b91cdb900b478292d78a8dbfab24906bbdd3252be93b688f9c03e96c0b9121ca`, and `peer=8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`. The fresh Task 5 build matches iwasm, native probe, and peer; its Wasm artifact differs in custom debug metadata and was not substituted into the original trials. Per-trial hashes and raw log checksums are in `results/manifest.json`.

The build-time revision snapshot is incomplete as described in `audit-current-state.md`, `build-provenance/verified-20261004/review.md`, and `report.md`. No source commit was pushed. Existing unrelated dirty Boost and WAMR submodule state remains untouched.
