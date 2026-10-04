# WAMR C/R State Boundary Verification

## Question

This experiment separates three claims about the current WAMR checkpoint/restore path:

1. C globals compiled into the Wasm module are restored as guest state.
2. A true host-native global in a native shared library starts from fresh process initialization in the restored iwasm process.
3. On changed-IP restore, `netif_wasm_refresh()` updates an already-restored source-side `netif_wasm` object rather than normally reconstructing `netif_default` from NULL.

The conclusion below is limited to the tested WAMR implementation and the same-host Docker topology used here.

## Experimental design

The experiment used an isolated worktree and branch:

- worktree: `/home/osslab/20261004-mros2-wasm-cr-state-boundary`
- branch: `experiment/cr-state-boundary`
- root baseline: `e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0`
- lwip-wasm baseline: `160d01d0a088fad9b20ce334bad1e3a110576500`

Instrumentation was observation-only:

- guest sentinel: `static volatile uint32_t cr_guest_probe`
- native sentinel: `static uint32_t host_probe` in `libcr_state_probe.so`
- pre-mutation `netif_wasm_refresh()` logging
- no socket recreation, delay change, discovery change, QoS change, or payload change was introduced

The application acceptance gate remained:

`Wasm publish -> native peer receive -> native peer echo publish -> Wasm callback`

Execution order was preserved: no-C/R control, then 3 same-IP trials, then changed-IP trials only after all same-IP trials passed.

## Artifact provenance

Current experiment revisions after evidence capture:

- root: `733f029ca77ed430880f7ddae1b1b7d45212fe44`
- instrumented lwip-wasm: `50a6e414aa7c5863e634603102640741ea7c3dd1`

Built artifact hashes:

- iwasm: `fa63c40c2a17f8df6461d687a95cb01bf544e0b7788377d41c317dcec6d46822`
- `libcr_state_probe.so`: `b91cdb900b478292d78a8dbfab24906bbdd3252be93b688f9c03e96c0b9121ca`
- `echoback_string.wasm`: `52ecd6ffde313c25cc6c20298769f7c9ad816419b0ddce80555c5bc2417520e0`

The saved compile command shows `netif_wasm.c` compiled with `--target=wasm32-wasi-threads`. `llvm-nm` on the generated object shows symbols for `netif_default`, `netif_wasm`, and `ip_changed_pending`. `wasm-objdump` shows `cr_host_probe_get` and `cr_host_probe_set` imported from module `env`. `nm -D` on the native probe shows `get_native_lib`.

Exact configure/build commands, compiler database, hashes, and runtime build logs are under `experiments/cr-state-boundary/build-provenance/`.

## No-C/R control

`smoke/control/run-02` passed.

Observed:

- 10 consecutive application round trips passed, IDs 4 through 13.
- guest probe continuity passed.
- native probe continuity passed.
- 14 continuity observations were recorded.
- no spontaneous host-native reset occurred without C/R.

`run-01` was not used as experimental evidence because preflight stopped on an environment conflict with an older peer container occupying `.5`.

## Same-IP C/R results

All three `.3 -> .3` trials passed the planned state-boundary gates.

| Trial | Saved S | First post-R guest | First post-R native | netif default/self | stored | probed | app post gate |
|---|---:|---:|---:|---|---|---|---|
| same-01 | `0xA500000E` | `0xA500000E` | `0` | equal, non-NULL | `.3` | `.3` | PASS 10 consecutive |
| same-02 | `0xA500000E` | `0xA500000E` | `0` | equal, non-NULL | `.3` | `.3` | PASS 10 consecutive |
| same-03 | `0xA500000E` | `0xA500000E` | `0` | equal, non-NULL | `.3` | `.3` | PASS 10 consecutive |

In all three trials the restore log did not show the application startup path rerunning.

## Changed-IP C/R results

The raw evidence for all three `.3 -> .6` trials shows the planned state transition:

- first post-restore guest sentinel equals saved `S`;
- first post-restore native sentinel equals `0`;
- `netif_default` is non-NULL;
- `netif_default == &netif_wasm`;
- first pre-mutation stored IP is `.3`;
- first pre-mutation probed IP is `.6`;
- a later `netif_refresh` observation shows stored `.6`;
- application round trips recover and reach 10 consecutive successes.

