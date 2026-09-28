#!/usr/bin/env python3
"""Run one fixed-condition same-IP trial and always remove its containers."""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
REPO = Path("/home/osslab/mros2-wasm-service-communication-socket-journal")
STATE = Path("/tmp/mros2-wasm-sedp-hb-20260928-run67/state")
NETWORK = "mros2-cr-net"
EXPECTED_NETWORK = "609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408"
EXPECTED_IMAGE = "sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138"
PEER = "mros2-cr-run67-native-peer"
WIRE = "mros2-cr-run67-wiretap"
WAMR = "mros2-cr-run67-wamr"
CONTAINERS = (PEER, WIRE, WAMR)
HASHES = {
    "/tmp/mros2-wasm-cr-rerun-20260927/runtime/iwasm":
        "96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a",
    "/tmp/mros2-wasm-sedp-hb-20260928/app/echoback_string.wasm":
        "6cddd4b77fe1a5eaccf8de85af351272de6d228ce49ef1dfeafb6e4480195c81",
    "/tmp/mros2-posix-run04-final-build/mros2-posix":
        "8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1",
}
MIN_FREE_BYTES = 4 * 1024 ** 3

RESULT = {"experiment": "run-67"}
COMMANDS = []
PROCS = []
HANDLES = []
CREATED = []
CLEANED = False


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log(message):
    line = f"{utc_now()} {message}"
    print(line, flush=True)
    with (RAW / "orchestrator.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_cmd(args, cwd=None, timeout=120):
    COMMANDS.append({"utc": utc_now(), "argv": args})
    (RAW / "orchestrator-commands.txt").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in COMMANDS) + "\n",
        encoding="utf-8")
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, check=False)


def save_cmd(name, args, cwd=None, timeout=120):
    result = run_cmd(args, cwd=cwd, timeout=timeout)
    (RAW / name).write_text(
        result.stdout + ("\n--- stderr ---\n" + result.stderr if result.stderr else "")
        + f"\nrc={result.returncode}\n",
        encoding="utf-8")
    return result


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stop(reason, code=2):
    RESULT["stop"] = reason
    RESULT["code"] = code
    log(f"stop: {reason}")
    return code


