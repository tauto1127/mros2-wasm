#!/usr/bin/env python3
"""Sequential same-IP then changed-IP checkpoint/restore trials.

Adapted from the 2026-09-27 run-04 and run-06 runners. See adjustments.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


RUN_DIR = Path(__file__).resolve().parent
BUILD = RUN_DIR / "runtime-build"
STATE_ROOT = BUILD / "state"
RTK = Path("/home/osslab/.local/bin/rtk")
IWASM = BUILD / "runtime" / "iwasm"
WASM = BUILD / "app" / "echoback_string.wasm"
NATIVE_PROBE = BUILD / "runtime" / "libcr_state_probe.so"
PEER = Path("/tmp/mros2-posix-run04-final-build/mros2-posix")
EXPECTED_PEER = "8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1"
NETWORK = "mros2-cr-net"
NETWORK_ID = "609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408"
SUBNET = "172.18.0.0/16"
IMAGE = "ros:humble"
IMAGE_ID = "sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138"
LABEL_KEY = "io.mros2-cr.trial"
MIN_FREE = 6 * 1024 ** 3
STALL_S = 300
BODY = "Hello from mros2-posix onto Linux: {mid}"
KINDS = ("publish", "receive", "echo", "callback")

PUBLISH_RE = re.compile(r"publishing msg: 'Hello from mros2-posix onto Linux: (\d+)'")
CALLBACK_RE = re.compile(r"subscribed msg: 'Hello from mros2-posix onto Linux: (\d+)'")
RECEIVE_RE = re.compile(
    r"event=peer_receive topic=/to_linux id=(-?\d+) payload='([^']*)'"
)
ECHO_RE = re.compile(
    r"event=peer_echo_publish_return topic=/to_stm id=(-?\d+) payload='([^']*)'"
)
LOOP_RE = re.compile(r"\[CR-STATE\] loop id=(\d+) guest_before=0x([0-9a-fA-F]+) host_before=0x([0-9a-fA-F]+)")
ARMED_RE = re.compile(r"\[CR-STATE\] armed id=(\d+) value=0x([0-9a-fA-F]+)")
NETIF_REFRESH_RE = re.compile(r"\[CR-STATE\] netif_refresh default=(\S+) self=(\S+) same=(\d+) stored=0x([0-9a-fA-F]+) probed=0x([0-9a-fA-F]+) pending=(-?\d+)")
NETIF_INIT_RE = re.compile(r"\[CR-STATE\] netif_init default=(\S+) self=(\S+) same=(\d+) stored=0x([0-9a-fA-F]+)")
DYNAMIC_IP_RE = re.compile(r"netif_wasm: dynamic ip=0x([0-9a-fA-F]+)")
MONO_RE = re.compile(r"host_mono_ns=(\d+)")
UTC_RE = re.compile(r"host_utc=(\S+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def mono_ns():
    return time.monotonic_ns()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def parse_state_log(path):
    out = {"loops": [], "armed": [], "refresh": [], "init": [], "dynamic": []}
    path = Path(path)
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        mm = MONO_RE.search(line)
        mono = int(mm.group(1)) if mm else None
        m = LOOP_RE.search(line)
        if m:
            out["loops"].append({"mono": mono, "id": int(m.group(1)), "guest": int(m.group(2), 16), "host": int(m.group(3), 16)})
        m = ARMED_RE.search(line)
        if m:
            out["armed"].append({"mono": mono, "id": int(m.group(1)), "value": int(m.group(2), 16)})
        m = NETIF_REFRESH_RE.search(line)
        if m:
            out["refresh"].append({"mono": mono, "default": m.group(1), "self": m.group(2), "same": int(m.group(3)), "stored": int(m.group(4),16), "probed": int(m.group(5),16), "pending": int(m.group(6))})
        m = NETIF_INIT_RE.search(line)
        if m:
            out["init"].append({"mono": mono})
        m = DYNAMIC_IP_RE.search(line)
        if m:
            out["dynamic"].append({"mono": mono, "value": int(m.group(1),16)})
    return out


def ip_text(raw):
    return socket.inet_ntoa(struct.pack("=I", raw))


def load_expected_hashes():
    text = (RUN_DIR / "build-provenance" / "artifact-sha256.txt").read_text()
    found = {}
    for line in text.splitlines():
        digest, path = line.split(None, 1)
        found[Path(path).name] = digest
    required = ("iwasm", "echoback_string.wasm", "libcr_state_probe.so")
    if any(name not in found for name in required):
        raise RuntimeError(f"artifact hash file is incomplete: {text}")
    return {
        "iwasm": found["iwasm"],
        "wasm": found["echoback_string.wasm"],
        "native_probe": found["libcr_state_probe.so"],
        "peer": EXPECTED_PEER,
    }


@dataclass
class Obs:
    mono: int
    utc: str
    kind: str
    mid: int
    source: str


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
    done = {}
    for mid, kinds in grouped.items():
        if all(kind in kinds for kind in KINDS):
            done[mid] = kinds
    return done


def earliest_window(done, length=10):
    best = None
    for start in sorted(done):
        window = list(range(start, start + length))
        if not all(mid in done for mid in window):
            continue
        closing = max(window, key=lambda mid: max(done[mid][kind].mono for kind in KINDS))
        callback = done[closing]["callback"]
        established = max(done[closing][kind].mono for kind in KINDS)
        if best is None or established < best["established_mono"]:
            best = {
                "start": start,
                "ids": window,
                "closing_id": closing,
                "callback_mono": callback.mono,
                "callback_utc": callback.utc,
                "established_mono": established,
            }
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
    order = ("publish", "receive", "echo", "callback")
    reached = [kind for kind in order if kind in kinds]
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
    data = json.loads(result.stdout)[0]
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


def verify_hashes(expected):
    actual = {
        "iwasm": sha256(IWASM),
        "wasm": sha256(WASM),
        "native_probe": sha256(NATIVE_PROBE),
        "peer": sha256(PEER),
    }
    mismatch = {name: (actual[name], expected[name]) for name in actual if actual[name] != expected[name]}
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
    record = json.loads(inspected.stdout)[0]
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
    lines = [f"utc={utc_now()}", f"mono_ns={mono_ns()}", f"container={container}", f"pid={pid}", f"state={state}", f"args={args!r}", f"error={error!r}"]
    if state == "absent":
        lines.append("result=already-absent")
        write_text(log_path, "\n".join(lines) + "\n")
        return
    if state != "present" or not expected_iwasm(args, restore):
        lines.append("result=identity-mismatch-not-signaled")
        write_text(log_path, "\n".join(lines) + "\n")
        raise RuntimeError(f"refusing to stop unexpected process {pid}: {args!r}")
    started = mono_ns()
    result = docker(["exec", container, "kill", "-TERM", str(pid)], timeout=15)
    lines.append(f"sigterm_mono_ns={started}")
    lines.append(f"sigterm_rc={result.returncode}")
    for _ in range(40):
        state, current, _error = process_args(container, pid)
        if state == "absent":
            lines.append(f"exited_mono_ns={mono_ns()}")
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
        record = json.loads(inspected.stdout)[0]
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
    after_net = network_info()
    write_text(raw / "network-after-cleanup.json", json.dumps(after_net, indent=2) + "\n")
    remaining = docker(["ps", "-a", "--filter", f"label={LABEL_KEY}={label}", "--format", "{{.Names}}"])
    write_text(raw / "cleanup-after.txt", remaining.stdout + remaining.stderr)
    if remaining.stdout.strip():
        raise RuntimeError(f"labeled containers remain: {remaining.stdout.strip()}")


def state_manifest(state_dir, raw):
    started = mono_ns()
    started_utc = utc_now()
    entries = []
    for path in sorted(state_dir.rglob("*")):
        if path.is_file():
            entries.append((path.relative_to(state_dir).as_posix(), path.stat().st_size, sha256(path)))
    finished = mono_ns()
    sha_text = "".join(f"{digest}  {name}\n" for name, _size, digest in entries)
    detail = [f"hash_start_utc={started_utc}", f"hash_start_mono_ns={started}", f"hash_end_mono_ns={finished}", f"hash_elapsed_ns={finished - started}", f"state_dir={state_dir}"]
    detail.extend(f"{size}\t{digest}\t{name}" for name, size, digest in entries)
    write_text(raw / "checkpoint-state-files.sha256", sha_text)
    write_text(raw / "checkpoint-state-files.txt", "\n".join(detail) + "\n")
    return {
        "files": len(entries),
        "hash_elapsed_ns": finished - started,
        "hash_start_mono_ns": started,
        "hash_end_mono_ns": finished,
        "names": [name for name, _size, _digest in entries],
        "main_memory": next((size for name, size, _digest in entries if name == "main-memory.img"), 0),
        "main_socket": next((size for name, size, _digest in entries if name == "main-socket.img"), 0),
    }


def owned_state(path, trial_id):
    resolved = path.resolve()
    return (
        not path.is_symlink()
        and resolved.is_dir()
        and resolved.parent == STATE_ROOT.resolve()
        and resolved.name == trial_id
    )


def discard_pass_state(state_dir, trial_id, raw):
    if not owned_state(state_dir, trial_id):
        raise RuntimeError(f"refusing to delete unowned state path {state_dir}")
    manifest = (raw / "checkpoint-state-files.sha256").read_text(encoding="utf-8")
    again = []
    for listed in manifest.splitlines():
        digest, name = listed.split(None, 1)
        file_path = state_dir / name
        if not file_path.is_file() or sha256(file_path) != digest:
            raise RuntimeError(f"state manifest mismatch before delete: {name}")
        again.append(name)
    if "main-memory.img" not in again or "main-socket.img" not in again:
        raise RuntimeError("state manifest is missing memory or socket image")
    usage = shutil.disk_usage(state_dir)
    shutil.rmtree(state_dir)
    write_text(
        raw / "state-discarded.txt",
        f"utc={utc_now()}\npath={state_dir}\nremoved_files={len(again)}\n"
        f"disk_after_free={shutil.disk_usage('/tmp').free}\nusage_total_before_note={usage.total}\n",
    )


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
        return {"status": "missing", "reason": "no Finish to restore stack line before a separable completion point", "first_app_mono_ns": first_app}
    before_app = [item for item in stack_times if first_app is None or item <= first_app]
    after_app = [item for item in stack_times if first_app is not None and item > first_app]
    if not before_app or after_app:
        return {
            "status": "missing",
            "reason": "thread restore logs overlap application output or all occur after it",
            "stack_restore_count": len(stack_times),
            "before_app": len(before_app),
            "after_app": len(after_app),
            "first_app_mono_ns": first_app,
        }
    return {
        "status": "estimated",
        "restore_stage_end_mono_ns": before_app[-1],
        "stack_restore_count": len(before_app),
        "first_app_mono_ns": first_app,
        "elapsed_from_restore_command_ns": before_app[-1] - restore_start_mono,
    }


def wait_for_window(events, lock, process, *, wasm_source, min_exclusive, stall_s):
    best = 0
    progress_deadline = time.monotonic() + stall_s
    while True:
        if process.poll() is not None:
            return None, "process-exited", snapshot(events, lock)
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


def state_ready(state_dir):
    memory = state_dir / "main-memory.img"
    socket = state_dir / "main-socket.img"
    if not memory.is_file() or not socket.is_file():
        return False
    return memory.stat().st_size >= 1024 ** 3 and socket.stat().st_size > 0


def run_trial(mode, index, expected, arm):
    trial_id = f"{arm}-{mode}-run-{index:02d}"
    label = f"no-recover-{trial_id}"
    raw = RUN_DIR / "smoke" / mode / f"run-{index:02d}"
    if raw.exists():
        raise RuntimeError(f"trial directory already exists: {raw}")
    raw.mkdir(parents=True)
    state_dir = STATE_ROOT / trial_id
    if state_dir.exists() or STATE_ROOT.joinpath(trial_id).exists():
        raise RuntimeError(f"state directory already exists: {state_dir}")
    names = {
        "wamr": f"mros2-cr-nurec-{trial_id}-wamr",
        "peer": f"mros2-cr-nurec-{trial_id}-peer",
    }
    if mode == "changed":
        names = {
            "wamr": f"mros2-cr-nurec-{trial_id}-src",
            "peer": f"mros2-cr-nurec-{trial_id}-peer",
            "dest": f"mros2-cr-nurec-{trial_id}-dst",
        }
    created = []
    events = []
    lock = threading.Lock()
    threads = []
    result = {
        "trial_id": trial_id,
        "arm": arm,
        "mode": mode,
        "verdict": "STOP",
        "reason": "",
        "checkpointed": False,
        "N": None,
        "timings_ns": {},
        "utc": {},
        "guest_state_preserved": None,
        "native_state_reset": None,
        "netif_default_restored_nonnull": None,
        "netif_points_to_restored_object": None,
        "stored_ip_before_refresh": None,
        "probed_ip_before_refresh": None,
        "application_roundtrip_pass": False,
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
        conflicts = {ip: occupied[ip] for ip in needed if ip in occupied}
        name_conflicts = sorted(set(names.values()) & existing_names())
        image = json.loads(docker(["image", "inspect", IMAGE]).stdout)[0]
        hashes, mismatch = verify_hashes(expected)
        preflight = {
            "utc": utc_now(),
            "network_id": net["Id"],
            "subnet": net["IPAM"]["Config"][0]["Subnet"],
            "occupied_ips": occupied,
            "image_id": image["Id"],
            "hashes": hashes,
            "free_bytes": free,
        }
        write_text(raw / "preflight.json", json.dumps(preflight, indent=2) + "\n")
        if image["Id"] != IMAGE_ID:
            result["reason"] = f"image id mismatch {image['Id']}"
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
            "--workdir", "/state", IMAGE, "sleep", "infinity",
        ]
        peer_args = [
            "--network", NETWORK, "--ip", "172.18.0.5",
            *mount(raw, "/run/raw"),
            *mount(PEER, "/native-peer", readonly=True),
            IMAGE, "sleep", "infinity",
        ]
        create_container(names["wamr"], label, wamr_args, command_log)
        created.append(names["wamr"])
        create_container(names["peer"], label, peer_args, command_log)
        created.append(names["peer"])
        write_text(raw / "wamr-inspect.json", docker(["inspect", names["wamr"]]).stdout)
        write_text(raw / "peer-inspect.json", docker(["inspect", names["peer"]]).stdout)
        write_text(raw / "network-after-create.json", docker(["network", "inspect", NETWORK]).stdout)
        ldd = docker(["exec", names["peer"], "ldd", "/native-peer"], timeout=20)
        write_text(raw / "native-peer-ldd.txt", f"rc={ldd.returncode}\n{ldd.stdout}{ldd.stderr}")

        peer_pid_path = raw / "peer.pid"
        peer_proc, peer_thread, _peer_holder = start_logged(
            names["peer"],
            "echo $$ > /run/raw/peer.pid; exec /native-peer",
            raw / "peer-native.log",
            raw / "peer.command.txt",
            events, lock, "peer",
        )
        threads.append(peer_thread)
        peer_pid = wait_pid(peer_pid_path, peer_proc)
        peer_state, peer_argv, peer_error = process_args(names["peer"], peer_pid) if peer_pid else ("absent", "", "")
        write_text(raw / "peer-identity.txt", f"pid={peer_pid}\nstate={peer_state}\nargs={peer_argv!r}\nerror={peer_error!r}\n")
        if peer_state != "present" or "/native-peer" not in peer_argv:
            result["reason"] = "native peer process identity was not verified"
            return result

        wasm_pid_path = raw / "wasm-checkpoint.pid"
        wasm_proc, wasm_thread, wasm_holder = start_logged(
            names["wamr"],
            "echo $$ > /run/raw/wasm-checkpoint.pid; exec /runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 --native-lib=/runtime/libcr_state_probe.so /artifact/echoback_string.wasm",
            raw / "wasm-checkpoint.log",
            raw / "wasm-checkpoint.command.txt",
            events, lock, "checkpoint",
        )
        threads.append(wasm_thread)
        wasm_pid = wait_pid(wasm_pid_path, wasm_proc)
        wasm_state, wasm_argv, wasm_error = process_args(names["wamr"], wasm_pid) if wasm_pid else ("absent", "", "")
        write_text(
            raw / "wasm-checkpoint-identity.txt",
            f"collector_pid={wasm_proc.pid}\ncontainer_pid={wasm_pid}\nstate={wasm_state}\n"
            f"args={wasm_argv!r}\nerror={wasm_error!r}\n",
        )
        if wasm_state != "present" or not expected_iwasm(wasm_argv, False):
            result["reason"] = "checkpoint iwasm identity was not verified"
            return result

        window, status, _snap = wait_for_window(
            events, lock, wasm_proc, wasm_source="checkpoint", min_exclusive=None, stall_s=STALL_S,
        )
        if status != "pass":
            observed = snapshot(events, lock)
            result["reason"] = (
                f"pre-checkpoint gate {status}; last boundary: "
                + boundary_summary(observed, wasm_source="checkpoint")
            )
            result["verdict"] = "FAIL" if status == "process-exited" else "STOP"
            return result

        if mode == "control":
            markers = parse_state_log(raw / "wasm-checkpoint.log")
            armed_by_id = {item["id"]: item["value"] for item in markers["armed"]}
            continuity = []
            for loop in markers["loops"]:
                expected_s = armed_by_id.get(loop["id"] - 1)
                if expected_s is None:
                    continue
                continuity.append(
                    {
                        "id": loop["id"],
                        "expected": expected_s,
                        "guest": loop["guest"],
                        "host": loop["host"],
                        "guest_ok": loop["guest"] == expected_s,
                        "host_ok": loop["host"] == expected_s,
                    }
                )
            write_text(raw / "probe-timeline.json", json.dumps(continuity, indent=2) + "\n")
            result["application_roundtrip_pass"] = True
            result["pre_window"] = window["ids"]
            result["guest_probe_continuity"] = bool(continuity) and all(
                item["guest_ok"] for item in continuity
            )
            result["native_probe_continuity"] = bool(continuity) and all(
                item["host_ok"] for item in continuity
            )
            result["probe_continuity_observations"] = len(continuity)
            if result["guest_probe_continuity"] and result["native_probe_continuity"]:
                result["verdict"] = "PASS"
                result["reason"] = (
                    f"no-C/R control passed 10-roundtrip gate with "
                    f"{len(continuity)} sentinel continuity observations"
                )
            else:
                result["verdict"] = "FAIL"
                result["reason"] = "no-C/R sentinel continuity failed"
            stop_pid(names["wamr"], wasm_pid, False, raw / "wasm-control-stop.log")
            return result

        wasm_state, wasm_argv, wasm_error = process_args(names["wamr"], wasm_pid)
        if wasm_state != "present" or not expected_iwasm(wasm_argv, False):
            result["reason"] = f"iwasm identity changed before SIGUSR2: {wasm_argv!r} {wasm_error!r}"
            return result
        state_markers = parse_state_log(raw / "wasm-checkpoint.log")
        if not state_markers["armed"]:
            result["reason"] = "10-roundtrip gate passed without an armed sentinel marker"
            return result
        armed = state_markers["armed"][-1]
        result["saved_sentinel"] = armed["value"]
        result["checkpoint_armed_id"] = armed["id"]
        write_text(
            raw / "checkpoint-boundary.json",
            json.dumps(
                {
                    "armed_id": armed["id"],
                    "saved_sentinel": armed["value"],
                    "saved_sentinel_hex": f"0x{armed['value']:08x}",
                    "armed_mono_ns": armed["mono"],
                    "pre_window": window["ids"],
                },
                indent=2,
            )
            + "\n",
        )
        signal_mono = mono_ns()
        signal_utc = utc_now()
        signal = docker(["exec", names["wamr"], "kill", "-USR2", str(wasm_pid)], timeout=15)
        signal_done_mono = mono_ns()
        write_text(
            raw / "checkpoint-signal.log",
            f"command_start_utc={signal_utc}\ncommand_start_mono_ns={signal_mono}\n"
            f"command_return_mono_ns={signal_done_mono}\ncallback_mono_ns={window['callback_mono']}\n"
            f"callback_utc={window['callback_utc']}\nclosing_id={window['closing_id']}\n"
            f"window={window['ids']}\nrc={signal.returncode}\nstdout={signal.stdout!r}\n"
            f"stderr={signal.stderr!r}\nargs={wasm_argv!r}\n"
            f"delay_from_10th_callback_ns={signal_mono - window['callback_mono']}\n",
        )
        if signal.returncode:
            result["verdict"] = "FAIL"
            result["reason"] = "SIGUSR2 command failed"
            result["checkpointed"] = False
            return result

        wasm_thread.join(timeout=600)
        exit_status = wasm_holder.get("exit")
        exit_mono = None
        for line in (raw / "wasm-checkpoint.log").read_text(encoding="utf-8", errors="replace").splitlines():
            if "event=collector_process_exit" in line:
                match = MONO_RE.search(line)
                exit_mono = int(match.group(1)) if match else None
        if exit_status != 0 or exit_mono is None:
            result["verdict"] = "FAIL"
            result["reason"] = f"checkpoint process exit status {exit_status}"
            result["checkpointed"] = True
            return result
        stable_mono = None
        for _ in range(50):
            if state_ready(state_dir):
                size_a = (state_dir / "main-memory.img").stat().st_size
                time.sleep(0.2)
                size_b = (state_dir / "main-memory.img").stat().st_size
                if size_a == size_b:
                    stable_mono = mono_ns()
                    break
            time.sleep(0.2)
        if stable_mono is None:
            result["verdict"] = "FAIL"
            result["reason"] = "checkpoint exited but memory/socket state was not written"
            result["checkpointed"] = True
            return result
        result["checkpointed"] = True
        state_complete_mono = exit_mono if (state_dir / "main-memory.img").stat().st_size >= 1024 ** 3 else stable_mono
        manifest = state_manifest(state_dir, raw)
        if manifest["main_memory"] < 1024 ** 3 or manifest["main_socket"] <= 0:
            result["verdict"] = "FAIL"
            result["reason"] = "checkpoint state image missing after hash"
            return result

        observed = snapshot(events, lock)
        publishes = [obs for obs in observed if obs.source == "checkpoint" and obs.kind == "publish"]
        if not publishes:
            result["verdict"] = "FAIL"
            result["reason"] = "no checkpoint publish IDs"
            return result
        pre_done = completions(observed, wasm_source="checkpoint")
        result["pre_complete_ids"] = sorted(pre_done)
        boundary_n = max(obs.mid for obs in publishes)
        signal_markers = parse_state_log(raw / "wasm-checkpoint.log")
        armed_at_signal = [
            item
            for item in signal_markers["armed"]
            if item["mono"] is not None and item["mono"] <= signal_done_mono
        ]
        if not armed_at_signal or armed_at_signal[-1]["id"] != armed["id"]:
            result["verdict"] = "FAIL"
            result["reason"] = "armed sentinel advanced between boundary capture and SIGUSR2"
            return result
        if boundary_n != armed["id"]:
            result["verdict"] = "FAIL"
            result["reason"] = (
                f"checkpoint publish boundary id={boundary_n} does not match armed id={armed['id']}"
            )
            return result
        extra = [obs.mid for obs in publishes if window["callback_mono"] < obs.mono <= signal_mono]
        result["N"] = boundary_n
        result["timings_ns"]["checkpoint"] = state_complete_mono - signal_mono
        result["timings_ns"]["checkpoint_signal_to_process_exit"] = exit_mono - signal_mono
        result["timings_ns"]["state_hash"] = manifest["hash_elapsed_ns"]
        result["timings_ns"]["tenth_callback_to_sigusr2"] = signal_mono - window["callback_mono"]
        result["utc"]["sigusr2"] = signal_utc
        result["extra_publishes_before_signal"] = extra
        result["pre_window"] = window["ids"]
        write_text(raw / "checkpoint-boundary.txt", f"N={boundary_n}\nextra_publishes={extra}\nwindow={window['ids']}\n")

        restore_container = names["wamr"]
        if mode == "changed":
            wasm_state, _args, _error = process_args(names["wamr"], wasm_pid)
            if wasm_state != "absent":
                result["verdict"] = "FAIL"
                result["reason"] = "source iwasm still present before changed-IP restore"
                return result
            again = network_info()
            occupied = occupied_ips(again)
            if "172.18.0.6" in occupied or names["dest"] in existing_names():
                result["verdict"] = "STOP"
                result["reason"] = f"destination IP or name became busy: {occupied.get('172.18.0.6')}"
                return result
            dest_args = [
                "--network", NETWORK, "--ip", "172.18.0.6",
                *mount(raw, "/run/raw"),
                *mount(IWASM.parent, "/runtime", readonly=True),
                *mount(WASM.parent, "/artifact", readonly=True),
                *mount(state_dir, "/state"),
                "--workdir", "/state", IMAGE, "sleep", "infinity",
            ]
            create_container(names["dest"], label, dest_args, command_log)
            created.append(names["dest"])
            write_text(raw / "dest-inspect.json", docker(["inspect", names["dest"]]).stdout)
            restore_container = names["dest"]

        hashes_after, mismatch_after = verify_hashes(expected)
        write_text(raw / "hashes-before-restore.json", json.dumps(hashes_after, indent=2) + "\n")
        if mismatch_after:
            result["verdict"] = "STOP"
            result["reason"] = f"artifact hash changed before restore: {mismatch_after}"
            return result

        restore_pid_path = raw / "wasm-restore.pid"
        restore_mono = mono_ns()
        restore_utc = utc_now()
        restore_proc, restore_thread, restore_holder = start_logged(
            restore_container,
            "echo $$ > /run/raw/wasm-restore.pid; exec /runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 --native-lib=/runtime/libcr_state_probe.so --restore /artifact/echoback_string.wasm",
            raw / "wasm-restore.log",
            raw / "wasm-restore.command.txt",
            events, lock, "restore",
        )
        threads.append(restore_thread)
        restore_pid = wait_pid(restore_pid_path, restore_proc)
        restore_state, restore_argv, restore_error = process_args(restore_container, restore_pid) if restore_pid else ("absent", "", "")
        write_text(
            raw / "wasm-restore-identity.txt",
            f"collector_pid={restore_proc.pid}\ncontainer_pid={restore_pid}\nstate={restore_state}\n"
            f"args={restore_argv!r}\nerror={restore_error!r}\ncommand_start_utc={restore_utc}\n"
            f"command_start_mono_ns={restore_mono}\n",
        )
        if restore_state != "present" or not expected_iwasm(restore_argv, True):
            result["verdict"] = "FAIL"
            result["reason"] = "restore iwasm identity was not verified"
            return result

        post_window, post_status, _post_snap = wait_for_window(
            events, lock, restore_proc, wasm_source="restore", min_exclusive=boundary_n, stall_s=STALL_S,
        )
        final_events = snapshot(events, lock)
        stage = restore_stage_from_log(raw / "wasm-restore.log", restore_mono)
        result["restore_stage"] = stage
        result["post_boundary"] = boundary_summary(final_events, wasm_source="restore", min_exclusive=boundary_n)
        if stage.get("status") == "estimated":
            result["timings_ns"]["restore_stage"] = stage["elapsed_from_restore_command_ns"]
            result["utc"]["restore_stage_end_note"] = "estimated from last Finish to restore stack before application output"
        else:
            result["timings_ns"]["restore_stage"] = None

        restore_markers = parse_state_log(raw / "wasm-restore.log")
        first_loop = restore_markers["loops"][0] if restore_markers["loops"] else None
        first_refresh = restore_markers["refresh"][0] if restore_markers["refresh"] else None
        expected_probe_ip = "172.18.0.3" if mode == "same" else "172.18.0.6"
        result["guest_state_preserved"] = bool(
            first_loop and first_loop["guest"] == result["saved_sentinel"]
        )
        result["native_state_reset"] = bool(first_loop and first_loop["host"] == 0)
        result["netif_default_restored_nonnull"] = bool(
            first_refresh
            and first_refresh["default"] not in ("(nil)", "0x0", "0", "NULL", "null")
        )
        result["netif_points_to_restored_object"] = bool(
            first_refresh and first_refresh["same"] == 1
        )
        result["stored_ip_before_refresh"] = (
            None if first_refresh is None else ip_text(first_refresh["stored"])
        )
        result["probed_ip_before_refresh"] = (
            None if first_refresh is None else ip_text(first_refresh["probed"])
        )
        result["startup_reran"] = bool(restore_markers["init"])
        result["first_post_restore_guest_native"] = first_loop
        result["first_post_restore_netif_refresh"] = first_refresh
        result["application_roundtrip_pass"] = post_status == "pass"
        result["destination_ip_observed_after_refresh"] = any(
            item["mono"] > first_refresh["mono"] and ip_text(item["stored"]) == expected_probe_ip
            for item in restore_markers["refresh"]
        ) if first_refresh is not None else False
        state_gate_pass = all(
            (
                result["guest_state_preserved"],
                result["native_state_reset"],
                result["netif_default_restored_nonnull"],
                result["netif_points_to_restored_object"],
                result["stored_ip_before_refresh"] == "172.18.0.3",
                result["probed_ip_before_refresh"] == expected_probe_ip,
                not result["startup_reran"],
            )
        )
        if mode == "changed":
            state_gate_pass = state_gate_pass and result["destination_ip_observed_after_refresh"]

        if post_status == "pass":
            if not state_gate_pass:
                result["verdict"] = "FAIL"
                result["reason"] = "application gate passed but one or more state-boundary gates failed"
                stop_pid(restore_container, restore_pid, True, raw / "wasm-restore-stop.log")
                return result
            post_done = completions(final_events, wasm_source="restore", min_exclusive=boundary_n)
            first_id = min(post_done, key=lambda mid: max(post_done[mid][kind].mono for kind in KINDS))
            first_callback = post_done[first_id]["callback"]
            first_receive = min(
                (obs for obs in final_events if obs.source == "peer" and obs.kind == "receive" and obs.mono >= restore_mono),
                key=lambda obs: obs.mono,
                default=None,
            )
            last_pre = max(pre_done, key=lambda mid: pre_done[mid]["callback"].mono)
            result["verdict"] = "PASS"
            result["reason"] = f"post window {post_window['ids']}"
            result["post_window"] = post_window["ids"]
            result["timings_ns"]["recovery_to_first_new_callback"] = first_callback.mono - restore_mono
            result["timings_ns"]["restore_to_first_peer_receive"] = (
                None if first_receive is None else first_receive.mono - restore_mono
            )
            result["timings_ns"]["last_pre_callback_to_first_post_callback"] = (
                first_callback.mono - pre_done[last_pre]["callback"].mono
            )
            result["utc"]["restore_command"] = restore_utc
            result["utc"]["first_new_callback"] = first_callback.utc
            result["first_new_id"] = first_id
            result["first_peer_receive_id"] = None if first_receive is None else first_receive.mid
            stop_pid(restore_container, restore_pid, True, raw / "wasm-restore-stop.log")
            return result

        elapsed = mono_ns() - restore_mono
        result["timings_ns"]["unresolved_or_fail_elapsed_from_restore"] = elapsed
        result["utc"]["restore_command"] = restore_utc
        if post_status == "process-exited":
            result["verdict"] = "FAIL"
            result["reason"] = f"restore process exited before 10 new round trips; last boundary: {result['post_boundary']}"
        else:
            result["verdict"] = "UNRESOLVED"
            result["reason"] = (
                f"operator stall {STALL_S}s without a longer consecutive post-restore run; "
                f"elapsed_ns={elapsed}; last boundary: {result['post_boundary']}"
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
            remove_labeled(created, label, raw)
        except Exception as error:
            cleanup_error = error
        try:
            if result.get("verdict") == "PASS" and result.get("checkpointed") and cleanup_error is None:
                discard_pass_state(state_dir, trial_id, raw)
            elif result.get("checkpointed"):
                write_text(raw / "state-kept.txt", f"utc={utc_now()}\npath={state_dir}\nreason={result.get('reason')}\n")
        except Exception as error:
            cleanup_error = error
        if cleanup_error is not None:
            result["verdict"] = "STOP"
            result["reason"] += f"; cleanup error: {cleanup_error}"
        for thread in threads:
            thread.join(timeout=5)
        write_text(raw / "result.json", json.dumps(result, indent=2) + "\n")
        write_text(raw / "disk-after.txt", f"utc={utc_now()}\nfree_bytes={shutil.disk_usage('/tmp').free}\n")
        print(f"[CR-VAL] {trial_id} {result['verdict']} {result['reason']}", flush=True)


def probe_logs(expected):
    """No-checkpoint check that application lines are visible promptly."""
    label = "no-recover-log-probe"
    raw = RUN_DIR / "log-probe"
    if raw.exists():
        raise SystemExit(f"probe directory already exists: {raw}")
    raw.mkdir(parents=True)
    state_dir = STATE_ROOT / "log-probe"
    if state_dir.exists():
        raise SystemExit(f"probe state already exists: {state_dir}")
    names = ["mros2-cr-nurec-log-probe-wamr", "mros2-cr-nurec-log-probe-peer"]
    if set(names) & existing_names():
        raise SystemExit("probe container names already exist")
    net = network_info()
    occupied = occupied_ips(net)
    if "172.18.0.3" in occupied or "172.18.0.5" in occupied:
        raise SystemExit(f"probe IPs occupied: {occupied}")
    hashes, mismatch = verify_hashes(expected)
    if mismatch:
        raise SystemExit(f"hash mismatch before probe: {mismatch}")
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir()
    created = []
    try:
        command_log = raw / "docker-commands.log"
        create_container(names[0], label, [
            "--network", NETWORK, "--ip", "172.18.0.3",
            *mount(raw, "/run/raw"),
            *mount(IWASM.parent, "/runtime", readonly=True),
            *mount(WASM.parent, "/artifact", readonly=True),
            *mount(state_dir, "/state"),
            "--workdir", "/state", IMAGE, "sleep", "infinity",
        ], command_log)
        created.append(names[0])
        create_container(names[1], label, [
            "--network", NETWORK, "--ip", "172.18.0.5",
            *mount(PEER, "/native-peer", readonly=True),
            IMAGE, "sleep", "infinity",
        ], command_log)
        created.append(names[1])
        argv = [str(RTK), "proxy", "docker", "exec", names[0], "sh", "-c",
                "exec /runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 --native-lib=/runtime/libcr_state_probe.so /artifact/echoback_string.wasm"]
        write_text(raw / "command.txt", shlex.join(argv) + "\n")
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
        seen = False
        deadline = time.monotonic() + 25
        lines = []
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if line:
                lines.append(line)
                if "mros2-posix start!" in line or "publishing msg:" in line:
                    seen = True
                    break
            elif process.poll() is not None:
                break
        write_text(raw / "probe.log", "".join(lines))
        alive = process.poll() is None
        if alive:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        status = "visible" if seen else ("process-exited" if not alive else "not-visible")
        write_text(raw / "probe-result.txt", f"status={status}\nhashes={json.dumps(hashes)}\nlines={len(lines)}\n")
        print(f"[CR-VAL] log probe {status}", flush=True)
        return 0 if seen else (2 if not alive else 10)
    finally:
        remove_labeled(created, label, raw)
        if state_dir.exists() and not any(state_dir.iterdir()):
            state_dir.rmdir()


def summarize(results):
    def stats(rows, key):
        values = [row["timings_ns"][key] for row in rows if row.get("verdict") == "PASS" and row.get("timings_ns", {}).get(key) is not None]
        if not values:
            return {"n": 0}
        return {
            "n": len(values),
            "mean_s": sum(values) / len(values) / 1e9,
            "min_s": min(values) / 1e9,
            "max_s": max(values) / 1e9,
        }

    def count(mode):
        rows = [row for row in results if row["mode"] == mode]
        return {
            "trials": len(rows),
            "pass": sum(row["verdict"] == "PASS" for row in rows),
            "checkpoint": stats(rows, "checkpoint"),
            "restore_stage": stats(rows, "restore_stage"),
            "recovery": stats(rows, "recovery_to_first_new_callback"),
        }

    summary = {"same": count("same"), "changed": count("changed"), "trials": results}
    write_text(RUN_DIR / "summary.json", json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    import sys
    expected = load_expected_hashes()
    if len(sys.argv) == 2 and sys.argv[1] == "probe":
        return probe_logs(expected)
    if len(sys.argv) != 5 or sys.argv[1] != "run" or sys.argv[2] not in ("control", "same", "changed") or sys.argv[3] != "experimental":
        raise SystemExit("usage: campaign.py {probe|run <control|same|changed> experimental <1-3>}")
    try:
        index = int(sys.argv[4])
    except ValueError as error:
        raise SystemExit("trial must be an integer from 1 to 3") from error
    if index not in (1, 2, 3):
        raise SystemExit("trial must be an integer from 1 to 3")
    if sys.argv[2] in ("same", "changed"):
        control_results = sorted((RUN_DIR / "smoke" / "control").glob("run-*/result.json"))
        if not any(json.loads(path.read_text()).get("verdict") == "PASS" for path in control_results):
            raise SystemExit("a no-C/R control run must PASS before C/R trials")
    if sys.argv[2] == "changed":
        for same_index in (1, 2, 3):
            same_result = RUN_DIR / "smoke" / "same" / f"run-{same_index:02d}" / "result.json"
            if not same_result.exists() or json.loads(same_result.read_text()).get("verdict") != "PASS":
                raise SystemExit("all three same-IP trials must PASS before changed-IP trials")
    result = run_trial(sys.argv[2], index, expected, sys.argv[3])
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
