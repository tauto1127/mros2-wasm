# run-09 ID and body check

The gate files keep one JSON object per ID. This note only lists the accepted IDs and the publishes that did not reach an accepted callback before each gate closed.

## Pre-checkpoint, 60 seconds

Accepted IDs: 4, 5, 6, 7, 9, 10, 11, 12, 13, 14.

All ten use the same body `Hello from mros2-posix onto Linux: <id>`, native `epoch` order, Wasm line order, and a Wasm callback after the native echo return. Their publish-collector timestamps are 30116–4452614 ns later than the native receive timestamps (`collector_skew`). None are ordered by host monotonic time alone.

At the moment this gate passed, publishes 0, 1, 2, and 3 had no matching native receive in the window yet.

## 30-second baseline

Accepted IDs: 16–23, 25–39, 41–44. The largest publish ID already present when the window opened was 15. Skew for these 27 IDs is 121980–4646780 ns, all `collector_skew`.

## Post-restore, 90 seconds

`N=45`. Accepted IDs, all with `APP publish_begin` in `wasm-restore.log`: 46, 47, 48, 49, 50, 51, 52, 53, 55, 56. Skew is 168098–4409022 ns, all `collector_skew`.

ID 54 reached native echo return and has no Wasm callback line. ID 57's Wasm callback is in `wasm-restore.log` at line 1075, after the gate had already stopped at ten accepted IDs and still before the 90-second deadline. Neither is in the ten.
