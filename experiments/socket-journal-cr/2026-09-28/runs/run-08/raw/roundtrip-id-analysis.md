---
sources:
  - "roundtrip-gate.status"
  - "wasm-checkpoint.log"
  - "peer-native.log"
---

# run-08 pre-checkpoint ID/body audit

- Gate window monotonic ns: `2325169012642350` through `2325229012642350`.
- Distinct Wasm publish IDs: 58 (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59).
- Distinct IDs with the same body at Wasm publish and native receive: 56.
- Distinct IDs with the same body at publish, native receive, and native echo-return logs: 56.
- Distinct IDs with the same body at all four application events: 0.
- Distinct IDs with all four events strictly ordered by captured host monotonic timestamps: 0.
- Native receive IDs: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59.
- Native echo-return IDs: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59.
- Wasm callback IDs: none.
- Within-window last stages: Wasm-publish-only IDs 0, 1; native-receive-and-echo-only IDs 7, 26; matching records through native echo return IDs 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59. No ID reached a recorded Wasm callback.

The native peer source log contains an epoch timestamp and logs `peer_receive` before `peer_echo_publish_return` in the callback. The Wasm `host_mono_ns` prefix is assigned when the host collector reads each output line; it is a collector receipt time, not an application-side timestamp. The gate therefore reports strict full-order success only where all four captured records support that order. No Wasm callback line was observed in this gate window.

## Same-body native stage records

- ID 2: `Hello from mros2-posix onto Linux: 2`
- ID 3: `Hello from mros2-posix onto Linux: 3`
- ID 4: `Hello from mros2-posix onto Linux: 4`
- ID 5: `Hello from mros2-posix onto Linux: 5`
- ID 6: `Hello from mros2-posix onto Linux: 6`
- ID 8: `Hello from mros2-posix onto Linux: 8`
- ID 9: `Hello from mros2-posix onto Linux: 9`
- ID 10: `Hello from mros2-posix onto Linux: 10`
- ID 11: `Hello from mros2-posix onto Linux: 11`
- ID 12: `Hello from mros2-posix onto Linux: 12`
- ID 13: `Hello from mros2-posix onto Linux: 13`
- ID 14: `Hello from mros2-posix onto Linux: 14`
- ID 15: `Hello from mros2-posix onto Linux: 15`
- ID 16: `Hello from mros2-posix onto Linux: 16`
- ID 17: `Hello from mros2-posix onto Linux: 17`
- ID 18: `Hello from mros2-posix onto Linux: 18`
- ID 19: `Hello from mros2-posix onto Linux: 19`
- ID 20: `Hello from mros2-posix onto Linux: 20`
- ID 21: `Hello from mros2-posix onto Linux: 21`
- ID 22: `Hello from mros2-posix onto Linux: 22`
- ID 23: `Hello from mros2-posix onto Linux: 23`
- ID 24: `Hello from mros2-posix onto Linux: 24`
- ID 25: `Hello from mros2-posix onto Linux: 25`
- ID 27: `Hello from mros2-posix onto Linux: 27`
- ID 28: `Hello from mros2-posix onto Linux: 28`
- ID 29: `Hello from mros2-posix onto Linux: 29`
- ID 30: `Hello from mros2-posix onto Linux: 30`
- ID 31: `Hello from mros2-posix onto Linux: 31`
- ID 32: `Hello from mros2-posix onto Linux: 32`
- ID 33: `Hello from mros2-posix onto Linux: 33`
- ID 34: `Hello from mros2-posix onto Linux: 34`
- ID 35: `Hello from mros2-posix onto Linux: 35`
- ID 36: `Hello from mros2-posix onto Linux: 36`
- ID 37: `Hello from mros2-posix onto Linux: 37`
- ID 38: `Hello from mros2-posix onto Linux: 38`
- ID 39: `Hello from mros2-posix onto Linux: 39`
- ID 40: `Hello from mros2-posix onto Linux: 40`
- ID 41: `Hello from mros2-posix onto Linux: 41`
- ID 42: `Hello from mros2-posix onto Linux: 42`
- ID 43: `Hello from mros2-posix onto Linux: 43`
- ID 44: `Hello from mros2-posix onto Linux: 44`
- ID 45: `Hello from mros2-posix onto Linux: 45`
- ID 46: `Hello from mros2-posix onto Linux: 46`
- ID 47: `Hello from mros2-posix onto Linux: 47`
- ID 48: `Hello from mros2-posix onto Linux: 48`
- ID 49: `Hello from mros2-posix onto Linux: 49`
- ID 50: `Hello from mros2-posix onto Linux: 50`
- ID 51: `Hello from mros2-posix onto Linux: 51`
- ID 52: `Hello from mros2-posix onto Linux: 52`
- ID 53: `Hello from mros2-posix onto Linux: 53`
- ID 54: `Hello from mros2-posix onto Linux: 54`
- ID 55: `Hello from mros2-posix onto Linux: 55`
- ID 56: `Hello from mros2-posix onto Linux: 56`
- ID 57: `Hello from mros2-posix onto Linux: 57`
- ID 58: `Hello from mros2-posix onto Linux: 58`
- ID 59: `Hello from mros2-posix onto Linux: 59`
