# WAMR C/R State Boundary Verification Plan for Luna

## Goal

現在の WAMR checkpoint/restore が、どの状態を復元し、どの状態を新しい restore process 側で初期化するのかを、同一の checkpoint boundary 上で実験的に分離して確認する。

検証する主張は次の3つ。

1. `wasm32-wasi-threads` にコンパイルされた C global（guest sentinel、`netif_default`、`netif_wasm` など）は guest state として C/R 後も保持される。
2. `iwasm --native-lib` でロードする host-native shared library の true native global は、新しい restore process では初期値から始まる。
3. changed-IP restore (`172.18.0.3 -> 172.18.0.6`) では、`netif_wasm_refresh()` が NULL の `netif_default` を作り直すのではなく、restore された source-side の `.3` 状態を `.6` に更新している。

重要: これは仮説であり、実験結果をこの結論に合わせてはならない。

---

## Environment and fixed baselines

研究ホスト:

```bash
ssh osslab@rt.takutk.com -p 7000
```

基準 integration worktree:

```text
/home/osslab/20260930-mros2-wasm-eintr-no-udp-recover-integration
```

root baseline:

```text
e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0
```

lwip-wasm baseline:

```text
160d01d0a088fad9b20ce334bad1e3a110576500
```

実験専用 worktree / branch:

```text
/home/osslab/20261004-mros2-wasm-cr-state-boundary
experiment/cr-state-boundary
```

この worktree はすでに存在する。計画作成時点の HEAD:

```text
b000f2194c63b2c2c93cc089661be1c1adccf302
test: scaffold C/R state-boundary experiment
```

merge-base は指定 baseline `e61522aa...`。

---

## Planning-time observed dirty state

実験 worktree には、すでに途中成果がある。

```text
A  experiments/cr-state-boundary/build-native-probe.sh
A  experiments/cr-state-boundary/native_probe.c
 m lwip-wasm
 m third_party/cartographer-library/wasi/boost
 ? third_party/wamr
 M workspace/echoback_string/app.cpp
?? experiments/cr-state-boundary/__pycache__/
?? experiments/cr-state-boundary/build-provenance/
?? experiments/cr-state-boundary/build.sh
?? experiments/cr-state-boundary/build/
?? experiments/cr-state-boundary/campaign.py
?? experiments/cr-state-boundary/provenance/paused-existing-peer-before.json
?? experiments/cr-state-boundary/runtime-build/
?? experiments/cr-state-boundary/smoke/
?? experiments/cr-state-boundary/state_probe.py
?? experiments/cr-state-boundary/test_campaign_parser.py
```

計画作成時点で確認済みの source diff:

- `workspace/echoback_string/app.cpp`:
  - guest sentinel `cr_guest_probe`
  - native import `cr_host_probe_get/set`
  - `[CR-STATE] loop`
  - deterministic sentinel
  - `[CR-STATE] armed`
- `lwip-wasm/src/netif/netif_wasm.c`:
  - `netif_init` diagnostic
  - `netif_refresh` pre-mutation diagnostic

これらは見た範囲では観測用変更のみ。ただし「存在する」ことと「正しく build/runtime verification 済み」は区別すること。

`third_party/wamr` には experiment 用 build directory が untracked。
Boost submodule に dirty state がある。どちらも勝手に clean/reset しない。

---

# Global constraints

以下は全 Task で絶対に守る。

- `integration/network-migration` worktreeを直接編集しない。
- 実験専用 worktreeのみ編集する。
- `git clean` を実行しない。
- unrelated dirty stateを reset/revert/delete しない。
- existing untracked experiment artifact を削除しない。
- production behavior を変えない。
- socket recreation を追加しない。
- retry/recovery path を変更しない。
- Discovery logic を変更しない。
- topic/QoS/publish payload を変更しない。
- delay/timing を変更しない。
- checkpoint implementation 自体を変更しない。
- WAMR source を primary experiment のために変更しない。
- instrumentation を checkpoint signal handler に追加しない。
- upstream / `oss-fun` へ push しない。
- 原則 push しない。
- 仮に push が必要でも `tauto1127` namespace のみ。
- 失敗した experiment を PASS にするために実装を変更し続けない。
- 「観測」「source/build classification」「因果解釈」を分離する。
- same-IP が成立するまで changed-IP の結果を原因説明に使用しない。
- pointer 数値そのものは強い証拠としない。non-NULL、pointer equality、stored IP、sentinel の組で判断する。

