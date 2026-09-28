# C/R 再実験 run-03

Sol承認済みのdiagnostic runを実施しました。60秒のC/R前gateは不通過で、C/R本試験には進んでいません。

- 計画・probe: Sol re-review **APPROVE**（2026-09-27）
- 結果: peer `eth0`でWasm SPDP frame 62件を観測。peer IGMP membershipとPID 1のUDP `7400` / `7410` / `7411`を確認
- gate: peer graphのremote Wasm endpoint 0、peer receive/echo 0、Wasm callback 0
- C/R: **未実施**。checkpoint signal、restore、journal dump/replayなし
- 研究内の前回C/R: [2026-09-24探索的run](../../../2026-09-24/runs/exploratory-cr-01/report.md)ではrestore後のUDP `EINTR`とsocket再作成を観測。ただしROS endpoint／app往復の成立は確認していない
- 詳細: [`report.md`](report.md)、実測値: [`metadata.md`](metadata.md)
- raw logs: [`raw/`](raw/)
