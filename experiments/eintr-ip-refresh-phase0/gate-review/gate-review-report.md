# EINTR IP refresh — history and final Gate Review

Date: 2026-10-01. Parent decision: **Gate Review FAIL for the current candidate; stop before production implementation.** Phase0/Gate A remains PASS in its original tested scope. A bounded safety revision is feasible, but no revised production contract/primitive has passed all gates. Production-worker model verification is a separate unresolved infrastructure blocker.

## 1. SPDP period history

### Confirmed code/build selection

The recorded Phase0 `echoback_string` Wasm build uses **1000 ms** from root `include/rtps/config.h:77`. Root CMake adds root `include/` explicitly for `rtps/config.h`; actual `SPDPAgent.cpp` compile commands place it before embeddedRTPS includes. `SPDP_RESEND_PERIOD_MS` is a C++ constant, not a macro override. Desktop's `config_desktop.h = 10000` is a different, unselected configuration. Recorded approximately one-second periodic measurements agree with the code/build selection.

Other applications using the same CMake target function receive the same root config by source inspection; separate service builds were not executed in this request. Thus 1000 is not a Phase0-only temporary change. It is not universally 1000 across embeddedRTPS targets: desktop/STM/Aurix currently declare 10000, R5 1000; effective selection depends on the target's supplied config.

| Event | Commit | Author/date (author and commit dates, unless noted) | Message / evidenced reason |
| --- | --- | --- | --- |
| Desktop config introduced with 10000 | embeddedRTPS `f6087231993f56d03825e6ef3b62c0473956ab94` | Andreas Wuestenberg; 2019-03-12T17:15:57+01:00 | `Added desktop config.`; no interval-specific reason |
| R5 config introduced with 1000 | embeddedRTPS `35869c86e1dfd31a98d87a519784d9283b2c5399` | Alexandru Kampmann; 2021-05-20T12:24:25+02:00; committer GitHub | `Feature/multicast-fastdds-liveliness (#4)`; no interval-specific reason |
| Earliest located project config with 10000, then `workspace/include/rtps/config.h` | root `6e4d41c788dec521f5e585c5bb31ac1ca367fb6a` | Takashi Mori; 2022-01-14T14:32:06+09:00 | `add mros2 posix codes`; no interval-specific reason |
| Config moved to top-level include; value still 10000 | root `cab2f523d102e69c836a86adbd904059e5ff5964` | Takase Hideki / takasehideki; 2022-10-16T20:06:23+09:00 | `change include/ location`; R100 rename, not initial introduction |
| **Actual root 10000 → 1000 change** | root **`fc1843de2ca080f584f244c72b5ed7ea0c88275f`** | **Takase Hideki / takasehideki; 2022-10-17T18:25:41+09:00** | **`track rtps/config.h for latest embeddedRTPS (by copying from mros2-mbed)`**; config copy/update is evidenced, numeric interval rationale beyond that is unknown |
| Service-discovery config update, interval remains 1000 | root `e15cc5e7511ce662f0e0ef6a7eb8eca15ad949a0` | takuto1127; 2026-05-31T11:17:02+09:00 | `ROS2連携のためのservice discovery不具合修正(E2E成立)`; parent and commit both1000, not the interval change |

The October2022 change predates 2026 service work and July/September IP migration. The initial worker incorrectly attributed the numerical change to e15cc5e and introduction to cab2f523. Parent directly checked exact diff/parent snapshots and rename-following history; the retained worker corrected/retracted these claims. Only the corrected report is accepted: `reports/spdp-history-corrected.md`.

Commands included `git log --follow --name-status`, `git log -p`, `git show --format=fuller`, and before/after `git show <commit>:<path>`. No fetch/mutation was needed in source repos. Historical conclusions are bounded to available local refs, not unknown upstream history.

## 2. Gate Review — decision and source evidence

**FAIL: do not adopt the writer-only guard + atomic pending candidate.** This is not a claim that atomic ownership is impossible or that the problems cannot be repaired.

### A. Common guard: correct responsibility, insufficient total contract

Only current external refresh caller: `SPDPAgent::refreshLocalIp()` (`mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp:80–103`), invoked by `runBroadcast():124`. It is also the only current pending consumer. Proposed new receive caller: saved-EINTR branch in `lwip-wasm/src/core/udp.c:380–391`.