各 source change は原則:

```text
1つの小さい変更
-> build/static verification
-> git diff --check
-> 必要な最小 runtime smoke
-> commit
-> 次の Task
```

とする。

---

# Experimental hypotheses and falsification conditions

## H1: Guest C global is restored

guest sentinel:

```cpp
static volatile uint32_t cr_guest_probe = 0;
```

checkpoint 前に sentinel `S` を保存する。

支持する観測:

```text
pre-C/R:          guest = S
first post-R:     guest = S
```

反証:

```text
first post-R guest != S
```

この場合、理由を推測して変更を加えず、raw evidence を保存する。

## H2: Host-native global starts fresh

native shared library:

```c
static uint32_t host_probe = 0;
```

支持する観測:

```text
pre-C/R:          host = S
first post-R:     host = 0
```

反証:

```text
first post-R host == S
```

または、0以外の予期しない値。

この場合もコードを合わせに行かない。

## H3: restored netif is refreshed, not reconstructed

changed-IP first pre-mutation observation で:

```text
netif_default != NULL
netif_default == &netif_wasm
stored_ip = 172.18.0.3
probed_ip = 172.18.0.6
```

その後に stored IP が `.6` になる。

反証:

- first refresh で `netif_default == NULL`
- stored IP が checkpoint source の `.3` でない
- first observation が mutation 後である
- first observation の一意性を確定できない

---

# Application-level acceptance gate

既存の correlated round trip を使用する。

```text
Wasm publish
-> native peer receive
-> native peer echo publish
-> Wasm callback
```

単なる publish log だけでは成功にしない。

必要な gate:

- no-C/R control: 10 consecutive full round trips
- each same-IP trial:
  - pre-C/R 10 consecutive full round trips
  - post-R 10 consecutive full round trips
- each changed-IP trial:
  - pre-C/R 10 consecutive full round trips
  - post-R 10 consecutive full round trips

---

# Task 0: Audit and freeze the existing partial experiment

## Purpose

既存途中成果を消したり再実装したりせず、今どこまで進んでいるかを確定する。

## Actions

研究ホストに接続後、実験 worktree で以下を記録する。

```bash
git status --short --branch
git log --oneline --decorate -10
git rev-parse HEAD
git merge-base e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0 HEAD
git submodule status --recursive
git diff -- workspace/echoback_string/app.cpp
git -C lwip-wasm diff -- src/netif/netif_wasm.c
git diff --cached
```

さらに、`experiments/cr-state-boundary/` の source-like files を読む。

最低限:

```text
native_probe.c
build-native-probe.sh
build.sh
campaign.py
state_probe.py
test_campaign_parser.py
```

## Classification

各 file/change を次のどれかに分類し、audit note に残す。

```text
A. plan-aligned source instrumentation
B. generated build/runtime artifact
C. pre-existing unrelated dirty state
D. unknown / needs explanation
```

## Output

```text
experiments/cr-state-boundary/provenance/audit-current-state.md
```

## Stop condition

production behavior を変える既存変更、または説明不能な source modification が見つかった場合、その変更には触れず、audit に記録する。

既存の plan-aligned instrumentation が正しいなら、作り直さず引き継ぐ。

---

# Task 1: Reconfirm provenance and isolation

## Verify immutable baseline

read-only で integration worktree:

```bash
git -C /home/osslab/20260930-mros2-wasm-eintr-no-udp-recover-integration rev-parse HEAD
git -C /home/osslab/20260930-mros2-wasm-eintr-no-udp-recover-integration status --short --branch
git -C /home/osslab/20260930-mros2-wasm-eintr-no-udp-recover-integration/lwip-wasm rev-parse HEAD
```

期待値:

