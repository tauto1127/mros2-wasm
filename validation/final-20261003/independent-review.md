# Independent review — ROUND2/MAX2

## Review

- **Correct — prior startup P1 resolved.** `Domain::completeInit()` selects only successfully published builtin participants and rejects all-failed readiness (`mros2/embeddedRTPS/src/entities/Domain.cpp:65–80`). `SPDPAgent::start()` independently rejects uninitialized, null-participant, and unpublished startup (`src/discovery/SPDPAgent.cpp:94–104`). The publication snapshot briefly holds only the existing Participant mutex (`src/entities/Participant.cpp:431–435`); it introduces no nested core/SEDP locking or transaction mutation.

  Actual-source regressions cover all six builtin failures through `completeInit()`, direct incomplete-agent startup, later SEDP initialization failure after SPDP initialization, and healthy startup (`validation/rtps/projection-fixture.cpp:793–880`). Retained RED fails the former startup assertion; final GREEN records all six cases and the late-agent PASS.

- **Correct — prior lifecycle-audit P1 resolved.** Docker inspection exceptions become evidence rather than escaping before audit (`validation/campaign/run.py:461–480`). Stop/disconnect attempts retain command results and inspection errors, with unknown post-state failing safely (`run.py:531–602`). Initial and pre-action failures receive rejection audits. Immutable-ID targeting, ownership/endpoint checks, `.5` protection, and no-remove behavior remain intact. Actual-method fake-Docker tests cover exception boundaries and combined command/inspection failures (`test_owned_container_retirement.py:187–326`).

- **Correct — production scope preserved.** Recorded final lwIP, mros2, WAMR, and `PreparedDiscovery.h` hashes match the previously reviewed implementation. The embeddedRTPS repair changes startup eligibility, not projection preparation/commit, applied-last assignment, reliable history semantics, latest-only SPDP, identities, or the 1000 ms interval. The original full-source review remains applicable.

- **Finding — P2: trace inputs can misclassify an instrumented run as a normal control.** `run.py:1423–1439` validates normal-build provenance, but `1441–1461` subsequently accepts trace inputs and replaces the selected application with the instrumented derivative. The no-C/R result still derives `normal_app_control` and `controlCasePassed` from the normal-control flag (`1255`), contrary to that flag’s uninstrumented-normal purpose (`1405`).

  **Source-path proof:** supply a valid normal manifest together with valid `--trace-app` and `--trace-manifest`; the trace branch replaces `args.app`, while the normal result classification remains enabled. **Smallest fix:** reject trace inputs when `--normal-no-cr-control` is selected and add a CLI-combination regression. The actual fresh control had both trace inputs null, so its evidence is unaffected.

- **Merge verdict: OK with notes.** Both prior P1 findings are closed; no remaining P0/P1 identified. The P2 is report-only. This review is not parent adoption or publication authorization.

## Validation disposition

**Sufficient for this repair’s acceptance:** targeted actual-source regressions, the full final projection suite, three clean final-source normal builds, lifecycle exception tests, and fresh normal communication evidence.

Inspected evidence includes:

- Final ten-task suite: `validation/rtps/runs/20261003T003252-all-2332558/coverage.manifest` and aggregate log, using the fixed-runtime SHA pin.
- Three successful final builds under `validation/rtps/runs/20261003T-startup-repair2-T11-final/`; unchanged service-template manifests and retained warnings.
- Worker-attested lifecycle validation: 16 focused tests and 44 campaign tests; subsequent provenance validation: four focused tests. These were inspected, not independently rerun.
- Fresh `.6` control: `/tmp/t12-normal-control-final-20261003/runs/1790989163-b98eb619ab/`. Inputs pin final normal app SHA `b66ded95023a51022e4ebe19cca65663f83c173590dc9bef6d5cba5b27d326fc`. Result records ten correlated/body-matching IDs 4–13, zero checkpoints, `controlCasePassed=true`, `actualCasePassed=false`; matching application/peer log entries were inspected.
- Persistent lifecycle audit records the owned immutable-ID stop and subsequent disconnect refusal for incomplete endpoint identity. No disconnect or removal followed.

**No additional C/R campaign is required to close these bounded repairs:** successful startup is exercised, while the post-startup refresh/transaction/runtime/observer seams are unchanged. Historical SAME, CHANGED, and retained REPEATED C/R evidence remains evidence for the **pre-round2 startup binary**, not the newly built normal artifact. Any claim that the exact final artifact passed C/R would require its own validation.

## Residual risks and limits

- Mocked exception tests do not prove live Docker exception behavior; the fresh control exercised successful stop and safe disconnect refusal, not successful explicit disconnect.
- Historical unauthorized source-container deletion, overwritten checkpoint images, and irreversible evidence losses remain disclosed and cannot be retro-certified.
- Existing observer/runtime limitations remain: bounded measurements do not establish all schedules, atomic guest-time freshness, or every WAMR waiter/lifetime assumption.
- Review was read-only: no edits, executable tests, builds, campaigns, cleanup, staging, or publication. Recorded hashes were inspected, not independently recomputed.