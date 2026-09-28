#!/usr/bin/env python3
"""Derive a timestamp-bounded summary from immutable run-06 raw logs."""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re

from run06_common import RAW, utc_now, write_new


PUBLISH = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")
CALLBACK = re.compile(r"APP callback topic=/to_stm id=(\d+)")
RECEIVE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+)")
ECHO = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+)")
TIME = re.compile(r"\b(?:host_utc|utc)=([^\s]+)")


def read(name):
    return (RAW / name).read_text(encoding="utf-8", errors="replace")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def timestamp(line):
    match = TIME.search(line)
    return parse_time(match.group(1)) if match else None


def through(text, start, finish):
    selected = []
    for line in text.splitlines():
        when = timestamp(line)
        if when is not None and start <= when <= finish:
            selected.append(line)
    return "\n".join(selected)


def unique_ids(pattern, text):
    return {int(value) for value in pattern.findall(text)}


def id_summary(values):
    values = sorted(values)
    return {"count": len(values), "min": values[0] if values else None,
            "max": values[-1] if values else None}


def main():
    checkpoint_signal = read("checkpoint-signal.log")
    checkpoint_max = int(re.search(r"checkpoint_max_publish_id=(\d+)", checkpoint_signal).group(1))
    restore_status = read("wasm-restore.status")
    restore_start = parse_time(re.search(r"^start_utc=(.+)$", restore_status, re.MULTILINE).group(1))
    wasm_all = read("wasm-restore.log")
    verified_line = next(line for line in wasm_all.splitlines() if "event=process_verified" in line)
    verified_time = timestamp(verified_line)
    post_gate_log = read("postcr-gate.log")
    timeout_line = next(line for line in post_gate_log.splitlines() if "event=postcr_gate_timeout" in line)
    timeout = timestamp(timeout_line)

    peer_all = read("peer-native.log")
    wasm_window = through(wasm_all, verified_time, timeout)
    peer_window = through(peer_all, verified_time, timeout)
    published = unique_ids(PUBLISH, wasm_window)
    callbacks = unique_ids(CALLBACK, wasm_window)
    received = unique_ids(RECEIVE, peer_window)
    echoed = unique_ids(ECHO, peer_window)
    post_publish = {item for item in published if item > checkpoint_max}
    post_receive = {item for item in received if item > checkpoint_max}
    post_echo = {item for item in echoed if item > checkpoint_max}
    post_callback = {item for item in callbacks if item > checkpoint_max}
    full = post_publish & post_receive & post_echo & post_callback

    restore_end = re.search(
        r"SOCKET_JOURNAL event=restore_end[^\n]*replay_count=(\d+)[^\n]*"
        r"successful_count=(\d+)[^\n]*failure_count=(\d+)[^\n]*"
        r"fallback_count=(\d+)[^\n]*skipped_count=(\d+)[^\n]*"
        r"unknown_count=(\d+)[^\n]*function_return=(-?\d+)", wasm_all,
    )
    dump_end = re.search(
        r"SOCKET_JOURNAL event=dump_end[^\n]*dump_count=(\d+) overflow=(\d+) result=(-?\d+)",
        read("wasm-checkpoint.log"),
    )

    restore_lines = wasm_window.splitlines()
    local_ip_updates = [line for line in restore_lines if "netif_wasm: local ip changed" in line]
    callback_ids = sorted(callbacks)
    recoveries = sorted(set(re.findall(r"UDP_RECV_RECOVERY result=ok.*?local_port=(\d+)", wasm_all)))

    frames = []
    for line in read("peer-wire.jsonl").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        when = parse_time(item["utc"]) if item.get("utc") else None
        if when and verified_time <= when <= timeout and item.get("event") == "rtps_udp_frame":
            frames.append(item)
    data_frames = [item for item in frames if item.get("data_entities")]
    flow_counts = Counter(
        (item.get("src_ip"), item.get("dst_ip"), item.get("dst_port"))
        for item in data_frames
    )
    wasm_to_peer = sum(
        count for (src, dst, port), count in flow_counts.items()
        if src == "172.18.0.6" and dst == "172.18.0.5" and port == 7411
    )
    peer_to_old_ip = sum(
        count for (src, dst, port), count in flow_counts.items()
        if src == "172.18.0.5" and dst == "172.18.0.3" and port == 7411
    )
    peer_to_new_ip = sum(
        count for (src, dst, port), count in flow_counts.items()
        if src == "172.18.0.5" and dst == "172.18.0.6" and port == 7411
    )

    stop_log = read("wasm-restore-stop.log")
    stop_match = re.search(r"^utc=(.+)$", stop_log, re.MULTILINE)
    stop_time = parse_time(stop_match.group(1)) if stop_match else timeout
    peer_after_gate = through(peer_all, timeout, stop_time)
    after_gate_receive = {i for i in unique_ids(RECEIVE, peer_after_gate) if i > checkpoint_max}
    after_gate_echo = {i for i in unique_ids(ECHO, peer_after_gate) if i > checkpoint_max}

    data = {
        "created_utc": utc_now(),
        "gate_window": {
            "restore_process_start_utc": restore_start.isoformat(),
            "restore_process_verified_utc": verified_time.isoformat(),
            "deadline_result_utc": timeout.isoformat(),
            "checkpoint_max_publish_id": checkpoint_max,
            "wasm_publish_ids_after_checkpoint": id_summary(post_publish),
            "peer_receive_ids_after_checkpoint": id_summary(post_receive),
            "peer_echo_ids_after_checkpoint": id_summary(post_echo),
            "wasm_callback_ids_after_checkpoint": sorted(post_callback),
            "complete_roundtrip_ids": sorted(full),
            "verdict": "fail" if len(full) < 10 else "pass",
        },
        "checkpoint": {
            "dump_count": int(dump_end.group(1)) if dump_end else None,
            "overflow": int(dump_end.group(2)) if dump_end else None,
            "result": int(dump_end.group(3)) if dump_end else None,
        },
        "restore": {
            "replay_count": int(restore_end.group(1)) if restore_end else None,
            "successful_count": int(restore_end.group(2)) if restore_end else None,
            "failure_count": int(restore_end.group(3)) if restore_end else None,
            "fallback_count": int(restore_end.group(4)) if restore_end else None,
            "skipped_count": int(restore_end.group(5)) if restore_end else None,
            "unknown_count": int(restore_end.group(6)) if restore_end else None,
            "function_return": int(restore_end.group(7)) if restore_end else None,
            "local_ip_update_lines": local_ip_updates,
            "udp_receive_recovery_ok_ports": recoveries,
            "callback_ids_seen_in_restore_log": callback_ids,
        },
        "wire_during_gate_window": {
            "data_frames_by_source_destination_port": [
                {"source_ip": src, "destination_ip": dst, "destination_port": port, "count": count}
                for (src, dst, port), count in sorted(flow_counts.items())
            ],
            "wasm_172_18_0_6_to_peer_172_18_0_5_port_7411_data_frames": wasm_to_peer,
            "peer_172_18_0_5_to_old_ip_172_18_0_3_port_7411_data_frames": peer_to_old_ip,
            "peer_172_18_0_5_to_new_ip_172_18_0_6_port_7411_data_frames": peer_to_new_ip,
        },
        "post_gate_observation": {
            "from_utc": timeout.isoformat(),
            "stopped_after_utc": stop_time.isoformat(),
            "elapsed_seconds_after_gate_until_stop": round((stop_time - timeout).total_seconds(), 3),
            "additional_peer_receive_ids": id_summary(after_gate_receive),
            "additional_peer_echo_ids": id_summary(after_gate_echo),
            "note": "The same restore process continued during passive boundary inspection after the 90-second gate timed out; no second checkpoint/restore or configuration change occurred.",
        },
    }
    write_new(RAW / "analysis-summary.json", json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
