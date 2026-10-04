# Current state audit

Audit date: 2026-10-04 (Asia/Tokyo)

## Worktree and revisions

- Worktree: `/home/osslab/20261004-mros2-wasm-cr-state-boundary`
- Branch: `experiment/cr-state-boundary`
- HEAD: `ed296ca2f4d8790a2823ca40c376c2cb15629fa9` (`fix: restore report code literals`)
- Merge-base with the plan baseline: `e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0`
- The HEAD history already contains the native probe, guest instrumentation, lwIP observation pointer, reproducible build/campaign, recorded evidence, and report commits. The planned experiment is therefore substantially ahead of the original scaffold.

## Source and change classification

| Item | Classification | Audit |
|---|---|---|
| `experiments/cr-state-boundary/native_probe.c`, `build-native-probe.sh` | A. Plan-aligned experiment source | Committed in `1a9d7a7a`; `host_probe` is a zero-initialized native-library global with get/set wrappers registered for `env`. |
| `workspace/echoback_string/app.cpp` change from baseline | A. Plan-aligned source instrumentation | Committed in `1b0b2b6e`; logs guest/native values before setting both sentinels, then logs the armed marker. The reviewed diff leaves payload, topic, publish, and delay behavior intact. |
| `lwip-wasm/src/netif/netif_wasm.c` change in lwIP submodule HEAD | A. Plan-aligned source instrumentation | Submodule HEAD `50a6e414`; adds `netif_init` and pre-mutation `netif_refresh` diagnostics. Its current working tree has no source diff. The root pins this revision in `6202b42e`. |
| `experiments/cr-state-boundary/build.sh`, `campaign.py`, `test_campaign_parser.py` | A. Plan-aligned experiment tooling | Committed in `1874fd84`. Their build provenance and raw run evidence are already present. |
| `experiments/cr-state-boundary/report.md` | A. Experiment documentation | Committed in `e062709b` and corrected in `ed296ca2`; existing report claims are not treated as a substitute for the task-by-task evidence review. |
| `experiments/cr-state-boundary/state_probe.py` | D. Unknown / needs explanation | Untracked and only seven lines long, containing imports and no implementation. It is not used by the campaign imports found during this audit. Preserve it unchanged until its origin and intended role are established. |
| `experiments/cr-state-boundary/plan.md` | D. Untracked task input | The plan being executed is untracked in this worktree. Preserve it unchanged. |

## Generated and unrelated state

- B. Generated experiment artifacts: `experiments/cr-state-boundary/__pycache__/`, `build/`, `runtime-build/`, and the existing `build-provenance/` and `smoke/` evidence. These are retained as found.
- B. WAMR submodule contains untracked `product-mini/platforms/linux/build-cr-state-boundary/` and `build-cr-state-boundary-classic/` directories. No WAMR source diff was found; do not clean these directories.
- C. The Boost submodule has modified nested submodule pointers for `libs/iostreams` and `libs/test`. This matches the pre-existing unrelated Boost dirty state called out in the plan; it is untouched.

## Stop-condition review

The reviewed application and lwIP changes are observation-only and match the plan. No production behavior change or unexplained production-source modification was found. The untracked `state_probe.py` is an incomplete experiment helper stub; it has not been edited or used. Other independent tasks can proceed, but Task 6 must resolve whether this stub is needed before using it or drawing any result from it.