Putting exclusion **inside** `netif_wasm_refresh()` is correct: both callers must cross one serialization primitive before probing. Separate recv/SPDP guards would not work. BUSY must remain distinct from FAILED/SAME/CHANGED; losers do not wait or clear another owner's claim. Sequential duplicates are permitted and would be measured later.

### B. Existing locks and major reader/snapshot problems

`TcpipCoreLock` maps to a private default pthread mutex (`lwip-wasm/src/core/lwip.c:13,22,36–44`). It serializes some network access, including ordinary bind/IGMP call intervals. Current SPDP owns it during refresh. There is no existing public try-acquire wrapper; existing blocking core acquisition does not satisfy nonwaiting recv. CMSIS timeout-zero mutex acquisition first uses a blocking internal synchronization lock, so it cannot be assumed strictly nonblocking.

**P1 major conditions verified independently by reviewer and parent:**

1. **Writer exclusion does not protect plain readers.** Refresh writes plain IP unconditionally, including SAME, and fallback publishes mask/IP/default. `Locator.h:111–117` and `UdpDriver.cpp:85–87` read without common synchronization. The periodic-vs-subnet race already exists; the proposed receive writer additionally races bind/IGMP reads previously protected by core. Hardware/Wasm scalar alignment does not make these C/C++ plain conflicting accesses race-safe. Byte-wise locator reads can be mixed; no observed mixed-locator trial is claimed.
2. **Atomic pending bit is not an IP snapshot.** Existing plain read-clear can lose a store; SPDP consumes before checking probe failure (`SPDPAgent.cpp:87–90`). Atomic store/exchange repairs the bit operation but not coherent association with payload. Participant endpoint refresh and the two announcement locator bundles independently read IP. The same captured IP must feed all three, and FAILED/BUSY must preserve pending.
3. **Lock boundary must avoid recursion/inversion.** An internally locking refresh cannot retain SPDP's current outer core acquisition. Holding core through Participant/SEDP/writer work can invert against writer→transport→core paths. Capture data under synchronization, then release before RTPS rebuild/send work.

Root config has `MAX_NUM_PARTICIPANTS=1` (`include/rtps/config.h:52`), one static mROS Domain and one SPDP agent per created participant. A global consuming notification can be reviewed within that scope; multi-Domain/multi-participant notification support is not silently promised.

### C. C11 atomics/toolchain

Artifact-level evidence supports C11 bool/flag/integer atomics with the actual wasi-sdk21, wasm32-wasi-threads, pthread/shared-memory flags and unchanged validated classic WAMR. No unresolved libatomic helper appears; disassembly contains byte and integer CAS/exchange. The synthetic runtime logs report lock-free bool/flag/integer and matching contention counts. The classic interpreter internally uses a host shared-memory lock for RMW; guest compiler lock-free does NOT mean host execution is mutex-free.

For a private guard, atomic_bool strong CAS is suitable and default seq_cst is adequate. Acquire on successful claim/release on owner clear could be a later explicit reduction; weak orders were not tested. Losers never clear. If existing core try-acquire is adopted, an extra atomic guard/pending is unnecessary when all publication/consume/readers share that mutex. Such a different primitive still needs its own target and C/R validation.

**Execution provenance limitation:** the atomic worker's final model verification failed. Its native acceptance is NOT PASS. Parent and a successfully verified independent read-only reviewer inspected actual source/compiler/disassembly/raw logs, accepting only the bounded technical observations described in section4.

### D. Claimed owner through C/R

The synthetic held atomic guard/canary were recorded in the memory-image cross-check. Restore logs show the owner continuing while guard1, restored contender BUSY, owner common cleanup, subsequent winner and guard0 in both logical success/error trials. This supports continuation/cleanup, not owner loss. Guest flag must not be blindly reset at restore.

Actual netif probe uses socket→connect→getsockname→close. The current socket journal does NOT record CONNECT. Source supports two mid-probe cases: replayed open/unconnected socket can cause address-check failure, or guest locals can retain an already-read source IP. Correct cleanup and subsequent periodic probe can plausibly recover; this is **inference**, not an exact-probe experiment or an inevitable stuck flag. This limitation predates proposed receive probing. It does not alone demand generation/socket recreation/CONNECT replay under eventual-recovery requirements.

