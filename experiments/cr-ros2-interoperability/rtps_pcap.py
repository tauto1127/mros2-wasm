"""Observation-only RTPS classifier for the ROS 2 checkpoint/restore captures.

The parser reads classic pcap (tcpdump -w) and does not send or modify traffic.
mROS 2 frames are recognized by vendor id {13, 37} from embeddedRTPS Config.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field


PCAP_MAGIC = 0xA1B2C3D4
PCAP_MAGIC_NS = 0xA1B23C4D
LINKTYPE_ETHERNET = 1
LINKTYPE_LINUX_SLL = 113

MROS2_VENDOR = (13, 37)
SUBMSG_ACKNACK = 0x06
SUBMSG_HEARTBEAT = 0x07
SUBMSG_INFO_TS = 0x09
SUBMSG_INFO_DST = 0x0E
SUBMSG_DATA = 0x15
SUBMSG_DATA_FRAG = 0x16

PID_SENTINEL = 0x0001
PID_TOPIC_NAME = 0x0005
PID_TYPE_NAME = 0x0007
PID_UNICAST_LOCATOR = 0x002F
PID_DEFAULT_UNICAST_LOCATOR = 0x0031
PID_METATRAFFIC_UNICAST_LOCATOR = 0x0032
PID_METATRAFFIC_MULTICAST_LOCATOR = 0x0033
PID_PARTICIPANT_GUID = 0x0050
PID_ENDPOINT_GUID = 0x005A

SPDP_WRITER = "000100c2"
SEDP_PUB_WRITER = "000003c2"
SEDP_SUB_WRITER = "000004c2"


@dataclass
class RtpsRecord:
    ts: float
    src: str
    dst: str
    sport: int
    dport: int
    vendor: str
    guid_prefix: str
    submessage: str
    writer_id: str = ""
    reader_id: str = ""
    topics: list = field(default_factory=list)
    types: list = field(default_factory=list)
    endpoint_guids: list = field(default_factory=list)
    participant_guids: list = field(default_factory=list)
    unicast_locators: list = field(default_factory=list)
    default_unicast_locators: list = field(default_factory=list)
    metatraffic_unicast_locators: list = field(default_factory=list)
    metatraffic_multicast_locators: list = field(default_factory=list)


def _locator(blob, little):
    if len(blob) < 24:
        return None
    order = "<" if little else ">"
    kind, port = struct.unpack_from(order + "iI", blob, 0)
    address = blob[8:24]
    if kind == 1:
        ip = socket.inet_ntoa(address[12:16])
    else:
        ip = address.hex()
    return {"kind": kind, "ip": ip, "port": port}


def _cstring(blob, little):
    if len(blob) < 4:
        return ""
    order = "<" if little else ">"
    length = struct.unpack_from(order + "I", blob, 0)[0]
    if length <= 0 or 4 + length > len(blob) + 8:
        raw = blob[4:]
    else:
        raw = blob[4:4 + length]
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _empty_params():
    return {
        "topics": [],
        "types": [],
        "endpoint_guids": [],
        "participant_guids": [],
        "unicast_locators": [],
        "default_unicast_locators": [],
        "metatraffic_unicast_locators": [],
        "metatraffic_multicast_locators": [],
    }


def _merge_params(destination, source):
    for key, value in source.items():
        destination.setdefault(key, []).extend(value)


def _parameters(payload, little):
    found, _used = _parameters_and_size(payload, little)
    return found


def _parameters_and_size(payload, little):
    found = _empty_params()
    if len(payload) < 4:
        return found, 0
    encapsulation = payload[:2]
    body_little = encapsulation == b"\x00\x03" or (encapsulation != b"\x00\x02" and little)
    order = "<" if body_little else ">"
    offset = 4
    while offset + 4 <= len(payload):
        pid, length = struct.unpack_from(order + "HH", payload, offset)
        offset += 4
        if pid == PID_SENTINEL:
            break
        value = payload[offset:offset + length]
        offset += length
        if pid == PID_TOPIC_NAME:
            found["topics"].append(_cstring(value, body_little))
        elif pid == PID_TYPE_NAME:
            found["types"].append(_cstring(value, body_little))
        elif pid in (PID_ENDPOINT_GUID, PID_PARTICIPANT_GUID) and len(value) >= 16:
            guid = value[:16].hex()
            key = "endpoint_guids" if pid == PID_ENDPOINT_GUID else "participant_guids"
            found[key].append(guid)
        elif pid == PID_UNICAST_LOCATOR:
            item = _locator(value, body_little)
            if item:
                found["unicast_locators"].append(item)
        elif pid == PID_DEFAULT_UNICAST_LOCATOR:
            item = _locator(value, body_little)
            if item:
                found["default_unicast_locators"].append(item)
        elif pid == PID_METATRAFFIC_UNICAST_LOCATOR:
            item = _locator(value, body_little)
            if item:
                found["metatraffic_unicast_locators"].append(item)
        elif pid == PID_METATRAFFIC_MULTICAST_LOCATOR:
            item = _locator(value, body_little)
            if item:
                found["metatraffic_multicast_locators"].append(item)
    return found, offset


def _submessages(packet):
    if len(packet) < 20 or packet[:4] != b"RTPS":
        return None
    vendor = (packet[6], packet[7])
    guid_prefix = packet[8:20].hex()
    records = []
    offset = 20
    while offset + 4 <= len(packet):
        sub_id = packet[offset]
        flags = packet[offset + 1]
        little = bool(flags & 0x01)
        order = "<" if little else ">"
        octets = struct.unpack_from(order + "H", packet, offset + 2)[0]
        start = offset + 4
        end = len(packet) if octets == 0 else min(len(packet), start + octets)
        body = packet[start:end]
        name = {
            SUBMSG_ACKNACK: "ACKNACK",
            SUBMSG_HEARTBEAT: "HEARTBEAT",
            SUBMSG_INFO_TS: "INFO_TS",
            SUBMSG_INFO_DST: "INFO_DST",
            SUBMSG_DATA: "DATA",
            SUBMSG_DATA_FRAG: "DATA_FRAG",
        }.get(sub_id, f"0x{sub_id:02x}")
        item = {
            "submessage": name,
            "vendor": f"{vendor[0]:02x}{vendor[1]:02x}",
            "guid_prefix": guid_prefix,
            "writer_id": "",
            "reader_id": "",
        }
        if sub_id in (SUBMSG_DATA, SUBMSG_DATA_FRAG) and len(body) >= 20:
            extra_flags, qos_octets = struct.unpack_from(order + "HH", body, 0)
            del extra_flags
            reader_id = body[4:8].hex()
            writer_id = body[8:12].hex()
            item["reader_id"] = reader_id
            item["writer_id"] = writer_id
            qos_at = 4 + qos_octets
            data_flag = bool(flags & 0x04)
            inline_flag = bool(flags & 0x02)
            found = _empty_params()
            cursor = qos_at
            if inline_flag and cursor <= len(body):
                inline, used = _parameters_and_size(body[cursor:], little)
                _merge_params(found, inline)
                cursor += used
            if data_flag and cursor <= len(body):
                _merge_params(found, _parameters(body[cursor:], little))
            item.update(found)
        if name in ("DATA", "DATA_FRAG", "HEARTBEAT", "ACKNACK"):
            records.append(item)
        if octets == 0:
            break
        offset = end
    header = {
        "vendor": f"{vendor[0]:02x}{vendor[1]:02x}",
        "guid_prefix": guid_prefix,
        "mros2": vendor == MROS2_VENDOR,
    }
    return header, records


def iter_pcap(blob):
    if len(blob) < 24:
        return
    magic = struct.unpack_from("<I", blob, 0)[0]
    if magic not in (PCAP_MAGIC, PCAP_MAGIC_NS):
        return
    endian = "<"
    linktype = struct.unpack_from(endian + "I", blob, 20)[0]
    divisor = 1_000_000_000 if magic == PCAP_MAGIC_NS else 1_000_000
    offset = 24
    while offset + 16 <= len(blob):
        ts_sec, ts_frac, incl, _orig = struct.unpack_from(endian + "IIII", blob, offset)
        offset += 16
        frame = blob[offset:offset + incl]
        offset += incl
        parsed = _ipv4_udp(frame, linktype)
        if parsed is None:
            continue
        src, dst, sport, dport, payload = parsed
        sub = _submessages(payload)
        if sub is None:
            continue
        _header, records = sub
        for record in records:
            yield RtpsRecord(
                ts=ts_sec + ts_frac / divisor,
                src=src,
                dst=dst,
                sport=sport,
                dport=dport,
                vendor=record["vendor"],
                guid_prefix=record["guid_prefix"],
                submessage=record["submessage"],
                writer_id=record.get("writer_id", ""),
                reader_id=record.get("reader_id", ""),
                topics=record.get("topics", []),
                types=record.get("types", []),
                endpoint_guids=record.get("endpoint_guids", []),
                participant_guids=record.get("participant_guids", []),
                unicast_locators=record.get("unicast_locators", []),
                default_unicast_locators=record.get("default_unicast_locators", []),
                metatraffic_unicast_locators=record.get("metatraffic_unicast_locators", []),
                metatraffic_multicast_locators=record.get("metatraffic_multicast_locators", []),
            )


def _ipv4_udp(frame, linktype):
    if linktype == LINKTYPE_ETHERNET:
        if len(frame) < 14:
            return None
        ethertype = struct.unpack_from("!H", frame, 12)[0]
        offset = 14
        if ethertype == 0x8100 and len(frame) >= 18:
            ethertype = struct.unpack_from("!H", frame, 16)[0]
            offset = 18
        if ethertype != 0x0800:
            return None
    elif linktype == LINKTYPE_LINUX_SLL:
        if len(frame) < 16:
            return None
        protocol = struct.unpack_from("!H", frame, 14)[0]
        if protocol != 0x0800:
            return None
        offset = 16
    else:
        return None
    ip = frame[offset:]
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    header_len = (ip[0] & 0x0F) * 4
    if ip[9] != 17 or len(ip) < header_len + 8:
        return None
    src = socket.inet_ntoa(ip[12:16])
    dst = socket.inet_ntoa(ip[16:20])
    sport, dport = struct.unpack_from("!HH", ip, header_len)
    return src, dst, sport, dport, ip[header_len + 8:]


def _ips(items):
    return sorted({item["ip"] for item in items if item.get("kind") == 1})


def _compact(record):
    return {
        "ts": record.ts,
        "src": record.src,
        "dst": record.dst,
        "sport": record.sport,
        "dport": record.dport,
        "vendor": record.vendor,
        "guid_prefix": record.guid_prefix,
        "writer_id": record.writer_id,
        "topics": record.topics,
        "unicast": _ips(record.unicast_locators),
        "default_unicast": _ips(record.default_unicast_locators),
        "metatraffic_unicast": _ips(record.metatraffic_unicast_locators),
        "participant_guids": record.participant_guids,
        "endpoint_guids": record.endpoint_guids,
    }


def summarize(blob, *, checkpoint_epoch, restore_epoch, mode):
    rows = list(iter_pcap(blob))
    mros = [row for row in rows if row.vendor == "0d25"]
    before = [row for row in mros if checkpoint_epoch is None or row.ts <= checkpoint_epoch]
    after = [row for row in mros if restore_epoch is None or row.ts >= restore_epoch]
    pre_spdp = [row for row in before if row.writer_id == SPDP_WRITER]
    post_spdp = [row for row in after if row.writer_id == SPDP_WRITER]
    pre_prefixes = sorted({row.guid_prefix for row in before})
    post_prefixes = sorted({row.guid_prefix for row in after})
    post_src = sorted({row.src for row in after})
    expected_src = "172.18.0.3" if mode in ("control", "same") else "172.18.0.6"

    def sedp(rows_in, writer):
        return [_compact(row) for row in rows_in if row.writer_id == writer]

    def user_to(src_ip):
        hits = [
            row for row in rows
            if row.submessage == "DATA"
            and row.writer_id not in (SPDP_WRITER, SEDP_PUB_WRITER, SEDP_SUB_WRITER)
            and row.dst == src_ip
            and (restore_epoch is None or row.ts >= restore_epoch)
        ]
        return sorted({(row.src, row.dst, row.dport) for row in hits})

    post_spdp_from_expected = [
        row for row in post_spdp if row.src == expected_src
    ]
    post_default_ips = sorted({
        ip
        for row in post_spdp_from_expected
        for ip in _ips(row.default_unicast_locators)
    })
    post_meta_ips = sorted({
        ip
        for row in post_spdp_from_expected
        for ip in _ips(row.metatraffic_unicast_locators)
    })
    post_sedp = [
        row for row in after
        if row.writer_id in (SEDP_PUB_WRITER, SEDP_SUB_WRITER) and row.src == expected_src
    ]
    post_sedp_ips = sorted({
        ip for row in post_sedp for ip in _ips(row.unicast_locators)
    })
    summary = {
        "frames": len(rows),
        "mros2_frames": len(mros),
        "pre_guid_prefixes": pre_prefixes,
        "post_guid_prefixes": post_prefixes,
        "guid_continuity": bool(set(pre_prefixes) & set(post_prefixes)) if mode != "control" else None,
        "post_mros2_sources": post_src,
        "expected_post_source": expected_src,
        "post_spdp_count": len(post_spdp_from_expected),
        "post_spdp_default_ips": post_default_ips,
        "post_spdp_metatraffic_ips": post_meta_ips,
        "post_sedp_unicast_ips": post_sedp_ips,
        "pre_spdp_sample": [_compact(row) for row in pre_spdp[:3]],
        "post_spdp_sample": [_compact(row) for row in post_spdp_from_expected[:6]],
        "post_sedp_pub_sample": sedp(after, SEDP_PUB_WRITER)[:6],
        "post_sedp_sub_sample": sedp(after, SEDP_SUB_WRITER)[:6],
        "post_user_data_toward_expected_source": [
            {"src": src, "dst": dst, "dport": dport}
            for src, dst, dport in user_to(expected_src)
        ],
        "post_user_data_toward_old_source": [
            {"src": src, "dst": dst, "dport": dport}
            for src, dst, dport in user_to("172.18.0.3")
        ] if mode == "changed" else [],
        "submessage_counts": {},
    }
    counts = summary["submessage_counts"]
    for row in rows:
        counts[row.submessage] = counts.get(row.submessage, 0) + 1
    summary["classification"] = classify(summary, mode)
    return summary


def classify(summary, mode):
    if mode == "control":
        return {"code": "control", "reason": "cold-start capture; C/R classes are not applied"}
    expected = summary["expected_post_source"]
    if summary["post_spdp_count"] == 0:
        return {
            "code": "E",
            "reason": f"no post-restore mROS 2 SPDP from {expected} in the peer capture",
        }
    advertised = set(summary["post_spdp_default_ips"]) | set(summary["post_spdp_metatraffic_ips"])
    if expected not in advertised:
        return {
            "code": "E",
            "reason": (
                f"post-restore SPDP from {expected} does not advertise {expected}; "
                f"default={summary['post_spdp_default_ips']} "
                f"metatraffic={summary['post_spdp_metatraffic_ips']}"
            ),
        }
    if not summary["guid_continuity"]:
        return {
            "code": "E",
            "reason": "post-restore mROS 2 GUID prefix does not intersect the pre-checkpoint prefix set",
        }
    sedp_ips = set(summary["post_sedp_unicast_ips"])
    if sedp_ips and expected not in sedp_ips:
        return {
            "code": "C",
            "reason": f"SPDP advertises {expected} but SEDP unicast locators are {sorted(sedp_ips)}",
        }
    toward_new = summary["post_user_data_toward_expected_source"]
    toward_old = summary["post_user_data_toward_old_source"]
    if mode == "changed" and toward_old and not toward_new and "172.18.0.6" in advertised:
        if sedp_ips and expected in sedp_ips:
            return {
                "code": "D",
                "reason": "discovery locators include .6, but captured user DATA still targets .3 and not .6",
            }
        return {
            "code": "B",
            "reason": "SPDP advertises .6, while captured user DATA still targets .3",
        }
    if mode == "changed" and sedp_ips and expected in sedp_ips and not toward_new:
        return {
            "code": "D",
            "reason": "SPDP and SEDP advertise .6, and no post-restore user DATA toward .6 was captured",
        }
    return {
        "code": "advertised",
        "reason": "capture shows mROS 2 re-advertising the expected source locator; application gate decides resume",
    }


def build_fixture_spdp():
    """One Ethernet/IPv4/UDP/RTPS SPDP DATA frame used by the parser self-check."""
    locator = struct.pack("<iI", 1, 7411) + b"\x00" * 12 + socket.inet_aton("172.18.0.6")
    meta = struct.pack("<iI", 1, 7410) + b"\x00" * 12 + socket.inet_aton("172.18.0.6")
    prefix = bytes(range(1, 13))
    params = b"".join((
        struct.pack("<HH", PID_DEFAULT_UNICAST_LOCATOR, 24) + locator,
        struct.pack("<HH", PID_METATRAFFIC_UNICAST_LOCATOR, 24) + meta,
        struct.pack("<HH", PID_PARTICIPANT_GUID, 16) + prefix + b"\x00\x00\x01\xc1",
        struct.pack("<HH", PID_SENTINEL, 0),
    ))
    payload = b"\x00\x03\x00\x00" + params
    data = struct.pack("<HH", 0, 16) + bytes.fromhex("000100c7") + bytes.fromhex(SPDP_WRITER)
    data += struct.pack("<iI", 0, 1) + payload
    sub = bytes([SUBMSG_DATA, 0x05]) + struct.pack("<H", len(data)) + data
    rtps = b"RTPS" + bytes([2, 2, 13, 37]) + prefix + sub
    udp_len = 8 + len(rtps)
    udp = struct.pack("!HHHH", 7410, 7400, udp_len, 0) + rtps
    ip_len = 20 + len(udp)
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, ip_len, 1, 0, 64, 17, 0,
        socket.inet_aton("172.18.0.6"),
        socket.inet_aton("239.255.0.1"),
    ) + udp
    frame = b"\x00" * 12 + struct.pack("!H", 0x0800) + ip
    header = struct.pack("<IHHIIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_ETHERNET)
    record = struct.pack("<IIII", 1_700_000_100, 0, len(frame), len(frame)) + frame
    return header + record
