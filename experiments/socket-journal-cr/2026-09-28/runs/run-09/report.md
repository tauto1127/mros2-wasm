# 結論

**合格。** 同一ホストの Docker 上で、Wasm と native mROS 2 を同じ IP のまま保存・復元したあと、復元プロセスの確認から 13.8 秒で、復元後に Wasm が新しく送った別々の ID 10 件が両側の subscriber callback まで届いた。

合格に数えたのは、同じ ID・同じ本文が次の 4 行に出ている往復だけである。`recvfrom()` の成功や送信関数の戻りは数に入れていない。

| 段階 | 両側の受信処理まで揃った ID |
|---|---|
| 保存前 60 秒 | 10 件。ID `4, 5, 6, 7, 9, 10, 11, 12, 13, 14` |
| 続く 30 秒（チェックポイントなし） | 27 件。ID `16`–`23`, `25`–`39`, `41`–`44` |
| 復元後 90 秒 | 10 件。ID `46, 47, 48, 49, 50, 51, 52, 53, 55, 56`。保存直前の最大送信 ID は `N=45` で、この 10 件はすべて `N` より大きい |

実験ディレクトリは `experiments/socket-journal-cr/2026-09-28/runs/run-09/`。run-09 のコンテナ 3 つは停止・削除済みで、共有ネットワーク `mros2-cr-net` の ID は元のまま、接続コンテナは 0 である。

## 生ログ上の 1 往復

保存前の ID 4、本文 `Hello from mros2-posix onto Linux: 4`。

1. Wasm 送信: [wasm-checkpoint.log の 9159 行](raw/wasm-checkpoint.log)
2. native 受信: [peer-native.log の 4071 行](raw/peer-native.log)
3. native 返信処理の戻り: [peer-native.log の 4072 行](raw/peer-native.log)
4. Wasm 受信 callback: [wasm-checkpoint.log の 9169 行](raw/wasm-checkpoint.log)

復元後の ID 46、本文 `Hello from mros2-posix onto Linux: 46`。

1. Wasm 送信: [wasm-restore.log の 675 行](raw/wasm-restore.log)
2. native 受信: [peer-native.log の 4675 行](raw/peer-native.log)
3. native 返信処理の戻り: [peer-native.log の 4676 行](raw/peer-native.log)
4. Wasm 受信 callback: [wasm-restore.log の 695 行](raw/wasm-restore.log)

Wasm ログでは送信行が callback 行より前にある。native ログでは `peer_receive` の次の行が `peer_echo_publish_return` で、native 側の `epoch` は増えている。Wasm callback のホスト時刻は native 返信より約 0.9 秒後である。

ホストが標準出力を読んだ時刻では、Wasm 送信行が native 受信行より 0.03–4.5 ミリ秒遅い。この遅れは ID ごとに [ゲート記録](raw/postcr-gate.log) の `publish_minus_receive_ns` にある。4 つのホスト時刻だけを古い順に並べると、送信と受信の前後は決まらない。手順では、この差が 100 ミリ秒未満で、上の行順・`epoch`・callback が返信より後である場合だけ往復に数えると決めてから起動した。厳密に 4 つのホスト時刻が送信、受信、返信、callback の順だった ID は、3 つの区間とも 0 件である。

## 復元の記録

チェックポイント信号は 2026-09-28T04:57:07.781Z に、確認済みの `iwasm` PID 14 へ `SIGUSR2` を送った。その直前の最大送信 ID は `N=45`。checkpoint プロセスは exit 0 で終わった。Socket Journal は `main-socket.img` に 108 操作、`overflow=0`、`result=0` で、復元時は 108/108 が成功し、failure、fallback、skipped、unknown は 0、`function_return=0` だった。

復元直後、UDP 7411 を含む 4 つの local port `7400`, `7401`, `7410`, `7411` で `errno=27` が出て、その後の `UDP_RECV_RECOVERY` は 4 件とも `result=ok` だった。これは補助記録であり、上の 10 件の判定には使っていない。

90 秒の判定窓の中で、ゲートが 10 件に達して集計を閉じたあとに ID 57 の Wasm callback が残っている。ID 54 は native の受信と返信戻りまでで、Wasm callback の行はない。この 2 件は 10 件に含めていない。90 秒を過ぎてから数えた通信はない。ゲート終了後、復元プロセスは明示的な `SIGTERM` で止まり、collector の exit 143 はその停止である。

## 条件

実行ファイルの SHA-256 は run-04 の記録と一致した。`iwasm` は `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a`、Wasm アプリは `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76`、native アプリは `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`。再ビルドはしていない。ネットワークは既存の `mros2-cr-net`（`609362e37c7a...`）、Wasm `172.18.0.3`、native `172.18.0.5`。native ログの netif も `172.18.0.5` だった。

チェックポイント本体は `/tmp/mros2-wasm-cr-rerun-20260928-run09/state/` に残している。`main-memory.img` は 1073741824 バイト、SHA-256 `9d360afb440437cf8c1cef72fdba7db95c8cb1b107c803f9c445e67c53116280`。`main-socket.img` は 7780 バイト、SHA-256 `af808dd035febc705bce4f224b494a32da0df4ebacfc340d5ae20cef50dd3070`。ファイル一覧と照合値は [checkpoint-state-files.txt](raw/checkpoint-state-files.txt) と [checkpoint-state-files.sha256](raw/checkpoint-state-files.sha256)。

`ros2 topic list` は判定窓のあとで取り、`/to_linux` と `/to_stm` が見えた。トピック一覧と受動的な UDP 観測は合否に使っていない。既存の staged なパスは実行前後で変わっていない。commit と push はしていない。
