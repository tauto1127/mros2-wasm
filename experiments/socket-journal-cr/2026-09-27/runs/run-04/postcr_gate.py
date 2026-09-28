#!/usr/bin/env python3
"""Require ten post-restore round trips with IDs greater than checkpoint N."""

from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time


TAG = "[CR-RERUN-20260927-R04]"
GATE_NS = 90_000_000_000
VERIFY_WAIT_NS = 30_000_000_000
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
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("usage: postcr_gate.py MAX_PRE_CR_PUBLISH_ID")
    checkpoint_max = int(sys.argv[1])
    raw = Path(__file__).resolve().parent / "raw"
    wasm_path = raw / "wasm-restore.log"
    peer_path = raw / "peer-native.log"
    log_path = raw / "postcr-gate.log"
    status_path = raw / "postcr-gate.status"
    if log_path.exists() or status_path.exists():
        raise SystemExit("refusing to overwrite an existing post-C/R gate artifact")

    start_ns = time.monotonic_ns()
    with log_path.open("x", encoding="utf-8") as log:
        def record(event, **fields):
            details = " ".join(f"{key}={value!r}" for key, value in fields.items())
            line = (f"{TAG} utc={utc_now()} mono_ns={time.monotonic_ns()} "
                    f"event={event} {details}\n")
            log.write(line)
            log.flush()
            print(line, end="", flush=True)

        record("postcr_gate_start", checkpoint_max=checkpoint_max, deadline_seconds=90)
        verified_ns = None
        while verified_ns is None:
            content = read(wasm_path)
            verified_line = next((line for line in content.splitlines()
                                  if "event=process_verified" in line), None)
            match = re.search(r"\bhost_mono_ns=(\d+)\b", verified_line or "")
            if match:
                verified_ns = int(match.group(1))
                record("restore_process_verified", process_verified_mono_ns=verified_ns,
                       deadline_mono_ns=verified_ns + GATE_NS)
                break
            if (raw / "wasm-restore.status").exists():
                record("restore_collector_exited_before_verification")
                status_path.write_text("result=collector_exit_before_verify\n",
                                       encoding="utf-8")
                return 2
            if time.monotonic_ns() - start_ns >= VERIFY_WAIT_NS:
                record("restore_process_not_verified_timeout")
                status_path.write_text("result=process_not_verified_timeout\n",
                                       encoding="utf-8")
                return 2
            time.sleep(0.05)

        deadline_ns = verified_ns + GATE_NS
        last_counts = {}
        while time.monotonic_ns() < deadline_ns:
            wasm = read(wasm_path)
            peer = read(peer_path)
            published = ids(PUBLISH_RE, wasm)
            received = ids(RECEIVE_RE, peer)
            echoed = ids(ECHO_RE, peer)
            callbacks = ids(CALLBACK_RE, wasm)
            roundtrips = {
                message_id for message_id in published & received & echoed & callbacks
                if message_id > checkpoint_max
            }
            last_counts = {
                "published": len({i for i in published if i > checkpoint_max}),
                "peer_received": len({i for i in received if i > checkpoint_max}),
                "peer_echoed": len({i for i in echoed if i > checkpoint_max}),
                "wasm_callbacks": len({i for i in callbacks if i > checkpoint_max}),
                "full_roundtrips": len(roundtrips),
                "roundtrip_ids": ",".join(map(str, sorted(roundtrips))),
            }
            if "event=peer_ready" in peer and len(roundtrips) >= 10:
                record("postcr_gate_pass", checkpoint_max=checkpoint_max, **last_counts)
                status_path.write_text("result=pass\n" +
                                       f"checkpoint_max={checkpoint_max}\n" +
                                       "".join(f"{k}={v}\n" for k, v in last_counts.items()),
                                       encoding="utf-8")
                return 0
            time.sleep(0.1)

        record("postcr_gate_timeout", checkpoint_max=checkpoint_max, **last_counts)
        status_path.write_text("result=timeout\n" +
                               f"checkpoint_max={checkpoint_max}\n" +
                               "".join(f"{k}={v}\n" for k, v in last_counts.items()),
                               encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
