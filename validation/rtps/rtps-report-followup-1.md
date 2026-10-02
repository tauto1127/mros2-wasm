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

---

# Follow-up 1 continuation — incomplete / not ready

This section records the authorized same-writer continuation. The initial report above is retained verbatim. The live worktree was verified before edits: root `c88b569a567529c5c49cb64e698c8cbdea987206`, `mros2` `912cfbdd1af9a28be685ab67803093d84bb31ed1`, embeddedRTPS `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182`, lwIP `fbac6d22cd08d12fccfc27c4efa383a8be32335f`. Existing status included modified lwIP and mros2 gitlinks and untracked `bootstrap/` and `validation/`; no staged files. The experimental checkout stayed at root `c88b569a567529c5c49cb64e698c8cbdea987206`, lwIP `fbac6d22cd08d12fccfc27c4efa383a8be32335f`, mros2 `912cfbdd1af9a28be685ab67803093d84bb31ed1`, embeddedRTPS `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182`; no experimental source was modified.

## Follow-up edits

The earlier typed builtin endpoint pointers and checked initialization changes were retained. This continuation additionally changed `UdpDriver` to expose a copied local-IP helper and make `isSameSubnet` copy IP+mask under the WASI snapshot API or platform core lock for non-WASI; Locator local-IP reads and Domain GUID seeding now use the copied helper. SPDP no longer calls the removed pending API or holds an outer TcpipCoreLock around the coordinator. These edits are only partial: the SPDP path still acts only on `CHANGED`, has no applied-IP retry sentinel, and does not implement prepare/commit. Do not treat it as satisfying the approved semantics.

Exact changed tracked files (12):

- `mros2/embeddedRTPS/include/rtps/common/Locator.h`
- `mros2/embeddedRTPS/include/rtps/communication/UdpDriver.h`
- `mros2/embeddedRTPS/include/rtps/discovery/BuiltInEndpoints.h`
- `mros2/embeddedRTPS/include/rtps/discovery/SEDPAgent.h`
- `mros2/embeddedRTPS/include/rtps/discovery/SPDPAgent.h`
- `mros2/embeddedRTPS/include/rtps/entities/Domain.h`
- `mros2/embeddedRTPS/include/rtps/entities/Participant.h`
- `mros2/embeddedRTPS/src/communication/UdpDriver.cpp`
- `mros2/embeddedRTPS/src/discovery/SEDPAgent.cpp`
- `mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp`
- `mros2/embeddedRTPS/src/entities/Domain.cpp`
- `mros2/embeddedRTPS/src/entities/Participant.cpp`

Nested embeddedRTPS diff is 12 files, 160 insertions/63 deletions. Hashes at report time:

```
88249645a3fd696212ae220ea6c9ba35bd0ee8525cfb1843b2d23713483c2248  include/rtps/discovery/BuiltInEndpoints.h
e98d98538bf55215bfcebbf23260efb936ac6df50399d0cdcdd9606a246dff1b  include/rtps/discovery/SEDPAgent.h
98a399d059d01b1db22cec52befba5251c6e0488a2d6da90ead949429b6c673b  include/rtps/discovery/SPDPAgent.h
a9b1f3589d6f3f6551038c58acf131b518726602d063c446d75435dd1696d957  include/rtps/entities/Domain.h
c0587b2da311280b43f9ba0f62949ee5774956234f3bdce6d734e78611598276  include/rtps/entities/Participant.h
fe52c3f049bba28894f36656649adf0de8a6f0efaea76e32ae39a9d2255728b4  include/rtps/communication/UdpDriver.h
44d31115a898e682267acef2a79f54732993ab24722ccbb910e7f7ea9de2b96b  include/rtps/common/Locator.h
bb9ba8ce9e3eedbf79bf05616807a8390ff7763d8277f1f65cb2e993e7f7eb2f  src/discovery/SEDPAgent.cpp
70ab6d27489b6020d27aba80ed7538178be42c219f6b6b507ee491b338b76497  src/discovery/SPDPAgent.cpp
2a78ce8bbd216c74844f67424c2c0d843cbd23d3cc51a700150aa717abf0afb0  src/entities/Domain.cpp
5b98c9530d5973775621edcd36dbc7510ee22176bd8bdaa85e665207a17385b4  src/entities/Participant.cpp
7053cf2af330263acf7a4d8037756b73473686a355359d41b098c0bfa2a6e4a2  src/communication/UdpDriver.cpp
```

