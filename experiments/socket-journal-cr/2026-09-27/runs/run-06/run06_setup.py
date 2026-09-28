#!/usr/bin/env python3
"""Preflight, create, inspect, and remove only run-06 Docker containers."""

import json
import shlex
import shutil
import sys
import time
from pathlib import Path

from run06_common import (
    APP_DIR, CONTAINERS, EXPECTED_HASHES, IMAGE, IMAGE_ID, LABEL_KEY,
    LABEL_VALUE, NETWORK, PEER, RAW, REFERENCE_WIRETAP, ROOT, RUN_DIR,
    RUNTIME_DIR, STATE, TMP_ROOT, WASM, IWASM, docker, rtk, sha256,
    utc_now, write_new,
)


NETWORK_ID = "609362e37c7a945ba44d7f2416fe24159ed9d9adb36207f8eb844b95b3c37408"
SUBNET = "172.18.0.0/16"
CANDIDATE_IPS = {"172.18.0.3", "172.18.0.5", "172.18.0.6"}
MIN_FREE_BYTES = 4 * 1024**3


def checked(result, label):
    if result.returncode:
        raise RuntimeError(
            f"{label} failed rc={result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def inspect_network():
    output = checked(docker("network", "inspect", NETWORK, timeout=20), "network inspect")
    data = json.loads(output)[0]
    if data["Id"] != NETWORK_ID:
        raise RuntimeError(f"unexpected Docker network ID: {data['Id']}")
    subnet = data["IPAM"]["Config"][0]["Subnet"]
    if subnet != SUBNET:
        raise RuntimeError(f"unexpected Docker network subnet: {subnet}")
    return data


def existing_names():
    output = checked(docker("ps", "-a", "--format", "{{.Names}}"), "docker ps")
    return {line.strip() for line in output.splitlines() if line.strip()}


def occupied_ips(network):
    return {
        entry.get("IPv4Address", "").split("/")[0]: name
        for name, entry in (network.get("Containers") or {}).items()
        if entry.get("IPv4Address")
    }


def preflight(*, destination=False):
    network = inspect_network()
    names = existing_names()
    image_raw = checked(docker("image", "inspect", IMAGE), "image inspect")
    image = json.loads(image_raw)[0]
    if image["Id"] != IMAGE_ID:
        raise RuntimeError(f"unexpected {IMAGE} image ID: {image['Id']}")

    state = {
        "utc": utc_now(),
        "network": network,
        "image": {"id": image["Id"], "architecture": image["Architecture"], "os": image["Os"]},
        "existing_container_names": sorted(names),
        "candidate_ips": sorted(CANDIDATE_IPS),
        "occupied_ips": occupied_ips(network),
        "artifacts": {},
        "tmp_free_bytes": shutil.disk_usage("/tmp").free,
        "tmp_root_exists": TMP_ROOT.exists(),
        "destination_preflight": destination,
    }

    target_roles = ("destination",) if destination else ("source", "peer", "wiretap", "destination")
    target_names = {CONTAINERS[role] for role in target_roles}
    conflicts = sorted(target_names & names)
    if conflicts:
        raise RuntimeError(f"run-06 container names already exist: {conflicts}")

    occupied = occupied_ips(network)
    check_ips = {"172.18.0.6"} if destination else CANDIDATE_IPS
    ip_conflicts = {ip: occupied[ip] for ip in check_ips if ip in occupied}
    if ip_conflicts:
        raise RuntimeError(f"candidate Docker IPs are occupied: {ip_conflicts}")

    if destination:
        if not STATE.is_dir() or not any(STATE.iterdir()):
            raise RuntimeError(f"run-06 checkpoint state is absent or empty: {STATE}")
        for role in ("source", "peer"):
            result = docker("inspect", CONTAINERS[role])
            record = json.loads(checked(result, f"inspect {role}"))[0]
            if not record["State"]["Running"]:
                raise RuntimeError(f"run-06 {role} container is not running")
    else:
        if TMP_ROOT.exists():
            raise RuntimeError(f"refusing to reuse existing run-06 temp path: {TMP_ROOT}")
        if any(RAW.iterdir()):
            raise RuntimeError("run-06/raw is not empty; refusing to overwrite evidence")
        if state["tmp_free_bytes"] < MIN_FREE_BYTES:
            raise RuntimeError(f"less than 4 GiB free under /tmp: {state['tmp_free_bytes']}")
        if not REFERENCE_WIRETAP.is_file():
            raise RuntimeError(f"run-04 wiretap source is missing: {REFERENCE_WIRETAP}")
        for path, expected in EXPECTED_HASHES.items():
            if not path.is_file():
                raise RuntimeError(f"required artifact is missing: {path}")
            actual = sha256(path)
            state["artifacts"][str(path)] = {"sha256": actual, "expected": expected}
            if actual != expected:
                raise RuntimeError(f"artifact hash mismatch: {path}: {actual}")

    return state


def record_cmd(label, args, result, *, path):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"[{utc_now()}] {label} rc={result.returncode}\n")
        stream.write("command=" + shlex.join(["rtk", "proxy", *map(str, args)]) + "\n")
        stream.write(result.stdout)
        if result.stderr:
            stream.write("stderr:\n" + result.stderr)
        stream.write("\n")
        stream.flush()


