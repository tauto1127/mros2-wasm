#!/usr/bin/env python3
"""Passive AF_PACKET observer for RTPS UDP frames on the ROS peer interface."""

import datetime
import ipaddress
import json
import signal
import socket
import struct
import sys


TAG = "[CR-DISCOVERY-PROBE-R25]"
INTERFACE = "eth0"
RTPS_PORTS = {7400, 7401, 7410, 7411}
running = True


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def emit(out, event, **fields):
    out.write(json.dumps({"event": event, "utc": utc_now(), **fields}, sort_keys=True) + "\n")
    out.flush()


def decode_rtps(payload):
    result = {"rtps_magic": payload[:4] == b"RTPS"}
    if not result["rtps_magic"] or len(payload) < 20:
        return result

    result["rtps_version"] = payload[4:6].hex()
    result["vendor_id"] = payload[6:8].hex()
    result["guid_prefix"] = payload[8:20].hex()
    submessages = []
    data_entities = []
    offset = 20
    while offset + 4 <= len(payload):
        submessage_id = payload[offset]
        flags = payload[offset + 1]
        byte_order = "<" if flags & 1 else ">"
        submessage_length = struct.unpack(byte_order + "H", payload[offset + 2:offset + 4])[0]
        submessages.append(f"0x{submessage_id:02x}")
        body_start = offset + 4
        body_end = body_start + submessage_length
        if body_end > len(payload):
            break
        if submessage_id == 0x15 and submessage_length >= 20:
            body = payload[body_start:body_end]
            data_entities.append({
                "reader_id": body[4:8].hex(),
                "writer_id": body[8:12].hex(),
            })
        if submessage_length == 0:
            break
        offset = body_end
    result["submessage_ids"] = submessages
    if data_entities:
        result["data_entities"] = data_entities
    return result


def decode_frame(frame):
    if len(frame) < 14:
        return None
    ether_type = struct.unpack("!H", frame[12:14])[0]
    offset = 14
    if ether_type in (0x8100, 0x88A8) and len(frame) >= 18:
        ether_type = struct.unpack("!H", frame[16:18])[0]
        offset = 18
    if ether_type != 0x0800 or len(frame) < offset + 20:
        return None

    ip_header_length = (frame[offset] & 0x0F) * 4
    if ip_header_length < 20 or len(frame) < offset + ip_header_length + 8:
        return None
    if frame[offset + 9] != 17:  # UDP
        return None

    src_ip = str(ipaddress.IPv4Address(frame[offset + 12:offset + 16]))
    dst_ip = str(ipaddress.IPv4Address(frame[offset + 16:offset + 20]))
    udp_offset = offset + ip_header_length
    src_port, dst_port, udp_length = struct.unpack("!HHH", frame[udp_offset:udp_offset + 6])
    if src_port not in RTPS_PORTS and dst_port not in RTPS_PORTS:
        return None
    payload_start = udp_offset + 8
    payload_end = min(len(frame), udp_offset + udp_length)
    payload = frame[payload_start:payload_end]
    return {
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "udp_payload_bytes": len(payload),
        **decode_rtps(payload),
    }


def stop(_signum, _frame):
    global running
    running = False


def main():
    global running
    path = sys.argv[1] if len(sys.argv) > 1 else "/capture/peer-wire.jsonl"
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        sock.bind((INTERFACE, 0))
        sock.settimeout(0.25)
        out = open(path, "x", encoding="utf-8")
    except Exception as error:
        print(f"{TAG} capture_error={type(error).__name__}: {error}", flush=True)
        return 2

    with sock, out:
        emit(out, "capture_ready", interface=INTERFACE, filter_ports=sorted(RTPS_PORTS),
             mode="AF_PACKET/SOCK_RAW; no promiscuous mode; no packet injection")
        print(f"{TAG} capture_ready interface={INTERFACE} path={path}", flush=True)
        while running:
            try:
                frame, _address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as error:
                if running:
                    emit(out, "capture_error", error=f"{type(error).__name__}: {error}")
                    return 3
                break
            event = decode_frame(frame)
            if event is not None:
                emit(out, "rtps_udp_frame", **event)
        emit(out, "capture_stop", reason="signal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
