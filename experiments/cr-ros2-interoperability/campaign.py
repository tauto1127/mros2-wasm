#!/usr/bin/env python3
"""ROS 2 peer checkpoint/restore campaign.

The Wasm artifact and iwasm command match experiments/cr-state-boundary.
Only the peer and the output directory change. Production sources are not
modified.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rtps_pcap import summarize as summarize_pcap


RUN_DIR = Path(__file__).resolve().parent
SUBJECT = RUN_DIR.parent / "cr-state-boundary" / "runtime-build"
STATE_ROOT = Path("/tmp/mros2-cr-ros2-interoperability")
RTK = Path("/home/osslab/.local/bin/rtk")
IWASM = SUBJECT / "runtime" / "iwasm"
WASM = SUBJECT / "app" / "echoback_string.wasm"
NATIVE_PROBE = SUBJECT / "runtime" / "libcr_state_probe.so"
PEER_DIR = RUN_DIR / "ros2_peer"
NETWORK = "mros2-cr-net"
NETWORK_ID = "609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408"
SUBNET = "172.18.0.0/16"
WASM_IMAGE = "ros:humble"
WASM_IMAGE_ID = "sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138"
PEER_IMAGE = "mros2-cr-ros2-peer:humble-20261004"
LABEL_KEY = "io.mros2-cr.ros2"
MIN_FREE = 6 * 1024 ** 3
STALL_S = 300
BODY = "Hello from mros2-posix onto Linux: {mid}"
KINDS = ("publish", "receive", "echo", "callback")
EXPECTED = {
    "iwasm": "fa63c40c2a17f8df6461d687a95cb01bf544e0b7788377d41c317dcec6d46822",
    "wasm": "52ecd6ffde313c25cc6c20298769f7c9ad816419b0ddce80555c5bc2417520e0",
    "native_probe": "b91cdb900b478292d78a8dbfab24906bbdd3252be93b688f9c03e96c0b9121ca",
}
RMW = {
    "cyclonedds": "rmw_cyclonedds_cpp",
    "fastrtps": "rmw_fastrtps_cpp",
}

import re

PUBLISH_RE = re.compile(r"publishing msg: 'Hello from mros2-posix onto Linux: (\d+)'")
CALLBACK_RE = re.compile(r"subscribed msg: 'Hello from mros2-posix onto Linux: (\d+)'")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(-?\d+) payload='([^']*)'")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(-?\d+) payload='([^']*)'")
LOOP_RE = re.compile(r"\[CR-STATE\] loop id=(\d+) guest_before=0x([0-9a-fA-F]+) host_before=0x([0-9a-fA-F]+)")
ARMED_RE = re.compile(r"\[CR-STATE\] armed id=(\d+) value=0x([0-9a-fA-F]+)")
NETIF_REFRESH_RE = re.compile(
    r"\[CR-STATE\] netif_refresh default=(\S+) self=(\S+) same=(\d+) "
    r"stored=0x([0-9a-fA-F]+) probed=0x([0-9a-fA-F]+) pending=(-?\d+)"
)
NETIF_INIT_RE = re.compile(r"\[CR-STATE\] netif_init ")
MONO_RE = re.compile(r"host_mono_ns=(\d+)")
UTC_RE = re.compile(r"host_utc=(\S+)")
REBUILT_RE = re.compile(r"Rebuilt participant announcement after local IP change")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def mono_ns():
    return time.monotonic_ns()


def epoch_s():
    return time.time()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_json(text):
    return json.JSONDecoder().raw_decode(text.lstrip())[0]


def docker(args, timeout=120):
    return subprocess.run(
        [str(RTK), "proxy", "docker", *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ip_text(raw):
    return socket.inet_ntoa(struct.pack("=I", raw))


def parse_state_log(path):
    out = {"loops": [], "armed": [], "refresh": [], "init": [], "rebuilt": []}
    path = Path(path)
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        mono_match = MONO_RE.search(line)
        mono = int(mono_match.group(1)) if mono_match else None
        match = LOOP_RE.search(line)
        if match:
            out["loops"].append({
                "mono": mono,
                "id": int(match.group(1)),
                "guest": int(match.group(2), 16),
                "host": int(match.group(3), 16),
            })
        match = ARMED_RE.search(line)
        if match:
            out["armed"].append({
                "mono": mono,
                "id": int(match.group(1)),
                "value": int(match.group(2), 16),
            })
        match = NETIF_REFRESH_RE.search(line)
        if match:
            out["refresh"].append({
                "mono": mono,
                "default": match.group(1),
                "self": match.group(2),
                "same": int(match.group(3)),
                "stored": int(match.group(4), 16),
                "probed": int(match.group(5), 16),
                "pending": int(match.group(6)),
                "stored_ip": ip_text(int(match.group(4), 16)),
                "probed_ip": ip_text(int(match.group(5), 16)),
            })
        if NETIF_INIT_RE.search(line):
            out["init"].append({"mono": mono})
        if REBUILT_RE.search(line):
            out["rebuilt"].append({"mono": mono, "line": line.strip()})
    return out


def unique_first(items):
    stamped = [item for item in items if item.get("mono") is not None]
    if not stamped:
        return None
    first = min(item["mono"] for item in stamped)
    chosen = [item for item in stamped if item["mono"] == first]
    return chosen[0] if len(chosen) == 1 else None


def unique_latest_armed(items, at_or_before=None):
    eligible = [
        item for item in items
        if item.get("mono") is not None and (at_or_before is None or item["mono"] <= at_or_before)
    ]
    if not eligible:
        return None
    latest = max(item["mono"] for item in eligible)
    chosen = [item for item in eligible if item["mono"] == latest]
    return chosen[0] if len(chosen) == 1 else None


class Obs:
    def __init__(self, mono, utc, kind, mid, source):
        self.mono = mono
        self.utc = utc
        self.kind = kind
        self.mid = mid
        self.source = source


class LogReader:
    def __init__(self, events, lock):
        self.events = events
        self.lock = lock

    def parse(self, line, source):
        mono_match = MONO_RE.search(line)
        utc_match = UTC_RE.search(line)
        if not mono_match or not utc_match:
            return None
        mono = int(mono_match.group(1))
        utc = utc_match.group(1)
        publish = PUBLISH_RE.search(line)
        if publish:
            return Obs(mono, utc, "publish", int(publish.group(1)), source)
        callback = CALLBACK_RE.search(line)
        if callback:
            return Obs(mono, utc, "callback", int(callback.group(1)), source)
        receive = RECEIVE_RE.search(line)
        if receive and int(receive.group(1)) >= 0:
            mid = int(receive.group(1))
            if receive.group(2) == BODY.format(mid=mid):
                return Obs(mono, utc, "receive", mid, source)
        echo = ECHO_RE.search(line)
        if echo and int(echo.group(1)) >= 0:
            mid = int(echo.group(1))
            if echo.group(2) == BODY.format(mid=mid):
                return Obs(mono, utc, "echo", mid, source)
        return None

    def consume(self, process, log_path, source):
        with log_path.open("w", encoding="utf-8") as log:
            for line in process.stdout:
                rendered = f"host_utc={utc_now()} host_mono_ns={mono_ns()} {line.rstrip()}\n"
                log.write(rendered)
                log.flush()
                obs = self.parse(rendered, source)
                if obs is not None:
                    with self.lock:
                        self.events.append(obs)
            exit_status = process.wait()
            log.write(
                f"host_utc={utc_now()} host_mono_ns={mono_ns()} "
                f"event=collector_process_exit source={source} exit_status={exit_status}\n"
            )
            log.flush()
        return exit_status


def snapshot(events, lock):
    with lock:
        return list(events)


def completions(events, *, wasm_source, min_exclusive=None):
    grouped = defaultdict(dict)
    for obs in events:
        if obs.kind in ("publish", "callback") and obs.source != wasm_source:
            continue
        if obs.kind in ("receive", "echo") and obs.source != "peer":
            continue
        if min_exclusive is not None and not (obs.mid > min_exclusive):
            continue
        grouped[obs.mid].setdefault(obs.kind, obs)
    return {
        mid: kinds for mid, kinds in grouped.items()
        if all(kind in kinds for kind in KINDS)
    }


def earliest_window(done, length=10):
    best = None
    for start in sorted(done):
        window = list(range(start, start + length))
        if not all(mid in done for mid in window):
            continue
        established = max(max(done[mid][kind].mono for kind in KINDS) for mid in window)
        if best is None or established < best["established_mono"]:
            best = {"start": start, "ids": window, "established_mono": established}
    return best


def consecutive_length(done):
    ids = sorted(done)
    if not ids:
        return 0
    best = run = 1
    for previous, current in zip(ids, ids[1:]):
        run = run + 1 if current == previous + 1 else 1
        best = max(best, run)
    return best


def stage_name(kinds):
    reached = [kind for kind in KINDS if kind in kinds]
    return reached[-1] if reached else "none"


def boundary_summary(events, *, wasm_source, min_exclusive=None):
    grouped = defaultdict(dict)
    for obs in events:
        if obs.kind in ("publish", "callback") and obs.source != wasm_source:
            continue
        if obs.kind in ("receive", "echo") and obs.source != "peer":
            continue
        if min_exclusive is not None and not (obs.mid > min_exclusive):
            continue
        grouped[obs.mid].setdefault(obs.kind, obs)
    if not grouped:
        return "no matching application ID in this phase"
    furthest = max(grouped, key=lambda mid: (len(grouped[mid]), mid))
    return (
        f"id={furthest} reached={stage_name(grouped[furthest])} "
        f"ids_seen={min(grouped)}..{max(grouped)} count={len(grouped)}"
    )


def network_info():
    result = docker(["network", "inspect", NETWORK], timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    data = parse_json(result.stdout)[0]
    if data["Id"] != NETWORK_ID:
        raise RuntimeError(f"unexpected network id {data['Id']}")
    if data["IPAM"]["Config"][0]["Subnet"] != SUBNET:
        raise RuntimeError(f"unexpected subnet {data['IPAM']['Config']}")
    return data


def occupied_ips(data):
    found = {}
    for entry in (data.get("Containers") or {}).values():
        ip = entry.get("IPv4Address", "").split("/")[0]
        if ip:
            found[ip] = entry.get("Name")
    return found


def existing_names():
    result = docker(["ps", "-a", "--format", "{{.Names}}"])
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def verify_hashes():
    actual = {
        "iwasm": sha256(IWASM),
        "wasm": sha256(WASM),
        "native_probe": sha256(NATIVE_PROBE),
    }
    mismatch = {
        name: (actual[name], EXPECTED[name])
        for name in actual if actual[name] != EXPECTED[name]
    }
    return actual, mismatch


def mount(src, dst, readonly=False):
    spec = f"type=bind,src={src},dst={dst}"
    if readonly:
        spec += ",readonly"
    return ["--mount", spec]


def create_container(name, label, args, command_log):
    command = ["run", "--detach", "--name", name, "--label", f"{LABEL_KEY}={label}", *args]
    result = docker(command, timeout=120)
    with command_log.open("a", encoding="utf-8") as stream:
        stream.write(f"[{utc_now()}] rc={result.returncode}\n")
        stream.write(shlex.join([str(RTK), "proxy", "docker", *command]) + "\n")
        stream.write(result.stdout)
        stream.write(result.stderr)
        stream.write("\n")
    if result.returncode:
        raise RuntimeError(f"create {name} failed: {result.stderr.strip() or result.stdout.strip()}")
    inspected = docker(["inspect", name], timeout=30)
    if inspected.returncode:
        raise RuntimeError(inspected.stderr.strip())
    record = parse_json(inspected.stdout)[0]
    if record["Config"]["Labels"].get(LABEL_KEY) != label:
        raise RuntimeError(f"label missing on {name}")
    if not record["State"]["Running"]:
        raise RuntimeError(f"{name} is not running")
    return record


def process_args(container, pid):
    result = docker(["exec", container, "sh", "-c", f"ps -p {pid} -o args="], timeout=15)
    if result.returncode:
        return "absent" if not result.stdout.strip() else "error", result.stdout.strip(), result.stderr.strip()
    args = result.stdout.strip()
    if not args or args.endswith("<defunct>"):
        return "absent", args, ""
    return "present", args, ""


def start_logged(container, remote_command, log_path, command_path, events, lock, source):
    argv = [str(RTK), "proxy", "docker", "exec", container, "sh", "-c", remote_command]
    write_text(command_path, shlex.join(argv) + "\n")
    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    reader = LogReader(events, lock)
    holder = {}

    def run():
        holder["exit"] = reader.consume(process, log_path, source)

    thread = threading.Thread(target=run, name=f"log-{source}", daemon=True)
    thread.start()
    return process, thread, holder


def wait_pid(pid_path, process, timeout_s=20):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pid_path.exists():
            text = pid_path.read_text(encoding="utf-8").strip()
            if text.isdigit():
                return int(text)
        if process.poll() is not None:
            return None
        time.sleep(0.05)
    return None


def expected_iwasm(args, restore):
    required = (
        "/runtime/iwasm", "--addr-pool=0.0.0.0/0", "--max-threads=32", "-v=5",
        "--native-lib=/runtime/libcr_state_probe.so", "/artifact/echoback_string.wasm",
    )
    return all(part in args for part in required) and (("--restore" in args) == restore)


def stop_pid(container, pid, restore, log_path):
    state, args, error = process_args(container, pid)
    lines = [
        f"utc={utc_now()}",
        f"mono_ns={mono_ns()}",
        f"container={container}",
        f"pid={pid}",
        f"state={state}",
        f"args={args!r}",
        f"error={error!r}",
    ]
    if state == "absent":
        lines.append("result=already-absent")
        write_text(log_path, "\n".join(lines) + "\n")
        return
    if state != "present" or not expected_iwasm(args, restore):
        lines.append("result=identity-mismatch-not-signaled")
        write_text(log_path, "\n".join(lines) + "\n")
        raise RuntimeError(f"refusing to stop unexpected process {pid}: {args!r}")
    result = docker(["exec", container, "kill", "-TERM", str(pid)], timeout=15)
    lines.append(f"sigterm_rc={result.returncode}")
    for _ in range(40):
        state, _current, _error = process_args(container, pid)
        if state == "absent":
            lines.append("result=sigterm-exited")
            write_text(log_path, "\n".join(lines) + "\n")
            return
        time.sleep(0.25)
    lines.append("result=still-running")
    write_text(log_path, "\n".join(lines) + "\n")
    raise RuntimeError(f"pid {pid} still running after SIGTERM")


def remove_labeled(names, label, raw):
    before = []
    for name in names:
        inspected = docker(["inspect", name], timeout=20)
        if inspected.returncode:
            continue
        record = parse_json(inspected.stdout)[0]
        if record["Config"]["Labels"].get(LABEL_KEY) != label:
            raise RuntimeError(f"refusing to remove unlabeled container {name}")
        before.append({"name": name, "id": record["Id"], "status": record["State"]["Status"]})
    write_text(raw / "cleanup-before.json", json.dumps(before, indent=2) + "\n")
    lines = [f"utc={utc_now()}"]
    for name in names:
        if not any(item["name"] == name for item in before):
            lines.append(f"{name}:absent")
            continue
        stopped = docker(["stop", "--time", "5", name], timeout=30)
        removed = docker(["rm", name], timeout=30)
        lines.append(f"{name}:stop_rc={stopped.returncode}:rm_rc={removed.returncode}")
    write_text(raw / "cleanup-commands.txt", "\n".join(lines) + "\n")


def state_ready(state_dir):
    memory = state_dir / "main-memory.img"
    socket_img = state_dir / "main-socket.img"
    return (
        memory.is_file() and socket_img.is_file()
        and memory.stat().st_size >= 1024 ** 3
        and socket_img.stat().st_size > 0
    )


def state_manifest(state_dir, raw):
    started = mono_ns()
    entries = []
    for path in sorted(state_dir.rglob("*")):
        if path.is_file():
            entries.append((path.relative_to(state_dir).as_posix(), path.stat().st_size, sha256(path)))
    finished = mono_ns()
    write_text(raw / "checkpoint-state-files.sha256", "".join(f"{digest}  {name}\n" for name, _size, digest in entries))
    write_text(
        raw / "checkpoint-state-files.txt",
        "\n".join(
            [f"hash_elapsed_ns={finished - started}"]
            + [f"{size}\t{digest}\t{name}" for name, size, digest in entries]
        ) + "\n",
    )
    return {
        "hash_elapsed_ns": finished - started,
        "main_memory": next((size for name, size, _digest in entries if name == "main-memory.img"), 0),
        "main_socket": next((size for name, size, _digest in entries if name == "main-socket.img"), 0),
    }


def discard_pass_state(state_dir, raw):
    manifest = (raw / "checkpoint-state-files.sha256").read_text(encoding="utf-8")
    names = []
    for listed in manifest.splitlines():
        digest, name = listed.split(None, 1)
        file_path = state_dir / name
        if not file_path.is_file() or sha256(file_path) != digest:
            raise RuntimeError(f"state manifest mismatch before delete: {name}")
        names.append(name)
    if "main-memory.img" not in names or "main-socket.img" not in names:
        raise RuntimeError("state manifest is missing memory or socket image")
    shutil.rmtree(state_dir)
    write_text(raw / "state-discarded.txt", f"utc={utc_now()}\npath={state_dir}\nremoved_files={len(names)}\n")


def restore_stage_from_log(log_path, restore_start_mono):
    if not log_path.exists():
        return {"status": "missing", "reason": "restore log absent"}
    stack_times = []
    first_app = None
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        mono_match = MONO_RE.search(line)
        if not mono_match:
            continue
        mono = int(mono_match.group(1))
        if mono < restore_start_mono:
            continue
        if "Finish to restore stack" in line:
            stack_times.append(mono)
        if first_app is None and ("mros2-posix start!" in line or "publishing msg:" in line):
            first_app = mono
    if not stack_times:
        return {"status": "missing", "reason": "no Finish to restore stack line"}
    before_app = [item for item in stack_times if first_app is None or item <= first_app]
    after_app = [item for item in stack_times if first_app is not None and item > first_app]
    if not before_app or after_app:
        return {"status": "missing", "reason": "thread restore logs overlap application output"}
    return {
        "status": "estimated",
        "restore_stage_end_mono_ns": before_app[-1],
        "elapsed_from_restore_command_ns": before_app[-1] - restore_start_mono,
    }


def startup_reran(log_path):
    if not log_path.exists():
        return True
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return ("mros2-posix start!" in text) or ("[CR-STATE] netif_init " in text)


def wait_for_window(events, lock, wasm_proc, peer_proc, *, wasm_source, min_exclusive, stall_s):
    best = 0
    progress_deadline = time.monotonic() + stall_s
    while True:
        if wasm_proc.poll() is not None:
            return None, "process-exited", snapshot(events, lock)
        if peer_proc.poll() is not None:
            return None, "peer-exited", snapshot(events, lock)
        done = completions(snapshot(events, lock), wasm_source=wasm_source, min_exclusive=min_exclusive)
        length = consecutive_length(done)
        if length > best:
            best = length
            progress_deadline = time.monotonic() + stall_s
        window = earliest_window(done)
        if window is not None:
            return window, "pass", snapshot(events, lock)
        if time.monotonic() >= progress_deadline:
            return None, "stall", snapshot(events, lock)
        time.sleep(0.05)


def peer_command(rmw_key):
    rmw = RMW[rmw_key]
    lines = [
        "echo $$ > /run/raw/peer.pid",
        ". /opt/ros/humble/setup.bash",
        f"export RMW_IMPLEMENTATION={rmw}",
        "export ROS_DOMAIN_ID=0",
        "export ROS_LOCALHOST_ONLY=0",
    ]
    if rmw_key == "cyclonedds":
        lines.append("export CYCLONEDDS_URI=file:///opt/experiment/cyclonedds.xml")
    else:
        lines.append("export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/experiment/fastrtps.xml")
    lines.append("exec python3 -u /opt/experiment/echo_peer.py")
    return "; ".join(lines)


def iwasm_command(pid_name, restore):
    restore_flag = " --restore" if restore else ""
    return (
        f"echo $$ > /run/raw/{pid_name}; exec /runtime/iwasm --addr-pool=0.0.0.0/0 "
        "--max-threads=32 -v=5 --native-lib=/runtime/libcr_state_probe.so"
        f"{restore_flag} /artifact/echoback_string.wasm"
    )


def start_capture(container, raw):
    command = (
        "echo $$ > /run/raw/tcpdump.pid; exec tcpdump -i eth0 -n -s 0 -U "
        "-w /run/raw/rtps.pcap 'udp and net 172.18.0.0/16'"
    )
    result = docker(["exec", "-d", container, "sh", "-c", command], timeout=20)
    write_text(
        raw / "tcpdump.command.txt",
        f"utc={utc_now()}\nepoch_s={epoch_s()}\nrc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}\ncommand={command}\n",
    )
    return result.returncode == 0


def stop_capture(container, raw):
    result = docker(
        ["exec", container, "sh", "-c",
         "if [ -f /run/raw/tcpdump.pid ]; then kill -INT $(cat /run/raw/tcpdump.pid) || true; fi"],
        timeout=20,
    )
    write_text(
        raw / "tcpdump-stop.txt",
        f"utc={utc_now()}\nrc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
    )
    time.sleep(0.5)


def first_after(events, *, kind, source, minimum_mono):
    chosen = [
        obs for obs in events
        if obs.kind == kind and obs.source == source and obs.mono >= minimum_mono
    ]
    if not chosen:
        return None
    return min(chosen, key=lambda obs: obs.mono)


def record_round(result, key, obs):
    if obs is None:
        result[key] = None
        return
    result[key] = {"id": obs.mid, "utc": obs.utc, "mono_ns": obs.mono}


def run_trial(mode, index, rmw_key):
    trial_id = f"{rmw_key}-{mode}-run-{index:02d}"
    label = trial_id
    raw = RUN_DIR / "results" / rmw_key / mode / f"run-{index:02d}"
    if raw.exists():
        raise RuntimeError(f"trial directory already exists: {raw}")
    raw.mkdir(parents=True)
    state_dir = STATE_ROOT / trial_id
    if state_dir.exists():
        raise RuntimeError(f"state directory already exists: {state_dir}")
    names = {
        "wamr": f"mros2-cr-ros2-{trial_id}-wamr",
        "peer": f"mros2-cr-ros2-{trial_id}-peer",
    }
    if mode == "changed":
        names["dest"] = f"mros2-cr-ros2-{trial_id}-dst"
    created = []
    events = []
    lock = threading.Lock()
    threads = []
    result = {
        "trial_id": trial_id,
        "rmw": RMW[rmw_key],
        "mode": mode,
        "verdict": "STOP",
        "reason": "",
        "checkpointed": False,
        "application_roundtrip_pass": False,
        "startup_reran": None,
        "guid_continuity": None,
    }
    try:
        free = shutil.disk_usage("/tmp").free
        write_text(raw / "disk-before.txt", f"utc={utc_now()}\nfree_bytes={free}\n")
        if free < MIN_FREE:
            result["reason"] = f"/tmp free {free} bytes is below 6 GiB"
            return result
        net = network_info()
        write_text(raw / "network-before.json", json.dumps(net, indent=2) + "\n")
        occupied = occupied_ips(net)
        needed = {"172.18.0.3", "172.18.0.5"}
        if mode == "changed":
            needed.add("172.18.0.6")
        conflicts = {ip: occupied[ip] for ip in sorted(needed) if ip in occupied}
        name_conflicts = sorted(set(names.values()) & existing_names())
        wasm_image = parse_json(docker(["image", "inspect", WASM_IMAGE]).stdout)[0]
        peer_inspect = docker(["image", "inspect", PEER_IMAGE])
        if peer_inspect.returncode:
            result["reason"] = f"peer image {PEER_IMAGE} is not present"
            return result
        peer_image = parse_json(peer_inspect.stdout)[0]
        hashes, mismatch = verify_hashes()
        write_text(raw / "preflight.json", json.dumps({
            "utc": utc_now(),
            "network_id": net["Id"],
            "occupied_ips": occupied,
            "wasm_image_id": wasm_image["Id"],
            "peer_image_id": peer_image["Id"],
            "hashes": hashes,
            "free_bytes": free,
            "rmw": RMW[rmw_key],
        }, indent=2) + "\n")
        if wasm_image["Id"] != WASM_IMAGE_ID:
            result["reason"] = f"wasm image id mismatch {wasm_image['Id']}"
            return result
        if conflicts or name_conflicts or mismatch:
            result["reason"] = f"environment conflict ips={conflicts} names={name_conflicts} hashes={mismatch}"
            return result

        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir()
        command_log = raw / "docker-commands.log"
        wamr_args = [
            "--network", NETWORK, "--ip", "172.18.0.3",
            *mount(raw, "/run/raw"),
            *mount(IWASM.parent, "/runtime", readonly=True),
            *mount(WASM.parent, "/artifact", readonly=True),
            *mount(state_dir, "/state"),
            "--workdir", "/state", WASM_IMAGE, "sleep", "infinity",
        ]
        peer_args = [
            "--network", NETWORK, "--ip", "172.18.0.5",
            *mount(raw, "/run/raw"),
            *mount(PEER_DIR, "/opt/experiment", readonly=True),
            PEER_IMAGE, "sleep", "infinity",
        ]
        create_container(names["wamr"], label, wamr_args, command_log)
        created.append(names["wamr"])
        create_container(names["peer"], label, peer_args, command_log)
        created.append(names["peer"])
        write_text(raw / "wamr-inspect.json", docker(["inspect", names["wamr"]]).stdout)
        write_text(raw / "peer-inspect.json", docker(["inspect", names["peer"]]).stdout)
        write_text(raw / "network-after-create.json", docker(["network", "inspect", NETWORK]).stdout)
        if not start_capture(names["peer"], raw):
            result["reason"] = "tcpdump did not start in the ROS 2 peer container"
            return result

        peer_proc, peer_thread, _peer_holder = start_logged(
            names["peer"], peer_command(rmw_key), raw / "ros2-peer.log",
            raw / "peer.command.txt", events, lock, "peer",
        )
        threads.append(peer_thread)
        peer_pid = wait_pid(raw / "peer.pid", peer_proc)
        peer_state, peer_argv, peer_error = process_args(names["peer"], peer_pid) if peer_pid else ("absent", "", "")
        write_text(
            raw / "peer-identity.txt",
            f"pid={peer_pid}\nstate={peer_state}\nargs={peer_argv!r}\nerror={peer_error!r}\n"
            f"rmw={RMW[rmw_key]}\n",
        )
        if peer_state != "present" or "echo_peer.py" not in peer_argv:
            result["reason"] = "ROS 2 peer process identity was not verified"
            return result

        wasm_proc, wasm_thread, wasm_holder = start_logged(
            names["wamr"], iwasm_command("wasm-checkpoint.pid", False),
            raw / "wasm-checkpoint.log", raw / "wasm-checkpoint.command.txt",
            events, lock, "checkpoint",
        )
        threads.append(wasm_thread)
        wasm_pid = wait_pid(raw / "wasm-checkpoint.pid", wasm_proc)
        wasm_state, wasm_argv, wasm_error = process_args(names["wamr"], wasm_pid) if wasm_pid else ("absent", "", "")
        write_text(
            raw / "wasm-checkpoint-identity.txt",
            f"container_pid={wasm_pid}\nstate={wasm_state}\nargs={wasm_argv!r}\nerror={wasm_error!r}\n",
        )
        if wasm_state != "present" or not expected_iwasm(wasm_argv, False):
            result["reason"] = "checkpoint iwasm identity was not verified"
            return result

        window, status, _snap = wait_for_window(
            events, lock, wasm_proc, peer_proc,
            wasm_source="checkpoint", min_exclusive=None, stall_s=STALL_S,
        )
        if status != "pass":
            result["reason"] = (
                f"pre-checkpoint gate {status}; last boundary: "
                + boundary_summary(snapshot(events, lock), wasm_source="checkpoint")
            )
            result["verdict"] = "FAIL" if status in ("process-exited", "peer-exited") else "UNRESOLVED"
            result["post_boundary"] = result["reason"]
            return result

        if mode == "control":
            result["application_roundtrip_pass"] = True
            result["pre_window"] = window["ids"]
            result["verdict"] = "PASS"
            result["reason"] = f"no-C/R control passed IDs {window['ids']}"
            stop_pid(names["wamr"], wasm_pid, False, raw / "wasm-control-stop.log")
            return result

        markers = parse_state_log(raw / "wasm-checkpoint.log")
        armed = unique_latest_armed(markers["armed"])
        if armed is None:
            result["verdict"] = "FAIL"
            result["reason"] = "armed sentinel marker is missing or ambiguous"
            return result
        result["checkpoint_armed_id"] = armed["id"]
        result["saved_sentinel"] = f"0x{armed['value']:08x}"
        signal_mono = mono_ns()
        signal_epoch = epoch_s()
        signal_utc = utc_now()
        signal = docker(["exec", names["wamr"], "kill", "-USR2", str(wasm_pid)], timeout=15)
        signal_done = mono_ns()
        write_text(
            raw / "checkpoint-signal.log",
            f"command_start_utc={signal_utc}\ncommand_start_epoch_s={signal_epoch}\n"
            f"command_start_mono_ns={signal_mono}\ncommand_return_mono_ns={signal_done}\n"
            f"window={window['ids']}\nrc={signal.returncode}\nstdout={signal.stdout!r}\n"
            f"stderr={signal.stderr!r}\n",
        )
        if signal.returncode:
            result["verdict"] = "FAIL"
            result["reason"] = "SIGUSR2 command failed"
            return result
        wasm_thread.join(timeout=600)
        exit_status = wasm_holder.get("exit")
        if exit_status != 0:
            result["verdict"] = "FAIL"
            result["reason"] = f"checkpoint process exit status {exit_status}"
            result["checkpointed"] = True
            return result
        stable = None
        for _ in range(50):
            if state_ready(state_dir):
                size_a = (state_dir / "main-memory.img").stat().st_size
                time.sleep(0.2)
                size_b = (state_dir / "main-memory.img").stat().st_size
                if size_a == size_b:
                    stable = mono_ns()
                    break
            time.sleep(0.2)
        if stable is None:
            result["verdict"] = "FAIL"
            result["reason"] = "checkpoint exited but memory/socket state was not written"
            result["checkpointed"] = True
            return result
        result["checkpointed"] = True
        manifest = state_manifest(state_dir, raw)
        if manifest["main_memory"] < 1024 ** 3 or manifest["main_socket"] <= 0:
            result["verdict"] = "FAIL"
            result["reason"] = "checkpoint state image missing after hash"
            return result
        observed = snapshot(events, lock)
        publishes = [obs for obs in observed if obs.source == "checkpoint" and obs.kind == "publish"]
        boundary_n = max(obs.mid for obs in publishes)
        if boundary_n != armed["id"]:
            result["verdict"] = "FAIL"
            result["reason"] = (
                f"checkpoint publish boundary id={boundary_n} does not match armed id={armed['id']}"
            )
            return result
        result["N"] = boundary_n
        result["pre_window"] = window["ids"]
        result["timings_ns"] = {"checkpoint_signal_to_stable_image": stable - signal_mono}
        result["utc"] = {"sigusr2": signal_utc}
        result["epoch_s"] = {"sigusr2": signal_epoch}
        write_text(raw / "checkpoint-boundary.txt", f"N={boundary_n}\nwindow={window['ids']}\n")

        restore_container = names["wamr"]
        if mode == "changed":
            again = network_info()
            occupied = occupied_ips(again)
            if "172.18.0.6" in occupied or names["dest"] in existing_names():
                result["verdict"] = "STOP"
                result["reason"] = f"destination became busy: {occupied.get('172.18.0.6')}"
                return result
            dest_args = [
                "--network", NETWORK, "--ip", "172.18.0.6",
                *mount(raw, "/run/raw"),
                *mount(IWASM.parent, "/runtime", readonly=True),
                *mount(WASM.parent, "/artifact", readonly=True),
                *mount(state_dir, "/state"),
                "--workdir", "/state", WASM_IMAGE, "sleep", "infinity",
            ]
            create_container(names["dest"], label, dest_args, command_log)
            created.append(names["dest"])
            write_text(raw / "dest-inspect.json", docker(["inspect", names["dest"]]).stdout)
            restore_container = names["dest"]

        hashes_after, mismatch_after = verify_hashes()
        write_text(raw / "hashes-before-restore.json", json.dumps(hashes_after, indent=2) + "\n")
        if mismatch_after:
            result["verdict"] = "STOP"
            result["reason"] = f"artifact hash changed before restore: {mismatch_after}"
            return result

        restore_mono = mono_ns()
        restore_epoch = epoch_s()
        restore_utc = utc_now()
        restore_proc, restore_thread, _restore_holder = start_logged(
            restore_container, iwasm_command("wasm-restore.pid", True),
            raw / "wasm-restore.log", raw / "wasm-restore.command.txt",
            events, lock, "restore",
        )
        threads.append(restore_thread)
        restore_pid = wait_pid(raw / "wasm-restore.pid", restore_proc)
        restore_state, restore_argv, restore_error = (
            process_args(restore_container, restore_pid) if restore_pid else ("absent", "", "")
        )
        write_text(
            raw / "wasm-restore-identity.txt",
            f"container_pid={restore_pid}\nstate={restore_state}\nargs={restore_argv!r}\n"
            f"error={restore_error!r}\ncommand_start_utc={restore_utc}\n"
            f"command_start_epoch_s={restore_epoch}\ncommand_start_mono_ns={restore_mono}\n",
        )
        if restore_state != "present" or not expected_iwasm(restore_argv, True):
            result["verdict"] = "FAIL"
            result["reason"] = "restore iwasm identity was not verified"
            return result

        post_window, post_status, _post = wait_for_window(
            events, lock, restore_proc, peer_proc,
            wasm_source="restore", min_exclusive=boundary_n, stall_s=STALL_S,
        )
        final_events = snapshot(events, lock)
        stage = restore_stage_from_log(raw / "wasm-restore.log", restore_mono)
        restore_markers = parse_state_log(raw / "wasm-restore.log")
        reran = startup_reran(raw / "wasm-restore.log")
        result["startup_reran"] = reran
        result["restore_stage"] = stage
        result["post_boundary"] = boundary_summary(
            final_events, wasm_source="restore", min_exclusive=boundary_n,
        )
        result["first_post_restore_netif_refresh"] = unique_first(restore_markers["refresh"])
        result["later_netif_refresh"] = restore_markers["refresh"][1:8]
        result["spdp_rebuilt_lines"] = len(restore_markers["rebuilt"])
        result["utc"]["restore_command"] = restore_utc
        result["epoch_s"]["restore_command"] = restore_epoch
        result["timings_ns"]["restore_stage"] = stage.get("elapsed_from_restore_command_ns")
        record_round(result, "first_post_publish", first_after(
            final_events, kind="publish", source="restore", minimum_mono=restore_mono,
        ))
        record_round(result, "first_post_receive", first_after(
            final_events, kind="receive", source="peer", minimum_mono=restore_mono,
        ))
        record_round(result, "first_post_echo", first_after(
            final_events, kind="echo", source="peer", minimum_mono=restore_mono,
        ))
        record_round(result, "first_post_callback", first_after(
            final_events, kind="callback", source="restore", minimum_mono=restore_mono,
        ))
        result["application_roundtrip_pass"] = post_status == "pass" and not reran
        if post_status == "pass":
            result["post_window"] = post_window["ids"]
            result["timings_ns"]["restore_to_ten_consecutive"] = (
                post_window["established_mono"] - restore_mono
            )
            if reran:
                result["verdict"] = "FAIL"
                result["reason"] = "application gate passed but the startup path ran again after restore"
            else:
                result["verdict"] = "PASS"
                result["reason"] = f"post window {post_window['ids']}"
            if restore_proc.poll() is None and restore_pid:
                stop_pid(restore_container, restore_pid, True, raw / "wasm-restore-stop.log")
            return result
        result["verdict"] = "FAIL" if post_status in ("process-exited", "peer-exited") else "UNRESOLVED"
        result["reason"] = (
            f"post-restore gate {post_status}; startup_reran={reran}; "
            f"last boundary: {result['post_boundary']}"
        )
        if restore_proc.poll() is None and restore_pid:
            stop_pid(restore_container, restore_pid, True, raw / "wasm-restore-stop.log")
        return result
    except Exception as error:
        result["verdict"] = "STOP"
        result["reason"] = f"{type(error).__name__}: {error}"
        return result
    finally:
        cleanup_error = None
        try:
            if "peer" in names and names["peer"] in created:
                stop_capture(names["peer"], raw)
        except Exception as error:
            cleanup_error = error
        try:
            pcap = raw / "rtps.pcap"
            if pcap.is_file() and pcap.stat().st_size > 0:
                packet_summary = summarize_pcap(
                    pcap.read_bytes(),
                    checkpoint_epoch=result.get("epoch_s", {}).get("sigusr2") if mode != "control" else None,
                    restore_epoch=result.get("epoch_s", {}).get("restore_command"),
                    mode=mode,
                )
                result["rtps"] = {
                    "classification": packet_summary["classification"],
                    "guid_continuity": packet_summary["guid_continuity"],
                    "pre_guid_prefixes": packet_summary["pre_guid_prefixes"],
                    "post_guid_prefixes": packet_summary["post_guid_prefixes"],
                    "post_mros2_sources": packet_summary["post_mros2_sources"],
                    "post_spdp_count": packet_summary["post_spdp_count"],
                    "post_spdp_default_ips": packet_summary["post_spdp_default_ips"],
                    "post_spdp_metatraffic_ips": packet_summary["post_spdp_metatraffic_ips"],
                    "post_sedp_unicast_ips": packet_summary["post_sedp_unicast_ips"],
                    "submessage_counts": packet_summary["submessage_counts"],
                    "frames": packet_summary["frames"],
                }
                result["guid_continuity"] = packet_summary["guid_continuity"]
                write_text(raw / "rtps-summary.json", json.dumps(packet_summary, indent=2) + "\n")
                if (
                    mode != "control"
                    and result.get("verdict") == "PASS"
                    and packet_summary["guid_continuity"] is False
                ):
                    result["verdict"] = "FAIL"
                    result["reason"] += "; captured mROS 2 GUID prefix changed across restore"
                    result["application_roundtrip_pass"] = False
        except Exception as error:
            cleanup_error = error
        try:
            remove_labeled(created, label, raw)
        except Exception as error:
            cleanup_error = error
        try:
            if result.get("verdict") == "PASS" and result.get("checkpointed") and cleanup_error is None:
                discard_pass_state(state_dir, raw)
            elif result.get("checkpointed"):
                write_text(raw / "state-kept.txt", f"utc={utc_now()}\npath={state_dir}\nreason={result.get('reason')}\n")
            elif state_dir.exists() and not any(state_dir.iterdir()):
                state_dir.rmdir()
        except Exception as error:
            cleanup_error = error
        if cleanup_error is not None:
            result["verdict"] = "STOP"
            result["reason"] = f"{result.get('reason')}; cleanup error: {cleanup_error}"
        for thread in threads:
            thread.join(timeout=5)
        write_text(raw / "result.json", json.dumps(result, indent=2) + "\n")
        write_text(raw / "disk-after.txt", f"utc={utc_now()}\nfree_bytes={shutil.disk_usage('/tmp').free}\n")
        print(f"[CR-ROS2] {trial_id} {result['verdict']} {result['reason']}", flush=True)


def earlier_passed(rmw_key, mode, index):
    path = RUN_DIR / "results" / rmw_key / mode / f"run-{index:02d}" / "result.json"
    if not path.exists():
        return False
    return json.loads(path.read_text(encoding="utf-8")).get("verdict") == "PASS"


def main():
    import sys
    usage = "usage: campaign.py run <control|same|changed> <cyclonedds|fastrtps> <1-3>"
    if len(sys.argv) != 5 or sys.argv[1] != "run":
        raise SystemExit(usage)
    mode = sys.argv[2]
    rmw_key = sys.argv[3]
    if mode not in ("control", "same", "changed") or rmw_key not in RMW:
        raise SystemExit(usage)
    try:
        index = int(sys.argv[4])
    except ValueError as error:
        raise SystemExit(usage) from error
    if index not in (1, 2, 3):
        raise SystemExit(usage)
    if mode in ("same", "changed") and not earlier_passed(rmw_key, "control", 1):
        raise SystemExit(f"{rmw_key} no-C/R control must PASS before C/R")
    if mode == "changed":
        for same_index in (1, 2, 3):
            if not earlier_passed(rmw_key, "same", same_index):
                raise SystemExit(f"{rmw_key} same-IP must be 3/3 PASS before changed-IP")
    if rmw_key == "fastrtps":
        cyclone_changed = [
            earlier_passed("cyclonedds", "changed", number) for number in (1, 2, 3)
        ]
        if all(cyclone_changed):
            raise SystemExit("Fast DDS comparison runs only when Cyclone DDS changed-IP is not 3/3")
        if not earlier_passed("cyclonedds", "changed", 1) and index > 1 and not earlier_passed("fastrtps", "changed", 1):
            raise SystemExit("run one Fast DDS changed-IP trial before additional trials")
    result = run_trial(mode, index, rmw_key)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
