# Cleanup record

## Preserve and commit

- Preserve the fresh trial summary, provenance, copied gate inputs, result JSON, raw logs, checkpoint inventories, and per-file checksums under this evidence root.
- Preserve `experiments/cr-state-boundary/plan.md` and `cleanup-plan.md` as experiment/cleanup documentation.
- The isolated `campaign.py` is byte-identical to the tracked `experiments/cr-state-boundary/campaign.py`; its SHA-256 is recorded in `provenance/before.json`.

## Exclude from the evidence commit

- `experiments/cr-state-boundary/__pycache__/`: Python bytecode cache.
- `experiments/cr-state-boundary/build/`: small generated native build output.
- `experiments/cr-state-boundary/runtime-build/`: generated runtime/application binaries and checkpoint state images. The accepted trial logs and checkpoint image inventories are preserved separately; the runner discarded PASS checkpoint images after recording hashes.
- `experiments/cr-state-boundary/runtime-build-verified-20261004/`: generated fresh-build binaries; their hashes, commands, symbols, and build logs are already under `experiments/cr-state-boundary/build-provenance/`.
- `experiments/cr-state-boundary/state_probe.py`: an unreferenced stub containing imports only; it was not used by the fresh trials.
- `experiments/cr-state-boundary/cleanup-plan.md` is retained as documentation; it is not an experimental source change.

## Unrelated worktree contents

- `experiments/cr-ros2-interoperability/results/` is a separate, untracked experiment output. Its `fastrtps` control campaign was left running until it completed with the recorded `UNRESOLVED` pre-checkpoint gate stall. All 69 files (about 1.1 MB) were copied to `/home/osslab/20261004-cr-ros2-interoperability-results-preserved/`; `diff -qr` confirmed an exact match. It is not included in the C/R evidence commit.
- The branch already contains commit `3d5507cf937aaccdfcb515b12c8326de8281eaa8` (`test: start the ROS 2 peer with bash`), which modifies the separate ROS 2 interoperability campaign. It is already committed and will not be rewritten or reverted; the authorized branch push will include existing branch history.
- Boost remains dirty: the parent submodule reports modified pointers for `libs/iostreams` and `libs/test`; `libs/iostreams` has 700 status entries and `libs/test` has 126. No submodule content or pointer will be committed or changed by this cleanup.
- WAMR remains dirty only through untracked generated directories: `product-mini/platforms/linux/build-cr-state-boundary-classic/`, `build-cr-state-boundary-verified-20261004/`, and `build-cr-state-boundary/`. None is part of the fresh evidence commit.
- The integration worktree `/home/osslab/20260930-mros2-wasm-eintr-no-udp-recover-integration` remains untouched; its observed status is `?? experiments/`.
