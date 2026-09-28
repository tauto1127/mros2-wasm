# run-06 metadata

## 実行概要

| 項目 | 値 |
|---|---|
| 実施日 | 2026-09-27 |
| 実験範囲 | 同一物理ホスト上のDocker container間、別IPへのWasm mROS 2移行 |
| Docker network | 既存`mros2-cr-net`、ID `609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`、subnet `172.18.0.0/16` |
| 移行元 | `mros2-cr-run06-source`、`172.18.0.3` |
| native peer | `mros2-cr-run06-native-peer`、`172.18.0.5` |
| 移行先 | `mros2-cr-run06-destination`、`172.18.0.6` |
| Wire observer | `mros2-cr-run06-wiretap`、peerと同じnetwork namespace。受動観測のみ |
| Container image | `ros:humble`, image ID `sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138` |
| `iwasm` SHA-256 | `96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a` |
| Wasm SHA-256 | `0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76` |
| native peer SHA-256 | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |
| C/R state | `/tmp/mros2-wasm-cr-run06/state`（Git管理外） |

Docker networkとimageの事前状態は`raw/preflight.json`、artifact hashは`raw/setup.log`およびartifactを用意したrun-04の記録と照合した。各containerの実IPは`raw/*-container-inspect.json`に記録。

## 時系列（UTC）

| 時刻 | イベント | 証拠 |
|---|---|---|
| 11:16:20 | native peer ready | `raw/peer-native.log` |
| 11:16:48 | 移行元Wasm開始 | `raw/wasm-checkpoint.log` |
| 11:18:10.733–.806 | PID 38へcheckpoint signal | `raw/checkpoint-signal.log` |
| 11:18:11.785 | checkpoint終了、exit 0 | `raw/wasm-checkpoint.status` |
| 11:19:22 | 移行先container作成 | `raw/destination-container-inspect.json` |
| 11:19:55.773 | restore process開始 | `raw/wasm-restore.log` |
| 11:19:55.960 | restore processを確認、90秒ゲート開始 | `raw/analysis-summary.json` |
| 11:21:26.063 | post-C/Rゲートtimeout、不成立 | `raw/postcr-gate.status` |
| 11:23:51.930 | passive boundary inspection後、restore collector停止 | `raw/wasm-restore-stop.log` |
| 11:25:18前後 | run-06 containerを停止・削除 | `raw/cleanup.log` |

UTCからJSTへの換算は+9時間。90秒の公式ゲート終了後も、設定変更や再試行をせず、観測中のプロセスを145.867秒間継続させて境界を追加確認した。この追加観測はゲート判定に含めない。

## ゲートとC/Rの数値

| 段階 | 結果 |
|---|---|
| C/R前 complete round trip | 18 ID（5–22）でpass |
| 無C/R baseline | 30.0875秒で27 ID（33–42、44–58、60–61） |
| Checkpoint時の最大publish ID `N` | 81 |
| Socket Journal dump | 182 operations、overflow 0、result 0 |
| Restore replay | 182/182 successful、failure 0、fallback 2、skipped 0、unknown 0、function return 0 |
| UDP receive recovery | port 7400、7401、7410、7411で`result=ok` |
| 90秒 post-C/R完全往復 | 0 ID、timeout。不成立 |
| restore log中のWasm callback | ID 82のみ。`N=81`より後の完全往復には含めない |

移行先では`netif_wasm`がlocal IPを`0x060012ac`へ更新した。Docker inspect上の移行先IPは`172.18.0.6`であり、同じIPを示す。restore後、Wasm publish IDは83–169の87個、peer receive/echo IDは83–170の88個だった。これらを同じID集合として扱わず、完全往復の共通集合は0件と判定した。

## Gate window中のwire観測

| 送信元 | 宛先 | RTPS DATA frame数 |
|---|---|---:|
| Wasm `.6` | native peer `.5:7411` | 88 |
| Wasm `.6` | `239.255.0.1:7400` | 89 |
| native peer `.5` | `239.255.0.1:7400` | 91 |
| Wasm `.6` | native peer `.5:7410` | 2 |
| native peer `.5` | 旧IP `.3:7411` | 0 |
| native peer `.5` | 新IP `.6:7411` | 0 |

wire tapはpacket内のapplication IDを復号しない。peer callbackのIDは`raw/peer-native.log`を根拠とする。また、peerの`publish()`呼び出しが戻ったことだけではUDP送信の成功とはみなさず、wireでpeer発のunicast DATAは確認できなかったと記録する。

## 記録上の注意・cleanup

- `raw/source-route-preflight.txt`にはcontainer内に`ip` commandがなく失敗した初回採取が残る。以後は`/proc/net/route`等を使う代替採取を行い、成功した結果を`raw/*-proc-route-preflight.txt`に保存した。
- Gate終了時のstop helperは一時的に`[iwasm] <defunct>`を実行中プロセスとして扱い、停止確認を保留した。その後のprocess一覧では実行中のiwasmがないことを確認した。元の判定ログは改変せず`raw/wasm-restore-stop.log`と`raw/destination-processes-post-stop.txt`に残す。
- CleanupではDockerの`--time` deprecated warningが出たが、各run-06 containerのstop/removeは成功した。container名と後状態は`raw/cleanup.log`、`raw/containers-post-cleanup.txt`にある。
- 既存networkは削除・再設定していない。cleanup後も残り、run-06 containerは接続されていない（`raw/network-post-cleanup.json`）。他の既存containerには触れていない。
- Checkpoint state本体は`/tmp`に残し、Gitには追加していない。
