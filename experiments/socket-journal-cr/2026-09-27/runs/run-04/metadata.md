# run-04 metadata

## 判定

**C/R後のアプリ往復を確認。** 2026-09-27、native POSIX mROS 2 peerとWasm mROS 2 nodeを同一hostの隔離Docker bridgeにつなぎ、C/R前の受信ゲート・無C/R基準・C/R後ゲートを順に通過した。

## 条件とartifact

| 項目 | 実測値 |
|---|---|
| root repository | branch `debug/recvfrom-observability`, HEAD `0842ac9782cf51c5806619c2c3af9e1467435727` |
| Wasm側mROS 2 / lwip-wasm | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` / `5acfdb028b8d1b8ddf158671eeb7e539901ac11a` |
| WAMR | `2dd4eae0f301dd100e651c037ce6a3a8f56cce5e` |
| native POSIX mROS 2 tree | POSIX source `d267988c279411a685d63956e42e05d9bfc32b56`、mROS 2 `24a4a233672ff823429d11dfc30112c3f298c374`、lwip-posix `f1d576bde977f20a452654ab283fa11c03a2ffc1`。dirtyな元worktreeには書き込まず、コピー上でbuildした。 |
| Docker network | `mros2-cr-net`, ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`, bridge `172.18.0.0/16`, gateway `172.18.0.1` |
| container内の実IP | Wasm runner `172.18.0.3`、native mROS 2 peer `172.18.0.5`。双方のlwIP netif maskは`255.255.255.0`、Docker inspect上のprefixは`/16`。 |
| user endpoints | Wasm: publisher `/to_linux`・subscriber `/to_stm`; native peer: subscriber `/to_linux`・publisher `/to_stm` |
| message / domain | `std_msgs/msg/String`、Domain 0。1秒ごとの連番本文をpeerが同じIDでecho。 |
| 実行image | 両containerとも`ros:humble`, image ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138`。imageはOS/runtime環境として使用。peer process自体はrclpy/RMWではなくnative mROS 2 executable。 |
| iwasm SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| Wasm SHA-256 | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| native peer SHA-256 | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |
| native peer source SHA-256 | `8f9c0a072de9f9bf5516657c76c0229313e344ad5f6458198fa080ec0915fea4` |

hash一覧は[`raw/artifact-hashes-run04-final.txt`](raw/artifact-hashes-run04-final.txt)、revisionごとの記録は[`raw/`](raw/)を参照。

## containerとprocess

| 役割 | container | container ID | host PID / process |
|---|---|---|---|
| native peer | `mros2-cr-run04-native-peer` | `2da29ba280767e4a54063394b9806b39f56f729034c34d2f1b49b309b6dec5c7` | container内peer PID 14 |
| Wasm runner | `mros2-cr-run04-wamr` | `d3f67b71eeefe3a1188286e3a979cfe55a740d9f2fe249a48feca6a36cde45d7` | checkpoint iwasm PID 14、restore iwasm PID 58 |
| passive wire tap | `mros2-cr-run04-wiretap` | `e6dee2e74b8c81fb8681b7eeb155e9a8c03c46060e0300e28a1fe3c30da8bcd4` | peerと同じnetwork namespace、`CAP_NET_RAW`のみ追加 |

## 時刻とゲート

時刻はUTC。

| 区間 | 時刻・結果 |
|---|---|
| iwasm process verified | `07:42:24.718`, checkpoint PID 14 |
| C/R前受信ゲート | `07:42:36.114` pass。完全往復ID `1–10`、10 distinct IDs。 |
| 無C/R基準 | `07:42:52.453–07:43:22.548`, 30.095秒、pass。ID `28–44`, `46–56`の28件。 |
| checkpoint signal | `07:43:59.164`, PID 14へSIGUSR2、signal時点の最大publish ID `N=93`。 |
| checkpoint | `07:44:00.215`にcollector終了、host exit 0。`main-socket.img` 14,836 bytes、SHA-256 `b0a5c5a4104fc83304b167523aee1c8e5421b134f13f1b55f616d056b3eb0721`。 |
| journal dump | 206 operations、`overflow=0`, `result=0`。 |
| restore start / verified | `07:45:14.154` / `07:45:16.182`, 同じrunner container・IP `.3`・同じruntime/Wasm hash。 |
| journal replay | 206/206 success、failure/fallback/skipped/unknown各0、function return 0。 |
| post-C/R受信ゲート | `07:45:27.167` pass。`N=93`より大きい完全往復ID `95–104`の10件。 |
| restore終了 | post-C/Rゲートpass後にrestore iwasmへSIGTERM。collector exit 143はこの明示停止による。 |

gate statusは[`raw/roundtrip-gate.status`](raw/roundtrip-gate.status)、[`raw/no-cr-baseline.status`](raw/no-cr-baseline.status)、[`raw/postcr-gate.status`](raw/postcr-gate.status)。signal記録は[`raw/checkpoint-signal.log`](raw/checkpoint-signal.log)。

## Restore後の受信

Restore直後、UDP local port `7400`, `7401`, `7410`, `7411`の`recvfrom()`で`errno=27`が記録され、その後の`UDP_RECV_RECOVERY`は4件とも`result=ok`。Wasm `/to_stm` callbackはID 94から再開し、post-C/Rゲートはrestore logでpublish beginも確認できるID 95–104を用いてpassした。ID 94はC/R境界をまたいだin-flight callbackとして観測されたため、10件の判定には含めていない。

`raw/wasm-checkpoint.log`末尾の`SOCKET_JOURNAL event=dump_end`と、`raw/wasm-restore.log`の`event=restore_begin` / `event=restore_end`を参照。checkpoint state本体のmanifestは[`raw/checkpoint-state-files.sha256`](raw/checkpoint-state-files.sha256)。

## 保存・cleanup

- raw logs、計画、source、scripts、reportはこのrepositoryの`run-04/`に保存。
- `/tmp/mros2-wasm-cr-run04/state-run-04/`はrestore後も再確認できるよう残置。実使用量は約1.1 GiB。image本体はGit管理しない。
- run-04で作成した3 containerは停止・削除済み。既存の`mros2-cr-net`は削除・変更せず、cleanup後のnetwork attachmentは0。
- この実験用のcommit/pushは行っていない。既存のindex変更はそのまま保持。
