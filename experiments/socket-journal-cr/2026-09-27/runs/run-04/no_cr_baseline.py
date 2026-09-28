#!/usr/bin/env python3
"""Check for ten new full round trips in a 30-second no-C/R window."""

from datetime import datetime, timezone
from pathlib import Path
import re
import time


TAG = "[CR-RERUN-20260927-R04]"
WINDOW_NS = 30_000_000_000
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+)")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+)")
CALLBACK_RE = re.compile(r"APP callback topic=/to_stm id=(\d+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def ids(pattern, content):
    return {int(value) for value in pattern.findall(content)}


def main():
    raw = Path(__file__).resolve().parent / "raw"
    marker = raw / "gate-pass.ok"
    wasm_path = raw / "wasm-checkpoint.log"
    peer_path = raw / "peer-native.log"
    log_path = raw / "no-cr-baseline.log"
    status_path = raw / "no-cr-baseline.status"
    if not marker.exists():
        raise SystemExit("C/R gate marker is absent; refusing baseline/C/R continuation")
    if log_path.exists() or status_path.exists():
        raise SystemExit("refusing to overwrite an existing baseline artifact")

    gate_ids = set()
    marker_match = re.search(r"^distinct_roundtrip_ids=([0-9,]+)$",
                             read(marker), re.MULTILINE)
    if marker_match:
        gate_ids = {int(value) for value in marker_match.group(1).split(",")}
    wasm = read(wasm_path)
    published_at_start = ids(PUBLISH_RE, wasm)
    if not published_at_start:
        raise SystemExit("no Wasm publish IDs at baseline start")
    max_start_id = max(published_at_start)
    start_utc = utc_now()
    start_ns = time.monotonic_ns()
    deadline_ns = start_ns + WINDOW_NS
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"{TAG} utc={start_utc} mono_ns={start_ns} event=baseline_start "
                  f"max_publish_id={max_start_id}\n")
        log.flush()
        while time.monotonic_ns() < deadline_ns:
            time.sleep(0.2)

        wasm = read(wasm_path)
        peer = read(peer_path)
        published = ids(PUBLISH_RE, wasm)
        received = ids(RECEIVE_RE, peer)
        echoed = ids(ECHO_RE, peer)
        callbacks = ids(CALLBACK_RE, wasm)
        new_roundtrips = {
            message_id for message_id in published & received & echoed & callbacks
            if message_id > max_start_id
        }
        max_publish_id = max(published) if published else max_start_id
        peer_ready = "event=peer_ready" in peer
        result = "pass" if len(new_roundtrips) >= 10 and peer_ready else "fail"
        finish_utc = utc_now()
        finish_ns = time.monotonic_ns()
        fields = {
            "result": result,
            "start_utc": start_utc,
            "start_mono_ns": start_ns,
            "finish_utc": finish_utc,
            "finish_mono_ns": finish_ns,
            "duration_ns": finish_ns - start_ns,
            "start_max_publish_id": max_start_id,
            "max_publish_id": max_publish_id,
            "new_roundtrip_count": len(new_roundtrips),
            "new_roundtrip_ids": ",".join(map(str, sorted(new_roundtrips))),
            "prior_gate_ids": ",".join(map(str, sorted(gate_ids))),
            "peer_ready": str(peer_ready).lower(),
        }
        for key, value in fields.items():
            log.write(f"{TAG} utc={finish_utc} mono_ns={finish_ns} event=baseline_result "
                      f"{key}={value}\n")
        log.flush()
    status_path.write_text("".join(f"{key}={value}\n" for key, value in fields.items()),
                           encoding="utf-8")
    print(f"{TAG} event=baseline_result result={result} "
          f"new_roundtrip_count={len(new_roundtrips)} max_publish_id={max_publish_id}",
          flush=True)
    return 0 if result == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
