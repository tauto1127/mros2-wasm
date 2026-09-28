# run-03 metadata

## 計画・レビュー

- 計画: [`../../plan-run-03.md`](../../plan-run-03.md)
- C/R手順: [`../../plan.md`](../../plan.md)
- Sol re-review: **APPROVE**（2026-09-27）
- Run ID / tag: `run-03` / `[CR-RERUN-20260927-R03]`
- 判定: **60秒のC/R前ゲート不通過。C/R未実施。**
- 研究内の前回C/R: [2026-09-24探索的run](../../../2026-09-24/runs/exploratory-cr-01/report.md)ではcheckpoint/restore後の`EINTR`とsocket recoveryを観測した。ただしpeer graphとapp-level roundtripは成立していない。

## 前提条件

| 項目 | 実測値 |
|---|---|
| root revision | `0842ac9782cf51c5806619c2c3af9e1467435727`（run-02と同じ） |
| mROS 2 / lwip-wasm / WAMR | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` / `5acfdb028b8d1b8ddf158671eeb7e539901ac11a` / `2dd4eae0f301dd100e651c037ce6a3a8f56cce5e`（run-02と同じ） |
| Docker network | `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, `bridge`, `172.18.0.0/16`, gateway `.1`, `Internal=false` |
| network attachments | 起動前0、実験中はrun-03のpeerとWAMRだけ、cleanup後0 |
| ROS image | `ros:humble`, ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| iwasm SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| Wasm SHA-256 | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| checkpoint state | `/tmp/mros2-wasm-cr-rerun-20260927/state-run-03`。新規作成。実験後も空 |
| peer endpoint / QoS | `/to_linux` subscriber・`/to_stm` publisher、`std_msgs/msg/String`、BEST_EFFORT / VOLATILE |

起動前のnetwork、attachment、container名、image、artifact hash、revisionは[`raw/`](raw/)以下に保存した。run-02と同じ固定条件だった。

## 実行記録

| 項目 | 実測値 |
|---|---|
| peer container | ID `f13688184697e0a38d775d6696241012726b7869069171a3c77645c3f32bc10e`, host PID `1590753`, IP `.5`, container PID 1 |
| WAMR container | ID `9fbc7d33aacd3107781a96c059d6add94af4edd9604f44e3038cbcf923abc9ba`, host PID `1592906`, IP `.3` |
| wire tap / proc probe | peer内PID `51` / `57`。両方readyを記録し、終了時に`capture_stop` / `probe_stop`を記録 |
| proc probe | 合計332 snapshots、ゲート中60 snapshots。gate中の表読取・FD列挙不完全は0 |
| `process_verified` | `2026-09-27T05:18:45.779Z`、iwasm container PID `32` |
| ゲートdeadline | `2026-09-27T05:19:45.779Z`（process_verifiedから60秒） |
| peer graph | gate中60 snapshotsすべてでremote Wasm endpointなし |
| app往復 | peer receive 0、peer echo 0、Wasm callback 0。完全往復0件 |
| Wasm app publish log | `publish_begin` / `publish_return` markerは各60件。ログのinterleaveと終了時切断により、idを完全に読めるreturnは0–58の59件。callbackなし |
| Wasm SPDP wire capture | `.3 → 239.255.0.1:7400`のSPDP builtin participant writer `000100c2`を62 frames確認 |
| peer IGMP | ゲート末尾snapshotで`eth0`上に`239.255.0.1`、users=1 |
| peer PID 1 IPv4 UDP FD | ゲート末尾snapshotで`0.0.0.0:7400`→FD 9、`:7410`→FD 10、`:7411`→FD 12。FD所有関係はknown |
| watchdog / collector | watchdog `gate_timeout_after_term_runner_stop`、runner stop return code 0。collector exit status 143 |
| C/R | **未実施**。gate markerなし、SIGUSR2なし、restoreなし、journal imageなし |
| cleanup | run-03 containerは最終container listに存在せず、network attachments 0。state directoryは空 |

`ros:humble` image内に`ip`コマンドがなく、`ip address` / `ip route`はexit 127だった。peer/WAMRのDocker inspectと`/proc/net/route`・`/proc/net/dev`を保存した。Wasm logのlwIP netifは`.3`、mask `/24`。Docker bridgeは`/16`であり、この差はrun-02と同じ。

## 生ログと解釈

- `peer-socket-state.jsonl`には各snapshotの`/proc/net/igmp`、`/proc/net/udp`、未解析の`/proc/net/udp6`原文を保存した。
- UDP4表とPID 1 FD列挙は対応づけて記録した。UDP6原文からIPv6 socketの有無は推定していない。
- `peer-wire.jsonl`はpeer `eth0`での受動観測。interfaceにframeが届いた事実は示すが、特定UDP socketが受け取ったことやFast DDSが処理したことは単独では示さない。
- 計測期間中のWasm logにはpeer participant prefixとbuiltin participant reader/writer IDのRTPS DATA parse記録もある。peer側graphではremote Wasm endpointが現れなかったため、発見は対称でなかった。
- cleanup時にpeer processは`ExternalShutdownException`を出してexit 1となった。gate中の通信判定とは分けて記録する。

raw artifact一覧と結論は[`report.md`](report.md)を参照。
