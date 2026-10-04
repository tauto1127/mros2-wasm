# WAMR C/R State Boundary Verification

## Question

This experiment separates three claims about the current WAMR checkpoint/restore path:

1. C globals compiled into the Wasm module are restored as guest state.
2. A true host-native global in a native shared library starts from fresh process initialization in the restored iwasm process.
3. On changed-IP restore,  updates an already-restored source-side  object rather than normally reconstructing  from NULL.

The conclusion below is limited to the tested WAMR implementation and the same-host Docker topology used here.

## Experimental design

The experiment used an isolated worktree and branch:

- worktree: 
- branch: 
- root baseline: 
- lwip-wasm baseline: 

Instrumentation was observation-only:

- guest sentinel: 
- native sentinel:  in 
- pre-mutation  logging
- no socket recreation, delay change, discovery change, QoS change, or payload change was introduced

The application acceptance gate remained:



Execution order was preserved: no-C/R control, then 3 same-IP trials, then changed-IP trials only after all same-IP trials passed.

## Artifact provenance

Current experiment revisions after evidence capture:

- root: 
- instrumented lwip-wasm: 

Built artifact hashes:

- iwasm: 
- : 
- : 

The saved compile command shows  compiled with .  on the generated object shows symbols for , , and .  shows  and  imported from module SHELL=/bin/bash
QT_ACCESSIBILITY=1
PWD=/home/takuto1127
LOGNAME=takuto1127
SYSTEMD_EXEC_PID=206224
HOME=/home/takuto1127
LANG=en_US.UTF-8
INVOCATION_ID=13c89b93b83d448580bce66a135bd7fa
MANAGERPID=967
USER=takuto1127
SHLVL=0
XDG_RUNTIME_DIR=/run/user/1000
JOURNAL_STREAM=8:1703580
XDG_DATA_DIRS=/usr/local/share/:/usr/share/:/var/lib/snapd/desktop
PATH=/home/takuto1127/.codexify/bin:/home/takuto1127/.local/bin:/home/takuto1127/.cargo/bin:/home/takuto1127/.grok/bin:/home/takuto1127/.nvm/versions/node/v22.22.0/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
_=/usr/bin/env.  on the native probe shows .

Exact configure/build commands, compiler database, hashes, and runtime build logs are under .

## No-C/R control

 passed.

Observed:

- 10 consecutive application round trips passed, IDs 4 through 13.
- guest probe continuity passed.
- native probe continuity passed.
- 14 continuity observations were recorded.
- no spontaneous host-native reset occurred without C/R.

 was not used as experimental evidence because preflight stopped on an environment conflict with an older peer container occupying .

## Same-IP C/R results

All three  trials passed the planned state-boundary gates.

| Trial | Saved S | First post-R guest | First post-R native | netif default/self | stored | probed | app post gate |
|---|---:|---:|---:|---|---|---|---|
| same-01 |  |  |  | equal, non-NULL |  |  | PASS 10 consecutive |
| same-02 |  |  |  | equal, non-NULL |  |  | PASS 10 consecutive |
| same-03 |  |  |  | equal, non-NULL |  |  | PASS 10 consecutive |

In all three trials the restore log did not show the application startup path rerunning.

## Changed-IP C/R results

The raw evidence for all three  trials shows the planned state transition:

- first post-restore guest sentinel equals saved ;
- first post-restore native sentinel equals ;
-  is non-NULL;
- ;
- first pre-mutation stored IP is ;
- first pre-mutation probed IP is ;
- a later  observation shows stored ;
- application round trips recover and reach 10 consecutive successes.

| Trial | First stored | First probed | Later stored  | guest/native | app gate | Harness verdict |
|---|---|---|---|---|---|---|
| changed-01 |  |  | yes |  | PASS | original JSON FAIL; reanalysis against plan PASS |
| changed-02 |  |  | yes |  | PASS | PASS |
| changed-03 |  |  | yes |  | PASS | PASS |

### Harness discrepancy in changed-01

The first changed-IP run exposed a campaign bug, not a production/instrumentation failure. The initial runner checked  markers for the post-refresh destination value, while the plan explicitly required a later  observation with stored .

The raw  for changed-01 contains, in order:

1. 
2. immediately afterward, 
3. continuing application round trips

The original  is preserved unchanged as FAIL.  records the discrepancy and evaluates the same raw evidence against the planned criterion as passing. The campaign predicate was then corrected to inspect later  stored-IP observations; no production behavior or instrumentation was changed to make the experiment pass.

## State-boundary table

| State | Where it lives | Pre-C/R | First post-R | Verdict |
|---|---|---:|---:|---|
| guest sentinel | Wasm C global / guest memory |  |  | restored |
|  | C global compiled into Wasm | non-NULL | non-NULL | restored |
|  | Wasm-side object relation | true | true | restored relation observed |
| stored netif IP | Wasm-side  state |  |  before refresh | restored |
| native sentinel | host shared-library global |  |  | fresh process state |

## Directly observed facts

The experiment directly observed the following at runtime:

- A deterministic guest sentinel written before checkpoint was still present immediately after restore in every C/R trial.
- A deterministic host-native sentinel written before checkpoint was  on the first observation in the restored iwasm process in every C/R trial.
- On same-IP restore,  was non-NULL and equal to  before refresh mutation.
- On changed-IP restore, the first pre-mutation observation showed restored stored IP  while the current probed IP was .
- A subsequent observation showed stored IP .
- The application-level four-stage round-trip gate passed before and after restore in the accepted trials.

## Facts confirmed from build/source

The build/source evidence confirms:

-  is compiled for , not as part of the host-native iwasm binary.
- The generated Wasm-side object contains , , and  symbols.
- The guest module imports the native probe functions through WAMR's native library interface.
-  is a  inside the separately loaded native shared library and is initialized to zero by normal process/library initialization.
- The added  diagnostic is emitted before the state-changing assignment.

## Causal interpretation

The combined runtime and build evidence supports this interpretation for the tested implementation:

> In the tested WAMR C/R path, C globals compiled into the Wasm module are part of restored guest state. The mROS 2/lwIP  state therefore survives restore with the source-side IP. A host-native global in a freshly loaded native library begins from fresh process initialization. On changed-IP restore,  corrects the already-restored source-side network state to the destination IP; it is not normally reconstructing  from NULL.

This wording is intentionally narrower than saying all native globals are recreated by WAMR restore. The experiment directly tests a host-native global in a WAMR native library, not every possible WAMR-core native variable.

## Unverified / out of scope

The following remain unverified:

- Whether every WAMR-core native global has the same lifecycle as the native-library sentinel.
- Cross-physical-host migration behavior.
- Other WAMR build configurations, AOT/JIT modes, or different C/R implementations.
- Whether pointer numeric values themselves are meaningful across implementations; only non-NULL state and equality to the restored object are used as supporting evidence here.
- Any claim that the fallback  path can never be needed in other startup or failure modes.

No production comment was changed as part of this experiment. Any production wording change should be a separate reviewed implementation task.
