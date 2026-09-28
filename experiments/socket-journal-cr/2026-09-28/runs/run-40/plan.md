---
created: 2026-09-28
last_updated: 2026-09-28
last_verified: 2026-09-28
sources:
  - "/home/osslab/mros2-wasm-service-communication-socket-journal/experiments/socket-journal-cr/2026-09-28/runs/run-08/report.md and raw logs"
  - "/home/osslab/mros2-wasm-service-communication-socket-journal/experiments/socket-journal-cr/2026-09-28/runs/run-09/report.md and raw logs"
  - "/home/osslab/mros2-wasm-service-communication-socket-journal/mros2/embeddedRTPS/src/discovery/SEDPAgent.cpp"
  - "/home/osslab/mros2-wasm-service-communication-socket-journal/mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp"
  - "/home/osslab/mros2-wasm-service-communication-socket-journal/mros2/embeddedRTPS/include/rtps/entities/StatefulWriter.tpp"
  - "Heptabase survey 39364618-c215-4dba-9489-dab88034dcb2"
---
# mROS 2-Wasm SEDP競合 診断計画

## 現在地

この文書は**計画のみ**を扱う。現時点では、この計画に基づく研究コードの変更、ビルド成果物の作成、コンテナ操作、実験実行は行っていない。

run-08 と run-09 は、同じローカルDocker上のアドレスと比較可能な実行物を使っていたが、チェックポイント前の時点で結果が分かれた。run-08 は60秒のC/R前往復ゲートに失敗したためチェックポイントを実施していない。一方 run-09 はC/R前ゲートに合格し、その後、同一IPでの復元後ゲートでも新しい10件の完全往復に成功した。

run-08 のパケット観測では、Wasmからpeerへのuser DATAは存在したが、peerからWasmへのuser DATAは確認できなかった。また、期待するmetatraffic経路上で、WasmからpeerへのSEDP DATA / HEARTBEATも確認できなかった。したがって現在の仮説は、**C/Rそのものの不具合ではなく、起動時discoveryの未検証なrace condition**である。

次の調査では、挙動への影響をできるだけ小さくしたログを追加し、SEDP/SPDPのwriter処理順序を観測する。まずC/Rを行わない起動時だけの試験で成功パターンと失敗パターンを再現・分類し、その後に初めて同一IP C/Rを再実行する価値があるか判断する。

**Lunaへの実行引き継ぎ:** 実装と実験実行はLunaが担当する。この文書を実行時の契約とする。今回の計画作成セッションでは研究コードを変更せず、実験も行わない。Lunaが追加してよいのは、以下に定義した診断用ログとローカルDocker上の診断実験だけである。原因修正は、診断結果を確認した後の別フェーズとする。

## 調べたいこと

remote SEDP builtin reader proxy が登録される前に、local SEDP endpoint広告が `StatefulWriterT::progress()` によって論理的に送信済みとして消費されてしまい、その結果peerがWasm側endpointを認識できず、peerからWasmへのuser DATAが送られなくなっているのかを確認する。

## 仮説

失敗する起動では、次の順序になっていると仮定する。

1. `SEDPAgent::addReader()` / `addWriter()` がSEDPのhistory changeを作る。
2. SEDP writerにmatched remote reader proxyがまだ無い状態でwriter workerが動く。
3. `StatefulWriterT::progress()` は何も送らないが、`m_nextSequenceNumberToSend` だけを進める。
4. その後SPDPがpeerを発見し、`addNewMatchedReader()` がbuiltin reader proxyを登録する。
5. 先ほどのSEDP history changeはunsent状態へ戻されず、再スケジュールもされないため、peerは該当するWasm endpointを知ることができない。

成功する起動では、SEDP changeをprogressする前にproxyが登録されるか、あるいはproxy登録後に実際の再送経路が働いてchangeが送信されるはずである。

## 固定する条件と調査範囲