## Commands and validation

- `git -C mros2/embeddedRTPS diff --check` — passed.
- Actual changed C++ translation units were compiled to WebAssembly object files with `/opt/wasi-sdk-21/bin/clang++ --target=wasm32-wasi-threads -std=gnu++17 -c` and real source/config/project/CMSIS/lwIP include trees, output under `/tmp/rtps-followup-1-objects/`. The five compiled units were `SPDPAgent.cpp`, `SEDPAgent.cpp`, `Participant.cpp`, `Domain.cpp`, and `UdpDriver.cpp`; all produced wasm object files. Existing warnings remain: a non-void locator serializer lacks a return in one path and `PARTICIPANT_VERBOSE` is redefined. This is translation-unit compilation, not a linked embeddedRTPS/app target build.
- Earlier failed direct/ad-hoc syntax attempts are described above; the final successful object compile supersedes the missing-include attempts as compile evidence, not as a test or integration build.
- `git diff --cached --quiet`, `git -C mros2 diff --cached --quiet`, and `git -C mros2/embeddedRTPS diff --cached --quiet` — passed; no staged files.
- No focused tests were added/run; no app/root integration build, Docker, campaign, commit, or push was performed.

## Still-blocking approved-contract claims / next bounded work

The assigned C++ section is **not complete** and output readiness is false. The following are still blockers, not PASS claims:

1. No `m_lastAppliedIp` sentinel or SEDP-domain access protocol. SPDP takes action only on coordinator `CHANGED`; after a failed projection the next unchanged refresh would not retry (the exact required failure/ABA hazard).
2. No one captured current-IP snapshot fed to every user locator and both ParticipantData locator lists. Locator convenience calls independently sample; no explicit captured-IP locator constructors/update path. No applied-IP gating or safe retry.
3. No SPDP/SEDP serialized temporary data, sticky UCDR checks, temporary SPDP byte buffer validation, owned `PBufWrapper` prepare, or byte-identical failure guarantee.
4. No concrete writer private friend prepared-ALIVE move insertion, fixed-history prepared API, SPDP latest-only history/cursor behavior, SEDP historical immutable SN behavior, supported capacity rejection, or proof all commit operations are infallible. Existing `newChange` bool/void semantics are not replaced/proven.
5. Runtime addWriter/addReader publication and SEDP birth/registration are not serialized as one transaction; no birth-before/during/after projection semantics, pointer publication gate, or endpoint registration failure behavior.
6. Participant array add/get/find/matching/multicast/remove/heartbeat accesses are not all guarded/snapshotted. Expired heartbeat removal still nests endpoint removal and SEDP work under Participant mutex; unmatched diagnostics are still called while that lock is held. Lock-order/no-deadlock requirements are unmet.
7. Domain/agent failure initialization is improved but not fully transactional: SPDP may initialize before SEDP failure and callback/mutex cleanup/retry is not established; no focused false-publication/init-failure tests.
8. No required actual-source focused tests for zero endpoints, history2 capacity, registration birth ordering, each serialization/allocation failure, unchanged bytewise old state, B-fail/current-A retry, successful no-fail commit, latest-only SPDP, SEDP SN preservation, or expired-participant lock order.
9. No linked actual target/application build or native mapping test; only the five C++ object compilations passed. Selected call graph/nested-lock proof is incomplete. The WASI snapshot calls have not had runtime tests.

The next bounded step is a single integrated embeddedRTPS C++ seam review/repair implementing items 1–8 with focused tests in the project test/build style, followed by compile of the final changed translation units and focused test commands. Do not adopt this partial diff, and do not start an unrelated child or widen into lwIP/root/application work.

The report is updated in the authoritative runtime output file `.../implementation/rtps.md`; the initial report text remains above. No source was staged, committed, or pushed.