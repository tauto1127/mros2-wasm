# Final repair-review round 2 — lifecycle exception-audit fix

**Disposition:** this narrowly assigned validation-tooling P1 is repaired and checked; ready for independent review. No production files were changed. No application campaign, C/R, live Docker operation, or container mutation was run. Those are intentionally outside this slice; this report claims no fresh case verdict (`actualCasePassed=false`, `controlCasePassed=false`). Review readiness is not application acceptance or production adoption.

## Repair

Changed only `validation/campaign/run.py` and `validation/campaign/test_owned_container_retirement.py`.

- Docker inspection exceptions are normalized to explicit evidence containing full executed argv, Docker arguments, exception type/error, return code where supplied, partial stdout/output and stderr. The initial `inspect_owned()` call still uses the actual ownership-label guard, but can now return its command evidence to the audit path. Immutable-ID reinspection now returns normalized failure evidence rather than throwing out of the lifecycle method.
- Stop/disconnect actions append their persistent JSONL action audit even when the action throws or the subsequent inspection times out/fails. Command and inspection errors are both retained rather than one masking the other. Unknown after-state remains `null`/unknown and fails the action; no disconnect follows an unverified stop. Missing `State.Running` is not interpreted as stopped, and malformed/missing network snapshots are not interpreted as detached.
- ID-targeting, ownership/endpoint checks, `.5` peer guard and stop/disconnect-only/no-remove behavior remain intact. Audit remains under `<campaign-root>/<session-id>/container-lifecycle.jsonl`, outside `/raw` and `/state`.

## RED/GREEN and validation

**RED on the old actual helper:** before implementing the normalization, ran `python3 -m unittest validation.campaign.test_owned_container_retirement -v` with the new fake-Docker exception cases. Seven exception-audit cases errored: post-operation inspection exceptions escaped before the action audit, and the initial exception audit lacked normalized exception evidence. No live Docker was involved.

After repair:

- `python3 -m unittest validation.campaign.test_owned_container_retirement -v` — **PASS**, 16 tests.
- `python3 -m unittest discover -s validation/campaign -p 'test_*.py' -v` — **PASS**, 44 tests.
- `python3 -m py_compile validation/campaign/run.py validation/campaign/test_owned_container_retirement.py validation/campaign/test_guest_state.py` — **PASS**.
- `git diff --check` — **PASS** for root.
- `git diff --cached --quiet` and nested equivalents — **PASS**, no staged files.

The actual-method fake-Docker tests inject `TimeoutExpired` and `OSError`/transport failures at initial name inspection, immutable-ID pre-stop inspection, post-stop inspection, pre-disconnect inspection and post-disconnect inspection. They also combine stop/disconnect command exceptions with post-action inspection exceptions. Assertions verify exact attempted argv and partial streams/errors are persisted, after-state remains unknown where appropriate, no unsafe next action runs, and no remove occurs. Additional cases cover malformed unknown stop/detach state, ownership rejection, protected `.5` peer rejection, and default/failed cleanup preservation. **Mocked command-boundary tests are not live Docker proof.**

## Exact current review bundle

New, non-overwriting bundle: `/tmp/eintr-final-repair2-review-20261003-uOqnsS/`.

It contains complete tracked diffs, full per-repository HEAD/status/cached-diff metadata, `PreparedDiscovery.h` byte copy/hash and exact add-file diff, and exact untracked validation test add-file patches/copies. It includes the current startup/publication round-2 changes, this lifecycle repair, the full dirty root state, and the nested repository snapshots. It does not overwrite prior round-1 bundles or `/tmp/eintr-final-review-live-diffs-20261002`.

HEADs: root `739dd1d6d48f8ee7fef39636cb038e240d7f3890`; lwIP `fbac6d22cd08d12fccfc27c4efa383a8be32335f`; mros2 `912cfbdd1af9a28be685ab67803093d84bb31ed1`; embeddedRTPS `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182`; WAMR `db2054224dcff9686f3f98850a29c554974096bc`.

Exact tracked diff SHA-256: root `b7f8e1bd5b8352f541acd1e1f9feffb0c188ac6d0c9399ee83d53a19b7113c3f`; lwIP `588c97bc4496ba803c53747a60dcab1c93678498e9a6fa0a7ace3589ad4b1fcc`; mros2 `df36992bfcc1f3db050cbc0327ccca8010e5c37128a3ea73ca31b0114d572cbe`; embeddedRTPS `ef8a59ed007b966e9a3cd1eaa87cac9026421c20465f3649ff326b7c2ef18e9f`; WAMR `c747dc9f9a66b105480909bdcb807b8fc4ae004da0739fdbd888c857a51166da`.

Additional exact bundle hashes: untracked validation-test patch `cfb9541be439ebeda1f02046e32514caf8f3d5b44762845aa5e25ca34363bb20`; `PreparedDiscovery.h` add-file diff `7da0249e5b33b0d20dbc83fb59cd59126e8e425d0650dda3a74000ebb6b3f686`; bundle checksum manifest `05d9d771deaec2b84ace74dbb428597bcd8a6bb76f4d352551af7e516c9d812b`. Header source SHA remains `09811065af93c1d84ef24face33ac05f5fa2d3ceaa5ffedafdb5fdf723b4ffd7`.

All four nested production diff hashes match the completed startup round-2 snapshot exactly (`nested-source-comparison.txt` has `match=yes` for lwIP, mros2, embeddedRTPS and WAMR); no nested source changed in this lifecycle task.

## Changed-file hashes and residuals

- `validation/campaign/run.py` — `a3cded2f2df5ea10864cc605327dfbbbf396cd261890c3ec3c17601743d3fb09`
- `validation/campaign/test_owned_container_retirement.py` — `8f996eec6dd2ec2b41a263936dac731591ffc19fe576adffbd48f88eb1a3ffa2`

The reviewer can now inspect the complete current repository snapshot. Live Docker stop/disconnect remains untested in this slice; it is not claimed as a broken application or campaign gate. Existing communication evidence is unchanged. Parent separately verified bytes/hashes for all four retained checkpoint images. The unauthorized source-container deletion and prior irreversible evidence losses remain disclosed and cannot be retro-certified. No cleanup, staging, commit, push, wiki, adoption, or publication occurred.