```text
root = e61522aac9e775bda8ab5c3cbbe8f05fe197e8a0
lwip = 160d01d0a088fad9b20ce334bad1e3a110576500
```

integration worktree の `?? experiments/` を消さない。

## Record experiment revisions

以下を保存:

```text
root
cmsis-wasm
lwip-wasm
mros2
mros2/embeddedRTPS
third_party/wamr
```

Output:

```text
experiments/cr-state-boundary/provenance/revisions-before.txt
experiments/cr-state-boundary/provenance/status-before.txt
```

既存ファイルがある場合は中身を読み、必要なら追記用の別ファイルを作る。上書きで evidence を失わない。

---

# Task 2: Verify and commit the host-native sentinel

## Files

```text
experiments/cr-state-boundary/native_probe.c
experiments/cr-state-boundary/build-native-probe.sh
```

## Required implementation

shared library 内に:

```c
static uint32_t host_probe = 0;
```

Wasmから:

```text
cr_host_probe_get() -> uint32_t
cr_host_probe_set(uint32_t)
```

を呼べる。

module は `env`。

WAMR の dynamic native-library API の既存 sample を一次情報として確認する。

## Static verification

build:

```bash
./experiments/cr-state-boundary/build-native-probe.sh
```

最低限:

```bash
nm -D experiments/cr-state-boundary/build/libcr_state_probe.so | grep get_native_lib
```

registration symbol と intended exported native functions を確認。

native global 初期値は固定 0 のまま。

## Behavior constraint

time/PID/random で初期化しない。
constructor で値を変えない。
WAMR core を変更しない。

## Commit boundary

static/load smoke が通り、diff が native probe のみなら:

```text
test: add native state probe for C/R boundary
```

既に staged されている場合でも、内容を確認してから commit。

---

# Task 3: Verify and commit the guest sentinel instrumentation

## File

```text
workspace/echoback_string/app.cpp
```

## Required behavior

publish loop の最初、値を書き換える前に:

```text
[CR-STATE] loop id=N guest_before=0x... host_before=0x...
```

を出す。

sentinel:

```text
S = 0xA5000000 | (id & 0xffff)
```

を guest/native の両方へ set。

checkpoint boundary 用:

```text
[CR-STATE] armed id=N value=0x...
```

を出す。

## Important placement

`loop` observation は guest/native を書き換える前。
`armed` は両 sentinel set 後。

existing message payload, count semantics, publish, QoS, topic, `osDelay(1000)` を変えない。

## Static verification

fresh Wasm build 後:

```bash
wasm-objdump -x <echoback_string.wasm> | grep -E 'cr_host_probe_(get|set)'
```

imports が `env` 側に存在すること。

no-C/R smoke で:

```text
initial loop: guest_before=0, host_before=0
next loop:    guest_before=previous S, host_before=previous S
```

が継続すること。

## Commit boundary

```text
test: instrument guest and native probe continuity
```

---

# Task 4: Verify and commit pre-mutation lwIP diagnostics

## File

```text
lwip-wasm/src/netif/netif_wasm.c
```

## Required observation

`netif_wasm_refresh()` で:

1. `probe_local_ip(&addr)` succeeds
2. まだ state を変更していない

この位置で:

```text
[CR-STATE] netif_refresh
  default=<ptr>
  self=<ptr>
  same=<0|1>
  stored=<hex>
  probed=<hex>
  pending=<n>
```

を1行で parseable に記録。

startup の `netif_wasm_add()` 後に:

```text
[CR-STATE] netif_init ...
```

を出してよい。

## Critical check

diagnostic log が必ず以下より前:

```c
if (netif_default == NULL) { ... }
netif_wasm.ip_addr.addr = addr;
```

## Diff gate

`lwip-wasm/src/netif/netif_wasm.c` の experiment diff は read/log のみであること。

assignment追加、lock追加、sleep追加、refresh call追加は禁止。

## Commit boundary

submodule 内で commit を作る場合は experiment-local branch/commit とし、root 側 submodule pointer 更新も独立して記録する。

意図しない remote push はしない。

commit message:

```text
test: observe restored lwIP global state before refresh
```

---

