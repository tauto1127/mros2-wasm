#!/usr/bin/env python3
"""Start a verified WAMR phase, signal its checkpoint, or stop its exact PID."""

from datetime import datetime, timezone
import re
import shlex
import os
import subprocess
import sys
import time

from run06_common import CONTAINERS, RAW, rtk, utc_now, mono_ns, write_new


PUBLISH_RE = re.compile(r"APP publish_begin topic=/to_linux id=(\d+)")


def process_args(container, pid):
    result = rtk(["docker", "exec", container, "sh", "-c", f"ps -p {pid} -o args="], timeout=10)
    if result.returncode:
        if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
            return "absent", "", ""
        return "error", "", result.stderr.strip() or result.stdout.strip()
    args = result.stdout.strip()
    if args.endswith("<defunct>"):
        return "absent", args, ""
    return ("absent" if not args else "present"), args, ""


def expected(args, phase):
    required = ("/runtime/iwasm", "--addr-pool=0.0.0.0/0", "--max-threads=32",
                "-v=5", "/artifact/echoback_string.wasm")
    if not all(item in args for item in required):
        return False
    return ("--restore" in args) == (phase == "restore")


def start(phase, container):
    wanted_container = CONTAINERS["source"] if phase == "checkpoint" else CONTAINERS["destination"]
    if container != wanted_container:
        raise SystemExit(f"{phase} must run in {wanted_container}, not {container}")
    log_path = RAW / f"wasm-{phase}.log"
    status_path = RAW / f"wasm-{phase}.status"
    pid_path = RAW / f"wasm-{phase}.pid"
    host_pid_path = RAW / f"wasm-{phase}.host-pid"
    command_path = RAW / f"wasm-{phase}.command.txt"
    for path in (log_path, status_path, pid_path, host_pid_path, command_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing run artifact: {path}")

    argv_in_container = ["/runtime/iwasm", "--addr-pool=0.0.0.0/0",
                         "--max-threads=32", "-v=5"]
    if phase == "restore":
        argv_in_container.append("--restore")
    argv_in_container.append("/artifact/echoback_string.wasm")
    remote_command = (
        f"echo $$ > /run/raw/wasm-{phase}.pid; exec {shlex.join(argv_in_container)}"
    )
    argv = ["rtk", "proxy", "docker", "exec", "--workdir", "/state",
            container, "sh", "-c", remote_command]
    write_new(command_path, shlex.join(argv) + "\n")
    started_utc = utc_now()
    started_ns = mono_ns()
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    write_new(host_pid_path, f"collector_pid={os.getpid()}\n"
              f"docker_exec_pid={process.pid}\nphase={phase}\ncontainer={container}\n")

    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"[CR-RUN06-WAMR] host_utc={started_utc} host_mono_ns={started_ns} "
                  f"phase={phase} event=launch container={container} host_pid={process.pid}\n")
        log.flush()
        deadline = time.monotonic() + 15
        guest_pid = None
        while time.monotonic() < deadline:
            if pid_path.exists():
                value = pid_path.read_text(encoding="utf-8").strip()
                if value.isdigit():
                    guest_pid = int(value)
                    break
            if process.poll() is not None:
                break
            time.sleep(0.1)

        if guest_pid is None:
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log.write(f"[CR-RUN06-WAMR] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                      f"phase={phase} event=pid_acquisition_failed output={output!r}\n")
            write_new(status_path, f"result=pid_acquisition_failed\nphase={phase}\n"
                      f"host_exit_status={process.returncode}\n")
            return 2

        state, args, error = process_args(container, guest_pid)
        if state != "present" or not expected(args, phase):
            process.terminate()
            output, _ = process.communicate(timeout=5)
            log.write(f"[CR-RUN06-WAMR] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                      f"phase={phase} event=process_identity_failed pid={guest_pid} "
                      f"state={state} args={args!r} error={error!r} output={output!r}\n")
            write_new(status_path, f"result=process_identity_failed\nphase={phase}\n"
                      f"container_pid={guest_pid}\nargs={args!r}\n")
            return 2

        verified_utc = utc_now()
        verified_ns = mono_ns()
        log.write(f"[CR-RUN06-WAMR] host_utc={verified_utc} host_mono_ns={verified_ns} "
                  f"phase={phase} container_pid={guest_pid} event=process_verified args={args!r}\n")
        log.flush()
        print(f"[CR-RUN06-WAMR] phase={phase} container_pid={guest_pid} event=process_verified",
              flush=True)
        line_count = 0
        for line in process.stdout:
            line_count += 1
            rendered = (f"[CR-RUN06-WAMR] host_utc={utc_now()} host_mono_ns={mono_ns()} "
                        f"phase={phase} container_pid={guest_pid} " + line.rstrip("\n") + "\n")
            log.write(rendered)
            log.flush()
            if line_count % 5000 == 0:
                print(f"[CR-RUN06-WAMR] phase={phase} log_lines={line_count}", flush=True)
        exit_status = process.wait()
        finish_utc = utc_now()
        finish_ns = mono_ns()
        write_new(status_path, f"result=process_exit\nphase={phase}\ncontainer={container}\n"
                  f"container_pid={guest_pid}\nstart_utc={started_utc}\n"
                  f"finish_utc={finish_utc}\nfinish_mono_ns={finish_ns}\n"
                  f"host_exit_status={exit_status}\n")
        log.write(f"[CR-RUN06-WAMR] host_utc={finish_utc} host_mono_ns={finish_ns} "
                  f"phase={phase} container_pid={guest_pid} event=process_exit exit_status={exit_status}\n")
        log.flush()
    return exit_status


def signal_checkpoint(container):
    if container != CONTAINERS["source"]:
        raise SystemExit(f"checkpoint signal is restricted to {CONTAINERS['source']}")
    marker = RAW / "gate-pass.ok"
    baseline = RAW / "no-cr-baseline.status"
    if not marker.is_file() or not baseline.is_file() or "result=pass" not in baseline.read_text():
        raise SystemExit("refusing checkpoint: pre-C/R gate and 30-second baseline must pass")
    log_path = RAW / "wasm-checkpoint.log"
    pid_path = RAW / "wasm-checkpoint.pid"
    signal_log = RAW / "checkpoint-signal.log"
    if signal_log.exists():
        raise SystemExit(f"refusing to overwrite {signal_log}")
    publishes = [int(v) for v in PUBLISH_RE.findall(log_path.read_text(encoding="utf-8", errors="replace"))]
    if not publishes or not pid_path.is_file():
        raise SystemExit("checkpoint publish IDs or PID are missing")
    pid_text = pid_path.read_text(encoding="utf-8").strip()
    if not pid_text.isdigit():
        raise SystemExit(f"invalid checkpoint PID: {pid_text!r}")
    pid = int(pid_text)
    state, args, error = process_args(container, pid)
    if state != "present" or not expected(args, "checkpoint"):
        raise SystemExit(f"checkpoint process identity check failed: state={state} args={args!r} error={error!r}")
    before_utc = utc_now()
    before_ns = mono_ns()
    result = rtk(["docker", "exec", container, "kill", "-USR2", str(pid)], timeout=10)
    after_utc = utc_now()
    after_ns = mono_ns()
    line = (f"[CR-RUN06] event=checkpoint_signal container={container} pid={pid} "
            f"checkpoint_max_publish_id={max(publishes)} publish_count={len(publishes)} "
            f"before_utc={before_utc} before_mono_ns={before_ns} "
            f"after_utc={after_utc} after_mono_ns={after_ns} "
            f"returncode={result.returncode} stdout={result.stdout.strip()!r} "
            f"stderr={result.stderr.strip()!r} process_args={args!r}\n")
    write_new(signal_log, line)
    print(line, end="", flush=True)
    if result.returncode:
        raise RuntimeError("checkpoint signal command failed")


def stop(phase, container):
    wanted = CONTAINERS["source"] if phase == "checkpoint" else CONTAINERS["destination"]
    if container != wanted:
        raise SystemExit(f"{phase} process stop is restricted to {wanted}")
    pid_path = RAW / f"wasm-{phase}.pid"
    log_path = RAW / f"wasm-{phase}-stop.log"
    if log_path.exists():
        raise SystemExit(f"refusing to overwrite {log_path}")
    if not pid_path.is_file():
        raise SystemExit(f"PID file missing: {pid_path}")
    pid_text = pid_path.read_text(encoding="utf-8").strip()
    if not pid_text.isdigit():
        raise SystemExit(f"invalid PID: {pid_text!r}")
    pid = int(pid_text)
    state, args, error = process_args(container, pid)
    if state == "absent":
        write_new(log_path, f"result=already-exited\ncontainer={container}\npid={pid}\n")
        return
    if state != "present" or not expected(args, phase):
        raise RuntimeError(f"refusing to signal unexpected process: state={state} args={args!r} error={error!r}")
    result = rtk(["docker", "exec", container, "kill", "-TERM", str(pid)], timeout=10)
    lines = [f"utc={utc_now()}", f"container={container}", f"pid={pid}",
             f"args={args!r}", f"sigterm_rc={result.returncode}",
             f"stdout={result.stdout.strip()!r}", f"stderr={result.stderr.strip()!r}"]
    for _ in range(40):
        state, current, error = process_args(container, pid)
        if state == "absent":
            lines.append("result=sigterm-exited")
            write_new(log_path, "\n".join(lines) + "\n")
            return
        if state != "present" or not expected(current, phase):
            lines.append(f"result=identity-no-longer-verifiable args={current!r} error={error!r}")
            write_new(log_path, "\n".join(lines) + "\n")
            raise RuntimeError("process identity became unverifiable while stopping")
        time.sleep(0.25)
    lines.append("result=still-running-after-sigterm")
    write_new(log_path, "\n".join(lines) + "\n")
    raise RuntimeError("expected run-06 iwasm is still running after SIGTERM; no broader stop was attempted")


def main():
    if len(sys.argv) == 3 and sys.argv[1] in ("checkpoint", "restore"):
        return start(sys.argv[1], sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "signal-checkpoint":
        signal_checkpoint(sys.argv[2])
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "stop":
        stop(sys.argv[2], sys.argv[3])
        return 0
    raise SystemExit("usage: run06_wasm.py {checkpoint|restore} CONTAINER | signal-checkpoint SOURCE | stop {checkpoint|restore} CONTAINER")


if __name__ == "__main__":
    raise SystemExit(main())
