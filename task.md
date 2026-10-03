# EINTR IP refresh — task board

更新: 2026-10-03。これは**作業分解・引継ぎ用の計画**。文書の作成自体は採用・公開の許可ではない。

## 最新確定状態（以下の旧分解表より優先）

- T01–T10: DONE。最終 actual-source 全10-task suite `validation/rtps/runs/20261003T003252-all-2332558/coverage.manifest`。初期化6失敗を `completeInit()` まで延長、後段SEDP失敗／正常起動も実行。
- T11: DONE。最終 startup source の通常3target clean build、template hash不変、observerなし。`validation/rtps/runs/20261003T-startup-repair2-T11-final/`。
- T12: historical instrumented SAME/CHANGED/REPEATED + final normal no-C/R done as recorded. At user's later request, exact final normal app `.3→.6` C/R attempted; **FAIL** post-restore application gate: 226 Wasm publishes,232 native receives/echo publish returns,0 Wasm callbacks. Logged current IP changed to `.6`; no end-to-end recovery. Full evidence and bounded disposition: `validation/final-normal-cr-20261003.md`. Do not continue SAME/REPEATED until this failure is understood and resources/authority are rechecked.
- T13: DONE。final repair-review **2/2**、独立 **OK with notes**、P1二件閉鎖、P2 trace+normal flag併用の誤分類をreport-onlyで繰越。親がlive diff/new header、通常3artifact＋23pins、4image全file/selected bytesを照合し **明示採用**。`validation/final-adoption-20261003.md` が採用判断・ordered20項目・残余リスクの正本。
- T14: dependency/source publication DONE to verified tauto1127 remotes. Wiki working note now records the exact final-artifact C/R failure (remote main `84397f4`, plus concurrent durable migration-page/log update from another session). Initial source adoption/push is historical and not retracted; exact final-artifact C/R recovery acceptance is **NOT MET**. `validation/final-normal-cr-20261003.md` records the retained failure; P2 also remains.
- 間違った旧PASS、画像上書き／消失、未許可docker rmによるrootfs/object inspectability損失は撤回／開示したまま。最新helperはID固定stop/disconnectのみ、例外監査・unknown fail-closed。削除なし、連続`.5` peer不変。

以下は2026-10-02時点の分解・失敗履歴／task contractを残したもの。旧PARTIAL/BLOCKED/repair-review0回の記述を最新状態として再利用しない。

## 0. 現在地と正本

- Root: `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl`、branch `fix/eintr-ip-refresh`。
- 正本: `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh/experiments/eintr-ip-refresh-phase0/gate-b/approved-design.md`。変更しない。本計画と食い違えば正本を優先し、親へ戻す。
- 基点: root `c88b569a567529c5c49cb64e698c8cbdea987206`、lwIP `fbac6d22cd08d12fccfc27c4efa383a8be32335f`、mros2 `912cfbdd1af9a28be685ab67803093d84bb31ed1`、embeddedRTPS `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182`。
- C++部分diff: `validation/rtps/final-delegated-diff.diff`、SHA256 `acffe689756e1c01cf23128689aafa5ef06f7ca671211e60cafca0edfc8faeb4`。12 files、204 insertions/78 deletions。未採用・未commit。
- 引継ぎ: `validation/rtps/{parent-stop-state.txt,rtps-report-followup-2.md,before-followup-1.diff,before-followup-2.diff}`。
- 読み取った実装事実: `mros2` は CMake `INTERFACE` libraryでsourcesを消費する。`embeddedRTPS/CMakeLists.txt` はない。「既存のstandalone embeddedRTPS targetをlink済み」と扱わない。
- Operatorがこの計画の実行を承認。親takeoverを再開し、T01 fixtureは実build/run済み。既存C++追加実装2回の未完了履歴は保持。最終review未起動、repair-reviewは0回。中心transactionは親担当、独立小taskはLuna候補。

### 確認済み／未確認

