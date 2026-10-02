# embeddedRTPS projection seam status — partial, not ready

## Implemented in this pass

Changed only selected embeddedRTPS sources/headers (nine files). `BuiltInEndpoints` now carries concrete `StatelessWriter/Reader*` for SPDP and `StatefulWriter/Reader*` for SEDP rather than base-class pointers. SPDP/SEDP initialization and `Participant::addBuiltInEndpoints` now return checked bool status and reject missing endpoint prerequisites; Participant publishes its builtin-ready flag only after both agent initializations pass and prechecks the fixed arrays for room. `Domain::createBuiltinWritersAndReaders` checks all three concrete writer init results, avoids advancing builtin counters until all registration succeeds, and `createParticipant` does not advance its published participant ID on a failed builtin setup.

## Exact changed files

- `mros2/embeddedRTPS/include/rtps/discovery/BuiltInEndpoints.h`
- `mros2/embeddedRTPS/include/rtps/discovery/SEDPAgent.h`
- `mros2/embeddedRTPS/include/rtps/discovery/SPDPAgent.h`
- `mros2/embeddedRTPS/include/rtps/entities/Domain.h`
- `mros2/embeddedRTPS/include/rtps/entities/Participant.h`
- `mros2/embeddedRTPS/src/discovery/SEDPAgent.cpp`
- `mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp`
- `mros2/embeddedRTPS/src/entities/Domain.cpp`
- `mros2/embeddedRTPS/src/entities/Participant.cpp`

## Validation

- `git -C mros2/embeddedRTPS diff --check` — passed.
- Attempted WASI C++ syntax check of the changed translation units. It did **not** complete: the first invocation lacked `arch/cc.h`; adding the project public/system includes then exposed absent `cmsis_os.h` in this direct ad-hoc invocation and a missing mros2 config include on one file. This is not a successful compile and does not establish target compatibility. Preserve the errors in the session output; no production target build was run.
- No focused C++ tests added or run. No application build/campaign run.
- No files staged; no commits or pushes.

## Blocking incomplete contract work / residual risks

This is deliberately **not** a complete implementation of approved sections 3–4. No source adoption or ready claim is warranted. Remaining mandatory work includes: migrate all selected current-IP readers (Locator, UdpDriver, Domain GUID seeding) using safe copied snapshots with native conditional mapping; replace SPDP's pending consumer/outer core lock with the shared coordinator and one captured IP; serialize registration, birth, projection and applied state in the SEDP lock domain; add the single applied-IP sentinel; implement full failure-atomic prepare/infallible-commit including owned pbuf preparation, sticky serializer checks, typed private prepared-ALIVE writer/cache path, SPDP latest-only replacement, SEDP history/SN preservation/capacity rejection, and applied assignment last; implement participant pointer/count snapshots and expired-participant lock-order fixes; then add the required focused actual-source failure/birth/capacity/history tests and run the target compile/tests.

The new bool init checks cannot roll back a SPDP mutex/callback if later SEDP initialization fails; a partially failed participant slot is not reusable. Domain also registers transport ports before builtin initialization. These failures avoid advertising a successful participant but are not yet a complete transactional startup/recovery solution. Focused tests must cover this path. Build the changed C++ files using the repository's actual configured build environment rather than inferring compatibility from the failed manual syntax checks.

`git status --short` at the repository root: `m lwip-wasm`, `m mros2`, `?? bootstrap/`, `?? validation/` (preexisting lwIP handoff artifacts plus these source edits; do not stage them indiscriminately). Nested source diff is nine files, 97 insertions/42 deletions. Root/lwIP experimental worktree and its old82a diff were not modified by this step.