# Task 5: Reproducible build and static classification

## Purpose

runtime result より先に、各 state がどこにコンパイルされているかを evidence 化する。

## Build inputs

既存:

```text
experiments/cr-state-boundary/build.sh
```

があるため、まず内容を監査する。問題なければ再利用。

Wasm build は既存の validated WASI SDK 21 pattern を参照する。

WAMR runtime は pinned experiment worktree の `third_party/wamr` を使う。

feature family:

```text
classic interpreter ON
wasi-threads ON
thread manager ON
shared memory ON
libc-wasi ON
legacy WAMR pthread OFF
```

## Do not

WAMR source を primary experiment 用に変更しない。

## Save exact build commands

```text
experiments/cr-state-boundary/build-provenance/
```

に:

- configure command
- build command
- compiler version
- WASI SDK version
- compile_commands.json
- artifact paths
- SHA-256

を保存。

## Static classification gate

`compile_commands.json` で `netif_wasm.c` の compile command を確認し:

```text
--target=wasm32-wasi-threads
```

を evidence として保存。

object に:

```text
netif_default
netif_wasm
ip_changed_pending
```

の symbol を確認できる範囲で確認。

例:

```bash
/opt/wasi-sdk-21/bin/llvm-nm <netif_wasm.c.obj> | grep -E 'netif_default|netif_wasm|ip_changed_pending'
```

## Artifact hashes

最低限:

```text
iwasm
echoback_string.wasm
libcr_state_probe.so
native peer
```

source/restore で iwasm/Wasm/native-probe hash が同一であること。

---

# Task 6: Audit/finish the deterministic campaign runner

## Existing files

```text
experiments/cr-state-boundary/campaign.py
experiments/cr-state-boundary/state_probe.py
experiments/cr-state-boundary/test_campaign_parser.py
```

まず既存コードを読み、要求との差分だけを補う。

## Required parsed events

```text
[CR-STATE] loop ...
[CR-STATE] armed ...
[CR-STATE] netif_init ...
[CR-STATE] netif_refresh ...
```

## Pre-checkpoint sequence

runner は:

1. application full-roundtrip 10 consecutive を確認
2. complete `armed id=N value=S` を1つ確定
3. `checkpoint-boundary.json` に N/S を保存
4. その後のみ SIGUSR2

とする。

曖昧な armed marker では checkpoint しない。

## Post-restore sequence

1. resume後最初の `loop` を確定
2. saved S と `guest_before`, `host_before` を比較
3. resume後最初の `netif_refresh` pre-mutation marker を確定
4. topology-specific assertion
5. post-R full-roundtrip 10 consecutive

## Per-trial result schema

単一 boolean に潰さず最低限:

```json
{
  "guest_state_preserved": null,
  "native_state_reset": null,
  "netif_default_restored_nonnull": null,
  "netif_points_to_restored_object": null,
  "stored_ip_before_refresh": null,
  "probed_ip_before_refresh": null,
  "application_roundtrip_pass": null
}
```

加えて:

```text
saved_sentinel
checkpoint_armed_id
first_post_restore_loop
first_post_restore_netif_refresh
pre_roundtrip_count
post_roundtrip_count
startup_reran
artifact_hashes
```

を残す。

## Fail closed

以下なら trial を failed/invalid とする:

- saved S が一意に取れない
- first post-R loop が曖昧
- first post-R refresh が曖昧
- checkpoint boundary と log が相関できない
- artifact hash mismatch
- application startup が restore 後に再実行された疑い

## Parser tests

synthetic snippets で最低限:

- guest persisted / native reset
- guest failed
- native unexpectedly persisted
- missing armed
- ambiguous first marker
- same-IP refresh
- changed-IP refresh

をテスト。

## Commit boundary

runner/parser tests が通れば:

```text
test: add deterministic C/R state-boundary campaign
```

---

# Task 7: No-C/R control x1

## Purpose

instrumentation 自体が状態を壊していないことと、native global が通常 process 内では保持されることを確認。

## Fresh run

C/R は行わない。

## Required observations

initial:

```text
guest_before = 0
host_before = 0
```