| ID | 状態 | 確認の範囲 |
|---|---|---|
| D00 | DONE | Gate A: 旧Phase0のsame/changed-IP・同一ホスト通信C/R。今回の製品実装の証拠ではない |
| D01 | DONE | Gate B: 設計・実装開始のみPASS。実probe/private coreのrun09 C/R証拠は保存済み |
| D02 | DONE | clean pins/worktree、fresh CMSIS/lwIP dependency build/install |
| D03 | DONE | lwIP C seam: coordinator/snapshot/EINTR errno保持。actual-source WASI focused5casesとlwIP rebuild/install |
| P00 | PARTIAL | C++: typed builtin/init checks、copied IP reads、explicit-IP locator、changed-path一つのsnapshot。object compileのみ |
| G00 | BLOCKED | C++全投影の受入れ、3normal app builds、application campaign、final review/adoption/publication |

D03も最終source diffが変われば必要な再検証をする。P00はDONEに昇格させない。

## 1. 進め方

- Operator追加指示: 使用量を抑えるため実装はLuna worker中心。親SolはInterface・依存・統合/Gate/最終採用を所有し、中心transactionのcode writingも凍結したInterfaceに沿ってLunaへ委託する。毎taskの親チェックは省略。
- 同時production writerは1人。Git/Dockerもserial。実装worktreeは共有するので、同時writeはしない。
- **1依頼 = 1つの下記ID**。「残りC++を全部」は渡さない。task実装とC++全体受入れを区別する。
- Operator指示: 毎taskの機械的test/rebuildは不要。実装と親diff確認を先に進め、重要なfailure-atomicity/lock-order casesはT10でまとめて、3builds/C/RはT11/T12で検証する。変更していない同一source/hashのtestは繰り返さない。
- Operator追加指示: 親の毎task diff確認/承認待ちも省略する。IMPLEMENTEDは担当の実装済み報告による引継ぎで、親検証・testsは未実施。親のsource/evidence検証は統合後と最終adoptionへまとめる。VERIFIED/DONEは実command/exit/log/hashを確認した範囲のみ。object compile/未実行caseをPASSにしない。
- 予定30–45分で完了できるサイズを目安にする。これは見積もりで、黙ってkillするtimeoutではない。越えそうならpartial diffと具体的blockerを親へ返す。
- build/test setupに失敗したら、そのcommand/errorを保存し最小修正に絞る。同じ失敗で大きなtaskを丸ごと再依頼しない。
- Scope外、新しいInterface、commitがfallibleになる、deadlock、安全条件緩和が必要なら親へ戻す。pending/event/generationやgeneric Writer redesignで逃げない。
- **No source commit/staging/push before final parent adoption**。この`task.md`とvalidation artifactも自動でproduction commitへ混ぜない。

## 2. 実行順と担当

担当は再開時の予定。Luna候補は新しい委託の承認ではない。

| ID | Task | 依存 | 担当予定 | 状態 |
|---|---|---|---|---|
| T01 | focused C++ target fixtureと検証commandを成立させる | D02,D03,P00 | 親 | DONE・実WASI build/run |
| T02 | 固定historyへのprepared move insertion | T01 | Luna | IMPLEMENTED・検証待ち |
| T03 | SEDP StatefulWriterのprivate prepared admission | T02 | Luna | IMPLEMENTED・検証待ち |
| T04 | SPDP StatelessWriterのprivate latest-only replacement | T02 | Luna | IMPLEMENTED・検証待ち |
| T05 | Participant collectionsのsnapshotとcleanup lock order | T01 | 親 | IMPLEMENTED・検証待ち（legacy refreshはT07で置換） |
| T06 | TEMP serialization・owned pbuf preparation | T01 | 親 | IMPLEMENTED・検証待ち |
| T07 | applied-IPと投影transactionを統合する | T03,T04,T05,T06 | Luna | IMPLEMENTED・検証待ち |
| T08 | endpoint birthをSEDP domainへ統合する | T05,T06,T07 | Luna | IMPLEMENTED・検証待ち |
| T09 | startup失敗・WASI/native accessor整合性 | T07,T08 | Luna | IMPLEMENTED・検証待ち |
| T10 | C++全体failure/ABA/concurrency受入れ | T02–T09 | Luna | worker報告: 106位置＋解放/whole-locator・ABA/history/noalloc・typed init6失敗・birth70位置・実commit越し登録PASS。lock/native/all残・全体NOT PASS/採用未了 |
| T11 | normal3buildsとdefault/debug状態確認 | T10 | Luna | BLOCKED |
| T12 | same/changed/repeated/no-C/R serial campaign | T11 | 親（Luna候補） | BLOCKED |
| T13 | fresh independent final review + 親live adoption | T12 | fresh reviewer + 親 | BLOCKED |
| T14 | dependency-order publication・wiki・最終報告 | T13採用 | 親 | BLOCKED |

