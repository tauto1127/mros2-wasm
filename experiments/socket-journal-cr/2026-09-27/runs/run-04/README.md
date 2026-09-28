# run-04: native mROS 2 peerへのアプリデータ配送と同一IP C/R

**結果: 成功。** Wasm上のmROS 2 nodeからnative mROS 2 peerへの受信とechoを確認し、その後、同一container・同一IPでsocket-journal checkpoint/restoreを行って、ID 95–104の10件の完全往復を確認した。

詳細は[`report.md`](report.md)、実測条件と時刻は[`metadata.md`](metadata.md)を参照。

## このrunで使ったもの

- [`native_peer.cpp`](native_peer.cpp): POSIX版native mROS 2 peer。`/to_linux`で受信したIDを記録し、同じ本文を`/to_stm`へpublishする。
- [`native-peer-ip.patch`](native-peer-ip.patch)と[`build_native_peer.py`](build_native_peer.py): dirtyな元worktreeを変更せず、`/tmp`の隔離コピーでpeerをビルドする。
- [`run_wasm_phase.py`](run_wasm_phase.py): 同じWAMR container上で初回起動／restoreを行い、stdout/stderrにUTC・monotonic時刻を付けて保存する。
- [`send_checkpoint_signal.py`](send_checkpoint_signal.py): 受信ゲートと無C/R基準の両方がpassし、checkpoint processのPID/argvが一致した場合だけSIGUSR2を送る。
- [`roundtrip_gate.py`](roundtrip_gate.py)、[`no_cr_baseline.py`](no_cr_baseline.py)、[`postcr_gate.py`](postcr_gate.py): IDを突き合わせ、開始・基準・復元後の各ゲートを判定する。
- [`rtps_wire_tap.py`](rtps_wire_tap.py): peerのnetwork namespaceでRTPS/UDP frameを受動観測する。packet injectionやpromiscuous modeは使わない。

## 主要ログ

- `raw/roundtrip-gate.status`: checkpoint前の10件の完全往復。
- `raw/no-cr-baseline.status`: 30秒の無C/R区間。
- `raw/checkpoint-signal.log`, `raw/wasm-checkpoint.log`, `raw/wasm-checkpoint.status`: signal時の最大ID、checkpoint、journal dump。
- `raw/wasm-restore.log`, `raw/wasm-restore.status`, `raw/postcr-gate.status`: journal replay、restore後のsocket recovery、10件の完全往復。
- `raw/peer-native.log`: native mROS 2 callbackが実際に受け取った本文とID、およびecho publish。
- `raw/peer-wire.jsonl`: peer interfaceで観測したRTPS DATAとUDP locator/port。
- `raw/*inspect*`, `raw/network-*.json`, `raw/containers-*.txt`: container・networkの前後状態。
- `raw/artifact-hashes-run04-final.txt`, `raw/checkpoint-state-files.sha256`: 実行artifactと一時checkpoint stateのhash。

ログは`raw/`に保存し、Git管理下に置く。1 GiB超のcheckpoint state本体は`/tmp/mros2-wasm-cr-run04/state-run-04/`に残し、Gitには入れない。

## ビルドログの読み分け

`raw/build-final.log`と`raw/artifact-hashes-run04-final.txt`が実行したnative peerの正本。`raw/build.log`、`raw/build-isolated.log`、`raw/artifact-hashes-preflight.txt`は候補選定中の記録であり、実験には使っていない。native peerの実行binaryは`/tmp/mros2-posix-run04-final-build/mros2-posix`で、SHA-256は`8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`。

## 条件の差

9/17 surveyの`192.168.100.3/.5`はこのhostの物理LANと重なるため、ユーザー承認のもと、既存の隔離Docker bridge `mros2-cr-net`上の`172.18.0.3/.5`を使用した。IP以外の役割・topic・message型・通信相手はnative mROS 2 peerを使う9/17の構成に合わせた。差分と適用範囲は[`report.md`](report.md)を参照。
