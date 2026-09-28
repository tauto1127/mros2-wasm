#!/usr/bin/env python3
"""Summarize run-40 SEDP traces, passive RTPS frames, and gate IDs."""

from datetime import datetime
from pathlib import Path
import json
import re


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
TRACE_RE = re.compile(
    r"\[SEDP-RACE\]\s+seq=(\d+)\s+mono_ns=(\d+)\s+event=([A-Za-z0-9_]+)(?:\s+(.*))?"
)
FIELD_RE = re.compile(r"(?<!\S)([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
HOST_UTC_RE = re.compile(r"\bhost_utc=([^\s]+)")
HOST_MONO_RE = re.compile(r"\bhost_mono_ns=(\d+)")
COLLECTOR_PREFIX_RE = re.compile(
    r"^\[SEDP-RACE-RUN40\] host_utc=[^\s]+ host_mono_ns=\d+ phase=\w+ container_pid=\d+ $"
)
SEDP_WRITERS = {"000003c2", "000004c2"}


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def status_file(path):
    values = {}
    for line in read(path).splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def iso(value):
    return datetime.fromisoformat(value)


def trace_events():
    events = []
    for line_number, line in enumerate(read(RAW / "wasm-checkpoint.log").splitlines(), 1):
        match = TRACE_RE.search(line)
        if not match:
            continue
        fields = dict(FIELD_RE.findall(match.group(4) or ""))
        host_mono = HOST_MONO_RE.search(line)
        host_utc = HOST_UTC_RE.search(line)
        marker = line.find("[SEDP-RACE]")
        prefix_before_event = line[:marker] if marker >= 0 else ""
        events.append({
            "seq": int(match.group(1)),
            "mono_ns": int(match.group(2)),
            "event": match.group(3),
            "fields": fields,
            "host_mono_ns": int(host_mono.group(1)) if host_mono else None,
            "host_utc": host_utc.group(1) if host_utc else None,
            "source_line": line_number,
            "line_had_prefix_interleave": not bool(COLLECTOR_PREFIX_RE.fullmatch(prefix_before_event)),
        })
    return events


def gate_records():
    records = {"complete": [], "incomplete": []}
    for line in read(RAW / "roundtrip-gate.log").splitlines():
        for name in records:
            marker = f"event={name}_roundtrip " if name == "complete" else "event=incomplete_publish "
            if marker not in line:
                continue
            payload = line.split(marker, 1)[1]
            records[name].append(json.loads(payload))
    return records


def frame_counts(start_utc, finish_utc):
    counts = {
        "wasm_to_peer_sedp_data_frames": 0,
        "wasm_to_peer_sedp_data_submessages": 0,
        "wasm_to_peer_sedp_heartbeat_frames": 0,
        "peer_to_wasm_sedp_data_frames": 0,
        "peer_to_wasm_sedp_data_submessages": 0,
        "peer_to_wasm_sedp_heartbeat_frames": 0,
        "wasm_to_peer_user_data_frames": 0,
        "wasm_to_peer_user_data_submessages": 0,
        "peer_to_wasm_user_data_frames": 0,
        "peer_to_wasm_user_data_submessages": 0,
        "rtps_frames_in_gate_window": 0,
    }
    for line in read(RAW / "peer-wire.jsonl").splitlines():
        item = json.loads(line)
        if item.get("event") != "rtps_udp_frame":
            continue
        stamp = iso(item["utc"])
        if stamp < start_utc or stamp > finish_utc:
            continue
        src, dst = item.get("src_ip"), item.get("dst_ip")
        if (src, dst) not in (("172.18.0.3", "172.18.0.5"), ("172.18.0.5", "172.18.0.3")):
            continue
        counts["rtps_frames_in_gate_window"] += 1
        direction = "wasm_to_peer" if src == "172.18.0.3" else "peer_to_wasm"
        ids = item.get("submessage_ids", [])
        ports = {item.get("src_port"), item.get("dst_port")}
        data_entities = item.get("data_entities", [])
        meta_data_count = sum(1 for entity in data_entities
                              if entity.get("writer_id", "").lower() in SEDP_WRITERS)
        user_data_count = sum(1 for entity in data_entities
                              if entity.get("writer_id", "").lower() not in SEDP_WRITERS)
        if 7410 in ports and meta_data_count:
            counts[f"{direction}_sedp_data_frames"] += 1
            counts[f"{direction}_sedp_data_submessages"] += meta_data_count
        if 7410 in ports and "0x07" in ids:
            counts[f"{direction}_sedp_heartbeat_frames"] += 1
        if 7411 in ports and user_data_count:
            counts[f"{direction}_user_data_frames"] += 1
            counts[f"{direction}_user_data_submessages"] += user_data_count
    return counts


def early_consumptions(events):
    changes = [event for event in events if event["event"] == "change_created"]
    exits = [event for event in events if event["event"] == "progress_exit"]
    proxies = [event for event in events if event["event"] == "proxy_added"]
    findings = []
    role_to_writer = {"publication": "sedp_publications", "subscription": "sedp_subscriptions"}
    for change in changes:
        writer = role_to_writer.get(change["fields"].get("role"))
        seq = change["fields"].get("sequence")
        consume = next((event for event in exits
                        if event["fields"].get("writer") == writer
                        and event["fields"].get("next_before") == seq
                        and event["fields"].get("proxies_empty_before") == "1"
                        and event["fields"].get("send_attempted") == "0"
                        and event["seq"] > change["seq"]), None)
        proxy = next((event for event in proxies
                      if event["fields"].get("writer") == writer
                      and event["fields"].get("add_success") == "1"
                      and consume and event["seq"] > consume["seq"]), None)
        findings.append({
            "role": change["fields"].get("role"),
            "topic": change["fields"].get("topic"),
            "change_seq": seq,
            "change_trace_seq": change["seq"],
            "consumed_without_proxy": consume is not None,
            "progress_trace_seq": consume["seq"] if consume else None,
            "next_after": consume["fields"].get("next_after") if consume else None,
            "proxy_added_later": proxy is not None,
            "proxy_trace_seq": proxy["seq"] if proxy else None,
        })
    return findings


def main():
    gate = status_file(RAW / "roundtrip-gate.status")
    wasm_log = read(RAW / "wasm-checkpoint.log")
    verified_match = next((HOST_UTC_RE.search(line) for line in wasm_log.splitlines()
                           if "event=process_verified" in line and HOST_UTC_RE.search(line)), None)
    start_utc = iso(verified_match.group(1)) if verified_match else iso(gate["start_utc"])
    finish_utc = iso(gate["finish_utc"])
    events = trace_events()
    findings = early_consumptions(events)
    counts = frame_counts(start_utc, finish_utc)
    ids = gate_records()
    result = {
        "run": "run-40",
        "pre_gate": gate.get("result"),
        "complete_roundtrips": int(gate.get("complete_roundtrips", "0")),
        "complete_ids": [item.get("id") for item in ids["complete"]],
        "incomplete_ids_and_stages": [
            {"id": item.get("id"), "last_stage": item.get("last_stage")}
            for item in ids["incomplete"]
        ],
        "trace_event_count": len(events),
        "trace_had_interleaved_prefix": any(item["line_had_prefix_interleave"] for item in events),
        "early_consumptions": findings,
        "wire_counts_in_pre_gate_window": counts,
        "wire_window_utc": {"start": start_utc.isoformat(), "finish": finish_utc.isoformat()},
    }
    (RAW / "sedp-race-trace.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in events), encoding="utf-8")
    (RAW / "run-analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    trace_lines = [
        "# run-40 application ID/body analysis",
        "",
        f"Pre-C/R gate: `{gate.get('result')}`, {gate.get('complete_roundtrips')} complete ordered round trips.",
        "",
        "Accepted ID/body pairs:",
        "",
    ]
    for item in ids["complete"]:
        trace_lines.append(f"- ID `{item.get('id')}`: `{item.get('payload')}` ({item.get('order')}).")
    trace_lines.extend(["", "Incomplete publishes (ID and last observed stage):", ""])
    for item in ids["incomplete"]:
        trace_lines.append(
            f"- ID `{item.get('id')}`: `{item.get('payload')}`; last stage `{item.get('last_stage')}`."
        )
    (RAW / "roundtrip-id-analysis.md").write_text("\n".join(trace_lines) + "\n", encoding="utf-8")

    wire_lines = [
        "# run-40 passive wire counts",
        "",
        f"Window: Wasm process verification through pre-gate completion (`{start_utc.isoformat()}` to `{finish_utc.isoformat()}` UTC).",
        "Counts are captured DATA submessages or frames containing a HEARTBEAT submessage; DATA is identified by the RTPS builtin SEDP writer entity IDs on metatraffic port 7410, and non-builtin writer IDs on user port 7411.",
        "",
    ]
    wire_lines.extend(f"- `{key}`: {value}" for key, value in counts.items())
    (RAW / "wire-counts.md").write_text("\n".join(wire_lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
