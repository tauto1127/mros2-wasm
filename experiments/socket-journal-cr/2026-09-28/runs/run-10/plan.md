# run-10 plan: SEDP discovery ordering probe

目的は、run-08型の保存前片方向不通が、local SEDP changeの消費とremote builtin reader proxy登録の順序競合で説明できるか観測すること。

run-09と同じネットワーク、IP、native peer、iwasm、アプリ通信、60秒/30秒/90秒の合格条件を使う。差はWasmアプリだけで、embeddedRTPSへ観測用 `DISCOVERY_PROBE` ログを追加して再ビルドしたものを使う。制御フローは変更しない。

確認したい順序:

1. `event=sedp_change`
2. `event=writer_progress_begin` の `proxies_empty`
3. `event=spdp_builtin_capabilities`
4. `event=add_reader_proxy_begin/end`

失敗時に `writer_progress_begin proxies_empty=1` がproxy追加より先に起き、`next`だけ進んでいればrace仮説を支持する。計測ログ自体がスレッドタイミングを変える可能性は制約として扱う。