def mount(src, dst, readonly=False):
    spec = f"type=bind,src={src},dst={dst}"
    if readonly:
        spec += ",readonly"
    return ["--mount", spec]


def run_container(role, args, created):
    name = CONTAINERS[role]
    command = [
        "run", "--detach", "--name", name,
        "--label", f"{LABEL_KEY}={LABEL_VALUE}",
        *args,
    ]
    result = docker(*command, timeout=120)
    record_cmd(f"create_{role}", command, result, path=RAW / "docker-commands.log")
    checked(result, f"create {role} container")
    created.append(name)
    return result.stdout.strip()


def container_inspect(name, filename):
    output = checked(docker("inspect", name, timeout=20), f"inspect {name}")
    write_new(RAW / filename, json.dumps(json.loads(output), indent=2) + "\n")
    record = json.loads(output)[0]
    if not record["State"]["Running"]:
        raise RuntimeError(f"container did not remain running: {name}")
    if record["Config"]["Labels"].get(LABEL_KEY) != LABEL_VALUE:
        raise RuntimeError(f"run label missing on {name}")
    return record


def record_routes(container, filename):
    lines = [f"utc={utc_now()}", f"container={container}"]
    for target in ("/proc/net/route", "/proc/net/dev", "/sys/class/net/eth0/address"):
        result = rtk(["docker", "exec", container, "cat", target], timeout=15)
        lines.extend((f"file={target}", f"returncode={result.returncode}",
                      result.stdout.rstrip(), f"stderr={result.stderr.rstrip()}"))
    write_new(RAW / filename, "\n".join(lines) + "\n")


def snapshot_routes(container, filename):
    if container not in {CONTAINERS["source"], CONTAINERS["peer"], CONTAINERS["destination"]}:
        raise SystemExit("route snapshot is restricted to run-06 containers")
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise SystemExit("provide a plain .txt filename, not a path")
    record_routes(container, filename)


def snapshot_processes(container, filename):
    if container not in {CONTAINERS["source"], CONTAINERS["peer"], CONTAINERS["destination"]}:
        raise SystemExit("process snapshot is restricted to run-06 containers")
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise SystemExit("provide a plain .txt filename, not a path")
    result = rtk(["docker", "exec", container, "ps", "-eo", "pid=,args="], timeout=15)
    body = (f"utc={utc_now()}\ncontainer={container}\nreturncode={result.returncode}\n"
            f"stdout:\n{result.stdout}stderr:\n{result.stderr}")
    write_new(RAW / filename, body)