subsequent loop:

```text
guest_before == previous armed S
host_before == previous armed S
```

これが連続して成立。

application full roundtrip 10 consecutive。

## Failure rule

C/Rなしで:

- host probe が 0 に戻る
- guest/host が divergence
- application roundtrip が壊れる

ならここで stop。

same-IP に進まない。

## Evidence directory

```text
experiments/cr-state-boundary/results/control-01/
```

最低限:

```text
wasm.log
peer.log
probe-timeline.json
artifact-hashes.json
revisions.txt
build-commands.txt
result.json
```

---

# Task 8: Same-IP C/R primary experiment x3

## Topology

```text
172.18.0.3 -> 172.18.0.3
```

## Run exactly 3 fresh trials

```text
same-ip-01
same-ip-02
same-ip-03
```

## Per-trial required sequence

1. fresh source run
2. pre-C/R full roundtrip 10 consecutive
3. wait for one complete `armed id=N value=S`
4. persist N/S
5. checkpoint
6. start fresh restore iwasm process with the same native library
7. capture first post-R `loop`
8. capture first post-R pre-mutation `netif_refresh`
9. post-R full roundtrip 10 consecutive

## Per-trial expected H1/H2 observations

```text
guest_before == S
host_before == 0
```

first post-R loop で、どちらも書き換える前に読むこと。

## Same-IP netif observations

```text
netif_default != NULL
netif_default == &netif_wasm
stored_ip == 172.18.0.3
probed_ip == 172.18.0.3
```

## Startup check

restore log に startup path の再実行がないこと。

例として:

```text
mros2-posix start!
initial netif_wasm_add marker
```

が restore process の restored execution path として二重に出ていないことを確認。

## Decision gate after 3 trials

H1/H2/H3のうち、この段階で判断可能な項目を trial別に表にする。

changed-IP に進む条件:

- control valid
- same-IP 3 trials が execution-wise valid
- checkpoint boundary が全 trial で一意
- first post-R observation が全 trial で一意
- application pre/post gate が全 trial で成立

H1/H2 の値が仮説と違っても、「実験として valid」なら結果をそのまま報告する。
ただし state boundary 自体が曖昧な場合は changed-IP 原因説明に進まない。

---

# Task 9: Changed-IP C/R x3

## Precondition

Task 8 の same-IP state-boundary experiment が valid であること。

## Topology

```text
172.18.0.3 -> 172.18.0.6
```

## Run exactly 3 fresh trials

```text
changed-ip-01
changed-ip-02
changed-ip-03
```

## Same sentinel gates

first post-R loop:

```text
guest_before == saved S
host_before == 0
```

仮説と異なった場合はそのまま記録。

## Critical first pre-mutation refresh observation

期待:

```text
netif_default != NULL
netif_default == &netif_wasm
stored_ip == 172.18.0.3
probed_ip == 172.18.0.6
```

この log が `netif_wasm.ip_addr.addr = addr` より前であることを source evidence でも示す。

## Later state

更新後に stored IP が `.6` になったことを、既存 log または次の観測で確認。

追加 refresh call を instrumentation のために挿入してはいけない。

## Application gate

pre 10 consecutive + post 10 consecutive。

---

# Task 10: Evidence integrity review

実験結果を解釈する前に、全 trial の evidence を機械的に確認する。

## Required per trial

- artifact hashes
- source/submodule revisions
- build commands
- checkpoint boundary
- saved sentinel S
- Wasm raw log
- peer raw log
- first post-R guest/native observation
- first post-R netif refresh pre-mutation observation
- application pre/post gate
- result.json

## Cross-trial checks

- source/restore artifact hashes identical within trial
- all accepted trials use intended root/lwip revisions
- no accidental runtime rebuild halfway through campaign
- no unintended source edit between trial 1/2/3
- no restored trial reused stale logs from previous run
- trial IDs/directories unique

## Save campaign manifest

```text
experiments/cr-state-boundary/results/manifest.json
```

---

# Task 11: Write report.md

Output:

```text
experiments/cr-state-boundary/report.md
```

## Required structure

