#!/usr/bin/env python3
"""Read-only snapshots of peer multicast groups and UDP sockets."""

import datetime
import json
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import time


TAG = "[CR-RERUN-20260927-R03]"
PROCESS_PID = 1
INTERVAL_SECONDS = 1.0
running = True


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def emit(out, event, **fields):
    row = {"event": event, "utc": utc_now(), "host_mono_ns": time.monotonic_ns(), **fields}
    out.write(json.dumps(row, sort_keys=True) + "\n")
    out.flush()


def read_proc_raw(path):
    try:
        # Read bytes first so Python's universal-newline conversion cannot
        # silently alter the /proc table that this probe preserves as evidence.
        return Path(path).read_bytes().decode("ascii", errors="replace")
    except OSError as error:
        return {"error": type(error).__name__, "errno": error.errno, "message": str(error)}


def decode_address_port(value):
    address_hex, port_hex = value.split(":", 1)
    address = socket.inet_ntoa(struct.pack("<I", int(address_hex, 16)))
    return address, int(port_hex, 16)


def parse_igmp(text):
    if isinstance(text, dict):
        return text
    groups = []
    interface = None
    for line in text.splitlines()[1:]:
        columns = line.split()
        if not columns:
            continue
        if ":" in line and len(columns) > 1 and columns[0].isdigit():
            interface = columns[1] if len(columns) > 1 else None
            continue
        try:
            group = socket.inet_ntoa(struct.pack("<I", int(columns[0], 16)))
        except (ValueError, OSError, struct.error):
            continue
        groups.append({
            "interface": interface,
            "group": group,
            "group_hex_proc": columns[0],
            "users": int(columns[1]) if len(columns) > 1 and columns[1].isdigit() else None,
            "timer": columns[2] if len(columns) > 2 else None,
            "reporter": columns[3] if len(columns) > 3 else None,
        })
    return groups


def process_socket_fds(pid):
    directory = Path(f"/proc/{pid}/fd")
    try:
        # Materialize the directory before reading links so directory errors
        # are distinguishable from per-FD races and permission failures.
        descriptors = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as error:
        return {}, {
            "directory_error": {
                "error": type(error).__name__,
                "errno": error.errno,
                "message": str(error),
            },
            "vanished_fd_races": [],
            "unreadable_fd_errors": [],
            "ownership_known": False,
        }
    sockets = {}
    vanished_fd_races = []
    unreadable_fd_errors = []
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError as error:
            # The FD closed after readdir. Keep this distinct from a permission
            # problem, but do not call the resulting snapshot conclusive.
            vanished_fd_races.append({
                "fd": descriptor.name,
                "error": type(error).__name__,
                "errno": error.errno,
                "message": str(error),
            })
            continue
        except OSError as error:
            unreadable_fd_errors.append({
                "fd": descriptor.name,
                "error": type(error).__name__,
                "errno": error.errno,
                "message": str(error),
            })
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inode = target[8:-1]
            sockets.setdefault(inode, []).append(descriptor.name)
    ownership_known = not vanished_fd_races and not unreadable_fd_errors
    return sockets, {
        "directory_error": None,
        "vanished_fd_races": vanished_fd_races,
        "unreadable_fd_errors": unreadable_fd_errors,
        "ownership_known": ownership_known,
    }


def parse_udp(text, process_sockets, ownership_known):
    if isinstance(text, dict):
        return text
    sockets = []
    for line in text.splitlines()[1:]:
        columns = line.split()
        if len(columns) < 10:
            continue
        try:
            local_ip, local_port = decode_address_port(columns[1])
            remote_ip, remote_port = decode_address_port(columns[2])
        except (ValueError, OSError, struct.error):
            continue
        inode = columns[9]
        sockets.append({
            "local_ip": local_ip,
            "local_port": local_port,
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "state": columns[3],
            "tx_rx_queue": columns[4],
            "uid": columns[7],
            "inode": inode,
            "drops": columns[12] if len(columns) > 12 else None,
            "pid1_fds": process_sockets.get(inode, []),
            "pid1_fd_ownership_known": ownership_known,
        })
    return sockets


def sample():
    igmp_text = read_proc_raw("/proc/net/igmp")
    udp_text = read_proc_raw("/proc/net/udp")
    udp6_text = read_proc_raw("/proc/net/udp6")
    process_sockets, process_fd_enumeration = process_socket_fds(PROCESS_PID)
    tables_read = all(isinstance(table, str) for table in (igmp_text, udp_text, udp6_text))
    ownership_known = process_fd_enumeration["ownership_known"]
    return {
        "process_pid": PROCESS_PID,
        "proc_tables_read": tables_read,
        "process_fd_enumeration": process_fd_enumeration,
        "pid1_fd_ownership_known": ownership_known,
        "preflight_usable": tables_read and ownership_known,
        "process_socket_inode_count": len(process_sockets),
        "igmp_groups": parse_igmp(igmp_text),
        "udp_sockets": parse_udp(udp_text, process_sockets, ownership_known),
        "igmp_table_raw": igmp_text,
        "udp_table_raw": udp_text,
        "udp6_table_raw_unparsed": udp6_text,
    }


def stop(_signum, _frame):
    global running
    running = False


def main():
    global running
    if len(sys.argv) != 2:
        raise SystemExit("usage: udp_socket_probe.py OUTPUT_JSONL")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    path = sys.argv[1]
    with open(path, "x", encoding="utf-8") as out:
        emit(out, "probe_ready", interface="eth0", process_pid=PROCESS_PID,
             sources=["/proc/net/igmp", "/proc/net/udp", "/proc/net/udp6", "/proc/1/fd"],
             mode="read-only; no socket calls; no ROS node")
        print(f"{TAG} probe_ready pid={os.getpid()} path={path}", flush=True)
        sample_number = 0
        while running:
            started = time.monotonic()
            sample_number += 1
            emit(out, "socket_state", sample=sample_number, **sample())
            remaining = max(0.0, INTERVAL_SECONDS - (time.monotonic() - started))
            time.sleep(remaining)
        emit(out, "probe_stop", reason="signal", samples=sample_number)
        print(f"{TAG} probe_stop samples={sample_number}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
