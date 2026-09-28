#!/usr/bin/env python3
"""Run a bounded SIGUSR1 no-op control on the instrumented mROS 2 Wasm app."""

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import subprocess
import threading
import time


TAG = "[CR-RERUN-20260927-R05-SIGUSR1]"
NETWORK = "mros2-cr-net"
IMAGE = "ros:humble"
EXPECTED_IMAGE_ID = "sha256:1813d3c85d7f96ff7d3012d865204583255740182db5d0065f8f8cd029a83138"
PEER_NAME = "mros2-cr-run05-sigusr1-peer"
WAMR_NAME = "mros2-cr-run05-sigusr1-wamr"
PEER_IP = "172.18.0.5"
WAMR_IP = "172.18.0.3"
RUNTIME_DIR = Path("/tmp/mros2-wasm-cr-rerun-20260927/runtime")
APP_DIR = Path("/tmp/mros2-wasm-cr-rerun-20260927/app")
PEER_BINARY = Path("/tmp/mros2-posix-run04-final-build/mros2-posix")
STATE_DIR = Path("/tmp/mros2-wasm-cr-run05-sigusr1/state")
EXPECTED_HASHES = {
    RUNTIME_DIR / "iwasm": "96c9f1ae89a29e8b2ab87eccdb54df4f7e6203be6945413cc19052df09f3920a",
    APP_DIR / "echoback_string.wasm": "0a725f9a303650a64358964a6f6ef0cd84d5cc82734fcbeb87ec8f7dd1d8df76",
    PEER_BINARY: "8f41fa890a8da84c9000772bba2fb8287553bea1311ccf7fd4d5d0daed7b27b1",
}
PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")
RECEIVE_RE = re.compile(r"event=peer_receive topic=/to_linux id=(\d+)")
ECHO_RE = re.compile(r"event=peer_echo_publish_return topic=/to_stm id=(\d+)")
CALLBACK_RE = re.compile(r"APP callback topic=/to_stm id=(\d+)")
WASI_ERRNO_RE = re.compile(r"sock_recv_from_return wasi_fd=\d+ wasi_errno=(\d+)")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def docker(*args, check=True):
    result = subprocess.run(["rtk", "proxy", "docker", *map(str, args)],
                            capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"docker command failed rc={result.returncode}: {result.stderr.strip()}")
    return result


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def message_ids(pattern, text):
    return {int(value) for value in pattern.findall(text)}


def roundtrips(wasm_text, peer_text):
    return (message_ids(PUBLISH_RE, wasm_text)
            & message_ids(RECEIVE_RE, peer_text)
            & message_ids(ECHO_RE, peer_text)
            & message_ids(CALLBACK_RE, wasm_text))


def append_event(path, event, **fields):
    rendered = " ".join(f"{key}={json.dumps(value, ensure_ascii=False)}"
                        for key, value in fields.items())
    line = (f"{TAG} utc={utc_now()} mono_ns={time.monotonic_ns()} "
            f"event={event} {rendered}\n")
    with path.open("a", encoding="utf-8") as output:
        output.write(line)
        output.flush()
    print(line, end="", flush=True)


