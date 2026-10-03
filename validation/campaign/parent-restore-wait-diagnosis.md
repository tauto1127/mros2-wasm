# Parent direct inspection: restore coordinator stuck before releasing normal threads

2026-10-02. Operator authorized SYS_PTRACE-limited read-only inspection and explicitly prohibited subagent use for this inspection. No subagent used. No target signal, debugger attach, ptrace operation, target write, socket recreation, checkpoint, restore or source repair performed. Helpers were read-only-rootfs, network=none, PID namespace of the owned failed app, sole SYS_PTRACE capability, narrow owned capture bind. Helpers exited; target app/peer remained live.

## Exact target

Failed SAME run `/tmp/t12-same/runs/1790947502-2ad22128d2`; container `ae12bd6be3c3725b7a0047cbd4c1de4df4ec01a2114c7f4a72d60c44cd7edfc8`, restore PID 53. Runtime SHA256 remains `77c3bcef496f45b190755eaf29108fe6fe957dfab6c9e57fa3efc9e578587b60`. Case remains NOT PASS.

## Measured findings

Read-only `/proc/53/task/*/syscall`, maps, and bounded `/proc/53/mem` reads identified native futex addresses, stack code pointers and runtime restore data. Kernel stack reads remained permission-denied; this is not a debugger-unwound backtrace. Native code pointer observations were corroborated with exact runtime disassembly, actual condition-variable addresses, and source layout.

- Native TID 85 has a `restore_sync_routine` return site `iwasm+0x3f502`, immediately after `usleep(10)` in the wait-for-waiter-count loop, not the later nonwaiter loop.
- Its actual restore arguments list eight saved guest waiters: `[8, -1, 1, 10, 9, 11, 7, 6]`. Loop index is 0; last target is guest thread 8 at exec-env `0x5f1e00be1090`.
- Actual atomic wait-map membership is seven guest threads: `[-1, 1, 6, 7, 9, 10, 11]`. Guest thread 8 is missing.
- Thread 8's actual running status is STOP (1), signal/status bytes `000000000000010000000000`. Its native thread is waiting on its exec-env restore condition variable, not reconstructed atomic.wait.
- Guest threads 2,3,4,5 also remain STOP in the initial post-restore `wasm_cluster_thread_waiting_run` call site (`iwasm+0x3fd9d`). Their native wait condition addresses match the observed futex addresses. They have not been released by final `continue_all`.
- Two snapshots showed the same missing waiter, loop index and stopped threads.

Evidence/scripts: `/tmp/t12-same/parent-wait-inspection/{waits.json,wait-memory.json,restore-state-first.json,restore-state.json,inspect_waits.py,read_wait_memory.py,read_restore_state.py,check_restore_progress.py}`. Struct offsets were established from exact runtime disassembly and corresponding source, not guessed wasm image offsets. Read-only heap/list traversal is not an atomic snapshot; agreement of repeated observations is recorded instead.

Red-capable diagnostic command:

```sh
python3 /tmp/t12-same/parent-wait-inspection/check_restore_progress.py /tmp/t12-same/parent-wait-inspection/restore-state.json
```

Exit 1: `RED: restore coordinator awaits a saved waiter still parked in restore waiting_run`.

## Source/disassembly explanation

`third_party/wamr/core/iwasm/interpreter/wasm_interp_classic.c:1421-1478` implements waiter-first resume. It waits only for main to park, then calls `wasm_cluster_thread_continue(target_env)` for each saved waiter and waits for the aggregate wait count to increase. It does not establish that each selected child has entered its initial restore park before continuing it. The later `wait_for_nonwaiters_stopped` does not protect that earlier waiter wakeup.

`thread_manager.c:944-952` unconditionally writes STOP in `wasm_cluster_thread_waiting_run`. `thread_manager.c:1009+`/exact `iwasm+0x2e910` continue routine writes RUNNING and signals while holding the wait lock. Thus a continue before the child's park can be overwritten by that child's subsequent STOP, losing the wakeup.

Exact disassembly shows the coordinator has passed the continue call for selected waiter 8 and is waiting for it; that same target remains STOP at the initial restore park. This strongly identifies the resume-before-park race as the mechanism for the observed stuck restore coordinator. Full chronological trace and an isolated deterministic race regression have not yet been captured; no repair/re-test claim is made.

This is a runtime restore-orchestration blockage, not evidence that the IP projection SEDP transaction itself is holding these five threads. Other defects are not ruled out. Ordinary atomic.wait activity of the other seven threads explains why partial app/observer progress can coexist with incomplete restore release.

## Next scope decision

An isolated runtime repair would need a race-safe handshake establishing each saved waiter's initial park under its existing wait lock before resume, followed by a deterministic race test and actual C/R validation. Merely increasing a timeout, forcing continue_all, editing live status, or restarting RTPS sockets is not an acceptable repair. Runtime changes would change the pinned runtime SHA and require explicit scope/provenance treatment separate from the original lwIP/RTPS implementation. No runtime source changed in this inspection.
