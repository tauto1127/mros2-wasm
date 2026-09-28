#!/usr/bin/env python3
"""Pass the pre-C/R gate only after ten distinct native-mROS2 round trips."""

from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time


TAG = "[CR-RERUN-20260927-R04]"
GATE_NS = 60_000_000_000
VERIFY_WAIT_NS = 30_000_000_000
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+)")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+)")
CALLBACK_RE = re.compile(r"APP callback topic=/to_stm id=(\d+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def ids(pattern, content):
    return {int(value) for value in pattern.findall(content)}


def main():
    raw = Path(__file__).resolve().parent / "raw"
    wasm_log = raw / "wasm-checkpoint.log"
    peer_log = raw / "peer-native.log"
    marker = raw / "gate-pass.ok"
    log_path = raw / "roundtrip-gate.log"
    status_path = raw / "roundtrip-gate.status"
    for path in (marker, log_path, status_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing artifact: {path}")

    start_ns = time.monotonic_ns()
    verified_ns = None
    with log_path.open("x", encoding="utf-8") as log:
        def record(event, **fields):
            details = " ".join(f"{key}={value!r}" for key, value in fields.items())
            line = (f"{TAG} utc={utc_now()} host_mono_ns={time.monotonic_ns()} "
                    f"event={event} {details}\n")
            log.write(line)
            log.flush()
            print(line, end="", flush=True)

        def finish(result, **fields):
            body = f"result={result}\n" + "".join(
                f"{key}={value}\n" for key, value in fields.items())
            status_path.write_text(body, encoding="utf-8")

        record("gate_start", seconds=60, criterion="10 distinct full message-ID round trips")
        while verified_ns is None:
            content = read_text(wasm_log)
            verified_line = next((line for line in content.splitlines()
                                  if "event=process_verified" in line), None)
            match = re.search(r"\bhost_mono_ns=(\d+)\b", verified_line or "")
            if match:
                verified_ns = int(match.group(1))
                record("process_verified_seen", process_verified_mono_ns=verified_ns,
                       deadline_mono_ns=verified_ns + GATE_NS)
                break
            if (raw / "wasm-checkpoint.status").exists():
                record("collector_exited_before_process_verified")
                finish("collector_exited_before_process_verified")
                return 2
            if time.monotonic_ns() - start_ns >= VERIFY_WAIT_NS:
                record("process_verified_not_seen_timeout")
                finish("process_verified_not_seen_timeout")
                return 2
            time.sleep(0.05)

        deadline_ns = verified_ns + GATE_NS
        last_counts = {}
        while time.monotonic_ns() < deadline_ns:
            wasm = read_text(wasm_log)
            peer = read_text(peer_log)
            published = ids(PUBLISH_RE, wasm)
            received = ids(RECEIVE_RE, peer)
            echoed = ids(ECHO_RE, peer)
            callbacks = ids(CALLBACK_RE, wasm)
            roundtrips = published & received & echoed & callbacks
            peer_ready = "event=peer_ready" in peer
            last_counts = {
                "published": len(published),
                "peer_received": len(received),
                "peer_echo_returned": len(echoed),
                "wasm_callbacks": len(callbacks),
                "full_roundtrips": len(roundtrips),
                "peer_ready": peer_ready,
            }
            if peer_ready and len(roundtrips) >= 10:
                marker_ns = time.monotonic_ns()
                with marker.open("x", encoding="utf-8") as marker_file:
                    marker_file.write(
                        f"gate_pass_host_mono_ns={marker_ns}\n"
                        f"distinct_roundtrip_ids={','.join(map(str, sorted(roundtrips)))}\n")
                record("gate_pass", marker_mono_ns=marker_ns,
                       roundtrip_ids=sorted(roundtrips), **last_counts)
                finish("gate_pass", marker_mono_ns=marker_ns,
                       roundtrip_ids=",".join(map(str, sorted(roundtrips))), **last_counts)
                return 0
            time.sleep(0.1)

        record("gate_timeout", **last_counts)
        finish("gate_timeout", **last_counts)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