def setup():
    data = None
    preflight_error = None
    try:
        data = preflight(destination=False)
    except Exception as error:
        preflight_error = f"{type(error).__name__}: {error}"
    preflight_record = {"result": "pass" if data is not None else "fail",
                        "error": preflight_error, "details": data}
    write_new(RAW / "preflight.json", json.dumps(preflight_record, indent=2) + "\n")
    write_new(RAW / "preflight.status", f"result={preflight_record['result']}\nerror={preflight_error or ''}\n")
    if preflight_error:
        raise RuntimeError(f"preflight failed; no containers created: {preflight_error}")

    created = []
    setup_log = RAW / "setup.log"
    try:
        TMP_ROOT.mkdir()
        STATE.mkdir()
        write_new(RAW / "docker-commands.log", "run-06 local Docker commands\n")

        wamr_args = [
            "--network", NETWORK, "--ip", "172.18.0.3",
            *mount(ROOT, "/repo", readonly=True),
            *mount(RUN_DIR, "/run"),
            *mount(RUNTIME_DIR, "/runtime", readonly=True),
            *mount(APP_DIR, "/artifact", readonly=True),
            *mount(STATE, "/state"),
            "--workdir", "/state", IMAGE, "sleep", "infinity",
        ]
        peer_args = [
            "--network", NETWORK, "--ip", "172.18.0.5",
            *mount(RUN_DIR, "/run"),
            *mount(PEER, "/native-peer", readonly=True),
            IMAGE, "sleep", "infinity",
        ]
        source_id = run_container("source", wamr_args, created)
        peer_id = run_container("peer", peer_args, created)

        wiretap_args = [
            "--network", f"container:{CONTAINERS['peer']}", "--cap-add", "NET_RAW",
            *mount(ROOT, "/repo", readonly=True),
            *mount(RUN_DIR, "/run", readonly=True),
            *mount(RAW, "/capture"),
            IMAGE, "python3", "/run/run06_wiretap.py", "/capture/peer-wire.jsonl",
        ]
        wiretap_id = run_container("wiretap", wiretap_args, created)
        for role in ("source", "peer", "wiretap"):
            container_inspect(CONTAINERS[role], f"{role}-container-inspect.json")
        network = json.loads(checked(docker("network", "inspect", NETWORK), "post-setup network inspect"))[0]
        write_new(RAW / "network-after-setup.json", json.dumps(network, indent=2) + "\n")
        record_routes(CONTAINERS["source"], "source-route-preflight.txt")
        peer_ldd = rtk(["docker", "exec", CONTAINERS["peer"], "sh", "-c", "ldd /native-peer"], timeout=15)
        write_new(RAW / "native-peer-ldd.txt",
                  f"returncode={peer_ldd.returncode}\n{peer_ldd.stdout}{peer_ldd.stderr}")

        capture_path = RAW / "peer-wire.jsonl"
        for _ in range(50):
            if capture_path.exists() and "capture_ready" in capture_path.read_text(encoding="utf-8", errors="replace"):
                break
            time.sleep(0.1)
        else:
            logs = docker("logs", CONTAINERS["wiretap"], timeout=15)
            raise RuntimeError(f"wiretap did not become ready: {logs.stdout} {logs.stderr}")

        write_new(setup_log, f"result=pass\nsource_container={source_id}\npeer_container={peer_id}\nwiretap_container={wiretap_id}\n")
        print(f"[CR-RUN06] setup complete: source=.3 peer=.5 wiretap=ready", flush=True)
    except Exception as error:
        with setup_log.open("a", encoding="utf-8") as stream:
            stream.write(f"result=fail\nerror={type(error).__name__}: {error}\n")
        for name in reversed(created):
            docker("rm", "--force", name, timeout=30)
        raise


def create_destination():
    data = None
    error_text = None
    try:
        data = preflight(destination=True)
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
    write_new(RAW / "preflight-destination.json",
              json.dumps({"result": "pass" if data is not None else "fail",
                          "error": error_text, "details": data}, indent=2) + "\n")
    if error_text:
        write_new(RAW / "preflight-destination.status", f"result=fail\nerror={error_text}\n")
        raise RuntimeError(f"destination preflight failed; no destination container created: {error_text}")
    write_new(RAW / "preflight-destination.status", "result=pass\n")

    args = [
        "--network", NETWORK, "--ip", "172.18.0.6",
        *mount(ROOT, "/repo", readonly=True),
        *mount(RUN_DIR, "/run"),
        *mount(RUNTIME_DIR, "/runtime", readonly=True),
        *mount(APP_DIR, "/artifact", readonly=True),
        *mount(STATE, "/state"),
        "--workdir", "/state", IMAGE, "sleep", "infinity",
    ]
    result = docker(
        "run", "--detach", "--name", CONTAINERS["destination"],
        "--label", f"{LABEL_KEY}={LABEL_VALUE}", *args, timeout=120,
    )
    record_cmd("create_destination", ["run", "--detach", "--name", CONTAINERS["destination"], *args],
               result, path=RAW / "docker-commands.log")
    checked(result, "create destination container")
    container_inspect(CONTAINERS["destination"], "destination-container-inspect.json")
    network = json.loads(checked(docker("network", "inspect", NETWORK), "destination network inspect"))[0]
    write_new(RAW / "network-after-destination.json", json.dumps(network, indent=2) + "\n")
    record_routes(CONTAINERS["destination"], "destination-route-preflight.txt")
    print("[CR-RUN06] destination container ready at 172.18.0.6", flush=True)