- run-08 / run-09 と同じホスト、既存の `mros2-cr-net` Docker networkを使う。
- Wasmは `172.18.0.3`、native peerは `172.18.0.5` のままにする。
- 記録済みmetadataから別条件が必要だと判明しない限り、アプリ挙動、QoS、起動順、ゲート判定、受動wire observerを変更しない。
- 物理LANと重なる `192.168.100.0/24` のDocker subnetは使わない。
- 別の物理ホストは使わない。
- 診断中はrecovery挙動、sequence number処理、discovery処理を変更しない。修正コードを混ぜない。
- `publish()` がreturnしたこと、`recvfrom()` が成功したこと、topic listに名前が出たこと、SPDP packetが存在したことだけをtopic通信成功の証拠にしない。

## 追加するログ

すべての診断ログには `[SEDP-RACE]` のような共通prefixを付け、monotonic timestampまたは単調増加するtrace sequenceを含める。後から機械的に並べ替えられるよう、1 event = 1行にする。

### 1. SEDP change作成

`SEDPAgent::addReader()` と `SEDPAgent::addWriter()` で、`newChange()` が返す `CacheChange` を取得し、次を記録する。

- event: `change_created`
- publications writer / subscriptions writer のどちらか
- local endpoint entity ID
- user endpointであればtopic名
- 割り当てられたRTPS sequence number
- 容易に取得できるならSEDP writer historyのmin/max

送信判断そのものは変更しない。

### 2. SEDP writerのprogress

`StatefulWriterT::progress()` で、2つのbuiltin SEDP writerだけを対象に、entry / exitで次を記録する。

- event: `progress_enter` / `progress_exit`
- writer entity ID
- `m_proxies.isEmpty()`（count用APIを増やすよりこちらを優先）
- `m_nextSequenceNumberToSend` の実行前後
- history min/max
- proxy loop内で実際にsendを試みたか

最重要の観測点は、`m_proxies.isEmpty() == true` の状態で `m_nextSequenceNumberToSend` が進むかどうかである。

### 3. remote builtin reader proxyの登録

`StatefulWriterT::addNewMatchedReader()` で、SEDP writerだけを対象に次を記録する。

- event: `proxy_added`
- writer entity ID
- remote reader GUID / entity ID
- `m_nextSequenceNumberToSend`
- history min/max
- addの成否

### 4. proxy登録につながるSPDP側の判断

`SPDPAgent::addProxiesForBuiltInEndpoints()` で、発見したparticipantごとに1回、次を記録する。

- event: `builtin_proxy_plan`
- participant GUID prefix
- 選択されたmetatraffic locator
- `hasPublicationReader()` / `hasSubscriptionReader()` と対応するwriter flag

### 5. 既存の受動観測

既存のpeer側wire captureはそのまま残す。各trialについて、最低でも次の件数を個別に集計する。

- Wasm -> peer のSEDP DATA（metatraffic unicast）
- Wasm -> peer のSEDP HEARTBEAT
- peer -> Wasm のSEDP traffic
- Wasm -> peer のuser DATA
- peer -> Wasm のuser DATA
- official gate内で成立した完全なapplication round trip

## 観測によるraceへの影響を抑える

`printf()` 自体がthread schedulingを変え、raceを隠す可能性がある。そのため、最初は必要最小限のtraceだけを入れる。

元のbuildでは成功・失敗が混在していたのに、instrumented buildではcold startを繰り返しても一方しか出なくなった場合、「raceが消えた」と結論づけず、まず観測コードによる摂動を疑う。

摂動が疑われる場合は、hot path上の直接出力をやめ、固定長・事前確保済みのin-memory trace bufferへcompactなnumeric eventを記録し、ゲート終了後にまとめてflushする。最初のinstrumentationで再現性が保たれている限り、ここまで侵襲的な変更は行わない。

## 実験手順

### Phase A: 起動時だけの分類

このPhaseではチェックポイントを行わない。

