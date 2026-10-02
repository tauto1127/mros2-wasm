#!/usr/bin/env python3
"""Generate and compile the observer-only lwIP C overlay for T12 instrumentation.

No canonical source or installed archive is modified. Generated patch, sources,
objects, link, and manifest are retained below the selected temporary output.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LWIP = ROOT / "lwip-wasm"
EXPECTED_DIFF_SHA256 = "588c97bc4496ba803c53747a60dcab1c93678498e9a6fa0a7ace3589ad4b1fcc"
EXPECTED_INPUTS = {
    "src/core/udp.c": "f8937ba44008c57045691a868454a7a7fe0e7ab6e2a3a18a918fd12d64ed33b2",
    "src/netif/netif_wasm.c": "4c401b1c1692aa53f5752c17c60753b531c80c086b2000a19d40eac27801aa4c",
}
HEADER_INPUTS = (
    LWIP / "src/include/netif_wasm_add.h",
    LWIP / "src/include/lwipopts.h",
    LWIP / "src/netif/netif_wasm_get.h",
    LWIP / "src/core/udp_multicast_manager.h",
    LWIP / "src/core/udp_multicast.h",
    LWIP / "lwip/src/include/lwip/arch.h",
    ROOT / "cmsis-wasm/public/include/cmsis_os.h",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected unique instrumentation seam, found {count}")
    return text.replace(old, new, 1)


def overlay_udp(original: str) -> str:
    text = replace_once(original,
        '#include "sys_utils.h"',
        '#include "sys_utils.h"\n#include "traceoverlay.h"\n#include <pthread.h>',
        "udp includes")
    text = replace_once(text,
        '      int saved_errno = errno;\n      if (saved_errno == EINTR) {',
        '      int saved_errno = errno;\n      int saved_fd = recv_fd;\n      if (saved_errno == EINTR) {',
        "capture true EINTR fd")
    text = replace_once(text,
        '    socklen_t socklen = sizeof(remote_addr);\n    recv_msglen = LWIP_UDP_RECVFROM(mcp->sd,',
        '    socklen_t socklen = sizeof(remote_addr);\n    int recv_fd = mcp->sd;\n    recv_msglen = LWIP_UDP_RECVFROM(recv_fd,',
        "capture actual recvfrom fd")
    old = '''        int refresh_status = netif_wasm_refresh();
        CMSIS_IMPL_ERROR("UDP_RECV_RECOVERY action=refresh status=%d reason=EINTR fd=%d",
                         refresh_status, mcp->sd);
        /* Probe/logging may change errno; retain recvfrom's EINTR result. */
        errno = saved_errno;
        continue;
'''
    new = '''        int refresh_status = netif_wasm_refresh();
        CMSIS_IMPL_ERROR("UDP_RECV_RECOVERY action=refresh status=%d reason=EINTR fd=%d",
                         refresh_status, saved_fd);
        /* Observer receives the true recv errno and descriptor; record() preserves errno. */
        uint16_t observed_result = refresh_status == NETIF_WASM_REFRESH_BUSY
            ? TRACE_RESULT_BUSY : refresh_status == NETIF_WASM_REFRESH_FAILED
            ? TRACE_RESULT_FAILED : refresh_status == NETIF_WASM_REFRESH_CHANGED
            ? TRACE_RESULT_CHANGED : TRACE_RESULT_UNCHANGED;
        traceoverlay_record(TRACE_EINTR, observed_result, 0, 0,
                            (uint32_t)saved_errno, (uint32_t)saved_fd,
                            (uint64_t)(uintptr_t)pthread_self());
        /* Probe, logger, and observer may alter errno; keep recvfrom's result. */
        errno = saved_errno;
        continue;
'''
    return replace_once(text, old, new, "UDP EINTR branch")


def overlay_coordinator(original: str) -> str:
    text = replace_once(original,
        '#include "netif_wasm_add.h"',
        '#include "netif_wasm_add.h"\n#include "traceoverlay.h"\n#include <pthread.h>\n#include <stdint.h>',
        "coordinator includes")
    start = text.index("int\nnetif_wasm_refresh(void)\n{")
    end = text.index("\nvoid\nnetif_wasm_get_ip_snapshot_core_locked", start)
    old = text[start:end]
    new = '''int
netif_wasm_refresh(void)
{
  in_addr_t addr = 0;
  uint32_t current_ip = 0;
  int snapshot_valid = 0;
  int lock_result = sys_trylock_tcpip_core();
  int refresh_result = NETIF_WASM_REFRESH_FAILED;
  uint64_t thread_id = (uint64_t)(uintptr_t)pthread_self();

  if (lock_result == EBUSY) {
    refresh_result = NETIF_WASM_REFRESH_BUSY;
    goto publish_observer;
  }
  if (lock_result != 0) goto publish_observer;

  /* No observer call occurs while the core mutex is owned. BUSY never reads
   * netif state; this snapshot is captured only by the lock winner. */
  if (netif_default == NULL) {
    sys_unlock_tcpip_core();
    goto publish_observer;
  }
  snapshot_valid = 1;
  current_ip = netif_default->ip_addr.addr;
  traceoverlay_record(TRACE_PROBE_ENTER, TRACE_RESULT_UNAVAILABLE,
                      current_ip, 0, 0, 1u, thread_id);
  int probe_status = probe_local_ip(&addr);
  traceoverlay_record(TRACE_PROBE_EXIT,
                      probe_status == 0 ? TRACE_RESULT_UNAVAILABLE : TRACE_RESULT_FAILED,
                      current_ip, probe_status == 0 ? addr : 0, 0, 1u, thread_id);
  if (probe_status != 0) {
    sys_unlock_tcpip_core();
    goto publish_observer;
  }
  if (current_ip == addr) {
    refresh_result = NETIF_WASM_REFRESH_UNCHANGED;
  } else {
    netif_default->ip_addr.addr = addr;
    refresh_result = NETIF_WASM_REFRESH_CHANGED;
  }
  sys_unlock_tcpip_core();

publish_observer:
  /* All record publication is after unlock (or after failed trylock). */
  traceoverlay_record(TRACE_TRYLOCK_ATTEMPT, TRACE_RESULT_UNAVAILABLE,
                      snapshot_valid ? current_ip : 0, 0, 0,
                      (uint32_t)lock_result, thread_id);
  uint16_t observed_result = refresh_result == NETIF_WASM_REFRESH_BUSY
      ? TRACE_RESULT_BUSY : refresh_result == NETIF_WASM_REFRESH_FAILED
      ? TRACE_RESULT_FAILED : refresh_result == NETIF_WASM_REFRESH_CHANGED
      ? TRACE_RESULT_CHANGED : TRACE_RESULT_UNCHANGED;
  traceoverlay_record(TRACE_TRYLOCK_OUTCOME, observed_result,
                      snapshot_valid ? current_ip : 0,
                      snapshot_valid && refresh_result == NETIF_WASM_REFRESH_CHANGED
                          ? addr : (snapshot_valid ? current_ip : 0),
                      (uint32_t)lock_result, snapshot_valid ? 1u : 0u,
                      thread_id);
  if (refresh_result == NETIF_WASM_REFRESH_CHANGED)
    printf("netif_wasm: local ip changed to 0x%08x\\n", addr);
  return refresh_result;
}
'''
    if not old.startswith("int\nnetif_wasm_refresh"):
        raise RuntimeError("coordinator seam unexpected")
    return text[:start] + new + text[end:]


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, help="temporary overlay destination (kept on success/failure)")
    p.add_argument("--sdk", type=Path, default=Path("/opt/wasi-sdk-21/bin"))
    a = p.parse_args(argv)
    diff = subprocess.run(["git", "-C", str(LWIP), "diff", "--binary"],
                          check=True, stdout=subprocess.PIPE).stdout
    diff_hash = sha(diff)
    if diff_hash != EXPECTED_DIFF_SHA256:
        raise SystemExit(f"current lwip-wasm source diff hash {diff_hash} does not match pinned {EXPECTED_DIFF_SHA256}")
    sources: dict[str, str] = {}
    source_bytes: dict[str, bytes] = {}
    input_hashes = {}
    for rel, expected in EXPECTED_INPUTS.items():
        raw = (LWIP / rel).read_bytes()
        actual = sha(raw)
        if actual != expected:
            raise SystemExit(f"{rel} SHA256 {actual} does not match pinned current source {expected}")
        input_hashes[rel] = actual
        source_bytes[rel] = raw
        sources[rel] = raw.decode().replace("\r\n", "\n")
    outputs = {
        "src/core/udp.c": overlay_udp(sources["src/core/udp.c"]),
        "src/netif/netif_wasm.c": overlay_coordinator(sources["src/netif/netif_wasm.c"]),
    }
    if a.out:
        out = a.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
    else:
        out = Path(tempfile.mkdtemp(prefix="mros2-traceoverlay-")).resolve()
    overlay_root = out / "overlay"
    (overlay_root / "src/core").mkdir(parents=True)
    (overlay_root / "src/netif").mkdir(parents=True)
    rendered_outputs = {}
    for rel, content in outputs.items():
        rendered = content.replace("\n", "\r\n") if b"\r\n" in source_bytes[rel] else content
        rendered_outputs[rel] = rendered.encode()
        (overlay_root / rel).write_bytes(rendered_outputs[rel])
    header = ROOT / "validation/campaign/traceoverlay.h"
    cfile = ROOT / "validation/campaign/traceoverlay.c"
    (overlay_root / "traceoverlay.h").write_bytes(header.read_bytes())
    (overlay_root / "traceoverlay.c").write_bytes(cfile.read_bytes())

    patch = []
    for rel in outputs:
        patch.extend(difflib.unified_diff(source_bytes[rel].decode().splitlines(True),
                      rendered_outputs[rel].decode().splitlines(True),
                      fromfile="a/lwip-wasm/"+rel, tofile="b/lwip-wasm/"+rel))
    patch_path = ROOT / "validation/campaign/traceoverlay-lwip.patch"
    patch_path.write_text("".join(patch))

    compiler = a.sdk / "clang"
    if not compiler.is_file(): raise SystemExit(f"missing WASI SDK clang: {compiler}")
    incs = [
        LWIP / "Third_Party/STM32CubeF7/Middlewares/Third_Party/LwIP/system",
        LWIP / "src/core", LWIP / "src/netif", LWIP / "src/include",
        LWIP / "lwip/src", LWIP / "lwip/src/include", LWIP / "lwip/system",
        ROOT / "cmsis-wasm/public/include",
        ROOT / "third_party/wamr/core/iwasm/libraries/lib-socket/inc",
        overlay_root,
    ]
    common = [str(compiler), "--target=wasm32-wasi", "-std=c11", "-pthread",
              "-DOS_POSIX", "-DSTM32F767xx", "-DosObjectsExternal",
              "-D iovec=iovec", "-D_DEFAULT_SOURCE", "-include", "sys/types.h",
              "-O0", "-g", "-Wall"]
    objects = []
    logs = []
    for rel in ("src/core/udp.c", "src/netif/netif_wasm.c", "traceoverlay.c"):
        obj = out / (Path(rel).stem + ".o")
        cmd = common + ["-I"+str(i) for i in incs] + ["-c", str(overlay_root/rel), "-o", str(obj)]
        r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
        logs.append({"command": shlex.join(cmd), "returncode": r.returncode,
                     "stdout": r.stdout, "stderr": r.stderr})
        if r.returncode:
            (out / "build.log.json").write_text(json.dumps(logs, indent=2)+"\\n")
            raise SystemExit(f"compile failed: {rel}; see {out/'build.log.json'}")
        objects.append(obj)
    nm = a.sdk / "llvm-nm"
    if not nm.is_file(): raise SystemExit(f"missing WASI SDK llvm-nm: {nm}")
    undefined_hooks = []
    for obj in objects[:2]:
        symbols = subprocess.run([str(nm), "-u", str(obj)], check=True,
                                 text=True, capture_output=True).stdout
        if "traceoverlay_record" not in symbols:
            raise SystemExit(f"instrumented unit {obj.name} does not reference traceoverlay ABI")
        undefined_hooks.append({"object": obj.name, "undefined_traceoverlay_record": True})
    observer_symbols = subprocess.run([str(nm), "--defined-only", str(objects[2])],
                                      check=True, text=True, capture_output=True).stdout
    if "traceoverlay_record" not in observer_symbols:
        raise SystemExit("observer object does not define traceoverlay_record ABI")
    linker = a.sdk / "wasm-ld"
    linked = out / "traceoverlay-lwip-hooks.wasm"
    cmd = [str(linker), "--allow-undefined", "--no-entry", "-o", str(linked), *map(str, objects)]
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    logs.append({"command": shlex.join(cmd), "returncode": r.returncode,
                 "stdout": r.stdout, "stderr": r.stderr})
    (out / "build.log.json").write_text(json.dumps(logs, indent=2)+"\\n")
    if r.returncode: raise SystemExit(f"overlay link failed; see {out/'build.log.json'}")
    compiler_version = subprocess.run([str(compiler), "--version"], check=True,
                                       text=True, capture_output=True).stdout.splitlines()[0]
    manifest = {
        "status": "C-seam overlay compile/link passed; not an application or campaign artifact",
        "source_diff_sha256": diff_hash, "input_sha256": input_hashes,
        "observer_header_sha256": sha(header.read_bytes()),
        "observer_source_sha256": sha(cfile.read_bytes()),
        "current_headers_sha256": {str(h.relative_to(ROOT)): sha(h.read_bytes())
                                    for h in HEADER_INPUTS},
        "compiler": compiler_version,
        "include_roots": [str(i.resolve()) for i in incs],
        "patch_path": str(patch_path.resolve()), "patch_sha256": sha(patch_path.read_bytes()),
        "overlay_sources": {rel: sha((overlay_root/rel).read_bytes()) for rel in outputs},
        "objects": {obj.name: sha(obj.read_bytes()) for obj in objects},
        "linked_hook_probe": str(linked), "linked_sha256": sha(linked.read_bytes()),
        "abi_resolution": {"instrumented_references": undefined_hooks,
                           "observer_defines_record": True, "wasm_link_passed": True},
        "disk_bytes": sum(x.stat().st_size for x in out.rglob("*") if x.is_file()),
        "safety": "only textual draining/logging is post-unlock; record is bounded lockfree observer work at true probe boundaries while core is held; BUSY has no snapshot; ring reservation is one CAS attempt with explicit loss; no malloc/syscalls/logs/locks in observer",
        "trace_schema": "traceoverlay_event-v2 with thread_id; post-unlock dump includes counters/lost/lockfree",
        "probe_interval": "PROBE_ENTER/EXIT are emitted immediately around probe_local_ip while the winning core lock is held; BUSY emits neither and carries no snapshot",
        "metrics": "lock-free observer counters; attempts/winners/busy/fail/outcomes/completions plus active/max-active probe interval; loss is explicit and nonzero rejects readiness",
        "timestamp_policy": "guest observer has no timestamp; campaign collector may timestamp drained events",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\\n")
    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(run())
