# C/R 再実験 run-02

run-01のC/R前ゲート不通過を受けた診断付き再試行です。計画は[`../../plan-run-02.md`](../../plan-run-02.md)、元のC/R手順は[`../../plan.md`](../../plan.md)にあります。

run-01と同じnetwork、peer/WAMR IP、image、ROS endpoint、runtime/Wasm binaryを使います。追加観測はpeer `eth0`の受動RTPS packet captureだけです。60秒ゲート未通過時に正確なiwasm PIDを停止するwatchdogを同時に起動します。

Sol review: **APPROVE**（2026-09-27）。peer graph上の両方向remote endpoint GID/countと、10件の同一ID往復をゲート証拠とします。Wasm側に直接matchログがない点も確認済みです。

`raw/`にはrun-02固有の全raw logを保存します。起動前の実条件、ゲート結果、C/Rを実施したかどうかは[`metadata.md`](metadata.md)と[`report.md`](report.md)に記録します。
