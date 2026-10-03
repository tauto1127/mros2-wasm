# Fresh normal no-C/R control — final repair round 2

**Disposition:** one corrected fresh noninstrumented normal control on `.6` completed successfully. This is communication smoke/control evidence only, not C/R acceptance, production adoption, or an `actualCasePassed` result. The run reports `controlCasePassed=true`, `actualCasePassed=false`, zero checkpoints.

## Normal build provenance and validation-tool pin

Used only the newly clean-built normal `echoback_string.wasm` from startup repair 2:

- Artifact: `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl/validation/rtps/runs/20261003T-startup-repair2-T11-final/build-echoback_string/echoback_string.wasm`
- App SHA-256: `b66ded95023a51022e4ebe19cca65663f83c173590dc9bef6d5cba5b27d326fc`
- Runtime SHA-256: `70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3`
- Native peer binary SHA-256: `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`

The explicit immutable build/source/artifact provenance manifest is `/tmp/t12-normal-control-final-20261003/control-provenance.json` (SHA-256 `d486e39b8aecddf0f549544c10be9054cd4ce8f6096c011b1aa29cd40a665c09`). It records app/runtime/peer paths and hashes, 23 source/config/compiler/toolchain/build-input pins, and the startup owner's configure/build commands. The runner now validates this manifest for normal no-C/R controls, including each pinned source file and all three selected artifacts. The previous T11 app pin is not waived: a normal control without the explicit manifest is rejected; default T11 pins remain in force for other modes. Focused regression covers the missing-manifest rejection and source/artifact hash validation.

## Control result

- Run: `/tmp/t12-normal-control-final-20261003/runs/1790989163-b98eb619ab/`
- Address: `.6` (`172.18.0.6`); network `mros2-cr-net`, exact ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, subnet `172.18.0.0/16`.
- Setup recorded `.5` as the only pre-existing network attachment and 8,487,165,952 free bytes (3 GiB minimum). The newly owned app occupied `.6` during the run. No `.3` container was added.
- `result.json`: **PASS for this normal smoke only** — IDs `4` through `13`, `fully_correlated=true`, `body_match=true`, `checkpoint_count=0`, `controlCasePassed=true`, `actualCasePassed=false`.
- `raw/no-cr/roundtrips.json` records those ten IDs and the runner's exact-body/complete-correlation assertions. Fresh app log `raw/no-cr/checkpoint.log` contains the matching callbacks, e.g. `Hello from mros2-posix onto Linux: <id>`. Fresh peer window `raw/peer/native-peer.log` records both native receive and echo publish-return with the exact same body for each ID 4–13.
- The continuous peer session was revalidated before and after: container ID `2af57313c148bcfd774dff5e793a75b5d3d52d2a9c355dfd4bafb9916ce5778c`, PID 12, start ticks `269744428`, zero restarts, `.5`, peer binary hash unchanged. Its original manifest and mounted live log were not overwritten. Final fresh Docker inspection still showed the same peer running on `.5`; the only network attachment afterward was that peer.
- No checkpoint, restore, C/R, instrumentation, or telemetry claim is made.

## Invocation history and lifecycle audit

The first invocation used a relative app path and failed before app/container creation because Docker requires an absolute bind-mount source. Its failure evidence is preserved unchanged at `/tmp/t12-normal-control-final-20261003/runs/1790989068-569d1ab83b/`. Parent authorized one corrected attempt. The successful, single corrected attempt used canonical absolute app/runtime/peer/output paths; exact argv is in `corrected-execution-command.txt`, and the no-Docker dry-run plan is `corrected-dry-run-plan.json`.

After the smoke, the helper audited an immutable-ID stop of the owned idle app container `62460015031ed7c1f97bc83d56919299ab4841135cb26c4df3090361b088a0dd`. Stop passed. On reinspection Docker returned the network ID but blank endpoint ID/IP fields; the helper therefore refused to disconnect and issued no disconnect command. The persistent audit is `container-lifecycle.jsonl` (SHA-256 `a32ed824e2c475c3ec724a1d7934ad4a5dde142d4d222913009ada5af83d90e3`). Container remains present and stopped (exit 137), its bind-mounted raw/state logs and object were preserved; all deletion remained off. No manual disconnect/retry or `docker rm` was performed. Network inspection showed `.6` detached from the active network container list, `.5` still present. This incomplete disconnect audit is an open residual, not a smoke-test failure.

## Narrow tooling change and review bundle

Changed only:

- `validation/campaign/run.py` — add explicit normal-build-manifest validation/CLI input and persist its path in the run inputs/setup; enforce fixed runtime/peer pins and preserve the legacy app pin absent provenance.
- `validation/campaign/test_runtime_pin.py` — add focused manifest validation and no-manifest rejection regression.

Focused checks passed: `python3 -m unittest validation.campaign.test_runtime_pin -v` (4 tests), `python3 -m py_compile validation/campaign/run.py validation/campaign/test_runtime_pin.py`, `git diff --check`, and root plus all nested `git diff --cached --quiet` checks. No staged files.

Fresh full source/status/hash bundle after the tooling/test changes: `/tmp/t12-normal-control-final-20261003/source-review-bundle-final/`; checksum manifest SHA-256 `1742922ff872e8b757fac6cbaaa44b1c58b0a411f9dd372392f73dbb415d04f2`. It includes current root and nested HEAD/status/cached/tracked diff snapshots and exact copies of changed tooling files. The full pre-existing dirty tree is included for review; it is not all part of this narrow change. Changed tooling copies: `run.py` SHA-256 `59cd7d29c766288833a847002ad05e8f760ced146526f2cd93dba5b3007ad96d`; focused test SHA-256 `b7b4318cd3d084a8ac23439905574b5deadab609692a4513d2e8732c71bb3c17`.

**Open review notes:** the normal communication control passed, but parent/reviewer disposition remains required. The authorized idle stop succeeded; endpoint reinspection prevented audited disconnect, and the owned stopped container remains (not deleted). No claim is made that any earlier C/R used this newly built normal app.