T02–T06は個別にtestできる内部seam。途中で部分投影を製品として有効化しない。T07–T10が揃うまでG00を開かない。

## 3. Task cards

`validation/rtps/run-task.sh`をT01で作成。現在T01のみ実装済み。他IDは今後追加するbatch検証Interfaceであり、未実装IDや未実行caseをPASS扱いしない。T01実測: `runs/20261002T043528-T01-2248396/`（build/run/link map/hashあり）。

### T01 — actual-source focused C++ fixture

- 入力: live C API、`mros2/CMakeLists.txt`のsource list、root config、SDK21、fresh CMSIS/lwIP install、D03 harnessの実include/link条件。
- 対象: `validation/rtps/`内の専用build/fixture/runner。production behaviorの変更はしない。
- 成果物: `run-task.sh T01`とtask別case追加箇所、actual-source C++/Micro-CDR/pbuf/既存mutexをlinkするtest executable、raw build/run logs、selected source/include/library hashes。
- 完了条件: WASI executableが既存classic iwasmで起動し、実PBufWrapper reserve/append/content/free、実UCDRのerror検出、production default無改変を確認できる。object compileだけは不可。
- Mock許可: transport/schedulerなどfixtureに不要な外部I/O。payload/history/lockを全てfakeに置換して本体の証明にしない。
- 非対象: アプリ通信、C/R、generic test framework、root CMake redesign。
- 検証: `bash validation/rtps/run-task.sh T01`。実行可能なcommandにならなければ親へ戻し、T02以降を起動しない。

### T02 — fixed history prepared insertion

- 入力: T01、`storages/{SimpleHistoryCache,CacheChange,PBufWrapper}.h`、既存SN/ring behavior。
- 対象: `SimpleHistoryCache.h`の最小内部prepared move seamとfocused cases。全public admissionの作り直しはしない。
- 成果物: validated owned ALIVE payloadを固定ringへ移す内部Interface、容量・所有権・SN・retire条件の説明。
- 完了条件: 準備済みrecordのcommitでallocation/serialization/rejectionなし。必要なmoveのnoexceptを確認。SN単調、wrap/full時の既存semantics維持、旧payload bytes不変、user historyに変更なし。
- 検証: `bash validation/rtps/run-task.sh T02`。実allocator counterでcommit中new allocationなし、prepare failureでSN/head/tail不変、ring wrap/fullを実行。
- 非対象: writer cursor、workload enqueue、locator、SPDP/SEDP transaction。一般public Writerへ新virtualを追加しない。

### T03 — private SEDP writer admission

- 入力: T02、concrete typed builtin writers、`StatefulWriter.{h,tpp}`。
- 対象: SEDP friend限定prepared-ALIVE commitと既存writer lock/cursor整合性。
- 完了条件: validated recordsはnormal writer lock内で必ずadmitでき、SN/cursor更新は実admission時のみ。非full旧SEDP recordはbytes/SN保持、full時は通常のbounded history/GAP/ACK規則を保つ。user `newChange`を変更しない。
- 検証: `bash validation/rtps/run-task.sh T03`。旧SN/newSN、full cursor、immutable payload、no-allocation/no rejectionを確認。
- 非対象: SEDP batch population bound/serialization、SPDP、birth、applied field。wire delivery成功とは呼ばない。

### T04 — private SPDP latest-only replacement

