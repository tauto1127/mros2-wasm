# cmsis-wasm 182dcaf の Checkpoint/Restore 検証

**結果: same-IP 10/10 PASS、changed-IP 10/10 PASS。** 停止した trial はない。全20試行で、checkpoint 前の連続10件と restore 後の新しい連続10件の完全往復が成立した。

life-wiki の `llm-context/working/mros2-wasm-cr-validation-planning.md` は存在しなかった。再作成していない。現在地は `mros2-wasm-network-migration.md` と `mros2-wasm-migration.md` から補った。研究リポジトリへの commit / push はしていない。

## 何を検証したか

親リポジトリ `7b632868ed9859dc152bc87a23c98d4afff43837`（`Fix wasm32 CMSIS timeout conversion`）に記録された `cmsis-wasm` `182dcaff50a0e9c626c84db365b1d762747a806b` を、同じ binary で20回使った。修正は `add_timespec()` で、wasm32 の 32-bit `tv_nsec` を溢れさせないよう timeout を秒と余りのナノ秒に分けて足す。

検証専用 worktree は `/home/osslab/mros2-wasm-cr-validation-182dcaf`、branch `validate/cmsis-timeout-cr-20260928`。既存の `debug/recvfrom-observability` worktree は reset / clean / build していない。submodule の作業ツリー HEAD も試行後に元のままである。

| 対象 | commit |
|---|---|
| root | `7b632868ed9859dc152bc87a23c98d4afff43837` |
| cmsis-wasm | `182dcaff50a0e9c626c84db365b1d762747a806b` |
| lwip-wasm | `78ef9fc33842bece9ad9a83c1cd0a448b779d64e` |
| nested lwip | `e6a8415df332ee34d7af02255b2aa1e8ee74348f` |
| mros2 | `a8d4481c4531f77b143d5e78ac32b333c338b0a2` |
| embeddedRTPS | `81a6a4fe9309f3cb16f0f3b60c92ca89b8602182` |
| WAMR | `db2054224dcff9686f3f98850a29c554974096bc` |
| wasmig（隔離コピー） | `c5015ee06acd3992ce826655825e1911da8c5945` |

`182dcaf` は GitHub の fetch では取れず、既存 submodule のローカル object から展開した。WAMR の `migration.cmake` だけ、FetchContent のソースが source tree の外にあるため `add_subdirectory` に binary directory を渡す1行を足した。通信と timeout の挙動は変えていない。システム Cargo 1.75 は wasmig の lockfile version 4 を読めないため、Cargo 1.97.1 でビルドした。

最終 artifact（全 trial で照合した同一 hash）:

| artifact | SHA-256 |
|---|---|
| iwasm | `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60` |
| echoback_string.wasm | `b0279232bba0daed3f7cd92ac1a61f5d4805465ad04550aa013864cce02d4d71` |
| native peer | `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1` |

Wasm は隔離 build の `libcmsis.a` をリンクしている。その中の `cmsis_wasm_thread_sync.c.obj` は 182dcaf のソースからコンパイルされ、逆アセンブルに `i64.div_u` / `i64.rem_u`（除数 1000）と `1000000000` の桁上げがある。run-04 / run-06 の古い Wasm は使っていない。native peer は run-04 の実行ファイルを read-only で使った。

ログの flush は足していない。checkpoint しない probe で `mros2-posix start!` がすぐ出て、netif は `172.18.0.3` を選んだ。

## 判定

完全往復は、同じ ID と同じ本文 `Hello from mros2-posix onto Linux: <id>` について Wasm publish、native peer の `/to_linux` callback、peer の `/to_stm` echo、Wasm の `/to_stm` callback が揃うこと。連続する10 ID だけを数えた。60秒 / 90秒の成功期限と30秒 baseline は使っていない。

全 trial で checkpoint 前の窓は ID 4–13、境界 `N=14`（SIGUSR2 前に追加で publish された ID 14 を含む）。same-IP の restore 後の窓は 16–25。changed-IP の窓は 17–26。いずれも `N` より大きい連続10件である。

ID 15 は restore 後に Wasm callback と peer の受信・echo がある一方、Wasm の publish 行が checkpoint 側にも restore 側にも無い。changed-IP では ID 16 の publish と peer 往復はあるが、Wasm callback 行が無い。これらの境界 ID は10件に数えていない。最初の完全な新規往復は same-IP が ID 16、changed-IP が ID 17 である。

same-IP は同じ `172.18.0.3` container で restore した。changed-IP は `172.18.0.3` で checkpoint し、同じ state を mount した新しい `172.18.0.6` container で restore した。peer は `172.18.0.5`。network は既存の `mros2-cr-net`（`609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408`、`172.18.0.0/16`）で、trial 後は当該 container だけを外した。

## 時間

主時計は host の monotonic time。表は PASS の n=10。単位は秒。checkpoint は SIGUSR2 コマンド開始から checkpoint process の正常終了までで、state hash の時間は含まない。hash は trial あたり約 0.62–0.67 秒で、manifest 確定後に別計測した。restore 段階は、restore コマンド開始から、最初のアプリ出力より前にある最後の `Finish to restore stack` までの概算である。20 trial ともこの完了点を特定できた。iwasm を後で止めた時刻は使っていない。通信復旧は restore コマンド開始から、最初の新規 ID の完全往復が成立した Wasm callback までである。

| 区間 | same-IP n=10 | changed-IP n=10 |
|---|---|---|
| checkpoint | 平均 1.053、範囲 1.030–1.077 | 平均 1.077、範囲 1.034–1.113 |
| restore 段階（概算） | 平均 0.280、範囲 0.266–0.289 | 平均 0.276、範囲 0.265–0.293 |
| 通信復旧 | 平均 4.134、範囲 4.043–4.662 | 平均 4.342、範囲 3.989–5.011 |

補助値も n=10。restore 開始から peer の最初の post-restore `/to_linux` 受信は、same-IP が平均 2.133 秒（2.042–2.661）、changed-IP が平均 2.339 秒（1.987–3.008）。最後の pre-C/R 完全往復から最初の post-C/R 完全往復は、same-IP が平均 6.152 秒（6.023–6.684）、changed-IP が平均 7.146 秒（6.750–7.865）。10件目の pre-C/R callback から SIGUSR2 開始までは 0.075–0.134 秒で、その間の追加 publish は全 trial で ID 14 の1件である。

成功 trial の checkpoint state は manifest と SHA-256 を確定し、path が `/tmp/mros2-wasm-cr-validation-182dcaf/state/<trial-id>` であることを確認してから削除した。失敗 trial は無い。共有 network の attachment は 0 に戻っている。packet capture は行っていない。

trial ごとの metadata、command、PID、inspect、log、時刻、cleanup は `trials/<trial-id>/raw/` にある。build の provenance は `build-provenance/`、runner の差分は `adjustments.md` にある。