def preflight():
    RAW.mkdir(parents=True, exist_ok=True)
    measured = []
    mismatch = []
    for path, expected in HASHES.items():
        file_path = Path(path)
        if not file_path.is_file():
            mismatch.append(f"missing {path}")
            continue
        digest = sha256_file(file_path)
        measured.append(f"{digest}  {path}")
        if digest != expected:
            mismatch.append(f"hash mismatch {path} {digest}")
        if path.endswith("mros2-posix") and not os.access(file_path, os.X_OK):
            mismatch.append(f"native peer is not executable {path}")
    (RAW / "artifact-hashes-preflight.txt").write_text("\n".join(measured) + "\n",
                                                       encoding="utf-8")
    if mismatch:
        (RAW / "preflight-mismatch.txt").write_text("\n".join(mismatch) + "\n",
                                                    encoding="utf-8")
        return stop("; ".join(mismatch))

    image = run_cmd(["rtk", "proxy", "docker", "image", "inspect", "ros:humble",
                     "--format", "{{.Id}}"])
    (RAW / "image-preflight.txt").write_text(image.stdout + image.stderr, encoding="utf-8")
    if image.stdout.strip() != EXPECTED_IMAGE:
        return stop(f"image id {image.stdout.strip()!r}")

    network = run_cmd(["rtk", "proxy", "docker", "network", "inspect", NETWORK])
    (RAW / "network-preflight.json").write_text(network.stdout, encoding="utf-8")
    try:
        network_doc = json.loads(network.stdout)[0]
    except (json.JSONDecodeError, IndexError) as error:
        return stop(f"network inspect unreadable: {error}")
    if network_doc.get("Id") != EXPECTED_NETWORK:
        return stop(f"network id {network_doc.get('Id')}")
    if network_doc.get("Containers"):
        return stop("mros2-cr-net already has containers attached")

    names = run_cmd(["rtk", "proxy", "docker", "ps", "-a", "--format", "{{.Names}}"])
    (RAW / "containers-preflight.txt").write_text(names.stdout, encoding="utf-8")
    existing = set(names.stdout.split())
    occupied = [name for name in CONTAINERS if name in existing]
    if occupied:
        return stop("container name in use: " + ",".join(occupied))

    free = run_cmd(["rtk", "proxy", "df", "-B1", "/tmp"])
    (RAW / "tmp-space-preflight.txt").write_text(free.stdout + free.stderr, encoding="utf-8")
    amounts = [int(value) for value in re.findall(r"\b\d{6,}\b", free.stdout)]
    if not amounts or amounts[-1] < MIN_FREE_BYTES:
        return stop(f"less than 4 GiB free on /tmp: {amounts[-1] if amounts else 'unknown'}")

    if STATE.exists() and any(STATE.iterdir()):
        return stop(f"{STATE} is not an empty unused directory")
    STATE.mkdir(parents=True, exist_ok=True)

    save_cmd("root-revision.txt",
             ["rtk", "proxy", "git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO)
    with (RAW / "root-revision.txt").open("a", encoding="utf-8") as handle:
        commit = run_cmd(["rtk", "proxy", "git", "rev-parse", "HEAD"], cwd=REPO)
        handle.write(commit.stdout)
    save_cmd("git-status-preflight.txt",
             ["rtk", "proxy", "git", "status", "--short"], cwd=REPO, timeout=180)
    save_cmd("staged-paths-preflight.txt",
             ["rtk", "proxy", "git", "diff", "--cached", "--name-only"], cwd=REPO, timeout=180)
    save_cmd("host-route-preflight.txt", ["rtk", "proxy", "ip", "route"])
    save_cmd("submodules-preflight.txt",
             ["rtk", "proxy", "git", "submodule", "status"], cwd=REPO, timeout=180)
    RESULT["preflight"] = "pass"
    log("preflight passed")
    return None


def docker_run(name, args):
    (RAW / f"{name}.command.txt").write_text(" ".join(args) + "\n", encoding="utf-8")
    result = run_cmd(args, timeout=180)
    (RAW / f"{name}.create.txt").write_text(
        result.stdout + result.stderr + f"\nrc={result.returncode}\n", encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"docker run failed for {name}: {result.stderr.strip()}")
    CREATED.append(args[args.index("--name") + 1])


def launch():
    docker_run("native-peer-container", [
        "rtk", "proxy", "docker", "run", "-d", "--name", PEER,
        "--network", NETWORK, "--ip", "172.18.0.5",
        "-v", "/tmp/mros2-posix-run04-final-build/mros2-posix:/native-peer:ro",
        "ros:humble", "sleep", "infinity",
    ])
    docker_run("wiretap-container", [
        "rtk", "proxy", "docker", "run", "-d", "--name", WIRE,
        "--network", f"container:{PEER}", "--cap-add", "NET_RAW",
        "-v", f"{ROOT}:/run", "-w", "/run",
        "ros:humble", "sleep", "infinity",
    ])
    docker_run("wamr-container", [
        "rtk", "proxy", "docker", "run", "-d", "--name", WAMR,
        "--network", NETWORK, "--ip", "172.18.0.3",
        "-v", "/tmp/mros2-wasm-cr-rerun-20260927/runtime:/runtime:ro",
        "-v", "/tmp/mros2-wasm-sedp-hb-20260928/app:/artifact:ro",
        "-v", f"{ROOT}:/run",
        "-v", f"{STATE}:/state",
        "-w", "/state",
        "ros:humble", "sleep", "infinity",
    ])
    for name in CONTAINERS:
        save_cmd(f"{name}.inspect.json", ["rtk", "proxy", "docker", "inspect", name], timeout=60)
    peer_ip = run_cmd(["rtk", "proxy", "docker", "inspect", "-f",
                       "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", PEER])
    wamr_ip = run_cmd(["rtk", "proxy", "docker", "inspect", "-f",
                       "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", WAMR])
    (RAW / "assigned-ips.txt").write_text(
        f"peer={peer_ip.stdout.strip()}\nwamr={wamr_ip.stdout.strip()}\n", encoding="utf-8")
    if peer_ip.stdout.strip() != "172.18.0.5" or wamr_ip.stdout.strip() != "172.18.0.3":
        return stop("assigned IP differed from 172.18.0.5 or 172.18.0.3")
    images = []
    for name in (PEER, WAMR):
        image = run_cmd(["rtk", "proxy", "docker", "inspect", "-f", "{{.Image}}", name])
        images.append(f"{name} {image.stdout.strip()}")
        if image.stdout.strip() != EXPECTED_IMAGE:
            (RAW / "container-image-ids.txt").write_text("\n".join(images) + "\n", encoding="utf-8")
            return stop(f"{name} image id {image.stdout.strip()}")
    (RAW / "container-image-ids.txt").write_text("\n".join(images) + "\n", encoding="utf-8")
    save_cmd("network-after-launch.json",
             ["rtk", "proxy", "docker", "network", "inspect", NETWORK], timeout=60)
    log("containers launched")
    return None


def spawn(args, stdout_name):
    handle = (RAW / stdout_name).open("w", encoding="utf-8")
    HANDLES.append(handle)
    proc = subprocess.Popen(args, stdout=handle, stderr=subprocess.STDOUT, text=True)
    PROCS.append(proc)
    log(f"spawned pid={proc.pid} {' '.join(args)}")
    return proc


def wait_for_text(path, needle, timeout_s):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() and needle in path.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(0.1)
    return False


def run_phases():
    peer_proc = spawn([sys.executable, str(ROOT / "peer_collector.py"), PEER, str(RAW)],
                      "peer-collector.stdout.log")
    if not wait_for_text(RAW / "peer-native.log", "ip=172.18.0.5", 30):
        return stop("native peer did not log ip=172.18.0.5")
    if peer_proc.poll() is not None:
        return stop(f"native peer collector exited early status={peer_proc.returncode}")
    wait_for_text(RAW / "peer-native.log", "event=peer_ready", 30)
    spawn([sys.executable, str(ROOT / "wiretap_collector.py"), WIRE, str(RAW)],
          "wiretap-collector.stdout.log")
    wait_for_text(RAW / "wiretap.stdout.log", "capture_ready", 15)
    spawn([sys.executable, str(ROOT / "run_wasm_phase.py"), "checkpoint", WAMR],
          "wasm-checkpoint.collector.stdout.log")

    pre = subprocess.run([sys.executable, str(ROOT / "roundtrip_evidence_gate.py"), "pre"],
                         check=False, text=True)
    RESULT["pre_gate_rc"] = pre.returncode
    log(f"pre-gate rc={pre.returncode}")
    if pre.returncode != 0:
        RESULT["checkpoint"] = "not_run_pre_gate_failed"
        RESULT["startup_only"] = "pre_gate_failed"
        return 0

    RESULT["checkpoint"] = "not_run_startup_probe_only"
    RESULT["startup_only"] = "pre_gate_pass"
    return 0

    baseline = subprocess.run([sys.executable, str(ROOT / "roundtrip_evidence_gate.py"), "baseline"],
                              check=False, text=True)
    RESULT["baseline_rc"] = baseline.returncode
    log(f"baseline rc={baseline.returncode}")
    if baseline.returncode != 0:
        RESULT["checkpoint"] = "not_run_baseline_failed"
        return 0

    signal_result = subprocess.run([sys.executable, str(ROOT / "send_checkpoint_signal.py")],
                                   check=False, text=True)
    RESULT["signal_rc"] = signal_result.returncode
    log(f"signal rc={signal_result.returncode}")
    signal_text = (RAW / "checkpoint-signal.log").read_text(encoding="utf-8") if (
        RAW / "checkpoint-signal.log").exists() else ""
    match = re.search(r"checkpoint_max_publish_id=(\d+)", signal_text)
    if signal_result.returncode != 0 or not match:
        RESULT["checkpoint"] = "signal_failed"
        return 0
    checkpoint_max = int(match.group(1))
    RESULT["checkpoint_max_publish_id"] = checkpoint_max

    deadline = time.time() + 180
    while time.time() < deadline and not (RAW / "wasm-checkpoint.status").exists():
        time.sleep(0.2)
    if not (RAW / "wasm-checkpoint.status").exists():
        RESULT["checkpoint"] = "timed_out_before_exit"
        return 0
    status = (RAW / "wasm-checkpoint.status").read_text(encoding="utf-8")
    exit_match = re.search(r"host_exit_status=(\d+)", status)
    RESULT["checkpoint_exit"] = int(exit_match.group(1)) if exit_match else None
    log(f"checkpoint exit={RESULT['checkpoint_exit']}")
    if RESULT["checkpoint_exit"] != 0:
        RESULT["restore"] = "not_run_checkpoint_exit_nonzero"
        return 0

    spawn([sys.executable, str(ROOT / "run_wasm_phase.py"), "restore", WAMR],
          "wasm-restore.collector.stdout.log")
    post = subprocess.run([sys.executable, str(ROOT / "roundtrip_evidence_gate.py"),
                           "post", str(checkpoint_max)], check=False, text=True)
    RESULT["post_gate_rc"] = post.returncode
    log(f"post-gate rc={post.returncode}")
    return 0


def container_exists(name):
    result = run_cmd(["rtk", "proxy", "docker", "inspect", name], timeout=30)
    return result.returncode == 0


def topic_list():
    if (RAW / "topic-list.log").exists() or not container_exists(PEER):
        return
    command = ["rtk", "proxy", "timeout", "8", "docker", "exec", PEER, "bash", "-lc",
               "source /opt/ros/humble/setup.bash; ROS_LOG_DIR=/tmp ROS_HOME=/tmp "
               "ros2 topic list --no-daemon"]
    (RAW / "topic-list.command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    result = run_cmd(command, timeout=20)
    (RAW / "topic-list.log").write_text(
        result.stdout + result.stderr + f"\nrc={result.returncode}\n", encoding="utf-8")


def kill_recorded(container, pid_file):
    if not pid_file.exists() or not container_exists(container):
        return f"{pid_file.name}:absent"
    pid = pid_file.read_text(encoding="utf-8").strip()
    if not pid.isdigit():
        return f"{pid_file.name}:invalid"
    result = run_cmd(["rtk", "proxy", "docker", "exec", container, "kill", "-TERM", pid],
                     timeout=20)
    return f"{pid_file.name}:rc={result.returncode}"


def cleanup():
    global CLEANED
    if CLEANED:
        return RESULT.get("cleanup", "already")
    CLEANED = True
    notes = []
    try:
        topic_list()
    except Exception as error:
        notes.append(f"topic_list_error={error}")
    for name in CONTAINERS:
        if container_exists(name):
            save_cmd(f"{name}.pre-stop.ps.txt",
                     ["rtk", "proxy", "docker", "exec", name, "ps", "-eo", "pid,args"],
                     timeout=20)
    if (RAW / "wasm-restore.pid").exists():
        notes.append(kill_recorded(WAMR, RAW / "wasm-restore.pid"))
    else:
        notes.append(kill_recorded(WAMR, RAW / "wasm-checkpoint.pid"))
    notes.append(kill_recorded(PEER, RAW / "peer-app.pid"))
    notes.append(kill_recorded(WIRE, RAW / "wiretap.pid"))
    existing = [name for name in CONTAINERS if container_exists(name)]
    if existing:
        save_cmd("containers-pre-cleanup.txt",
                 ["rtk", "proxy", "docker", "ps", "-a", "--filter", "name=mros2-cr-run67",
                  "--format", "{{.Names}} {{.Status}}"], timeout=30)
        stopped = run_cmd(["rtk", "proxy", "docker", "stop", "-t", "5", *existing], timeout=40)
        (RAW / "docker-stop.txt").write_text(
            stopped.stdout + stopped.stderr + f"\nrc={stopped.returncode}\n", encoding="utf-8")
        removed = run_cmd(["rtk", "proxy", "docker", "rm", *existing], timeout=40)
        (RAW / "docker-rm.txt").write_text(
            removed.stdout + removed.stderr + f"\nrc={removed.returncode}\n", encoding="utf-8")
        notes.append(f"stop_rc={stopped.returncode} rm_rc={removed.returncode}")
    else:
        notes.append("no containers left")
    for proc in PROCS:
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.terminate()
            notes.append(f"terminated host pid {proc.pid}")
    for handle in HANDLES:
        handle.close()
    save_cmd("containers-post-cleanup.txt",
             ["rtk", "proxy", "docker", "ps", "-a", "--format", "{{.Names}}"], timeout=30)
    save_cmd("network-post-cleanup.json",
             ["rtk", "proxy", "docker", "network", "inspect", NETWORK], timeout=60)
    hash_state()
    save_cmd("git-status-postrun.txt",
             ["rtk", "proxy", "git", "status", "--short"], cwd=REPO, timeout=180)
    save_cmd("staged-paths-postrun.txt",
             ["rtk", "proxy", "git", "diff", "--cached", "--name-only"], cwd=REPO, timeout=180)
    before = (RAW / "staged-paths-preflight.txt").read_text(encoding="utf-8") if (
        RAW / "staged-paths-preflight.txt").exists() else ""
    after = (RAW / "staged-paths-postrun.txt").read_text(encoding="utf-8")
    before_names = {line.strip() for line in before.splitlines() if line.strip() and not line.startswith("rc=")}
    after_names = {line.strip() for line in after.splitlines() if line.strip() and not line.startswith("rc=") and line.strip() != "--- stderr ---"}
    (RAW / "staged-compare.txt").write_text(
        "unchanged\n" if before_names == after_names
        else "changed\nonly_before=" + ",".join(sorted(before_names - after_names))
        + "\nonly_after=" + ",".join(sorted(after_names - before_names)) + "\n",
        encoding="utf-8")
    RESULT["cleanup"] = "; ".join(notes)
    log("cleanup " + RESULT["cleanup"])
    return RESULT["cleanup"]


def hash_state():
    list_lines = []
    hash_lines = []
    if STATE.exists():
        for path in sorted(item for item in STATE.rglob("*") if item.is_file()):
            relative = path.relative_to(STATE).as_posix()
            list_lines.append(f"{path.stat().st_size} {relative}")
            hash_lines.append(f"{sha256_file(path)}  {relative}")
    (RAW / "checkpoint-state-files.txt").write_text(
        ("\n".join(list_lines) + "\n") if list_lines else "", encoding="utf-8")
    (RAW / "checkpoint-state-files.sha256").write_text(
        ("\n".join(hash_lines) + "\n") if hash_lines else "", encoding="utf-8")


def on_signal(signum, _frame):
    RESULT["signal"] = signum
    cleanup()
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    RESULT["start_utc"] = utc_now()
    code = 0
    try:
        stopped = preflight()
        if stopped:
            code = stopped
        else:
            stopped = launch()
            if stopped:
                code = stopped
            else:
                code = run_phases() or 0
                RESULT["code"] = code
    except Exception as error:
        RESULT["exception"] = f"{type(error).__name__}: {error}"
        RESULT["code"] = 1
        code = 1
        log(RESULT["exception"])
    finally:
        try:
            cleanup()
        except Exception as error:
            RESULT["cleanup_exception"] = f"{type(error).__name__}: {error}"
            log(RESULT["cleanup_exception"])
        RESULT["finish_utc"] = utc_now()
        (RAW / "orchestrator-result.json").write_text(
            json.dumps(RESULT, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        log(f"run67_finished code={RESULT.get('code')} stop={RESULT.get('stop')} "
            f"pre={RESULT.get('pre_gate_rc')} baseline={RESULT.get('baseline_rc')} "
            f"post={RESULT.get('post_gate_rc')}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
