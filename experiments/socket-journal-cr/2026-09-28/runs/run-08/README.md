# run-08: same-IP Socket Journal topic round trip

This is an independent run of the fixed same-IP experiment in [`plan.md`](plan.md). The result and evidence are summarized in [`report.md`](report.md), with measured conditions in [`metadata.md`](metadata.md).

The binary artifacts were checked against run-04 before launch. The native peer and Wasm runner use the existing Docker network and the same `.5` / `.3` addresses as run-04 and run-07. The strict gate checks message IDs, payload equality, and the order of all four application log events.

The checkpoint body remains in the run-specific `/tmp/mros2-wasm-cr-rerun-20260928-run08/state/` directory. Its file list and hashes are recorded under `raw/`.
