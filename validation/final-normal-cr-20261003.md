# Exact final normal artifact C/R attempt — 2026-10-03

## Result: FAIL, not an accepted C/R

A retained external exact-artifact attempt was found while preparing the requested final C/R. This parent did not launch, alter, or claim ownership of its runner/container. The tested app hash is exactly the final normal `echoback_string.wasm` hash from round-2 startup repair. This record distinguishes measured evidence from authorship and inference.

- Attempt: `/tmp/final-normal-cr-20261003/runs/1790996694-f42769c834/`; result `/tmp/final-normal-cr-20261003/final-result.json` (SHA-256 `dcd33a25e949daa1613014ad7e39f1fe8dc4f45e8082472cc90b504990929a34`).
- Mode: same-host changed IP `.3` (`172.18.0.3`) → `.6` (`172.18.0.6`), normal uninstrumented final application, one checkpoint. App `b66ded95023a51022e4ebe19cca65663f83c173590dc9bef6d5cba5b27d326fc`; fixed runtime `70bfcdc4b109041deec3eef4677a605a3fb8d5e03cf16fb026ca4ca8a85938f3`; peer `8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1`. Build provenance manifest SHA `d486e39b8aecddf0f549544c10be9054cd4ce8f6096c011b1aa29cd40a665c09`.
- Before checkpoint: ten contiguous IDs4–13, fully correlated/body-matching.
- Checkpoint: 1 GiB memory, 3,604-byte socket image. Both mutable state and separate immutable archive contain51 files (1,073,760,999 bytes); parent read-only SHA checks show mutable/archive main-memory images match (`08736b9d340e31ddab8beffce21550664a63d61394fe1c4a7cd6427b41a5caad`) and socket images match (`76781bf504440736683326e5b8384ea0d3fba38b881a03bcbbf8398e71d7d3f0`). Setup recorded 8,285,069,312 free bytes, above the required5,369,757,696 dump+copy+margin+floor reservation.
- After restore: 226 Wasm publishes,232 native receives and echo publish-returns, **zero Wasm callbacks** and zero complete round trips. The acceptance gate required ten; result is **FAIL**. No claim of successful final-artifact C/R.
- Restore log records refresh statuses after EINTR including `netif_wasm: local ip changed to 0x060012ac` (network-order `.6`), then continues publishing. This confirms a logged current-IP update, not applied-IP/locator convergence or end-to-end recovery. The causal reason for missing subscriber callbacks is undetermined; do not infer it from this trace.
- The runner separately records stop success followed by safe disconnect refusal because Docker's stopped-container endpoint identity fields were incomplete. Container objects/images/state were preserved; deletion was not performed. The continuous `.5` peer was not restarted/modified and was the only container left attached to the network.

Evidence paths: checkpoint logs, source/restore logs, native peer log, lifecycle audit and state images are in `/tmp/final-normal-cr-20261003/`; the exact external run's stopped containers use validation labels `validation-1790996694-f42769c834` and `validation-exact-final-restore-20261003`. This parent only read/hashed artifacts and inspected Docker state; did not stop, disconnect or delete these objects.

## Disposition

This is a concrete final-artifact C/R communication failure, which supersedes the earlier statement that exact-final-artifact C/R had not been attempted. Historical instrumented SAME/CHANGED/REPEATED campaigns still pass for their earlier binaries, but cannot overwrite this result. Further same/repeated campaigns should wait until the missing callback path is understood; no automatic retry, source edit, live-container mutation, disk cleanup, or subagent action is authorized by this report. Current production remains previously adopted/published, but a claim that the final normal artifact passed changed-IP C/R is withdrawn. Any diagnosis/fix requires a new scoped decision and fresh validation/review as appropriate.
