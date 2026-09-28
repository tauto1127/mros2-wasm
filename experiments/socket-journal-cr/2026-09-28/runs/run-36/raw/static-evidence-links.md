# Reused static build and source evidence

This trial reuses the exact instrumented Wasm artifact and pinned inputs from run-31. No source or runtime build was performed for run-36.

- Source revisions: [run-31 submodules-commits.txt](../../run-31/raw/submodules-commits.txt), [run-31 root-revision.txt](../../run-31/raw/root-revision.txt)
- Diagnostic instrumentation diff: [SEDPAgent.patch](../../run-31/raw/SEDPAgent.patch), [SPDPAgent.patch](../../run-31/raw/SPDPAgent.patch), [StatefulWriter.patch](../../run-31/raw/StatefulWriter.patch), [SEDPRaceTrace.h.patch](../../run-31/raw/SEDPRaceTrace.h.patch)
- Application source and build inputs: [app-staged.diff](../../run-31/raw/app-staged.diff), [build-input-hashes.txt](../../run-31/raw/build-input-hashes.txt), [build-commands.md](../../run-31/raw/build-commands.md)
- Artifact hashes: [build-input-hashes.txt](../../run-31/raw/build-input-hashes.txt) and run-36 `artifact-hashes-preflight.txt`
- Wasm app: `/tmp/mros2-wasm-sedp-race-20260928-run31/app/echoback_string.wasm`
- iwasm runtime: `/tmp/mros2-wasm-cr-rerun-20260927/runtime/iwasm`
- Native peer: `/tmp/mros2-posix-run04-final-build/mros2-posix`