1. instrumented artifactは新しい独立output directoryへbuildし、run-08 / run-09のreference binaryを置き換えない。
2. root/submodule revision、source diff、build command、runtime / Wasm app / native peerのSHA-256を記録する。
3. 同じ起動手順で独立したcold-start trialを繰り返す。
4. 既存の60秒pre-C/R gateを変更せず使う。
5. gate判定が出たらそのtrialを終了し、そのtrial専用のcontainer/processだけcleanupする。
6. 成功クラスと失敗クラスをそれぞれ2回ずつ取得するまで続ける。ただし、両クラスが揃わないまま10 trialに達したら終了する。

この繰り返し条件はintermittentな挙動を診断するためのものであり、failure probabilityを統計的に推定するためのものではない。

### Phase B: 同一IP C/Rの確認

Phase Aでrace仮説が支持・反証されたか、またはinstrumentation下では間欠的起動失敗を再現できないと分かった後にだけ実施する。

- 変更していないpre-C/R gateに合格したtrialから開始する。
- 同じinstrumentationを保ったままcheckpointと同一IP restoreを行う。
- 既存のpost-restore 90秒gateを使い、復元後の新しいID 10件が4段階の完全往復を満たすことを要求する。
- このPhaseはrestoreをまたいでdiscovery state/orderが変わるかを確認するために使う。baseline gateですでに失敗したtrialをC/Rで救済する目的では使わない。

## 判定基準

### race仮説を強く支持する結果

失敗した起動で次の順序が観測される。

`change_created` -> `progress_enter(proxy_empty=true, nextSN=N)` -> `progress_exit(nextSN>N)` -> 後から `proxy_added`

さらに、そのendpoint広告に対応するWasm -> peer のSEDP DATAが出ていない。

一方、成功した起動ではproxy登録がprogressより先に起きるか、proxy登録後にreplay / resendされ、実際にSEDP DATAが送信される。

### race仮説が弱まる、または反証される結果

- 失敗起動でも必要なproxyがprogress前から存在し、該当するSEDP DATAも送信されている場合: peer側のSEDP receive / parse / matchを次に調べる。
- proxyは存在するがSEDP DATAが送信されない場合: SPDP順序ではなくwriter history / send selectionを調べる。
- peerがWasm Readerを受信・matchできているのにpeer -> Wasm user DATAが出ない場合: peer user writerのmatched-reader状態とUDP send判断をinstrumentする。
- peer -> Wasm user DATAがwire上に存在するのにWasm callbackが無い場合: 調査境界をWasm `recvfrom` -> RTPS parse/reader -> application callbackへ移す。

## 各diagnostic runで残す成果物

run-08 / run-09の既存証拠は変更せず、新しい日付付きrun directoryへ次を保存する。

- `plan.md`
- `metadata.md`
- source diff / revision manifest
- artifact hashes
- structured `[SEDP-RACE]` trace
- Wasm / native logs
- passive `peer-wire.jsonl`
- gate status と ID/body correlation analysis
- cleanup state
- `report.md`（結果、証拠の境界、仮説が supported / weakened / refuted / unresolved のどれかを明記）

成功・失敗を1組だけ観測したとしても、処理順の証拠が曖昧なら仮説を「確認済み」としない。

## Lunaが次に行うことと実装範囲

今回の計画作成セッションでは実験を行わない。実行担当はLunaとする。

Lunaは実装前に研究worktreeを必ず再読すること。現在のworktreeは意図的にdirtyであり、多数のstaged / untrackedな実験artifactが存在している。

Lunaがこの計画で変更してよい範囲は、ここで定義したtrace instrumentationとローカルDocker実験だけである。同じrunでbehavior fixを入れない。recovery algorithmを変更しない。cross-host migrationも試さない。

診断結果から有力な修正案が得られた場合は、その場で修正せず、reportを作成して停止する。修正実験は別の計画としてレビューする。

## Memory lifecycle

**Choice: Keep.** SEDP ordering仮説について明確なevidence classificationが得られ、次に調べる境界が決まった時点で、このノートをcloseまたはbroader noteへconsolidateする。それまでは本ノートをこの診断の実行引き継ぎ正本とし、`mros2-wasm-network-migration.md` は研究全体の広いコンテキストとして残す。
