#!/usr/bin/env python3
"""Require application-level message and ordering evidence for run-08 gates."""

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sys
import time


TAG = "[CR-RERUN-20260928-R08]"
RAW = Path(__file__).resolve().parent / "raw"
PRE_WINDOW_NS = 60_000_000_000
BASELINE_WINDOW_NS = 30_000_000_000
POST_WINDOW_NS = 90_000_000_000
VERIFY_WAIT_NS = 30_000_000_000
HOST_MONO_RE = re.compile(r"\bhost_mono_ns=(\d+)\b")
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+) payload='([^']*)'")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+) payload='([^']*)'")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+) payload='([^']*)'")
CALLBACK_RE = re.compile(r"APP callback topic=/to_stm id=(\d+) payload='([^']*)'")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read(path):
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def process_verified_ns(path):
    for line in read(path).splitlines():
        if "event=process_verified" in line:
            match = HOST_MONO_RE.search(line)
            if match:
                return int(match.group(1))
    return None


def parse_events(content, pattern, kind):
    events = []
    for line_number, line in enumerate(content.splitlines(), 1):
        match = pattern.search(line)
        stamp = HOST_MONO_RE.search(line)
        if match and stamp:
            events.append({"kind": kind, "id": int(match.group(1)),
                           "payload": match.group(2), "mono_ns": int(stamp.group(1)),
                           "line": line_number})
    return events


def full_roundtrips(wasm_text, peer_text, lower_ns, upper_ns, min_id=None):
    publishes = parse_events(wasm_text, PUBLISH_RE, "publish")
    receives = parse_events(peer_text, RECEIVE_RE, "receive")
    echoes = parse_events(peer_text, ECHO_RE, "echo")
    callbacks = parse_events(wasm_text, CALLBACK_RE, "callback")

    def in_window(event):
        return lower_ns <= event["mono_ns"] <= upper_ns

    for group in (publishes, receives, echoes, callbacks):
        group[:] = [event for event in group if in_window(event)]

    by_id = {}
    for publish in sorted(publishes, key=lambda event: event["mono_ns"]):
        message_id = publish["id"]
        if min_id is not None and message_id <= min_id:
            continue
        payload = publish["payload"]
        receive = next((event for event in receives
                        if event["id"] == message_id and event["payload"] == payload
                        and event["mono_ns"] > publish["mono_ns"]), None)
        echo = next((event for event in echoes
                     if receive and event["id"] == message_id
                     and event["payload"] == payload
                     and event["mono_ns"] > receive["mono_ns"]), None)
        callback = next((event for event in callbacks
                         if echo and event["id"] == message_id
                         and event["payload"] == payload
                         and event["mono_ns"] > echo["mono_ns"]), None)
        last_stage = ("wasm_publish" if receive is None else
                      "native_receive" if echo is None else
                      "native_echo_publish_return" if callback is None else
                      "wasm_callback")
        item = {"id": message_id, "payload": payload, "last_stage": last_stage,
                "publish_mono_ns": publish["mono_ns"]}
        if receive:
            item["receive_mono_ns"] = receive["mono_ns"]
        if echo:
            item["echo_mono_ns"] = echo["mono_ns"]
        if callback:
            item["callback_mono_ns"] = callback["mono_ns"]
        if callback:
            by_id[message_id] = item
        else:
            by_id.setdefault(f"incomplete-{message_id}", item)
    complete = [item for key, item in by_id.items() if isinstance(key, int)]
    complete.sort(key=lambda item: (item["publish_mono_ns"], item["id"]))
    incomplete = [item for key, item in by_id.items() if not isinstance(key, int)]
    incomplete.sort(key=lambda item: (item["publish_mono_ns"], item["id"]))
    return complete, incomplete, len(publishes), len(receives), len(echoes), len(callbacks)


def write_gate(name, result, start_utc, start_ns, finish_utc, finish_ns,
               roundtrips, incomplete, counts, **extra):
    log_path = RAW / f"{name}.log"
    status_path = RAW / f"{name}.status"
    for path in (log_path, status_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite {path}")
    fields = {
        "result": result,
        "start_utc": start_utc,
        "start_mono_ns": start_ns,
        "finish_utc": finish_utc,
        "finish_mono_ns": finish_ns,
        "duration_ns": finish_ns - start_ns,
        **counts,
        **extra,
    }
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"{TAG} event=gate_result name={name} "
                  f"{json.dumps(fields, ensure_ascii=False, sort_keys=True)}\n")
        for item in roundtrips:
            log.write(f"{TAG} event=complete_roundtrip "
                      f"{json.dumps(item, ensure_ascii=False, sort_keys=True)}\n")
        for item in incomplete:
            log.write(f"{TAG} event=incomplete_publish "
                      f"{json.dumps(item, ensure_ascii=False, sort_keys=True)}\n")
    status_path.write_text("".join(f"{key}={value}\n" for key, value in fields.items())
                           + "complete_ids=" + ",".join(str(item["id"]) for item in roundtrips)
                           + "\n", encoding="utf-8")
    print(f"{TAG} event=gate_result name={name} result={result} "
          f"complete_count={len(roundtrips)} ids="
          f"{','.join(str(item['id']) for item in roundtrips)}", flush=True)


def counts_for(wasm, peer, lower_ns, upper_ns, min_id=None):
    full, incomplete, publishes, receives, echoes, callbacks = full_roundtrips(
        wasm, peer, lower_ns, upper_ns, min_id)
    counts = {"publish_events": publishes, "native_receive_events": receives,
              "native_echo_return_events": echoes, "wasm_callback_events": callbacks,
              "complete_roundtrips": len(full), "peer_ready": "event=peer_ready" in peer}
    return full, incomplete, counts


def wait_for_verified(path, status_path, started_ns, wait_limit_ns):
    while True:
        verified_ns = process_verified_ns(path)
        if verified_ns is not None:
            return verified_ns
        if status_path.exists():
            return None
        if time.monotonic_ns() - started_ns >= wait_limit_ns:
            return None
        time.sleep(0.05)


def run_pre():
    name = "roundtrip-gate"
    wasm_path, peer_path = RAW / "wasm-checkpoint.log", RAW / "peer-native.log"
    start_utc, start_ns = utc_now(), time.monotonic_ns()
    verified_ns = wait_for_verified(wasm_path, RAW / "wasm-checkpoint.status",
                                    start_ns, VERIFY_WAIT_NS)
    if verified_ns is None:
        write_gate(name, "process_verification_failed", start_utc, start_ns,
                   utc_now(), time.monotonic_ns(), [], [], {},
                   detail="checkpoint iwasm process was not verified")
        return 2
    deadline = verified_ns + PRE_WINDOW_NS
    while time.monotonic_ns() < deadline:
        full, incomplete, counts = counts_for(read(wasm_path), read(peer_path),
                                               verified_ns, time.monotonic_ns())
        if counts["peer_ready"] and len(full) >= 10:
            break
        time.sleep(0.1)
    result = "pass" if counts.get("peer_ready") and len(full) >= 10 else "timeout"
    write_gate(name, result, start_utc, verified_ns, utc_now(), time.monotonic_ns(),
               full, incomplete, counts, deadline_mono_ns=deadline,
               criterion="10 distinct full ID+payload round trips in 60 seconds")
    if result == "pass":
        (RAW / "gate-pass.ok").write_text(
            f"gate_pass_host_mono_ns={time.monotonic_ns()}\n"
            f"distinct_roundtrip_ids={','.join(str(item['id']) for item in full)}\n",
            encoding="utf-8")
        return 0
    return 1


def run_baseline():
    name = "no-cr-baseline"
    marker = RAW / "gate-pass.ok"
    if not marker.is_file():
        raise SystemExit("pre-C/R evidence gate did not pass; refusing baseline/C/R continuation")
    wasm_path, peer_path = RAW / "wasm-checkpoint.log", RAW / "peer-native.log"
    wasm_start = read(wasm_path)
    published_start = parse_events(wasm_start, PUBLISH_RE, "publish")
    if not published_start:
        raise SystemExit("no Wasm publish events at baseline start")
    max_start_id = max(event["id"] for event in published_start)
    start_utc, start_ns = utc_now(), time.monotonic_ns()
    deadline = start_ns + BASELINE_WINDOW_NS
    while time.monotonic_ns() < deadline:
        time.sleep(min(0.25, max(0, deadline - time.monotonic_ns()) / 1e9))
    finish_ns, finish_utc = time.monotonic_ns(), utc_now()
    full, incomplete, counts = counts_for(read(wasm_path), read(peer_path),
                                           start_ns, finish_ns, max_start_id)
    result = "pass" if counts["peer_ready"] and len(full) >= 10 else "fail"
    write_gate(name, result, start_utc, start_ns, finish_utc, finish_ns,
               full, incomplete, counts, start_max_publish_id=max_start_id,
               criterion="10 distinct new full ID+payload round trips in 30 seconds")
    return 0 if result == "pass" else 1


def run_post(checkpoint_max):
    name = "postcr-gate"
    wasm_path, peer_path = RAW / "wasm-restore.log", RAW / "peer-native.log"
    gate_start_utc, gate_start_ns = utc_now(), time.monotonic_ns()
    verified_ns = wait_for_verified(wasm_path, RAW / "wasm-restore.status",
                                    gate_start_ns, VERIFY_WAIT_NS)
    if verified_ns is None:
        write_gate(name, "restore_process_verification_failed", gate_start_utc,
                   gate_start_ns, utc_now(), time.monotonic_ns(), [], [], {},
                   checkpoint_max=checkpoint_max)
        return 2
    deadline = verified_ns + POST_WINDOW_NS
    while time.monotonic_ns() < deadline:
        full, incomplete, counts = counts_for(read(wasm_path), read(peer_path),
                                               verified_ns, time.monotonic_ns(),
                                               checkpoint_max)
        if counts["peer_ready"] and len(full) >= 10:
            break
        time.sleep(0.1)
    result = "pass" if counts.get("peer_ready") and len(full) >= 10 else "timeout"
    write_gate(name, result, gate_start_utc, verified_ns, utc_now(),
               time.monotonic_ns(), full, incomplete, counts,
               checkpoint_max=checkpoint_max, deadline_mono_ns=deadline,
               criterion="10 distinct post-restore Wasm publish IDs > N with matching payloads and ordered callbacks within 90 seconds")
    return 0 if result == "pass" else 1


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: roundtrip_evidence_gate.py pre|baseline|post [CHECKPOINT_MAX]")
    mode = sys.argv[1]
    if mode == "pre" and len(sys.argv) == 2:
        return run_pre()
    if mode == "baseline" and len(sys.argv) == 2:
        return run_baseline()
    if mode == "post" and len(sys.argv) == 3 and sys.argv[2].isdigit():
        return run_post(int(sys.argv[2]))
    raise SystemExit("usage: roundtrip_evidence_gate.py pre|baseline|post [CHECKPOINT_MAX]")


if __name__ == "__main__":
    raise SystemExit(main())