| Trial | First stored | First probed | Later stored `.6` | guest/native | app gate | Harness verdict |
|---|---|---|---|---|---|---|
| changed-01 | `.3` | `.6` | yes | `S / 0` | PASS | original JSON FAIL; reanalysis against plan PASS |
| changed-02 | `.3` | `.6` | yes | `S / 0` | PASS | PASS |
| changed-03 | `.3` | `.6` | yes | `S / 0` | PASS | PASS |

### Harness discrepancy in changed-01

The first changed-IP run exposed a campaign bug, not a production/instrumentation failure. The initial runner checked `dynamic ip` markers for the post-refresh destination value, while the plan explicitly required a later `netif_refresh` observation with stored `.6`.

The raw `wasm-restore.log` for changed-01 contains, in order:

1. `stored=.3, probed=.6, same=1`
2. immediately afterward, `stored=.6, probed=.6`
3. continuing application round trips

The original `result.json` is preserved unchanged as FAIL. `result-reanalysis.json` records the discrepancy and evaluates the same raw evidence against the planned criterion as passing. The campaign predicate was then corrected to inspect later `netif_refresh` stored-IP observations; no production behavior or instrumentation was changed to make the experiment pass.

## State-boundary table

| State | Where it lives | Pre-C/R | First post-R | Verdict |
|---|---|---:|---:|---|
| guest sentinel | Wasm C global / guest memory | `S` | `S` | restored |
| `netif_default` | C global compiled into Wasm | non-NULL | non-NULL | restored |
| `netif_default == &netif_wasm` | Wasm-side object relation | true | true | restored relation observed |
| stored netif IP | Wasm-side `netif_wasm` state | `.3` | `.3` before refresh | restored |
| native sentinel | host shared-library global | `S` | `0` | fresh process state |

## Directly observed facts

The experiment directly observed the following at runtime:

- A deterministic guest sentinel written before checkpoint was still present immediately after restore in every C/R trial.
- A deterministic host-native sentinel written before checkpoint was `0` on the first observation in the restored iwasm process in every C/R trial.
- On same-IP restore, `netif_default` was non-NULL and equal to `&netif_wasm` before refresh mutation.
- On changed-IP restore, the first pre-mutation observation showed restored stored IP `.3` while the current probed IP was `.6`.
- A subsequent observation showed stored IP `.6`.
- The application-level four-stage round-trip gate passed before and after restore in the accepted trials.

## Facts confirmed from build/source

The build/source evidence confirms:

- `netif_wasm.c` is compiled for `wasm32-wasi-threads`, not as part of the host-native iwasm binary.
- The generated Wasm-side object contains `netif_default`, `netif_wasm`, and `ip_changed_pending` symbols.
- The guest module imports the native probe functions through WAMR's native library interface.
- `host_probe` is a `static uint32_t` inside the separately loaded native shared library and is initialized to zero by normal process/library initialization.
- The added `netif_wasm_refresh()` diagnostic is emitted before the state-changing assignment.

## Causal interpretation

The combined runtime and build evidence supports this interpretation for the tested implementation:

> In the tested WAMR C/R path, C globals compiled into the Wasm module are part of restored guest state. The mROS 2/lwIP `netif_default` state therefore survives restore with the source-side IP. A host-native global in a freshly loaded native library begins from fresh process initialization. On changed-IP restore, `netif_wasm_refresh()` corrects the already-restored source-side network state to the destination IP; it is not normally reconstructing `netif_default` from NULL.

This wording is intentionally narrower than saying all native globals are recreated by WAMR restore. The experiment directly tests a host-native global in a WAMR native library, not every possible WAMR-core native variable.

## Unverified / out of scope

The following remain unverified:

- Whether every WAMR-core native global has the same lifecycle as the native-library sentinel.
- Cross-physical-host migration behavior.
- Other WAMR build configurations, AOT/JIT modes, or different C/R implementations.
- Whether pointer numeric values themselves are meaningful across implementations; only non-NULL state and equality to the restored object are used as supporting evidence here.
- Any claim that the fallback `netif_default == NULL` path can never be needed in other startup or failure modes.

No production comment was changed as part of this experiment. Any production wording change should be a separate reviewed implementation task.