- 入力: T02、`StatelessWriter.{h,tpp}`、typed SPDP writer。
- 対象: SPDP friend限定prepared replacementとそのnormal writer lock/cursor。
- 完了条件: 準備済み最新recordへのreplace後、旧SPDP recordはperiodic resend対象から外れる。SNは単調、cursorは最新を指す。旧payload retire/freeは可、allocation/rejectionは不可。一般user/stateless historyは変更しない。
- 検証: `bash validation/rtps/run-task.sh T04`。A→B replacement後のretained bytes/cursor/resend selection、次のreplace、旧user履歴不変。
- 非対象: schedule/wire completion、SPDP timer変更、参加者locators。

### T05 — Participant fixed snapshots / lock order

- 入力: `Participant.{h,cpp}`のadd/key/full/get/find/matching/multicast/removal/heartbeat callgraphと既存mutex。
- 対象: 固定pointer/count snapshots、remote collectionのbrief guard、expired prefixesのcollect→unlock→remove、SEDP unmatched getter/remove guardsとdiagnosticの位置。
- 完了条件: array/countはguardされるがendpoint methods/SEDP/network呼出し前にParticipantをrelease。SEDP→Participantは可、逆は不可。remote lookupの返却pointer利用/lifetimeも追跡し、unlocked mutable remote dataの新しいraceを残さない。
- 検証: `bash validation/rtps/run-task.sh T05`。add/get/match snapshot、expired複数prefix/remove、unmatched diagnostic、非recursivemutexでcleanupが終了すること。timeoutだけをlock-orderの証明にしない。
- 非対象: 新しいendpoint-wide mutex、projection/applied/birthの実装。関連SEDP変更は既存mutex整合に限定。

### T06 — fallible preparation only

- 入力: captured valid network-order IP、T01、TopicData/SPDP serializer、PBufWrapper。
- 対象: discovery-private TEMP record preparation、必要なserializer return/error checks、SPDP TEMP outgoing bytes。
- 完了条件: 一つのIPがuser unicastとParticipantDataのdefault/metatraffic unicastへ入る。header/body/finalのsticky UCDR error、reserve/append/isValid/exact spaceUsedを全recordで確認。固定bounded storage、no vector。全fallible workをここに閉じ込める。
- 検証: `bash validation/rtps/run-task.sh T06`。小さいbufferのserialization failure、各pbuf allocation/append失敗、exact bytes/length、kind/port/GUID/multicast不変、temporary解放。
- 非対象: live attrs/outgoing bytes/history/SN/cursor/applied/queuesの変更。failure後に既存状態へ一切commitしない。

### T07 — parent-owned projection transaction / applied IP

- 入力: T03–T06の受入れ済みInterface、common coordinator/snapshot、existing SEDP mutex。
- 対象: `SPDPAgent`/`SEDPAgent`/必要なParticipant private projection経路。親がInterfaceを指定し、LunaがT07のみ実装。全C++残作業をまとめて渡さない。
- 完了条件: SPDPにONE `m_lastAppliedIp=0`。SEDP domain下でcurrent/appliedを比較し、equal no-op、mismatch prepare。coordinator `UNCHANGED`でもmismatchをretry。BUSYは即skip可。coreはRTPS処理前にrelease。
- Commit条件: typed init/kinds/bounds/population(history2)を事前validateし、brief Participant snapshot、全record/TEMP SPDP bytesをprepareしてからT03/T04のinfallible commit。intended locator fieldsだけ更新、outgoing bufferのUCDR pointer/lengthもlive storageへ正しくrebinding。appliedをLASTに代入。queue通知はbest-effort/local completion外。
- 検証: `bash validation/rtps/run-task.sh T07`。zero endpoints/initial0、capacity reject、coordinator unchanged+mismatch、complete success、concurrent current change、failure fingerprint不変。broadcast initial announceもunchecked legacy admissionで完了扱いしない。
- 非対象: timer変更、event/pending/generation、inbound SPDP mutexのSEDP内取得、socket再生成、rollback after history。
- 分割gate: このcardが45分目安を超えそうなら、親が受け入れ済みInterfaceを保ったprivate implementation substepsへ分ける。全体をLunaへ丸投げしない。