def read_file(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def peer_log_follower(container, output_path, stop_event, error_box):
    process = None
    try:
        process = subprocess.Popen(
            ["rtk", "proxy", "docker", "logs", "--follow", container],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        with output_path.open("w", encoding="utf-8") as output:
            while not stop_event.is_set():
                line = process.stdout.readline()
                if line:
                    output.write(line)
                    output.flush()
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.05)
    except Exception as exc:  # captured for the main thread's final verdict
        error_box.append(repr(exc))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


def main():
    run_dir = Path(__file__).resolve().parent
    raw = run_dir / "raw"
    raw.mkdir(exist_ok=True)
    wasm_log = raw / "wasm-sigusr1.log"
    peer_log = raw / "peer-native.log"
    signal_log = raw / "signal-control.log"
    status_path = raw / "signal-control.status"
    preflight_path = raw / "preflight.json"
    post_network_path = raw / "network-post-cleanup.json"
    for path in (wasm_log, peer_log, signal_log, status_path,
                 preflight_path, post_network_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing run artifact: {path}")
    if STATE_DIR.exists():
        raise SystemExit(f"refusing to reuse existing state path: {STATE_DIR}")
    for path in EXPECTED_HASHES:
        if not path.is_file():
            raise SystemExit(f"required run-04 artifact is missing: {path}")

    actual_hashes = {str(path): digest(path) for path in EXPECTED_HASHES}
    mismatches = {path: (EXPECTED_HASHES[Path(path)], actual)
                  for path, actual in actual_hashes.items()
                  if EXPECTED_HASHES[Path(path)] != actual}
    if mismatches:
        raise SystemExit(f"run-04 artifact hash mismatch: {mismatches}")

    existing = docker("ps", "-a", "--format", "{{.Names}}", check=True).stdout.splitlines()
    if PEER_NAME in existing or WAMR_NAME in existing:
        raise SystemExit("a run-05 container name already exists; refusing to reuse it")
    image_id = docker("image", "inspect", IMAGE, "--format", "{{.Id}}").stdout.strip()
    if image_id != EXPECTED_IMAGE_ID:
        raise SystemExit(f"image mismatch: expected {EXPECTED_IMAGE_ID}, got {image_id}")
    network = json.loads(docker("network", "inspect", NETWORK).stdout)[0]
    network_config = network.get("IPAM", {}).get("Config", [])
    subnets = [entry.get("Subnet") for entry in network_config]
    if "172.18.0.0/16" not in subnets:
        raise SystemExit(f"unexpected network subnet: {subnets}")
    if network.get("Containers"):
        raise SystemExit("shared experiment network is occupied; refusing to attach containers")
    preflight = {
        "utc": utc_now(), "network": NETWORK, "network_id": network.get("Id"),
        "subnets": subnets, "attachments_before": network.get("Containers", {}),
        "image": IMAGE, "image_id": image_id, "addresses": {"wasm": WAMR_IP, "peer": PEER_IP},
        "artifact_sha256": actual_hashes,
    }
    preflight_path.write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    STATE_DIR.mkdir(parents=True)

    peer_created = False
    wamr_created = False
    wasm_pid = None
    follower_stop = threading.Event()
    follower_errors = []
    follower = None
    result = "fail"
    details = {}
    try:
        peer_run = docker(
            "run", "--detach", "--name", PEER_NAME, "--network", NETWORK,
            "--ip", PEER_IP, "--volume", f"{PEER_BINARY}:/native-peer:ro",
            "--entrypoint", "/native-peer", IMAGE)
        peer_created = True
        append_event(signal_log, "peer_container_started", container_id=peer_run.stdout.strip())
        follower = threading.Thread(target=peer_log_follower,
                                    args=(PEER_NAME, peer_log, follower_stop, follower_errors),
                                    daemon=True)
        follower.start()

        repo_root = run_dir.parents[4]
        wamr_run = docker(
            "run", "--detach", "--name", WAMR_NAME, "--network", NETWORK,
            "--ip", WAMR_IP,
            "--volume", f"{repo_root}:/repo:ro",
            "--volume", f"{run_dir}:/run:rw",
            "--volume", f"{RUNTIME_DIR}:/runtime:ro",
            "--volume", f"{APP_DIR}:/artifact:ro",
            "--volume", f"{STATE_DIR}:/state:rw",
            "--workdir", "/state", IMAGE, "sleep", "infinity")
        wamr_created = True
        append_event(signal_log, "wamr_container_started", container_id=wamr_run.stdout.strip())

        remote = (
            "echo $$ > /run/raw/wasm-sigusr1.pid; "
            "exec /runtime/iwasm --addr-pool=0.0.0.0/0 --max-threads=32 -v=5 "
            "/artifact/echoback_string.wasm >> /run/raw/wasm-sigusr1.log 2>&1"
        )
        docker("exec", "--detach", "--workdir", "/state", WAMR_NAME, "sh", "-c", remote)
        pid_path = raw / "wasm-sigusr1.pid"
        pid_deadline = time.monotonic() + 10
        while not pid_path.is_file() and time.monotonic() < pid_deadline:
            time.sleep(0.05)
        pid_text = read_file(pid_path).strip()
        if not pid_text.isdigit():
            raise RuntimeError("iwasm PID file was not created")
        wasm_pid = int(pid_text)
        ps = docker("exec", WAMR_NAME, "ps", "-p", str(wasm_pid), "-o", "args=")
        process_args = ps.stdout.strip()
        if ps.returncode != 0 or "/runtime/iwasm" not in process_args or "/artifact/echoback_string.wasm" not in process_args:
            raise RuntimeError(f"iwasm process identity mismatch: {process_args!r}")
        append_event(signal_log, "wasm_process_verified", pid=wasm_pid, args=process_args)

        gate_deadline = time.monotonic() + 60
        initial_ids = set()
        while time.monotonic() < gate_deadline:
            wasm_text = read_file(wasm_log)
            peer_text = read_file(peer_log)
            initial_ids = roundtrips(wasm_text, peer_text)
            if "event=peer_ready" in peer_text and len(initial_ids) >= 10:
                break
            if "SIGUSR2 called" in wasm_text or "checkpoint done" in wasm_text:
                raise RuntimeError("unexpected checkpoint before SIGUSR1 control")
            time.sleep(0.1)
        if len(initial_ids) < 10 or "event=peer_ready" not in read_file(peer_log):
            raise RuntimeError(f"pre-signal roundtrip gate failed: ids={sorted(initial_ids)}")
        append_event(signal_log, "pre_signal_gate_pass", roundtrip_ids=sorted(initial_ids))

        errors_before = [int(value) for value in WASI_ERRNO_RE.findall(read_file(wasm_log))]
        if 27 in errors_before:
            raise RuntimeError(f"WASI errno 27 appeared before SIGUSR1: count={errors_before.count(27)}")
        before = {"utc": utc_now(), "mono_ns": time.monotonic_ns(), "pid": wasm_pid}
        sent = docker("exec", WAMR_NAME, "kill", "-USR1", str(wasm_pid), check=False)
        after = {"utc": utc_now(), "mono_ns": time.monotonic_ns(), "returncode": sent.returncode,
                 "stdout": sent.stdout.strip(), "stderr": sent.stderr.strip()}
        append_event(signal_log, "sigusr1_sent", before=before, after=after)
        if sent.returncode != 0:
            raise RuntimeError(f"SIGUSR1 delivery failed: {sent.stderr.strip()}")

        handler_deadline = time.monotonic() + 5
        while time.monotonic() < handler_deadline and "SIGUSR1 called" not in read_file(wasm_log):
            time.sleep(0.05)
        wasm_after_handler = read_file(wasm_log)
        if "SIGUSR1 called" not in wasm_after_handler:
            raise RuntimeError("WAMR did not log handling SIGUSR1")
        peer_after_handler = read_file(peer_log)
        ids_at_handler = roundtrips(wasm_after_handler, peer_after_handler)
        append_event(signal_log, "sigusr1_handler_seen", roundtrip_ids=sorted(ids_at_handler))

        observation_deadline = time.monotonic() + 8
        while time.monotonic() < observation_deadline:
            if follower_errors:
                raise RuntimeError(f"peer log follower failed: {follower_errors}")
            time.sleep(0.1)
        wasm_final = read_file(wasm_log)
        peer_final = read_file(peer_log)
        final_ids = roundtrips(wasm_final, peer_final)
        post_ids = final_ids - ids_at_handler
        errnos = [int(value) for value in WASI_ERRNO_RE.findall(wasm_final)]
        sigusr2_seen = "SIGUSR2 called" in wasm_final
        checkpoint_seen = "checkpoint done" in wasm_final
        details = {
            "pre_signal_roundtrip_ids": sorted(initial_ids),
            "roundtrip_ids_at_handler": sorted(ids_at_handler),
            "post_signal_roundtrip_ids": sorted(post_ids),
            "wasi_errno_27_count": errnos.count(27),
            "sigusr2_seen": sigusr2_seen,
            "checkpoint_seen": checkpoint_seen,
            "sigusr1_handler_seen": True,
        }
        if len(post_ids) < 5 or errnos.count(27) != 0 or sigusr2_seen or checkpoint_seen:
            raise RuntimeError(f"SIGUSR1 control criteria failed: {details}")
        result = "pass"
        append_event(signal_log, "sigusr1_control_pass", **details)

    except Exception as exc:
        details["failure"] = repr(exc)
        append_event(signal_log, "sigusr1_control_fail", error=repr(exc))
    finally:
        if wamr_created and wasm_pid is not None:
            check = docker("exec", WAMR_NAME, "ps", "-p", str(wasm_pid), "-o", "args=", check=False)
            args = check.stdout.strip()
            if check.returncode == 0 and "/runtime/iwasm" in args and "/artifact/echoback_string.wasm" in args:
                docker("exec", WAMR_NAME, "kill", "-TERM", str(wasm_pid), check=False)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    check = docker("exec", WAMR_NAME, "ps", "-p", str(wasm_pid), "-o", "args=", check=False)
                    if not check.stdout.strip():
                        break
                    time.sleep(0.1)
        if peer_created:
            docker("stop", "--time", "2", PEER_NAME, check=False)
            follower_stop.set()
            if follower is not None:
                follower.join(timeout=3)
            peer_tail = docker("logs", PEER_NAME, check=False)
            if peer_tail.returncode == 0:
                peer_log.write_text(peer_tail.stdout, encoding="utf-8")
            docker("rm", "--force", PEER_NAME, check=False)
        if wamr_created:
            docker("rm", "--force", WAMR_NAME, check=False)
        post = docker("network", "inspect", NETWORK, check=False)
        if post.returncode == 0:
            post_network_path.write_text(post.stdout, encoding="utf-8")
            post_data = json.loads(post.stdout)[0]
            attachments = post_data.get("Containers", {})
            append_event(signal_log, "cleanup_complete", network_attachments=attachments)
            if attachments:
                result = "fail"
                details["cleanup_failure"] = "shared network still has attachments"
        status = {"result": result, **details}
        status_path.write_text("".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n"
                                        for key, value in status.items()), encoding="utf-8")
        (raw / "containers-post-cleanup.txt").write_text(
            docker("ps", "-a", "--format", "{{.ID}} {{.Names}} {{.Status}} {{.Networks}}").stdout,
            encoding="utf-8")
        if follower is not None and follower.is_alive():
            follower_stop.set()
            follower.join(timeout=1)

    print(f"{TAG} result={result} status={status_path}", flush=True)
    return 0 if result == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
