#!/usr/bin/env python3
"""Passive AF_PACKET observer for RTPS UDP frames on the ROS peer interface."""

import datetime
import ipaddress
import json
import signal
import socket
import struct
import sys


TAG = "[SEDP-HB-RUN62]"
INTERFACE = "eth0"
RTPS_PORTS = {7400, 7401, 7410, 7411}
running = True


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def emit(out, event, **fields):
    out.write(json.dumps({"event": event, "utc": utc_now(), **fields}, sort_keys=True) + "\n")
    out.flush()


def decode_sequence_number(body, offset, byte_order):
    if offset + 8 > len(body):
        return None
    high = struct.unpack(byte_order + "i", body[offset:offset + 4])[0]
    low = struct.unpack(byte_order + "I", body[offset + 4:offset + 8])[0]
    return {"high": high, "low": low, "text": f"{high}:{low}"}


def decode_rtps(payload):
    result = {"rtps_magic": payload[:4] == b"RTPS"}
    if not result["rtps_magic"] or len(payload) < 20:
        return result

    result["rtps_version"] = payload[4:6].hex()
    result["vendor_id"] = payload[6:8].hex()
    result["guid_prefix"] = payload[8:20].hex()
    submessages = []
    data_entities = []
    heartbeats = []
    acknacks = []
    offset = 20
    while offset + 4 <= len(payload):
        submessage_id = payload[offset]
        flags = payload[offset + 1]
        byte_order = "<" if flags & 1 else ">"
        submessage_length = struct.unpack(
            byte_order + "H", payload[offset + 2:offset + 4]
        )[0]
        submessages.append(f"0x{submessage_id:02x}")
        body_start = offset + 4
        body_end = len(payload) if submessage_length == 0 else body_start + submessage_length
        if body_end > len(payload):
            break
        body = payload[body_start:body_end]

        # DATA: extraFlags(2), octetsToInlineQos(2), readerId(4),
        # writerId(4), writerSN(8), ...
        if submessage_id == 0x15 and len(body) >= 20:
            data_entities.append({
                "reader_id": body[4:8].hex(),
                "writer_id": body[8:12].hex(),
                "writer_sn": decode_sequence_number(body, 12, byte_order),
            })

        # HEARTBEAT: readerId(4), writerId(4), firstSN(8), lastSN(8), count(4)
        elif submessage_id == 0x07 and len(body) >= 28:
            heartbeats.append({
                "reader_id": body[0:4].hex(),
                "writer_id": body[4:8].hex(),
                "first_sn": decode_sequence_number(body, 8, byte_order),
                "last_sn": decode_sequence_number(body, 16, byte_order),
                "count": struct.unpack(byte_order + "I", body[24:28])[0],
            })

        # ACKNACK: readerId(4), writerId(4), baseSN(8), numBits(4),
        # bitmap(ceil(numBits/32)*4), count(4)
        elif submessage_id == 0x06 and len(body) >= 24:
            num_bits = struct.unpack(byte_order + "I", body[16:20])[0]
            word_count = (num_bits + 31) // 32
            count_offset = 20 + word_count * 4
            bitmap = []
            if count_offset + 4 <= len(body):
                for index in range(word_count):
                    word_offset = 20 + index * 4
                    bitmap.append(
                        f"0x{struct.unpack(byte_order + 'I', body[word_offset:word_offset + 4])[0]:08x}"
                    )
                count = struct.unpack(
                    byte_order + "I", body[count_offset:count_offset + 4]
                )[0]
            else:
                count = None
            acknacks.append({
                "reader_id": body[0:4].hex(),
                "writer_id": body[4:8].hex(),
                "base_sn": decode_sequence_number(body, 8, byte_order),
                "num_bits": num_bits,
                "bitmap": bitmap,
                "count": count,
            })

        if submessage_length == 0:
            break
        offset = body_end

    result["submessage_ids"] = submessages
    if data_entities:
        result["data_entities"] = data_entities
    if heartbeats:
        result["heartbeats"] = heartbeats
    if acknacks:
        result["acknacks"] = acknacks
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
