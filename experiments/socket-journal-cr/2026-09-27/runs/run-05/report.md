# run-05 report: SIGUSR1 no-op control

## 結論

**SIGUSR1を受け取っただけでは、WAMRのsocket受信は中断せず、通信も継続した。** 同じartifact・native mROS 2 peer・Docker networkを使い、SIGUSR1のhandler確認後にID 14–20の7件の完全往復を観測した。WASI errno 27、SIGUSR2 handler、checkpoint完了はいずれも0件だった。

したがってrun-04で観測した4件のWASI errno 27は、OS signal一般の副作用ではなく、**SIGUSR2から呼ばれるWAMR checkpoint routineが、checkpointに必要な安全点へ進ませるため、ブロック中のsocket操作を明示的にwakeした結果**と判断できる。

## 実験

| 条件 | 結果 |
|---|---|
| 事前の完全往復ゲート | ID 4–13の10件でpass |
| 制御信号 | SIGUSR1をiwasm PID 12へ送信。`SIGUSR1 called`を確認 |
| handler後の観測 | 約8.04秒でID 14–20の7件が完全往復 |
| guest-visible WASI errno 27 | 0件 |
| SIGUSR2 / checkpoint | どちらも観測なし |
| cleanup | run-05 containerを削除。共有networkはattachment 0 |

このrunは**C/Rを行っていない信号制御実験**であり、9/17に記録されたC/R後のcallback停止を再現したものではない。pass条件・artifact hash・実行時記録は[`plan.md`](plan.md)と[`raw/`](raw/)に保存した。

## run-04との比較

run-04では、SIGUSR2送信後にcheckpoint control threadが起動し、約202 ms後にWASI `sock_recv_from`がfd 7・10・8・6で`wasi_errno=27`を返した。WAMRの[`checkpoint_routine`](../../../../../third_party/wamr/core/iwasm/migration/wasm_thread_migration.c)はcheckpoint signalを各Wasm threadへ設定した後、[`wasm_cluster_wakeup_blocking_threads_for_checkpoint`](../../../../../third_party/wamr/core/iwasm/libraries/thread-mgr/thread_manager.c)を呼ぶ。同関数と[`wasm_runtime_wakeup_blocking_op_for_checkpoint`](../../../../../third_party/wamr/core/iwasm/common/wasm_blocking_op.c)のコメントには、ブロック中のsyscallをwakeして`EINTR`で戻し、interpreter loopへ復帰させる意図が明記されている。

一方、run-04のrestore側PID 58にはSIGUSR2を送っていない。restore後にguest `recvfrom()`が`errno=27`を返した4 socketは、local port 7411・7401・7400・7410、fd 10・6・8・7で、checkpoint側で中断された4つのWASI fdと対応する。その後4件とも`udp_mc_recover()`が成功し、UDP受信、RTPS queue、DATA parse（`reader_found=1`）、`newChange`、アプリcallbackが続いた。これは**checkpoint時に中断されたreceive callの結果がrestore後にguestへ戻り、既存のrecovery処理へ入った**という説明と強く整合する。対応関係の因果を独立に証明するthread/stack traceまでは取っていないため、この部分は「強く整合」と表現する。

比較記録は[run-04レポート](../run-04/report.md)、[`raw/wasm-checkpoint.log`](../run-04/raw/wasm-checkpoint.log)、[`raw/wasm-restore.log`](../run-04/raw/wasm-restore.log)を参照。

## 9/17の未解決点

この結果は、9/17にcallbackが継続しなかった原因を特定しない。9/17のsurveyには`recvfrom() == -1`とsocket再生成はあるが、失敗時のerrno、Wasm側への返信packet到達、RTPS parse/reader配送のログがない。さらに9/17の`192.168.100.3/.5`に対しrun-04/05は隔離bridge上の`172.18.0.3/.5`で、9/17のartifact hashもsurveyからは照合できない。

従って、現在言えるのは「errno 27はcheckpointのblocked-socket wakeupで説明でき、run-04ではrecovery後にcallbackまで戻った」まで。9/17固有のcallback lossがnetwork/locator、artifact差、またはrestore後のRTPS stateのどれによるかは未確定である。
