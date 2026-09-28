# run-02 metadata

実行値はraw logから確認して記録する。未確認の値は推測で補わない。

## 計画・レビュー

- 診断計画: [`../../plan-run-02.md`](../../plan-run-02.md)
- C/R手順: [`../../plan.md`](../../plan.md)
- Sol review: **APPROVE**（2026-09-27）
- Run ID: `run-02`
- Run tag: `[CR-RERUN-20260927-R02]`
- 判定: **C/R前ゲート不通過。C/R未実施。**

## 起動前に確認した条件

| 項目 | 実測値 |
|---|---|
| run-01比較元 | 同一Docker network、peer/WAMR IP、image、ROS endpoint、runtime/Wasm artifact |
| Docker network name / ID / options | `mros2-cr-net` / `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408` / bridge `172.18.0.0/16`, gateway `172.18.0.1`, `Internal=false` |
| 起動前network attachments | なし（`docker network inspect`で`Containers={}`） |
| ROS image ID | `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| instrumented iwasm SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| instrumented Wasm SHA-256 | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| run-02 raw directory | `experiments/socket-journal-cr/2026-09-27/runs/run-02/raw/`（起動前は空） |
| checkpoint state directory | `/tmp/mros2-wasm-cr-rerun-20260927/state-run-02`（起動前は未作成） |

## 実行結果

| 項目 | 値 / raw log |
|---|---|
| peer container ID / host PID / IP | `ee08beb68c908264e1811fdf03ac5ddecd094d4cfed666e4bdd71eef495980c5` / `1566681` / `172.18.0.5` |
| WAMR container ID / host PID / IP | `1587282e9b6a4cf7ad89139f2c9e3bf5f4defb934f4b29a4a513b4daf8b95819` / `1567892` / `172.18.0.3` |
| peer graph process / wire observer PID | container PID `1` / `40` |
| wire observer ready / stop | `2026-09-27T04:42:45.321Z` / `2026-09-27T04:46:08.932Z`。`capture_ready`と`capture_stop`を記録 |
| Wasm collector start | `2026-09-27T04:44:15.229Z` |
| `process_verified` | `2026-09-27T04:44:15.410Z`、container PID `21` |
| deadline / watchdog timeout | `04:45:15.410Z`（verifiedから60秒） / `04:45:15.594Z` |
| peer graph | 274 snapshotsすべてでpeer自身のendpointのみ。最後は`raw/ros-peer-run-02.log` |
| 異なる完全往復message ID数 | `0`。peer受信0、peer echo 0、Wasm callback 0 |
| Wasm `/to_linux` publish | `publish_begin` 59件、`publish_return` 59件、ID `0–58` |
| peer interfaceで見たWasm SPDP | `172.18.0.3 → 239.255.0.1:7400`を62 frames。writer ID `000100c2` |
| watchdog / collector終了 | watchdog fallbackは`04:45:17.879Z`。collector exit status `143`、WAMR container exit `137` |
| C/R実施 | **なし**。SIGUSR2未送信、restore未起動、journal image/dump/replayなし |
| cleanup / 最終状態 | run-02のpeer/WAMR containerを削除。`mros2-cr-net`は保持し、attachmentsなし。state-run-02は空 |

## 経路条件とraw記録

- peer/runner Docker IP prefixは`/16`、gatewayは`172.18.0.1`。両containerの`/proc/net/route`は`raw/*-pre-wasm-route.txt`。
- Wasm netifは`172.18.0.3`、mask `255.255.255.0`（`wasm-checkpoint.log`に`mask=0x00ffffff`）。run-01と同じ差異。
- 起動command、image inspect、container inspect、network inspect、wire capture、Wasm log、watchdog log/status、peer ROS logは`raw/`以下に保存。
