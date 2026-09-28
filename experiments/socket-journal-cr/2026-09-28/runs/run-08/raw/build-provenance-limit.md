---
sources:
  - "../../../../2026-09-27/runs/run-04/metadata.md"
  - "../../../../2026-09-27/runs/run-04/build_native_peer.py"
  - "../../../../2026-09-27/runs/run-04/native-peer-ip.patch"
  - "../../../../2026-09-27/runs/run-04/raw/build-final.log"
---
# Artifact provenance checked for run-08

Run-08 reused the three run-04 binaries without rebuilding them. Their measured SHA-256 values match run-04 metadata and run-07:

- `iwasm`: `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a`
- `echoback_string.wasm`: `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76`
- native peer: `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`

Run-04 metadata records the root, WAMR, Wasm mROS 2, Wasm lwIP, and native POSIX source revisions. Its `build_native_peer.py` shows that the native executable was built in an isolated `/tmp` copy of a dirty source worktree, with the run-04 `native_peer.cpp` copied over the app and `native-peer-ip.patch` applied to set `172.18.0.5`. The patch is saved in the run-04 directory.

The isolated source copy still exists, but its `.git` metadata points at an unavailable submodule worktree, so `git status` and `git diff` cannot recover the exact dirty source tree from that copy. The run-04 artifact set does not contain a full build-time diff for the Wasm-side binaries either. Run-08 therefore records the available revisions and known native build changes without claiming that the older build inputs were clean. This limitation does not affect the run-08 binary hash match.
