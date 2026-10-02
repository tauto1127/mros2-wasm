# lwIP current-IP/coordinator seam — implementation checkpoint

**Status: implementation applied; isolated seam acceptance NOT READY.** The requested source changes are in the new implementation checkout only. Target lwIP rebuild and install passed, but focused runtime validation (contention/probe/error/unchanged snapshot behavior) has not passed; a native harness compile attempt failed because the WASI-only `wasi_socket_ext.h` requires WASI SDK types. Per Gate B, this must not be presented as a completed validation gate. No source commit/staging, push, RTPS edits, root-source edits, or experimental-source edits were made.

## Implemented

- `lwip-wasm/src/core/lwip.c`: initialized the shared private core mutex statically with `PTHREAD_MUTEX_INITIALIZER`, removed its redundant MX init, and exposed `sys_trylock_tcpip_core()` (returns pthread result, so EBUSY remains distinguishable).
- `lwip-wasm/src/netif/netif_wasm.c`: removed `ip_changed_pending` and its take function. Startup publication and refresh publication are under the shared core mutex. Refresh tries the mutex before probe, maps EBUSY to BUSY and other acquisition/probe failures to FAILED, handles an explicit uninitialized-validity state, avoids IP payload stores on UNCHANGED, and releases once on every owner return path. Probe failures converge on one socket-close cleanup path. `netif_default` identity is preserved.
- `lwip-wasm/src/include/netif_wasm_add.h`: removed the take API, declares legacy-compatible refresh status constants and a copied network-byte-order IP/mask/validity snapshot API, with a separately named already-core-locked accessor.
- `lwip-wasm/src/include/lwipopts.h`: declares the private core trylock function.

`netif_wasm_get()` remains a raw pointer accessor with a documented caller-held-core-lock contract for internal lwIP C bind/IGMP sites. No C++ consumer migration is claimed. Existing `embeddedRTPS/SPDPAgent.cpp` still references the now-removed pending API and still has its outer lock; that is the next seam, not modified here. Therefore the full application is expected to be temporarily uncompilable pending that approved follow-on.

## Validation and evidence

Commands run:

- `cmake --build bootstrap/build/lwip --parallel 4` — passed against the fresh WASI target; target compiled updated core, netif and selected C sources, linked `liblwip.a`.
- `cmake --install bootstrap/build/lwip` — passed; installed updated library and public `netif_wasm_add.h` shim to this worktree.
- `git -c core.whitespace=cr-at-eol diff --check` in `lwip-wasm` — passed (CRLF source files accounted for).
- `grep -R 'ip_changed_pending\|take_ip_changed' lwip-wasm/src` — no matches.
- Attempted host-native standalone compile of `netif_wasm.c` with repository includes — failed because native `cc` does not define the WASI SDK `__wasi_*` types required by the included WAMR `wasi_socket_ext.h`. Raw compiler failure is in the session record; this is not treated as a product failure, but no focused replacement test was implemented/run.

No tests were added. Required focused scenarios remain unvalidated: deterministic probe-call absence on BUSY, ordinary-core BUSY, status mapping, error-path mutex release, unchanged payload/snapshot coherence, and snapshot contention/ordinary access. No claim of callgraph completeness beyond the inspected selected lwIP current-IP/netif sites is made; the next C++ seam must migrate its readers and remove its obsolete API call.

## Source state / integrity

Changed tracked files (all in `/home/osslab/20261001-mros2-wasm-eintr-ip-refresh-impl/lwip-wasm`):

- `src/core/lwip.c` SHA-256 `f57d498967674a97a9fc7dea4f976b8bbddfb99cc1740f9893574a2b39f6be12`
- `src/netif/netif_wasm.c` SHA-256 `661eb7feb7f2d10f1fa023103704e2c9eb4aa36109ba4a12b94f02a1153cb12e`
- `src/include/lwipopts.h` SHA-256 `45e138fcbee6e1c0f732bd40b2521ade02cc072f0efadb8a1cc80f98c1eb630f`
- `src/include/netif_wasm_add.h` SHA-256 `ac30876b88489498b2661da53ffe6c3cb464d5002f84985bfee3250e1c4862aa`

Diff: 4 files changed, 107 insertions, 51 deletions. `git status --short` lists only those four modified files. `git diff --cached --stat` is empty; no staged files or commits.

## Risks / next validation

Most important open item: focused target execution must verify the required coordinator/snapshot cases before this seam can be declared ready. A proper isolated WASI harness or another deterministic test strategy is needed; do not infer these from a successful archive build. Also confirm all ordinary readers use copied snapshot and all already-core-held C users use the `_core_locked`/raw contracts during the next selected-callsite integration. Existing C++ pending consumer removal/errno preservation remains explicitly outstanding.
