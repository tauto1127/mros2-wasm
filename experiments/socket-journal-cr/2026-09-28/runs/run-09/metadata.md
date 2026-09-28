# run-09 metadata

時刻は UTC。ホストの実験結果は [report.md](report.md)。

## 判定

保存前 60 秒で 10 件、続く 30 秒で 27 件、復元後 13.8 秒で ID が `N=45` より大きい 10 件の完全往復が記録された。3 区間とも `result=pass`。

## 固定した条件

| 項目 | 実測 |
|---|---|
| 実験 ID | `run-09` |
| root | `debug/recvfrom-observability`、HEAD `0842ac9782cf51c5806619c2c3af9e1467435727`。この commit は実行ファイルの証明には使っていない |
| network | `mros2-cr-net`、ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`。開始前と削除後の接続コンテナは 0 |
| image | `ros:humble`、`sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| Wasm | `mros2-cr-run09-wamr`、`172.18.0.3`、container `e23a6e3c84d8ec75b582b732ea2b22e292b11c610e59434278b89bdf8e1cdd1e`。checkpoint PID 14、restore PID 52 |
| native peer | `mros2-cr-run09-native-peer`、`172.18.0.5`、container `59d32cd18a3c4acd869d4c9067ca1ff243287f01e6b2bfa385c192fb7467b9e7`。アプリログの netif も `172.18.0.5` |
| wiretap | `mros2-cr-run09-wiretap`、peer と同じ network namespace、`CAP_NET_RAW`、container `8ae4a2cc9bea3f098ca339287e80141e2d9a8c1814c2e95ecb37c32dd4a7d43f` |
| 実行ファイル | [artifact-hashes-preflight.txt](raw/artifact-hashes-preflight.txt)。run-04 の 3 つの SHA-256 と一致 |
| state | `/tmp/mros2-wasm-cr-rerun-20260928-run09/state/` |

run-04 が記録しているソース版と、native ビルド時の未コミット差分をこの作業ツリーから完全には再現できないことは [build-provenance-limit.md](raw/build-provenance-limit.md) に残した。

## 時刻

| 段階 | UTC |
|---|---|
| preflight 通過 | 2026-09-28T04:56:20.546Z |
| native peer ready | 2026-09-28T04:56:21.685Z |
| checkpoint `iwasm` 確認 | 2026-09-28T04:56:22.099Z、PID 14 |
| 保存前ゲート pass | 2026-09-28T04:56:37.452Z。確認から 15.353 秒 |
| 30 秒区間 | 2026-09-28T04:56:37.504Z から 2026-09-28T04:57:07.590Z。30.000 秒 |
| `SIGUSR2` | 2026-09-28T04:57:07.781Z。`N=45` |
| checkpoint exit | 2026-09-28T04:57:08.816Z、exit 0 |
| restore `iwasm` 確認 | 2026-09-28T04:57:09.187Z、PID 52 |
| journal `restore_end` | 2026-09-28T04:57:10.901Z。108/108 |
| 復元後ゲート pass | 2026-09-28T04:57:22.980Z。確認から 13.793 秒 |
| コンテナ削除完了 | 2026-09-28T04:57:31.047Z |

## 片付け

`mros2-cr-run09-wamr`、`mros2-cr-run09-native-peer`、`mros2-cr-run09-wiretap` を停止して削除した。restore と native peer の exit 143 は、その `SIGTERM` による。wiretap は exit 0。削除後の `docker ps -a` にこの 3 つの名前はなく、network ID は同じで `Containers` は空だった。staged なパスの一覧は [staged-compare.txt](raw/staged-compare.txt) で unchanged。commit も push もしていない。