Exact production cleanup/retry remains to validate. The synthetic experiment does not attest pthread_mutex_trylock held-owner C/R if the revised design uses that primitive.

### E. Notification contract required before PASS

- Serialized publish/capture of pending plus one copied IP/mask/validity.
- FAILED/BUSY preserve prior payload and pending; no consuming call before error handling.
- Successful capture transfers pending work to an owned snapshot, clears the shared bit under the same serialization, then rebuilds without core ownership.
- All endpoint/default/metatraffic locators use that snapshot.
- A later writer sets pending again; an earlier rebuild must not erase it afterward.
- If rebuild gains explicit rejection, preserve owned work for retry/re-arm without clearing newer notifications.

These semantics are not implemented or fully primitive-tested, so the current candidate fails the stated Gate criteria.

## 3. Proposed plan changes — not approved production implementation

The independent reviewer supplies a bounded preferred alternative in `reports/concurrency-specialist.md`:

1. Expose one-shot `sys_trylock_tcpip_core()` using `pthread_mutex_trylock`, with acquired/EBUSY/error distinguished.
2. Both refresh entrypoints share internal try-core probe/publication/cleanup; remove SPDP outer lock.
3. Add SPDP refresh+pending+snapshot capture as one operation, plus a nonconsuming getter for other readers; retire sole plain pending consumer.
4. Pass one explicit IP into Participant/announcement locator builders; release core before those paths.
5. Join all netif/IP readers to common synchronization; raw-pointer use remains lock-required over its entire use interval. Preserve startup-only add before concurrent users: current core mutex is initialized later.
6. Name FAILED/SAME/CHANGED/BUSY; no blocking recv fallback.
7. Validate the actual try primitive/held-mutex C/R, failure cleanup, pending races and eventual retry before production approval.

A private atomic guard plus separate publication/snapshot synchronization is another option but adds two mechanisms. The preferred core alternative avoids unnecessary atomic proliferation; it is conditionally concurrency-acceptable, **not target/runtime PASS**.

At1000ms effective periodic propagation, leaving immediate SPDP wake as future work remains reasonable for this initial eventual-recovery requirement. A one-second setting is not a guaranteed recovery latency. No generation, recv barrier/condvar, wake refactor, actual RTPS getsockname, recreation, or udp_mc_recover was added.

## 4. Additional focused experiments actually produced

All under `atomic-owner/`, separate from production:

- C11 compile using actual pthread/shared-memory flags and existing socket extension shim. Initial missing extension declarations failed; logs preserved; correct existing header/shim compiled.
- Four pthreads ×2000 attempts per bool/flag/integer variant. Strengthened two trials each show positive `wins == protected count`, `bad=0`.
- Two initial same-IP synthetic held-owner C/R trials, followed by two strengthened trials (`success-02`, `failure-02`). **Four independent synthetic C/Rs, NOT repeated C/R of one application.**
- Strengthened image-state records: guard1 at4400, canary5917d272 at4404. Parent/reviewer checked extraction/assertion source and JSON; deleted PASS memory payloads were not independently reread after deletion.
- Both restore logs show owner1028 guard1/errno27; restored contender13113348 CONTINUATION_BUSY; PROBE_SUCCESS or PROBE_ERROR logical label; subsequent winner; RELEASED/PASS guard0.
- Both native recv calls were interrupted: synthetic PROBE_SUCCESS does NOT mean a successful route-IP syscall. Only common cleanup outcomes were exercised.

| Strengthened trial | bool wins | flag wins | integer wins | overlap detector |
| --- | ---: | ---: | ---: | ---: |
| success-02 | 3359 | 2855 | 3175 | 0 |
| failure-02 | 3057 | 2170 | 1915 | 0 |

Wasm hash: `c863fe3827fcee8ec51731bd4d184d3996b55b240006b645786063abcba76d4c`. Runtime hash unchanged: `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60`.

The tested synthetic owner sequence is supported by raw artifacts, but the **worker execution contract failed** and no overall Gate PASS follows. Detailed limitation-bearing worker report: `reports/atomic-owner-unaccepted-worker.md`; source/log hashes: `evidence-sha256.txt`.