### T08 — runtime birth / registration

- 入力: T05–T07、Domain createWriter/createReader→Participant→SEDPの実callgraph。
- 対象: user endpointのbirth、registration preparation/admission、active pointer/count publication。
- 完了条件: SEDP domain内でbirthはcompleted applied IP（nonzero）、まだ0ならcoreを解放済みinitial valid snapshotを使う。record acceptanceがactive publicationより先。失敗/capacity超過でactive arrays/count/既存history不変。published endpoint再initは禁止。Domain creationはsingle creation thread scopeを維持。
- 検証: `bash validation/rtps/run-task.sh T08`。projection前/待機中/後のbirth、allocation失敗、2までsupported/3はreject、builtin除外、failed birth未公開。
- 非対象: arbitrary concurrent Node creation、generic endpoint allocator redesign、new lock。SEDP→brief Participant順序を守る。

### T09 — startup / accessor integration checks

- 入力: P00のtyped/init partial diff、T07/T08、C API/native mapping。
- 対象: Domain concrete init checks、SPDP.init→SEDP.init→builtin publication、Locator/UdpDriver/GUID/current readersの残り整合。
- 完了条件: init失敗でfalse-readyやpartial builtin countsを公開しない。retry可能性を確認し、不可能なpartially initialized slotは再利用・成功扱いしない。core nested無し、non-WASIへWASI symbols漏れ無し、GUID/default identity/ports/multicast不変。
- 検証: `bash validation/rtps/run-task.sh T09`。各init failure、startup0、selected caller lockgraph、native mapping compile/run、zero/invalid snapshotが黙ってvalid locatorにならないこと。
- 非対象: startup全体の無関係なtransport lifecycle redesign。必要なら親へ戻す。

### T10 — full C++ acceptance gate

実行小task: **T10a**はactual-source fixture/runnerをWRITEしてlink・smoke、**T10b**はallocation/serialization/ABA/historyのassertionをWRITEしてrun、**T10c**はstartup/birth/capacity/locks/native mappingのassertionをWRITEしてrun。初回workerはfixture未作成と報告しただけなので、各委託の成果物を具体化する。既存fixtureにcaseがないことは作成taskのblockerではない。各小taskのpassedとT10全体PASSは別。

- 入力: T02–T09のexact diffとraw logs。
- 対象: 統合actual-source regression + 親live diff検査。production changesはgate中に行わない。
- Failure oracle: live locator fields、SPDP outgoing bytes/length、retained history bytes/SNs、cursor、appliedの明示的fingerprint。padding/lock内部/allocator bookkeepingをmemcmpして偽の保証にしない。
- 必須: EACH fallible serialization/allocation point、full population/capacity、no-allocation commit、SPDP latest-only/SEDP immutable historical SN、zero endpoints、birth/startup/expired lock order。ordinary checkpointed guest allocator/mutex/storageであることを確認。
- ABAを区別: applied=A → prepare B失敗 → current=Aなら、live stateが完全にAで残っているためequal no-opが正しい。partial Bが残らないことが条件。applied=0 → B失敗 → current=Aならmismatchをcommit。applied=A → B失敗 → 次のprobe UNCHANGED/current=BならretryしてBへcommit。
- 検証: `bash validation/rtps/run-task.sh all`、D03focused5cases再実行、configured linked test target、selected live lockgraph/diff。object compileだけは不可。
- 完了: 親が全mandatory case/logを実見してC++ seam READYと明記。未実行・inferenceはPASSにしない。これで初めてT11を開く。

### T11 — three normal builds

- 入力: T10 accepted diff、bootstrapのservice-template hashes、実optional-header recipe。
- 対象: `echoback_string`、`service_test_add_two_int`、`service_server_add_two_int`のclean normal builds、disabled-by-default trace overlay。
- 検証: SDK21 pthread toolchain/sysroot、root `-DCMAKE_APPNAME=<name>`、3つの`MODULE_<name>` executable targets。実configure/build commandとraw failure/warnings、source/config/app hashes、template before/after一致を保存。
- 完了: 3normal buildsが同じaccepted source diffに対応しdebugはdefault absent/disabled。service templateを書き換えてbuild成功にしない。