1. Research question
2. Hypotheses
3. Experimental design
4. Artifact/source provenance
5. Static/build classification
6. No-C/R control
7. Same-IP trials
8. Changed-IP trials
9. State-boundary comparison table
10. Directly observed facts
11. Facts confirmed from source/build
12. Causal interpretation
13. Failed/ambiguous observations
14. Limitations / unverified items
15. Reproducibility commands

## Required state table

```text
| State | Location/classification | Pre-C/R | First post-R | Verdict |
| guest sentinel | Wasm-side C global | S | ... | ... |
| netif_default | Wasm-side C global | non-NULL | ... | ... |
| stored netif IP | Wasm-side C state | .3 | ... before refresh | ... |
| native sentinel | host shared-library global | S | ... | ... |
```

## Observation vs inference

### Direct observation

例:

```text
first post-R guest_before was 0x...
first post-R host_before was 0
first pre-mutation netif stored=.3 probed=.6
```

### Build/source fact

例:

```text
netif_wasm.c was compiled with --target=wasm32-wasi-threads
the Wasm imports cr_host_probe_get/set from env
```

### Inference

上の2種類を組み合わせて初めて state-boundary を説明する。

## Forbidden unsupported wording

evidence が支持しない限り:

```text
Native globals are recreated from scratch by WAMR restore.
```

とは書かない。

native probe が 0 になった場合でも、より狭く:

```text
In the tested restore path, the host-native global in the newly loaded native library began at its process-initial value rather than the pre-checkpoint value.
```

程度から始める。

## Allowed conclusion only if all corresponding gates support it

```text
In the tested WAMR C/R path, C globals compiled into the Wasm module are restored as guest state. The fresh restore process's host-native probe begins from its initial native state. During changed-IP restore, netif_wasm_refresh() updates restored source-side lwIP/netif state from .3 to .6 rather than normally reconstructing netif_default from NULL.
```

scope:

```text
tested WAMR revision only
current mROS2/lwIP build
same-physical-host Docker topology
tested .3 -> .3 and .3 -> .6 cases
```

cross-host migration/general WAMR semantics へ一般化しない。

---

# Task 12: Final diff and commits

report 完成後:

```bash
git diff --check
git status --short --branch
```

root/submodule の commits と experiment evidence の関係を記録。

最後の documentation commit:

```text
test: document WAMR C/R state-boundary evidence
```

production comment の修正はこの experiment task には含めない。

たとえ実験が全 PASS でも:

```text
Native globals are recreated from scratch by WAMR restore.
```

という既存 production comment の変更は、report review 後の別 implementation task とする。

push はしない。

---

# Result interpretation matrix

## Case A

```text
guest S -> S
native S -> 0
netif non-NULL / same=1
changed-IP stored .3 / probed .6
application pass
```

=> intended state-boundary hypothesis strongly supported.

## Case B

```text
guest S -> S
native S -> S
```

=> guest state restorationは支持されるが、「fresh host-native state」の仮説は反証。native library/process lifecycle を別途調査する。今回の experiment code を PASS に合わせて変更しない。

## Case C

```text
guest != S
```

=> guest sentinel restoration仮説が反証または checkpoint-boundary が invalid。changed-IP の原因説明に進まず evidence を精査。

## Case D

```text
guest S -> S
netif_default == NULL
```

=> C globalsを一括で「restoreされる」と一般化できない。guest sentinel と netif の配置/lifecycle差を次の研究課題とする。

## Case E

```text
same-IP valid
changed-IP stored != .3 or first refresh ambiguous
```

=> H1/H2 と H3 を分離して報告。network migration mechanism の因果説明は未確定とする。

---

# Luna execution instruction

この plan を読んだ実行エージェントは、Task 0 から順番に進める。

重要:

- 既存途中成果を最初から作り直さない。
- 各 Task の verification が終わる前に次の source modification を混ぜない。
- same-IP gate 前に changed-IP へ進まない。
- failure は evidence であり、実装変更のトリガーではない。
- 各 commit は小さくする。
- 実験結果に合わせて仮説を書き換えるのではなく、仮説と観測の差を report に残す。
