# run-09: 同一 IP でのトピック往復の追加試行

**結果: 合格。** 保存前に 10 件、チェックポイントなしの 30 秒で 27 件、同じコンテナ・同じ IP へ復元したあと 10 件の完全往復を確認した。詳細は [report.md](report.md)、実測値は [metadata.md](metadata.md)。

判定は両側の subscriber callback に残った同じ ID と本文、および [procedure.md](procedure.md) に先に書いた順序である。`recvfrom()` の成功だけでは数えない。

チェックポイント本体は `/tmp/mros2-wasm-cr-rerun-20260928-run09/state/` に残し、Git 管理下にはファイル一覧と SHA-256 だけを置いた。
