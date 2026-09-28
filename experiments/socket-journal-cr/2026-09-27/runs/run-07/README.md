# run-07: native mROS 2 peer and same-IP Socket Journal C/R rerun

**Result: success for one same-IP run.** The native POSIX mROS 2 peer received and echoed the Wasm app messages before checkpoint. After checkpoint and restore in the same `.3` container, ten new message IDs completed the full round trip.

This rerun used the conditions and gates in [`run-04/plan.md`](../run-04/plan.md). It did not test a different IP or a different physical host. The detailed findings are in [`report.md`](report.md); run times and hashes are in [`metadata.md`](metadata.md).

Raw logs, gate results, and the wire capture are in `raw/`. The 1.1 GiB checkpoint state remains under `/tmp/mros2-wasm-cr-manual-20260928-01/state/`; only its file list and SHA-256 manifest are included here.
