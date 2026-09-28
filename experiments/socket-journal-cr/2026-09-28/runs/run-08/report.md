---
sources:
  - "plan.md"
  - "metadata.md"
  - "raw/roundtrip-gate.status"
  - "raw/roundtrip-id-analysis.md"
  - "raw/wasm-checkpoint.log"
  - "raw/peer-native.log"
  - "raw/topic-list.log"
  - "raw/network-post-cleanup.json"
---
# 結論

復元後の通信を調べる追加試行として、同一ホストのDocker環境で、まず保存前の往復を確認した。成功には、60秒以内に10件以上のメッセージについて、Wasmの送信、nativeアプリの受信、同じ本文の返信、Wasmアプリの受信処理がこの順で記録される必要があった。この保存前ゲートは失敗し、Wasm側の受信処理は一度も記録されなかった。そのためチェックポイントと復元は行っておらず、復元後の通信は未測定である。

ここでの「受信処理」は、アプリがトピックメッセージを受け取ったときに呼ばれるsubscriber callbackを指す。プロセス状態の保存・復元は、Wasmプロセスをチェックポイントから再開する操作を指す。

## 判定

| 段階 | 結果 |
|---|---|
| 保存前60秒ゲート | **不合格。** 4段階すべてが揃った往復は0件。58件のWasm送信IDと58件のnative受信IDが記録された。うち56 IDで、Wasm送信・native受信・native返信処理の本文が一致した。Wasm受信callbackは0件。 |
| 続く30秒の無保存基準 | 最初のゲート失敗により実施せず。 |
| チェックポイント／Socket Journal記録 | 実施せず。 |
| 復元後90秒ゲート | 復元を行っていないため、復元後の一致IDは未測定。 |

56件の同一ID・同一本文はID `2–6`、`8–25`、`27–59`だった。各本文とIDは[監査記録](raw/roundtrip-id-analysis.md)に列挙した。たとえばID 2、本文 `Hello from mros2-posix onto Linux: 2` は[Wasm送信ログ](raw/wasm-checkpoint.log#L246)、[native受信ログ](raw/peer-native.log#L136)、[native返信処理ログ](raw/peer-native.log#L137)に現れる。対応するWasm受信callbackの行は記録されていない。

ゲート時間内で、ID 0と1はWasm送信ログだけが確認できた。ID 7と26はnative受信・返信処理の記録があるが、同じ時間窓にはWasm送信ログがない。これらは56件の一致IDに含めていない。

nativeアプリのログでは、同じcallback内で`peer_receive`の後にecho publish関数の復帰が記録される。一方、Wasmログに付けた時刻はホストのcollectorが標準出力を読み取った時刻であり、アプリ内イベントの発生時刻ではない。ID 2ではWasm送信行のcollector時刻がnative受信・返信行より約0.5ミリ秒遅いため、別々の標準出力ログの時刻だけでは送信からnative受信への厳密な順序を確認できない。Wasm callbackも存在しないため、成功条件を満たしたIDはない。

`/to_linux`と`/to_stm`は補助的なtopic一覧にも現れた。受動観測器もRTPS/UDPフレームのメタデータを記録したが、これらはアプリcallbackへの配送証拠ではない。60秒の判定窓を過ぎてから片付けまでに記録された通信は、ゲート判定に加えていない。

## 条件と範囲

run-08は既存の`mros2-cr-net`上で、同じホスト・同じIP（Wasm `.3`、native peer `.5`）を使った1回の試行である。3つの実行ファイルのSHA-256はrun-04の値と一致した。保存前ゲートが通らなかったため、この試行からチェックポイント復元後の通信については結論できない。callbackが記録されなかった原因も、この観測だけでは特定できない。

実測条件・ソース版・実行ファイル照合値・時刻・cleanupは[metadata](metadata.md)に、両側の生ログは[Wasmログ](raw/wasm-checkpoint.log)と[nativeログ](raw/peer-native.log)に保存した。判定結果は[保存前ゲートstatus](raw/roundtrip-gate.status)にある。