### T12 — serial application campaigns

- 対象: same-IP、`.3→.6`、ONE live restored appのsuccessive >=2 checkpoints、no-C/R。continuous native peer、同一ホスト限定。
- 検証: EVERY checkpointの前後に10 fully correlated roundtrips（sendだけでなくnative callback/echo/Wasm callbackのID/body一致）。全raw logs/runtime/app/peer hashes/manifestsを保存。
- 指標: EINTR guest pthread/fd、probe attempts/winners/BUSY/FAILED/same/changed/overlap/sequential duplicates、current/applied、prepare/commit/retry/final convergence。one probe per burstと誤記しない。
- 条件: fixed1GiB C/R前>=3GiB free、owned labelled containersだけ操作、failed payload保持。自分のnew PASS payloadのみhash/assertions後cleanup可。no socket recreation、no unrelated cleanup。
- 完了: 全caseの実通信とstate assertions。restarted proxy/cross-host/arbitrary DDSへ一般化しない。collector時刻を精密guest latencyと呼ばない。

### T13 — final independent review / adoption

- 入力: final live diffs、T10–T12のexact artifacts/logs。
- Fresh read-only reviewerはwriter contextなし。親は別にlive source/evidenceを確認し明示accept/reject。
- 契約のfinal repair-reviewはmax2回、その後はbounded parent takeover/stop。現状0回。先のC++追加実装2回と混同せず、実装継続とfinal repair-reviewの履歴を別に記録する。新しい`task.md`で既存失敗や制限を消さない。権限が曖昧なら親→operatorへ確認。
- 完了: independent findingsが処理され、最終差分を親が明示採用。gate false/未確認ならT14へ進まない。

### T14 — scoped publication / memory

- 採用後だけembeddedRTPS→lwIP→mros2 gitlink→root pins（unchanged repo省略）。実験/task board/service templates/unrelatedを混ぜない。
- EACH push直前にactual URLが`github.com:tauto1127/...`のみと確認。oss-fun/upstream/force/alias推測は禁止。remote SHAを記録。
- Wikiは既存authorized cloneのworking planだけ。AGENTS→focused memory skill→routing/glossary、remote/FF/scope/memory checks。policyは変更しない。
- 最終報告: operatorのordered20項目、actual commit/push destinations、measured/source/inference/TODOを分離。

## 4. 次回委託packet（起動前に親が記入）

```text
Task ID: <ONE ID>
Scope: <allowed files + forbidden files>
Inputs: <accepted dependency report + exact live diff hash>
Interface: <frozen contract/preconditions/ownership/error/lock order>
Deliverables: <diff + tests + raw logs + command + artifact hashes>
Acceptance: <named checks; whole-C++ completionと混同しない>
Owner: <one writer, explicit cwd/branch/model>
Budget/stop: <checkpoint時点; scope/infra/commitfallibilityなら親へ戻す>
Output: <tool側でdurable path bind。task proseだけではbindしない>
```

partial returnはtaskをPARTIALにし、次に残り全部を再依頼しない。親が具体的blockerを一つに絞る。差分保持、native protocol、同じ既知runのresume eligibility、実URL/commit gatesを省略しない。

## 5. この計画作成の結果

- [x] 設計正本と最終partial diffを突き合わせ、既存完了と未完了を分離。
- [x] task別scope/Input/成果物/完了条件/検証/非対象/依存/担当を記録。
- [x] C++に存在しないstandalone target、未作成test runner、ABA時の正しいno-op/retryを明示。
- [x] Operator実行承認後、親がT01をbuild/run。actual PBufWrapper/pbuf pool再利用、UCDR sticky error、production core/sys mutexを確認。source behavior変更なし。
- [x] 親takeover開始。T02以降は毎taskの機械的testを省き、実装済み/検証待ちを区別して進める。