## 5. Worker/protocol infrastructure — separate blocker

- Initial workflow `7033e73f...`: serialization error for undefined outputPathMapping after history completion. Optional values changed to JSON null; same-protocol retry reused evidence.
- Concurrency worker `9e333483...`: requested `openai-codex/gpt-6-luna:low`, observed `gpt-6.1-sol`; verification failed. Its report was not adopted as verified Gate evidence.
- Atomic resumed worker `388f9e32...`: same final model mismatch; partial source/logs preserved, no production writes.
- Explicit worker/Sol retry workflow `9c485501...`: rejected before child launch because enforced `modelScope.agents.worker` permits only `openai-codex/gpt-6-luna`. No source change/session persisted.
- Appropriate **read-only reviewer**, which legitimately uses current Sol and cannot write/Git/Docker, completed successfully: workflow `8e883b55-ec78-439c-b7ca-f9e5252a34dc`, child `0804bfb6-a7ba-4c6a-82d1-10737ec13136`, actual bound report copied to `reports/concurrency-specialist.md`. This is not a writer-scope workaround.

No scope, response aliases, runner mode or persistent model config was changed. No CLI/foreground fallback was used. Another mutation-capable role was not used to bypass worker model restrictions. Before any production-writer retry, a genuinely verified Luna route or operator-approved scope change is required. This is infrastructure BLOCKED, separate from the source-design FAIL.

## 6. Implementation, validation, builds, commits and push status

| Requested deliverable | Final status |
| --- | --- |
| Implementation worktree `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl` | **Not created** |
| Production root/lwIP `fix/eintr-ip-refresh` branches | **Not created** |
| Production commits / root pin update | **None** |
| Implementation same-IP C/R | **Not run — Gate not passed** |
| Implementation changed-IP `.3→.6` | **Not run — Gate not passed** |
| Implementation repeated C/R in same application | **Not run — Gate not passed** |
| Implementation no-C/R communication | **Not run — Gate not passed** |
| Production EINTR/refresh/winner/BUSY/periodic/duplicate per checkpoint | **Unmeasured**, not zero |
| Three normal target builds in this request | **Not run**; only private C11 probe compiled |
| Post-implementation diff review | **Not applicable**; independent pre-Gate design review completed |
| Push | **None** |

Prior Phase0 same/changed application PASS results remain valid and separate. Do not substitute synthetic trials for requested production communication modes or claim three builds from older campaigns.

## 7. Safety and preserved state

`final-safety.log` verifies root/lwIP pinned branch/HEAD unchanged, all other submodule pins unchanged, staged files empty, source diff checks, existing service-header SHA256 checks, absent implementation worktree, no containers/network attachments, actual remote URLs and disk state. Root/lwIP binary diff remains the same temporary Phase0 instrumentation captured before this request's trials.

New private experiment artifacts/reports remain untracked; nothing added/committed/pushed. Existing failed Phase0 run-02 checkpoint is preserved. Each new synthetic PASS checkpoint was hashed/manifested and removed only from its newly created trial state. Docker network preserved. All delegated runs are terminal at final handoff; no C/R process remains running.

## 8. Remaining TODO and next safe action

1. Resolve enforced worker model verification without invented aliases or execution-mode bypass.
2. Review/test core try-acquire + coherent snapshot contract (or another explicitly safe repair), including held chosen primitive through C/R and exact-probe error/periodic retry.
3. Only after parent Gate PASS: clean baseline implementation, serial same/changed/repeated/no-C/R communication and per-checkpoint counters, three normal builds, distinct read-only final diff review, then ordered submodule commits/root pin if accepted.

Generation/epoch remains future work only if meaningful sequential duplicates are measured. Immediate SPDP wake and actual RTPS-socket getsockname remain separate future work. Cross-host migration is untested. No recv barrier, waits, socket recreation or udp_mc_recover is introduced.

**Research conclusion:** shared guest state and synthetic owner continuation are supported in the tested scope; safe production refresh requires synchronized readers and coherent notification/payload capture, not merely a shared writer flag. Current candidate cannot pass those criteria. Stop before implementation as instructed.