def state_manifest():
    if not STATE.is_dir():
        raise RuntimeError(f"state directory missing: {STATE}")
    entries = []
    for path in sorted(STATE.rglob("*")):
        if path.is_file():
            entries.append((path, path.stat().st_size, sha256(path)))
    if not entries:
        raise RuntimeError("checkpoint state directory is empty")
    sha_text = "".join(f"{digest}  {path.relative_to(STATE)}\n" for path, _size, digest in entries)
    detail = [f"utc={utc_now()}", f"state_dir={STATE}"]
    detail.extend(f"{size}\t{digest}\t{path.relative_to(STATE)}" for path, size, digest in entries)
    write_new(RAW / "checkpoint-state-files.sha256", sha_text)
    write_new(RAW / "checkpoint-state-files.txt", "\n".join(detail) + "\n")
    print(f"[CR-RUN06] state manifest recorded files={len(entries)}", flush=True)


def cleanup():
    pre = []
    for role, name in CONTAINERS.items():
        inspected = docker("inspect", name, timeout=15)
        if inspected.returncode:
            continue
        record = json.loads(inspected.stdout)[0]
        if record["Config"]["Labels"].get(LABEL_KEY) != LABEL_VALUE:
            raise RuntimeError(f"refusing to clean container without run-06 label: {name}")
        pre.append(record)
    write_new(RAW / "containers-pre-cleanup.json",
              json.dumps(pre, indent=2) + "\n")

    wire = CONTAINERS["wiretap"]
    if any(item["Name"].lstrip("/") == wire for item in pre):
        logs = docker("logs", wire, timeout=20)
        write_new(RAW / "wiretap.stdout.log", logs.stdout + logs.stderr)

    cleanup_lines = [f"utc={utc_now()}"]
    for role in ("wiretap", "destination", "source", "peer"):
        name = CONTAINERS[role]
        if not any(item["Name"].lstrip("/") == name for item in pre):
            cleanup_lines.append(f"{name}:absent")
            continue
        stopped = docker("stop", "--timeout", "5", name, timeout=20)
        cleanup_lines.append(f"{name}:stop_rc={stopped.returncode} out={stopped.stdout.strip()} err={stopped.stderr.strip()}")
        removed = docker("rm", name, timeout=20)
        cleanup_lines.append(f"{name}:rm_rc={removed.returncode} out={removed.stdout.strip()} err={removed.stderr.strip()}")
    write_new(RAW / "cleanup.log", "\n".join(cleanup_lines) + "\n")

    network = json.loads(checked(docker("network", "inspect", NETWORK), "post-cleanup network inspect"))[0]
    write_new(RAW / "network-post-cleanup.json", json.dumps(network, indent=2) + "\n")
    remaining = docker("ps", "-a", "--filter", f"label={LABEL_KEY}={LABEL_VALUE}",
                       "--format", "{{.ID}} {{.Names}} {{.Status}}")
    write_new(RAW / "containers-post-cleanup.txt", remaining.stdout + remaining.stderr)
    if remaining.returncode or remaining.stdout.strip() or network.get("Containers"):
        raise RuntimeError("cleanup verification failed; inspect containers-post-cleanup.txt and network-post-cleanup.json")
    print("[CR-RUN06] only run-06 containers removed; shared network preserved", flush=True)


def main():
    if len(sys.argv) == 2 and sys.argv[1] in {"setup", "destination", "state-manifest", "cleanup"}:
        {"setup": setup, "destination": create_destination,
         "state-manifest": state_manifest, "cleanup": cleanup}[sys.argv[1]]()
        return
    if len(sys.argv) == 4 and sys.argv[1] == "snapshot-routes":
        snapshot_routes(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "snapshot-processes":
        snapshot_processes(sys.argv[2], sys.argv[3])
        return
    raise SystemExit("usage: run06_setup.py {setup|destination|state-manifest|cleanup} | snapshot-routes|snapshot-processes CONTAINER FILENAME.txt")


if __name__ == "__main__":
    main()
