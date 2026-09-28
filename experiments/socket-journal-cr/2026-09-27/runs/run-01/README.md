# C/R 再実験 run-01

計画は [`../../plan.md`](../../plan.md) にあります。実験前提・build hash・container条件は `metadata.md`、生ログは `raw/`、結論と根拠は `report.md` に記録します。

**結果:** 60秒のC/R前ゲート不通過。`SIGUSR2`、checkpoint、restore、journal replayは未実行です。Wasm processは期限後も動き続け、起動から約188.5秒後にSIGTERMで停止しました。原因調査のログと計画との差は`report.md`に記録しています。

## 手順

1. `metadata.md` のpreflight欄を実値で埋め、Docker networkの接続containerと`.3`/`.5`の空きを確認します。
2. 既存のGit管理外WAMR build directoryと`lwip-wasm/public`を保持し、plan.mdの固定CMake optionsで一時directoryへ計測用iwasmとWasm appをbuildします。Wasm appのout-of-source buildが計測ログ入りlwIPを直接コンパイルします。iwasmとWasmを一時runtime/artifact directoryへコピーしてhashを記録します。
3. 同じローカル`ros:humble` imageからpeerとWAMR runnerを計画書どおりに起動します。peer nodeは`echo_peer.py`です。
4. `run_wasm_phase.py checkpoint mros2-cr-run01-wamr`を開始し、Wasm/peer双方のraw logでC/R前ゲートを確認します。60秒以内にゲートを満たさなければ、iwasmへSIGTERMを送り、C/Rを開始しません。ゲート後に30秒の無C/R観測を行います。
5. ゲートを満たした場合のみ、`plan.md`記載のSIGUSR2をcheckpoint processへ送ります。終了後、同じcollectorを`restore` phaseで起動します。
6. restore後のendpoint matchとmessage往復を90秒観測し、結果判定後にSIGTERMでrestore processを終了します。
7. containerのraw logを回収し、状態・hash・時刻を確定してから`report.md`を作ります。run-01ではpeer stdout全体を`raw/ros-peer-gate-failed.log`、停止時tailを`raw/ros-peer-stop-tail.log`として保存しました。

## collectorの契約

collectorは各phaseで新規log/status/PID artifactsのみを作り、既存run evidenceを上書きしません。remote shellがiwasmへ`exec`する前にcontainer PIDを記録し、`ps`でruntime・Wasm・restore flagを検証します。host UTC/monotonic時刻、container PID、Docker exec statusを`raw/`へ保存します。
